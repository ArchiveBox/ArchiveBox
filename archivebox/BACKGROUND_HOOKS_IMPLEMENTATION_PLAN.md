# Background Hooks Implementation Plan

## Overview

This plan implements support for long-running background hooks that run concurrently with other extractors, while maintaining proper result collection, cleanup, and state management.

**Key Changes:**
- Background hooks use `.bg.js`/`.bg.py`/`.bg.sh` suffix
- Runner hashes files and creates ArchiveFile records for tracking
- Filesystem-level deduplication (fdupes, ZFS, Btrfs) handles space savings
- Hooks emit single JSON output with optional structured data
- Binary FK is optional and only set when hook reports cmd
- Split `output` field into `output_str` (human-readable) and `output_data` (structured)
- Use ArchiveFile model (FK to ArchiveResult) instead of JSON fields for file tracking
- Output stats (size, mimetypes) derived via properties from ArchiveFile queries

---

## Phase 1: Database Migration

### Add new fields to ArchiveResult

```python
# archivebox/core/migrations/00XX_archiveresult_background_hooks.py

from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('core', 'XXXX_previous_migration'),
        ('machine', 'XXXX_latest_machine_migration'),
    ]

    operations = [
        # Rename output → output_str for clarity
        migrations.RenameField(
            model_name='archiveresult',
            old_name='output',
            new_name='output_str',
        ),

        # Add structured metadata field
        migrations.AddField(
            model_name='archiveresult',
            name='output_data',
            field=models.JSONField(
                null=True,
                blank=True,
                help_text='Structured metadata from hook (headers, redirects, etc.)'
            ),
        ),

        # Add binary FK (optional)
        migrations.AddField(
            model_name='archiveresult',
            name='binary',
            field=models.ForeignKey(
                'machine.InstalledBinary',
                on_delete=models.SET_NULL,
                null=True,
                blank=True,
                help_text='Primary binary used by this hook (optional)'
            ),
        ),
    ]
```

### ArchiveFile Model

Instead of storing file lists and stats as JSON fields on ArchiveResult, we use a normalized model that tracks files with hashes. Deduplication is handled at the filesystem level (fdupes, ZFS, Btrfs, etc.):

```python
# archivebox/core/models.py

class ArchiveFile(models.Model):
    """
    Track files produced by an ArchiveResult with hash for integrity checking.

    Files remain in their natural filesystem hierarchy. Deduplication is handled
    by the filesystem layer (hardlinks via fdupes, ZFS dedup, Btrfs dedup, etc.).
    """
    archiveresult = models.ForeignKey(
        'ArchiveResult',
        on_delete=models.CASCADE,
        related_name='files'
    )

    # Path relative to ArchiveResult output directory
    relative_path = models.CharField(
        max_length=512,
        help_text='Path relative to extractor output dir (e.g., "index.html", "responses/all/file.js")'
    )

    # Hash for integrity checking and duplicate detection
    hash_algorithm = models.CharField(max_length=16, default='sha256')
    hash = models.CharField(
        max_length=128,
        db_index=True,
        help_text='SHA-256 hash for integrity and finding duplicates'
    )

    # Cached filesystem stats
    size = models.BigIntegerField(help_text='File size in bytes')
    mime_type = models.CharField(max_length=128, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['archiveresult']),
            models.Index(fields=['hash']),  # Find duplicates across archive
        ]
        unique_together = [['archiveresult', 'relative_path']]

    def __str__(self):
        return f"{self.archiveresult.extractor}/{self.relative_path}"

    @property
    def absolute_path(self) -> Path:
        """Get absolute filesystem path."""
        return Path(self.archiveresult.pwd) / self.relative_path
```

**Benefits:**
- **Simple**: Single model, no CAS abstraction needed
- **Natural hierarchy**: Files stay in `snapshot_dir/extractor/file.html`
- **Flexible deduplication**: User chooses filesystem-level strategy
- **Easy browsing**: Directory structure matches logical organization
- **Integrity checking**: Hashes verify file integrity over time
- **Duplicate detection**: Query by hash to find duplicates for manual review

---

## Phase 2: Hook Output Format

### Hooks emit single JSON object to stdout

**Contract:**
- Hook emits ONE JSON object with `type: 'ArchiveResult'`
- Hook only provides: `status`, `output` (human-readable), optional `output_data`, optional `cmd`
- Runner calculates: `output_size`, `output_mimetypes`, `start_ts`, `end_ts`, `binary` FK

**Example outputs:**

```javascript
// Simple string output
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',
    output: 'Downloaded index.html (4.2 KB)'
}));

// With structured metadata
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',
    output: 'Archived https://example.com',
    output_data: {
        files: ['index.html', 'style.css', 'script.js'],
        headers: {'content-type': 'text/html', 'server': 'nginx'},
        redirects: [{from: 'http://example.com', to: 'https://example.com'}]
    }
}));

// With explicit cmd (for binary FK)
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',
    output: 'Archived with wget',
    cmd: ['wget', '-p', '-k', 'https://example.com']
}));

// Just structured data (no human-readable string)
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',
    output_data: {
        title: 'My Page Title',
        charset: 'UTF-8'
    }
}));
```

---

## Phase 3: Update HookResult TypedDict

```python
# archivebox/hooks.py

class HookResult(TypedDict):
    """Result from executing a hook script."""
    returncode: int                   # Process exit code
    stdout: str                       # Full stdout from hook
    stderr: str                       # Full stderr from hook
    output_json: Optional[dict]       # Parsed JSON output from hook
    start_ts: str                     # ISO timestamp (calculated by runner)
    end_ts: str                       # ISO timestamp (calculated by runner)
    cmd: List[str]                    # Command that ran (from hook or fallback)
    binary_id: Optional[str]          # FK to InstalledBinary (optional)
    hook: str                         # Path to hook script
```

**Note:** `output_files`, `output_size`, and `output_mimetypes` are no longer in HookResult. Instead, the runner hashes files and creates ArchiveFile records. Stats are derived via properties on ArchiveResult.

---

## Phase 4: Update run_hook() Implementation

### Location: `archivebox/hooks.py`

```python
def find_binary_for_cmd(cmd: List[str], machine_id: str) -> Optional[str]:
    """
    Find InstalledBinary for a command, trying abspath first then name.
    Only matches binaries on the current machine.

    Args:
        cmd: Command list (e.g., ['/usr/bin/wget', '-p', 'url'])
        machine_id: Current machine ID

    Returns:
        Binary ID if found, None otherwise
    """
    if not cmd:
        return None

    from machine.models import InstalledBinary

    bin_path_or_name = cmd[0]

    # Try matching by absolute path first
    binary = InstalledBinary.objects.filter(
        abspath=bin_path_or_name,
        machine_id=machine_id
    ).first()

    if binary:
        return str(binary.id)

    # Fallback: match by binary name
    bin_name = Path(bin_path_or_name).name
    binary = InstalledBinary.objects.filter(
        name=bin_name,
        machine_id=machine_id
    ).first()

    return str(binary.id) if binary else None


def parse_hook_output_json(stdout: str) -> Optional[dict]:
    """
    Parse single JSON output from hook stdout.

    Looks for first line with {type: 'ArchiveResult', ...}
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            if data.get('type') == 'ArchiveResult':
                return data  # Return first match
        except json.JSONDecodeError:
            continue
    return None


def run_hook(
    script: Path,
    output_dir: Path,
    timeout: int = 300,
    config_objects: Optional[List[Any]] = None,
    **kwargs: Any
) -> Optional[HookResult]:
    """
    Execute a hook script and capture results.

    Runner responsibilities:
    - Detect background hooks (.bg. in filename)
    - Capture stdout/stderr to log files
    - Return result (caller will hash files and create ArchiveFile records)
    - Determine binary FK from cmd (optional)
    - Clean up log files and PID files

    Hook responsibilities:
    - Emit {type: 'ArchiveResult', status, output_str, output_data (optional), cmd (optional)}
    - Write actual output files

    Args:
        script: Path to hook script
        output_dir: Working directory (where output files go)
        timeout: Max execution time in seconds
        config_objects: Config override objects (Machine, Crawl, Snapshot)
        **kwargs: CLI arguments passed to script

    Returns:
        HookResult for foreground hooks
        None for background hooks (still running)
    """
    import time
    from datetime import datetime, timezone
    from machine.models import Machine

    start_time = time.time()

    # 1. SETUP
    is_background = '.bg.' in script.name  # Detect .bg.js/.bg.py/.bg.sh
    effective_timeout = timeout * 10 if is_background else timeout

    # Infrastructure files (ALL hooks)
    stdout_file = output_dir / 'stdout.log'
    stderr_file = output_dir / 'stderr.log'
    pid_file = output_dir / 'hook.pid'

    # Capture files before execution
    files_before = set(output_dir.rglob('*')) if output_dir.exists() else set()
    start_ts = datetime.now(timezone.utc)

    # 2. BUILD COMMAND
    ext = script.suffix.lower()
    if ext == '.sh':
        interpreter_cmd = ['bash', str(script)]
    elif ext == '.py':
        interpreter_cmd = ['python3', str(script)]
    elif ext == '.js':
        interpreter_cmd = ['node', str(script)]
    else:
        interpreter_cmd = [str(script)]

    # Build CLI arguments from kwargs
    cli_args = []
    for key, value in kwargs.items():
        if key.startswith('_'):
            continue

        arg_key = f'--{key.replace("_", "-")}'
        if isinstance(value, bool):
            if value:
                cli_args.append(arg_key)
        elif value is not None and value != '':
            if isinstance(value, (dict, list)):
                cli_args.append(f'{arg_key}={json.dumps(value)}')
            else:
                str_value = str(value).strip()
                if str_value:
                    cli_args.append(f'{arg_key}={str_value}')

    full_cmd = interpreter_cmd + cli_args

    # 3. SET UP ENVIRONMENT
    env = os.environ.copy()
    # ... (existing env setup from current run_hook implementation)

    # 4. CREATE OUTPUT DIRECTORY
    output_dir.mkdir(parents=True, exist_ok=True)

    # 5. EXECUTE PROCESS
    try:
        with open(stdout_file, 'w') as out, open(stderr_file, 'w') as err:
            process = subprocess.Popen(
                full_cmd,
                cwd=str(output_dir),
                stdout=out,
                stderr=err,
                env=env,
            )

            # Write PID for all hooks
            pid_file.write_text(str(process.pid))

            if is_background:
                # Background hook - return immediately, don't wait
                return None

            # Foreground hook - wait for completion
            try:
                returncode = process.wait(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                returncode = -1
                with open(stderr_file, 'a') as err:
                    err.write(f'\nHook timed out after {effective_timeout}s')

        # 6. COLLECT RESULTS (foreground only)
        end_ts = datetime.now(timezone.utc)

        stdout = stdout_file.read_text() if stdout_file.exists() else ''
        stderr = stderr_file.read_text() if stderr_file.exists() else ''

        # Parse single JSON output
        output_json = parse_hook_output_json(stdout)

        # Get cmd - prefer hook's reported cmd, fallback to interpreter cmd
        if output_json and output_json.get('cmd'):
            result_cmd = output_json['cmd']
        else:
            result_cmd = full_cmd

        # 7. DETERMINE BINARY FK (OPTIONAL)
        # Only set if hook reports cmd AND we can find the binary
        machine = Machine.current()
        binary_id = None
        if output_json and output_json.get('cmd'):
            binary_id = find_binary_for_cmd(output_json['cmd'], machine.id)
        # If not found or not reported, leave binary_id=None

        # 8. INGEST OUTPUT FILES VIA BLOBMANAGER
        # BlobManager handles hashing, deduplication, and creating SnapshotFile records
        # Note: This assumes snapshot and extractor name are available in kwargs
        # In practice, ArchiveResult.run() will handle this after run_hook() returns
        # For now, we just return the result and let the caller handle ingestion

        # 9. CLEANUP
        # Delete empty logs (keep non-empty for debugging)
        if stdout_file.exists() and stdout_file.stat().st_size == 0:
            stdout_file.unlink()
        if stderr_file.exists() and stderr_file.stat().st_size == 0:
            stderr_file.unlink()

        # Delete ALL .pid files on success
        if returncode == 0:
            for pf in output_dir.glob('*.pid'):
                pf.unlink(missing_ok=True)

        # 10. RETURN RESULT
        return HookResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            output_json=output_json,
            start_ts=start_ts.isoformat(),
            end_ts=end_ts.isoformat(),
            cmd=result_cmd,
            binary_id=binary_id,
            hook=str(script),
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return HookResult(
            returncode=-1,
            stdout='',
            stderr=f'Failed to run hook: {type(e).__name__}: {e}',
            output_json=None,
            start_ts=start_ts.isoformat(),
            end_ts=datetime.now(timezone.utc).isoformat(),
            cmd=full_cmd,
            binary_id=None,
            hook=str(script),
        )
```

---

## Phase 5: Update ArchiveResult.run()

### Location: `archivebox/core/models.py`

```python
def run(self):
    """
    Execute this ArchiveResult's extractor and update status.

    For foreground hooks: Waits for completion and updates immediately
    For background hooks: Returns immediately, leaves status='started'
    """
    from django.utils import timezone
    from archivebox.hooks import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR, run_hook
    import dateutil.parser

    config_objects = [self.snapshot.crawl, self.snapshot] if self.snapshot.crawl else [self.snapshot]

    # Find hook for this extractor
    hook = None
    for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
        if not base_dir.exists():
            continue
        matches = list(base_dir.glob(f'*/on_Snapshot__{self.extractor}.*'))
        if matches:
            hook = matches[0]
            break

    if not hook:
        self.status = self.StatusChoices.FAILED
        self.output_str = f'No hook found for: {self.extractor}'
        self.retry_at = None
        self.save()
        return

    # Use plugin directory name instead of extractor name
    plugin_name = hook.parent.name
    extractor_dir = Path(self.snapshot.output_dir) / plugin_name

    # Run the hook
    result = run_hook(
        hook,
        output_dir=extractor_dir,
        config_objects=config_objects,
        url=self.snapshot.url,
        snapshot_id=str(self.snapshot.id),
    )

    # BACKGROUND HOOK - still running
    if result is None:
        self.status = self.StatusChoices.STARTED
        self.start_ts = timezone.now()
        self.pwd = str(extractor_dir)
        self.save()
        return

    # FOREGROUND HOOK - process result
    if result['output_json']:
        # Hook emitted JSON output
        output_json = result['output_json']

        # Determine status
        status = output_json.get('status', 'failed')
        status_map = {
            'succeeded': self.StatusChoices.SUCCEEDED,
            'failed': self.StatusChoices.FAILED,
            'skipped': self.StatusChoices.SKIPPED,
        }
        self.status = status_map.get(status, self.StatusChoices.FAILED)

        # Set output fields
        self.output_str = output_json.get('output', '')
        if 'output_data' in output_json:
            self.output_data = output_json['output_data']
    else:
        # No JSON output - determine status from exit code
        self.status = (self.StatusChoices.SUCCEEDED if result['returncode'] == 0
                      else self.StatusChoices.FAILED)
        self.output_str = result['stdout'][:1024] or result['stderr'][:1024]

    # Set timestamps (from runner)
    self.start_ts = dateutil.parser.parse(result['start_ts'])
    self.end_ts = dateutil.parser.parse(result['end_ts'])

    # Set command and binary (from runner)
    self.cmd = json.dumps(result['cmd'])
    if result['binary_id']:
        self.binary_id = result['binary_id']

    # Metadata
    self.pwd = str(extractor_dir)
    self.retry_at = None

    self.save()

    # INGEST OUTPUT FILES VIA BLOBMANAGER
    # This creates SnapshotFile records with deduplication
    if extractor_dir.exists():
        from archivebox.storage import BlobManager

        snapshot_files = BlobManager.ingest_directory(
            dir_path=extractor_dir,
            snapshot=self.snapshot,
            extractor=plugin_name,
            # Exclude infrastructure files
            exclude_patterns=['stdout.log', 'stderr.log', '*.pid']
        )

    # Clean up empty output directory (no real files after excluding logs/pids)
    if extractor_dir.exists():
        try:
            # Check if only infrastructure files remain
            remaining_files = [
                f for f in extractor_dir.rglob('*')
                if f.is_file() and f.name not in ('stdout.log', 'stderr.log', 'hook.pid', 'listener.pid')
            ]
            if not remaining_files:
                # Remove infrastructure files
                for pf in extractor_dir.glob('*.log'):
                    pf.unlink(missing_ok=True)
                for pf in extractor_dir.glob('*.pid'):
                    pf.unlink(missing_ok=True)
                # Try to remove directory if empty
                if not any(extractor_dir.iterdir()):
                    extractor_dir.rmdir()
        except (OSError, RuntimeError):
            pass

    # Queue discovered URLs, trigger indexing, etc.
    self._queue_urls_for_crawl(extractor_dir)

    if self.status == self.StatusChoices.SUCCEEDED:
        # Update snapshot title if this is title extractor
        extractor_name = get_extractor_name(self.extractor)
        if extractor_name == 'title':
            self._update_snapshot_title(extractor_dir)

        # Trigger search indexing
        self.trigger_search_indexing()
```

---

## Phase 6: Background Hook Finalization

### Helper Functions

Location: `archivebox/core/models.py` or new `archivebox/core/background_hooks.py`

```python
def find_background_hooks(snapshot) -> List['ArchiveResult']:
    """
    Find all ArchiveResults that are background hooks still running.

    Args:
        snapshot: Snapshot instance

    Returns:
        List of ArchiveResults with status='started'
    """
    return list(snapshot.archiveresult_set.filter(
        status=ArchiveResult.StatusChoices.STARTED
    ))


def check_background_hook_completed(archiveresult: 'ArchiveResult') -> bool:
    """
    Check if background hook process has exited.

    Args:
        archiveresult: ArchiveResult instance

    Returns:
        True if completed (process exited), False if still running
    """
    extractor_dir = Path(archiveresult.pwd)
    pid_file = extractor_dir / 'hook.pid'

    if not pid_file.exists():
        return True  # No PID file = completed or failed to start

    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Signal 0 = check if process exists
        return False  # Still running
    except (OSError, ValueError):
        return True  # Process exited or invalid PID


def finalize_background_hook(archiveresult: 'ArchiveResult') -> None:
    """
    Collect final results from completed background hook.

    Runner calculates all stats - hook just emits status/output/output_data.

    Args:
        archiveresult: ArchiveResult instance to finalize
    """
    from django.utils import timezone
    from machine.models import Machine
    import dateutil.parser

    extractor_dir = Path(archiveresult.pwd)
    stdout_file = extractor_dir / 'stdout.log'
    stderr_file = extractor_dir / 'stderr.log'

    # Read logs
    stdout = stdout_file.read_text() if stdout_file.exists() else ''
    stderr = stderr_file.read_text() if stderr_file.exists() else ''

    # Parse JSON output
    output_json = parse_hook_output_json(stdout)

    # Determine status
    if output_json:
        status_str = output_json.get('status', 'failed')
        status_map = {
            'succeeded': ArchiveResult.StatusChoices.SUCCEEDED,
            'failed': ArchiveResult.StatusChoices.FAILED,
            'skipped': ArchiveResult.StatusChoices.SKIPPED,
        }
        status = status_map.get(status_str, ArchiveResult.StatusChoices.FAILED)
        output_str = output_json.get('output', '')
        output_data = output_json.get('output_data')

        # Get cmd from hook (for binary FK)
        cmd = output_json.get('cmd')
    else:
        # No JSON output = failed
        status = ArchiveResult.StatusChoices.FAILED
        output_str = stderr[:1024] if stderr else 'No output'
        output_data = None
        cmd = None

    # Get binary FK from hook's reported cmd (if any)
    binary_id = None
    if cmd:
        machine = Machine.current()
        binary_id = find_binary_for_cmd(cmd, machine.id)

    # Update ArchiveResult
    archiveresult.status = status
    archiveresult.end_ts = timezone.now()
    archiveresult.output_str = output_str
    if output_data:
        archiveresult.output_data = output_data
    archiveresult.retry_at = None

    if binary_id:
        archiveresult.binary_id = binary_id

    archiveresult.save()

    # INGEST OUTPUT FILES VIA BLOBMANAGER
    # This creates SnapshotFile records with deduplication
    if extractor_dir.exists():
        from archivebox.storage import BlobManager

        # Determine extractor name from path (plugin directory name)
        plugin_name = extractor_dir.name

        snapshot_files = BlobManager.ingest_directory(
            dir_path=extractor_dir,
            snapshot=archiveresult.snapshot,
            extractor=plugin_name,
            exclude_patterns=['stdout.log', 'stderr.log', '*.pid']
        )

    # Cleanup
    for pf in extractor_dir.glob('*.pid'):
        pf.unlink(missing_ok=True)
    if stdout_file.exists() and stdout_file.stat().st_size == 0:
        stdout_file.unlink()
    if stderr_file.exists() and stderr_file.stat().st_size == 0:
        stderr_file.unlink()
```

### Update SnapshotMachine

Location: `archivebox/core/statemachines.py`

```python
class SnapshotMachine(StateMachine, strict_states=True):
    # ... existing states ...

    def is_finished(self) -> bool:
        """
        Check if snapshot archiving is complete.

        A snapshot is finished when:
        1. No pending archiveresults remain (queued/started foreground hooks)
        2. All background hooks have completed
        """
        # Check if any pending archiveresults exist
        if self.snapshot.pending_archiveresults().exists():
            return False

        # Check and finalize background hooks
        background_hooks = find_background_hooks(self.snapshot)
        for bg_hook in background_hooks:
            if not check_background_hook_completed(bg_hook):
                return False  # Still running

            # Completed - finalize it
            finalize_background_hook(bg_hook)

        # All done
        return True
```

---

## Phase 6b: ArchiveResult Properties for Output Stats

Since output stats are no longer stored as fields, we expose them via properties that query SnapshotFile records:

```python
# archivebox/core/models.py

class ArchiveResult(models.Model):
    # ... existing fields ...

    @property
    def output_files(self):
        """
        Get all SnapshotFile records created by this extractor.

        Returns:
            QuerySet of SnapshotFile objects
        """
        plugin_name = self._get_plugin_name()
        return self.snapshot.files.filter(extractor=plugin_name)

    @property
    def output_file_count(self) -> int:
        """Count of output files."""
        return self.output_files.count()

    @property
    def total_output_size(self) -> int:
        """
        Total size in bytes of all output files.

        Returns:
            Sum of blob sizes for this extractor's files
        """
        from django.db.models import Sum

        result = self.output_files.aggregate(total=Sum('blob__size'))
        return result['total'] or 0

    @property
    def output_mimetypes(self) -> str:
        """
        CSV of mimetypes ordered by size descending.

        Returns:
            String like "text/html,image/png,application/json"
        """
        from django.db.models import Sum
        from collections import OrderedDict

        # Group by mimetype and sum sizes
        files = self.output_files.values('blob__mime_type').annotate(
            total_size=Sum('blob__size')
        ).order_by('-total_size')

        # Build CSV
        mimes = [f['blob__mime_type'] for f in files]
        return ','.join(mimes)

    @property
    def output_summary(self) -> dict:
        """
        Summary statistics for output files.

        Returns:
            Dict with file count, total size, and mimetype breakdown
        """
        from django.db.models import Sum, Count

        files = self.output_files.values('blob__mime_type').annotate(
            count=Count('id'),
            total_size=Sum('blob__size')
        ).order_by('-total_size')

        return {
            'file_count': self.output_file_count,
            'total_size': self.total_output_size,
            'by_mimetype': list(files),
        }

    def _get_plugin_name(self) -> str:
        """
        Get plugin directory name from extractor.

        Returns:
            Plugin name (e.g., 'wget', 'singlefile')
        """
        # This assumes pwd is set to extractor_dir during run()
        if self.pwd:
            return Path(self.pwd).name
        # Fallback: use extractor number to find plugin
        # (implementation depends on how extractor names map to plugins)
        return self.extractor
```

**Query Examples:**

```python
# Get all files for this extractor
files = archiveresult.output_files.all()

# Get total size
size = archiveresult.total_output_size

# Get mimetype breakdown
summary = archiveresult.output_summary
# {
#   'file_count': 42,
#   'total_size': 1048576,
#   'by_mimetype': [
#     {'blob__mime_type': 'text/html', 'count': 5, 'total_size': 524288},
#     {'blob__mime_type': 'image/png', 'count': 30, 'total_size': 409600},
#     ...
#   ]
# }

# Admin display
print(f"{archiveresult.output_mimetypes}")  # "text/html,image/png,text/css"
```

**Performance Considerations:**

- Properties execute queries on access - cache results if needed
- Indexes on `(snapshot, extractor)` make queries fast
- For admin list views, use `select_related()` and `prefetch_related()`
- Consider adding `cached_property` for expensive calculations

---

## Phase 7: Rename Background Hooks

### Files to rename:

```bash
# Use .bg. suffix (not __background)
mv archivebox/plugins/consolelog/on_Snapshot__21_consolelog.js \
   archivebox/plugins/consolelog/on_Snapshot__21_consolelog.bg.js

mv archivebox/plugins/ssl/on_Snapshot__23_ssl.js \
   archivebox/plugins/ssl/on_Snapshot__23_ssl.bg.js

mv archivebox/plugins/responses/on_Snapshot__24_responses.js \
   archivebox/plugins/responses/on_Snapshot__24_responses.bg.js
```

### Update hook content to emit proper JSON:

Each hook should emit:
```javascript
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',  // or 'failed' or 'skipped'
    output: 'Captured 15 console messages',  // human-readable summary
    output_data: {  // optional structured metadata
        // ... specific to each hook
    }
}));
```

---

## Phase 8: Update Existing Hooks

### Update all hooks to emit proper JSON format

**Example: favicon hook**

```python
# Before
print(f'Favicon saved ({size} bytes)')
print(f'OUTPUT={OUTPUT_FILE}')
print(f'STATUS=succeeded')

# After
result = {
    'type': 'ArchiveResult',
    'status': 'succeeded',
    'output': f'Favicon saved ({size} bytes)',
    'output_data': {
        'size': size,
        'format': 'ico'
    }
}
print(json.dumps(result))
```

**Example: wget hook with explicit cmd**

```bash
# After wget completes
cat <<EOF
{"type": "ArchiveResult", "status": "succeeded", "output": "Downloaded index.html", "cmd": ["wget", "-p", "-k", "$URL"]}
EOF
```

---

## Testing Strategy

### 1. Unit Tests

```python
# tests/test_background_hooks.py

def test_background_hook_detection():
    """Test .bg. suffix detection"""
    assert is_background_hook(Path('on_Snapshot__21_test.bg.js'))
    assert not is_background_hook(Path('on_Snapshot__21_test.js'))

def test_find_binary_by_abspath():
    """Test binary matching by absolute path"""
    machine = Machine.current()
    binary = InstalledBinary.objects.create(
        name='wget',
        abspath='/usr/bin/wget',
        machine=machine
    )

    cmd = ['/usr/bin/wget', '-p', 'url']
    assert find_binary_for_cmd(cmd, machine.id) == str(binary.id)

def test_find_binary_by_name():
    """Test binary matching by name fallback"""
    machine = Machine.current()
    binary = InstalledBinary.objects.create(
        name='wget',
        abspath='/usr/local/bin/wget',
        machine=machine
    )

    cmd = ['wget', '-p', 'url']
    assert find_binary_for_cmd(cmd, machine.id) == str(binary.id)

def test_parse_hook_json():
    """Test JSON parsing from stdout"""
    stdout = '''
    Some log output
    {"type": "ArchiveResult", "status": "succeeded", "output": "test"}
    More output
    '''
    result = parse_hook_output_json(stdout)
    assert result['status'] == 'succeeded'
    assert result['output'] == 'test'
```

### 2. Integration Tests

```python
def test_foreground_hook_execution(snapshot):
    """Test foreground hook runs and returns results"""
    ar = ArchiveResult.objects.create(
        snapshot=snapshot,
        extractor='11_favicon',
        status=ArchiveResult.StatusChoices.QUEUED
    )

    ar.run()
    ar.refresh_from_db()

    assert ar.status in [
        ArchiveResult.StatusChoices.SUCCEEDED,
        ArchiveResult.StatusChoices.FAILED
    ]
    assert ar.start_ts is not None
    assert ar.end_ts is not None
    assert ar.output_size >= 0

def test_background_hook_execution(snapshot):
    """Test background hook starts but doesn't block"""
    ar = ArchiveResult.objects.create(
        snapshot=snapshot,
        extractor='21_consolelog',
        status=ArchiveResult.StatusChoices.QUEUED
    )

    start = time.time()
    ar.run()
    duration = time.time() - start

    ar.refresh_from_db()

    # Should return quickly (< 5 seconds)
    assert duration < 5
    # Should be in 'started' state
    assert ar.status == ArchiveResult.StatusChoices.STARTED
    # PID file should exist
    assert (Path(ar.pwd) / 'hook.pid').exists()

def test_background_hook_finalization(snapshot):
    """Test background hook finalization after completion"""
    # Start background hook
    ar = ArchiveResult.objects.create(
        snapshot=snapshot,
        extractor='21_consolelog',
        status=ArchiveResult.StatusChoices.STARTED,
        pwd='/path/to/output'
    )

    # Simulate completion (hook writes output and exits)
    # ...

    # Finalize
    finalize_background_hook(ar)
    ar.refresh_from_db()

    assert ar.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert ar.end_ts is not None
    assert ar.output_size > 0
```

---

## Migration Path

### Step 1: Create migration
```bash
cd archivebox
python manage.py makemigrations core --name archiveresult_background_hooks
```

### Step 2: Update run_hook()
- Add background hook detection
- Add log file capture
- Add output stat calculation
- Add binary FK lookup

### Step 3: Update ArchiveResult.run()
- Handle None result for background hooks
- Update field names (output → output_str, add output_data)
- Set binary FK

### Step 4: Add finalization helpers
- `find_background_hooks()`
- `check_background_hook_completed()`
- `finalize_background_hook()`

### Step 5: Update SnapshotMachine.is_finished()
- Check for background hooks
- Finalize completed ones

### Step 6: Rename hooks
- Rename 3 background hooks with .bg. suffix

### Step 7: Update hook outputs
- Update all hooks to emit JSON format
- Remove manual timestamp/status calculation

### Step 8: Test
- Unit tests
- Integration tests
- Manual testing with real snapshots

---

## Success Criteria

- ✅ Background hooks start immediately without blocking other extractors
- ✅ Background hooks are finalized after completion with full results
- ✅ All output stats calculated by runner, not hooks
- ✅ Binary FK optional and only set when determinable
- ✅ Clean separation between output_str (human) and output_data (machine)
- ✅ Log files cleaned up on success, kept on failure
- ✅ PID files cleaned up after completion
- ✅ No plugin-specific code in core (generic polling mechanism)

---

## Future Enhancements

### 1. Timeout for orphaned background hooks
If a background hook runs longer than MAX_LIFETIME after all foreground hooks complete, force kill it.

### 2. Progress reporting
Background hooks could write progress to a file that gets polled:
```javascript
fs.writeFileSync('progress.txt', '50%');
```

### 3. Multiple results per hook
If needed in future, extend to support multiple JSON outputs by collecting all `{type: 'ArchiveResult'}` lines.

### 4. Dependency tracking
Store all binaries used by a hook (not just primary), useful for hooks that chain multiple tools.
