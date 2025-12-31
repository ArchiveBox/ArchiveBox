# Process Hierarchy Tracking Implementation Plan

## Overview

This document outlines the plan to refactor ArchiveBox's process management to use the `machine.Process` model as the central data structure for tracking all subprocess spawning and lifecycle management.

### Goal

Create a complete hierarchy of `Process` records that track every subprocess from CLI invocation down to individual binary executions:

```
Process(cmd=['archivebox', 'add', 'https://example.com'])           # CLI entry
    └── Process(cmd=['supervisord', ...], parent=^)                 # Daemon manager
            └── Process(cmd=['orchestrator'], parent=^)             # Work distributor
                    └── Process(cmd=['crawl_worker'], parent=^)     # Crawl processor
                            └── Process(cmd=['snapshot_worker'], parent=^)
                                    └── Process(cmd=['archiveresult_worker'], parent=^)
                                            └── Process(cmd=['hook.py', ...], parent=^)  # Hook script
                                                    └── Process(cmd=['wget', ...], parent=^)  # Binary
```

---

## Phase 1: Model Changes

### 1.1 Add `parent` FK to Process Model

**File:** `archivebox/machine/models.py`

```python
class Process(ModelWithHealthStats):
    # ... existing fields ...

    # NEW: Parent process FK for hierarchy tracking
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
        help_text='Parent process that spawned this one'
    )
```

**Migration needed:** Yes, new nullable FK field.

### 1.2 Add Process Type Field

To distinguish between different process types in the hierarchy:

```python
class Process(ModelWithHealthStats):
    class TypeChoices(models.TextChoices):
        CLI = 'cli', 'CLI Command'
        SUPERVISORD = 'supervisord', 'Supervisord Daemon'
        ORCHESTRATOR = 'orchestrator', 'Orchestrator'
        WORKER = 'worker', 'Worker Process'
        HOOK = 'hook', 'Hook Script'
        BINARY = 'binary', 'Binary Execution'

    process_type = models.CharField(
        max_length=16,
        choices=TypeChoices.choices,
        default=TypeChoices.BINARY,
        db_index=True,
        help_text='Type of process in the execution hierarchy'
    )
```

### 1.3 Add `Process.current()` Class Method (like `Machine.current()`)

Following the pattern established by `Machine.current()`, add a method to get-or-create the Process record for the current OS process:

```python
import os
import sys
import psutil
from datetime import timedelta
from django.utils import timezone

_CURRENT_PROCESS = None
PROCESS_RECHECK_INTERVAL = 60  # Re-validate every 60 seconds
PID_REUSE_WINDOW = timedelta(hours=24)  # Max age for considering a PID match valid
START_TIME_TOLERANCE = 5.0  # Seconds tolerance for start time matching


class ProcessManager(models.Manager):
    def current(self) -> 'Process':
        return Process.current()

    def get_by_pid(self, pid: int, machine: 'Machine' = None) -> 'Process | None':
        """
        Find a Process by PID with proper validation against PID reuse.

        IMPORTANT: PIDs are reused by the OS! This method:
        1. Filters by machine (required - PIDs are only unique per machine)
        2. Filters by time window (processes older than 24h are stale)
        3. Validates via psutil that start times match

        Args:
            pid: OS process ID
            machine: Machine instance (defaults to current machine)

        Returns:
            Process if found and validated, None otherwise
        """
        machine = machine or Machine.current()

        # Get the actual process start time from OS
        try:
            os_proc = psutil.Process(pid)
            os_start_time = os_proc.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process doesn't exist - any DB record with this PID is stale
            return None

        # Query candidates: same machine, same PID, recent, still RUNNING
        candidates = self.filter(
            machine=machine,
            pid=pid,
            status=Process.StatusChoices.RUNNING,
            started_at__gte=timezone.now() - PID_REUSE_WINDOW,  # Only recent processes
        ).order_by('-started_at')  # Most recent first

        for candidate in candidates:
            # Validate start time matches (within tolerance)
            if candidate.started_at:
                db_start_time = candidate.started_at.timestamp()
                if abs(db_start_time - os_start_time) < START_TIME_TOLERANCE:
                    return candidate

        return None


class Process(ModelWithHealthStats):
    # ... existing fields ...

    objects: ProcessManager = ProcessManager()

    @classmethod
    def current(cls) -> 'Process':
        """
        Get or create the Process record for the current OS process.

        Similar to Machine.current(), this:
        1. Checks cache for existing Process with matching PID
        2. Validates the cached Process is still valid (PID not reused)
        3. Creates new Process if needed

        IMPORTANT: Uses psutil to validate PID hasn't been reused.
        PIDs are recycled by OS, so we compare start times.
        """
        global _CURRENT_PROCESS

        current_pid = os.getpid()
        machine = Machine.current()

        # Check cache validity
        if _CURRENT_PROCESS:
            # Verify: same PID, same machine, cache not expired
            if (_CURRENT_PROCESS.pid == current_pid and
                _CURRENT_PROCESS.machine_id == machine.id and
                timezone.now() < _CURRENT_PROCESS.modified_at + timedelta(seconds=PROCESS_RECHECK_INTERVAL)):
                return _CURRENT_PROCESS
            _CURRENT_PROCESS = None

        # Get actual process start time from OS for validation
        try:
            os_proc = psutil.Process(current_pid)
            os_start_time = os_proc.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            os_start_time = None

        # Try to find existing Process for this PID on this machine
        # Filter by: machine + PID + RUNNING + recent + start time matches
        if os_start_time:
            existing = cls.objects.filter(
                machine=machine,
                pid=current_pid,
                status=cls.StatusChoices.RUNNING,
                started_at__gte=timezone.now() - PID_REUSE_WINDOW,
            ).order_by('-started_at').first()

            if existing and existing.started_at:
                db_start_time = existing.started_at.timestamp()
                if abs(db_start_time - os_start_time) < START_TIME_TOLERANCE:
                    _CURRENT_PROCESS = existing
                    return existing

        # No valid existing record - create new one
        parent = cls._find_parent_process(machine)
        process_type = cls._detect_process_type()

        # Use psutil start time if available (more accurate than timezone.now())
        if os_start_time:
            from datetime import datetime
            started_at = datetime.fromtimestamp(os_start_time, tz=timezone.get_current_timezone())
        else:
            started_at = timezone.now()

        _CURRENT_PROCESS = cls.objects.create(
            machine=machine,
            parent=parent,
            process_type=process_type,
            cmd=sys.argv,
            pwd=os.getcwd(),
            pid=current_pid,
            started_at=started_at,
            status=cls.StatusChoices.RUNNING,
        )
        return _CURRENT_PROCESS

    @classmethod
    def _find_parent_process(cls, machine: 'Machine' = None) -> 'Process | None':
        """
        Find the parent Process record by looking up PPID.

        IMPORTANT: Validates against PID reuse by checking:
        1. Same machine (PIDs are only unique per machine)
        2. Start time matches OS process start time
        3. Process is still RUNNING and recent

        Returns None if parent is not an ArchiveBox process.
        """
        ppid = os.getppid()
        machine = machine or Machine.current()

        # Get parent process start time from OS
        try:
            os_parent = psutil.Process(ppid)
            os_parent_start = os_parent.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None  # Parent process doesn't exist

        # Find matching Process record
        candidates = cls.objects.filter(
            machine=machine,
            pid=ppid,
            status=cls.StatusChoices.RUNNING,
            started_at__gte=timezone.now() - PID_REUSE_WINDOW,
        ).order_by('-started_at')

        for candidate in candidates:
            if candidate.started_at:
                db_start_time = candidate.started_at.timestamp()
                if abs(db_start_time - os_parent_start) < START_TIME_TOLERANCE:
                    return candidate

        return None  # No matching ArchiveBox parent process

    @classmethod
    def _detect_process_type(cls) -> str:
        """
        Detect the type of the current process from sys.argv.
        """
        argv_str = ' '.join(sys.argv).lower()

        if 'supervisord' in argv_str:
            return cls.TypeChoices.SUPERVISORD
        elif 'orchestrator' in argv_str:
            return cls.TypeChoices.ORCHESTRATOR
        elif any(w in argv_str for w in ['crawl_worker', 'snapshot_worker', 'archiveresult_worker']):
            return cls.TypeChoices.WORKER
        elif 'archivebox' in argv_str:
            return cls.TypeChoices.CLI
        else:
            return cls.TypeChoices.BINARY

    @classmethod
    def cleanup_stale_running(cls, machine: 'Machine' = None) -> int:
        """
        Mark stale RUNNING processes as EXITED.

        Processes are stale if:
        - Status is RUNNING but OS process no longer exists
        - Status is RUNNING but started_at is older than PID_REUSE_WINDOW

        Returns count of processes cleaned up.
        """
        machine = machine or Machine.current()
        cleaned = 0

        stale = cls.objects.filter(
            machine=machine,
            status=cls.StatusChoices.RUNNING,
        )

        for proc in stale:
            is_stale = False

            # Check if too old (PID definitely reused)
            if proc.started_at and proc.started_at < timezone.now() - PID_REUSE_WINDOW:
                is_stale = True
            else:
                # Check if OS process still exists with matching start time
                try:
                    os_proc = psutil.Process(proc.pid)
                    if proc.started_at:
                        db_start = proc.started_at.timestamp()
                        os_start = os_proc.create_time()
                        if abs(db_start - os_start) > START_TIME_TOLERANCE:
                            is_stale = True  # PID reused by different process
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    is_stale = True  # Process no longer exists

            if is_stale:
                proc.status = cls.StatusChoices.EXITED
                proc.ended_at = proc.ended_at or timezone.now()
                proc.exit_code = proc.exit_code if proc.exit_code is not None else -1
                proc.save(update_fields=['status', 'ended_at', 'exit_code'])
                cleaned += 1

        return cleaned
```

**Key Benefits:**
- **Automatic hierarchy**: Calling `Process.current()` from anywhere auto-links to parent
- **Cached**: Like `Machine.current()`, avoids repeated DB queries
- **PID reuse protection**: Validates via psutil start time comparison (PIDs recycle!)
- **Machine-scoped**: All queries filter by `machine=Machine.current()`
- **Time-windowed**: Ignores processes older than 24h (stale PID matches)
- **Self-healing**: `cleanup_stale_running()` marks orphaned processes as EXITED

**Usage pattern:**
```python
# In any ArchiveBox code that spawns a subprocess:
parent = Process.current()  # Get/create record for THIS process
child = Process.objects.create(
    parent=parent,
    cmd=['wget', ...],
    ...
)
child.launch()
```

### 1.4 Add Helper Methods for Tree Traversal

```python
class Process(ModelWithHealthStats):
    # ... existing fields ...

    @property
    def root(self) -> 'Process':
        """Get the root process (CLI command) of this hierarchy."""
        proc = self
        while proc.parent_id:
            proc = proc.parent
        return proc

    @property
    def ancestors(self) -> list['Process']:
        """Get all ancestor processes from parent to root."""
        ancestors = []
        proc = self.parent
        while proc:
            ancestors.append(proc)
            proc = proc.parent
        return ancestors

    @property
    def depth(self) -> int:
        """Get depth in the process tree (0 = root)."""
        return len(self.ancestors)

    def get_descendants(self, include_self: bool = False) -> QuerySet['Process']:
        """Get all descendant processes recursively."""
        # Note: For deep hierarchies, consider using django-mptt or django-treebeard
        # For now, simple recursive query (limited depth in practice)
        from django.db.models import Q

        if include_self:
            pks = [self.pk]
        else:
            pks = []

        children = list(self.children.values_list('pk', flat=True))
        while children:
            pks.extend(children)
            children = list(Process.objects.filter(parent_id__in=children).values_list('pk', flat=True))

        return Process.objects.filter(pk__in=pks)
```

### 1.4 Add Process Lifecycle Methods

Move logic from `process_utils.py` and `hooks.py` into the model:

```python
class Process(ModelWithHealthStats):
    # ... existing fields ...

    @property
    def pid_file(self) -> Path:
        """Path to PID file for this process."""
        return Path(self.pwd) / 'process.pid'

    @property
    def cmd_file(self) -> Path:
        """Path to cmd.sh script for this process."""
        return Path(self.pwd) / 'cmd.sh'

    @property
    def stdout_file(self) -> Path:
        """Path to stdout log."""
        return Path(self.pwd) / 'stdout.log'

    @property
    def stderr_file(self) -> Path:
        """Path to stderr log."""
        return Path(self.pwd) / 'stderr.log'

    def _write_pid_file(self) -> None:
        """Write PID file with mtime set to process start time."""
        from archivebox.misc.process_utils import write_pid_file_with_mtime
        if self.pid and self.started_at:
            write_pid_file_with_mtime(
                self.pid_file,
                self.pid,
                self.started_at.timestamp()
            )

    def _write_cmd_file(self) -> None:
        """Write cmd.sh script for debugging/validation."""
        from archivebox.misc.process_utils import write_cmd_file
        write_cmd_file(self.cmd_file, self.cmd)

    def _build_env(self) -> dict:
        """Build environment dict for subprocess, merging stored env with system."""
        import os
        env = os.environ.copy()
        env.update(self.env or {})
        return env

    def launch(self, background: bool = False) -> 'Process':
        """
        Spawn the subprocess and update this Process record.

        Args:
            background: If True, don't wait for completion (for daemons/bg hooks)

        Returns:
            self (updated with pid, started_at, etc.)
        """
        import subprocess
        import time
        from django.utils import timezone

        # Ensure output directory exists
        Path(self.pwd).mkdir(parents=True, exist_ok=True)

        # Write cmd.sh for debugging
        self._write_cmd_file()

        with open(self.stdout_file, 'w') as out, open(self.stderr_file, 'w') as err:
            proc = subprocess.Popen(
                self.cmd,
                cwd=self.pwd,
                stdout=out,
                stderr=err,
                env=self._build_env(),
            )

            self.pid = proc.pid
            self.started_at = timezone.now()
            self.status = self.StatusChoices.RUNNING
            self.save()

            self._write_pid_file()

            if not background:
                try:
                    proc.wait(timeout=self.timeout)
                    self.exit_code = proc.returncode
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    self.exit_code = -1

                self.ended_at = timezone.now()
                self.stdout = self.stdout_file.read_text()
                self.stderr = self.stderr_file.read_text()
                self.status = self.StatusChoices.EXITED
                self.save()

        return self

    def is_alive(self) -> bool:
        """Check if this process is still running."""
        from archivebox.misc.process_utils import validate_pid_file

        if self.status == self.StatusChoices.EXITED:
            return False

        if not self.pid:
            return False

        return validate_pid_file(self.pid_file, self.cmd_file)

    def kill(self, signal_num: int = 15) -> bool:
        """
        Kill this process and update status.

        Args:
            signal_num: Signal to send (default SIGTERM=15)

        Returns:
            True if killed successfully, False otherwise
        """
        from archivebox.misc.process_utils import safe_kill_process
        from django.utils import timezone

        killed = safe_kill_process(self.pid_file, self.cmd_file, signal_num)

        if killed:
            self.exit_code = -signal_num
            self.ended_at = timezone.now()
            self.status = self.StatusChoices.EXITED
            self.save()

        return killed

    def poll(self) -> int | None:
        """
        Check if process has exited and update status if so.

        Returns:
            exit_code if exited, None if still running
        """
        from django.utils import timezone

        if self.status == self.StatusChoices.EXITED:
            return self.exit_code

        if not self.is_alive():
            # Process exited - read output and update status
            if self.stdout_file.exists():
                self.stdout = self.stdout_file.read_text()
            if self.stderr_file.exists():
                self.stderr = self.stderr_file.read_text()

            # Try to get exit code from pid file or default to unknown
            self.exit_code = self.exit_code or -1
            self.ended_at = timezone.now()
            self.status = self.StatusChoices.EXITED
            self.save()
            return self.exit_code

        return None  # Still running

    def wait(self, timeout: int | None = None) -> int:
        """
        Wait for process to exit, polling periodically.

        Args:
            timeout: Max seconds to wait (None = use self.timeout)

        Returns:
            exit_code

        Raises:
            TimeoutError if process doesn't exit in time
        """
        import time

        timeout = timeout or self.timeout
        start = time.time()

        while True:
            exit_code = self.poll()
            if exit_code is not None:
                return exit_code

            if time.time() - start > timeout:
                raise TimeoutError(f"Process {self.id} did not exit within {timeout}s")

            time.sleep(0.1)
```

---

## Phase 2: Hook System Changes

### 2.1 Update `run_hook()` to Create Process Records

**File:** `archivebox/hooks.py`

Current implementation creates `subprocess.Popen` directly. Refactor to:

1. Accept an optional `parent_process` parameter
2. Create a `Process` record for the hook script
3. Create a separate `Process` record for the binary (if hook reports one)

```python
def run_hook(
    script: Path,
    output_dir: Path,
    config: Dict[str, Any],
    timeout: Optional[int] = None,
    parent_process: Optional['Process'] = None,  # NEW
    **kwargs: Any
) -> HookResult:
    """
    Execute a hook script with the given arguments.

    Now creates Process records for tracking:
    - One Process for the hook script itself
    - Child Process records for any binaries the hook reports running
    """
    from archivebox.machine.models import Process, Machine

    # ... existing setup code ...

    # Create Process record for this hook
    hook_process = Process.objects.create(
        machine=Machine.current(),
        parent=parent_process,
        process_type=Process.TypeChoices.HOOK,
        cmd=cmd,
        pwd=str(output_dir),
        env=env,  # Store sanitized env
        timeout=timeout,
        status=Process.StatusChoices.QUEUED,
    )

    # Launch the hook
    hook_process.launch(background=is_background_hook)

    # ... rest of processing ...

    return HookResult(
        # ... existing fields ...
        process_id=str(hook_process.id),  # NEW: include process ID
    )
```

### 2.2 Update HookResult TypedDict

```python
class HookResult(TypedDict, total=False):
    """Raw result from run_hook()."""
    returncode: int
    stdout: str
    stderr: str
    output_json: Optional[Dict[str, Any]]
    output_files: List[str]
    duration_ms: int
    hook: str
    plugin: str
    hook_name: str
    records: List[Dict[str, Any]]
    process_id: str  # NEW: ID of the hook Process record
```

### 2.3 Handle Binary Process Records from Hook Output

Hooks can output JSONL records describing binaries they run. Parse these and create child `Process` records:

```python
def process_hook_binary_records(
    hook_process: 'Process',
    records: List[Dict[str, Any]]
) -> List['Process']:
    """
    Create child Process records for binaries reported by hook.

    Hooks output JSONL like:
        {"type": "Process", "cmd": ["wget", "-p", "..."], "exit_code": 0}
    """
    from archivebox.machine.models import Process

    binary_processes = []

    for record in records:
        if record.get('type') != 'Process':
            continue

        binary_process = Process.objects.create(
            machine=hook_process.machine,
            parent=hook_process,
            process_type=Process.TypeChoices.BINARY,
            cmd=record.get('cmd', []),
            pwd=record.get('pwd', hook_process.pwd),
            pid=record.get('pid'),
            exit_code=record.get('exit_code'),
            stdout=record.get('stdout', ''),
            stderr=record.get('stderr', ''),
            started_at=parse_datetime(record.get('started_at')),
            ended_at=parse_datetime(record.get('ended_at')),
            status=Process.StatusChoices.EXITED,
        )
        binary_processes.append(binary_process)

    return binary_processes
```

---

## Phase 3: Worker System Changes

### 3.1 Track Worker Processes in Database (Simplified with Process.current())

**File:** `archivebox/workers/worker.py`

With `Process.current()`, tracking becomes trivial:

```python
class Worker:
    # ... existing code ...

    db_process: 'Process | None' = None  # Database Process record

    def on_startup(self) -> None:
        """Called when worker starts."""
        from archivebox.machine.models import Process

        self.pid = os.getpid()
        self.pid_file = write_pid_file(self.name, self.worker_id)

        # Process.current() automatically:
        # - Creates record with correct process_type (detected from sys.argv)
        # - Finds parent via PPID (orchestrator)
        # - Sets machine, pid, started_at, status
        self.db_process = Process.current()

        # ... existing logging ...

    # _get_parent_process() NO LONGER NEEDED - Process.current() uses PPID

    def on_shutdown(self, error: BaseException | None = None) -> None:
        """Called when worker shuts down."""
        # ... existing code ...

        # Update database Process record
        if self.db_process:
            self.db_process.exit_code = 0 if error is None else 1
            self.db_process.ended_at = timezone.now()
            self.db_process.status = Process.StatusChoices.EXITED
            if error:
                self.db_process.stderr = str(error)
            self.db_process.save()
```

### 3.2 Track Orchestrator Process (Simplified)

**File:** `archivebox/workers/orchestrator.py`

```python
class Orchestrator:
    # ... existing code ...

    db_process: 'Process | None' = None

    def on_startup(self) -> None:
        """Called when orchestrator starts."""
        from archivebox.machine.models import Process

        self.pid = os.getpid()
        self.pid_file = write_pid_file('orchestrator', worker_id=0)

        # Process.current() handles everything:
        # - Detects type as ORCHESTRATOR from "orchestrator" in sys.argv
        # - Finds parent (supervisord) via PPID lookup
        self.db_process = Process.current()

        # ... existing logging ...

    # _get_parent_process() NO LONGER NEEDED
```

### 3.3 Track Supervisord Process

**File:** `archivebox/workers/supervisord_util.py`

```python
def start_new_supervisord_process(daemonize=False):
    from archivebox.machine.models import Process, Machine

    # ... existing setup ...

    proc = subprocess.Popen(...)

    # NEW: Create database Process record for supervisord
    db_process = Process.objects.create(
        machine=Machine.current(),
        parent=get_cli_process(),  # Find the CLI command's Process
        process_type=Process.TypeChoices.SUPERVISORD,
        cmd=['supervisord', f'--configuration={CONFIG_FILE}'],
        pwd=str(CONSTANTS.DATA_DIR),
        pid=proc.pid,
        started_at=timezone.now(),
        status=Process.StatusChoices.RUNNING,
    )

    # Store reference for later cleanup
    global _supervisord_db_process
    _supervisord_db_process = db_process

    # ... rest of function ...
```

---

## Phase 4: CLI Entry Point Changes

### 4.1 Simplified: Just Call `Process.current()`

With `Process.current()` implemented, CLI entry becomes trivial:

**File:** `archivebox/__main__.py` or `archivebox/cli/__init__.py`

```python
def main():
    from archivebox.machine.models import Process

    # Process.current() auto-creates the CLI process record
    # It detects process_type from sys.argv, finds parent via PPID
    cli_process = Process.current()

    try:
        # ... existing CLI dispatch ...
        result = run_cli_command(...)
        cli_process.exit_code = result
    except Exception as e:
        cli_process.exit_code = 1
        cli_process.stderr = str(e)
        raise
    finally:
        cli_process.ended_at = timezone.now()
        cli_process.status = Process.StatusChoices.EXITED
        cli_process.save()
```

**That's it!** No thread-local context needed. `Process.current()` handles:
- Creating the record with correct `process_type`
- Finding parent via PPID lookup
- Caching to avoid repeated queries
- Validating PID hasn't been reused

### 4.2 Context Management (DEPRECATED - Replaced by Process.current())

~~The following is no longer needed since `Process.current()` uses PPID lookup:~~

```python
# archivebox/machine/context.py - NO LONGER NEEDED

# Process.current() replaces all of this by using os.getppid()
# to find parent Process records automatically.

# OLD approach (don't use):
def get_cli_process() -> Optional['Process']:
    """
    Find the CLI process that started this execution.

    Tries:
    1. Thread-local storage (set by main CLI entry point)
    2. Environment variable ARCHIVEBOX_CLI_PROCESS_ID
    3. Query for running CLI process on this machine with matching PPID
    """
    # Try thread-local first
    process = get_current_cli_process()
    if process:
        return process

    # Try environment variable
    import os
    from archivebox.machine.models import Process

    process_id = os.environ.get('ARCHIVEBOX_CLI_PROCESS_ID')
    if process_id:
        try:
            return Process.objects.get(id=process_id)
        except Process.DoesNotExist:
            pass

    # Fallback: find by PPID
    ppid = os.getppid()
    return Process.objects.filter(
        pid=ppid,
        process_type=Process.TypeChoices.CLI,
        status=Process.StatusChoices.RUNNING,
    ).first()
```

---

## Phase 5: ArchiveResult Integration

### 5.1 Update ArchiveResult.run() to Pass Parent Process

**File:** `archivebox/core/models.py`

```python
class ArchiveResult(ModelWithOutputDir, ...):
    def run(self):
        """Execute this ArchiveResult's hook and update status."""
        from archivebox.hooks import run_hook

        # ... existing setup ...

        for hook in hooks:
            result = run_hook(
                hook,
                output_dir=plugin_dir,
                config=config,
                parent_process=self.process,  # NEW: pass our Process as parent
                url=self.snapshot.url,
                snapshot_id=str(self.snapshot.id),
                crawl_id=str(self.snapshot.crawl.id),
                depth=self.snapshot.depth,
            )

            # ... rest of processing ...
```

### 5.2 Update ArchiveResult.save() to Link Worker Process

```python
class ArchiveResult(ModelWithOutputDir, ...):
    def save(self, *args, **kwargs):
        is_new = self._state.adding

        if is_new and not self.process_id:
            from archivebox.machine.models import Process, Machine
            from archivebox.machine.context import get_current_worker_process

            # Get the worker's Process as parent
            worker_process = get_current_worker_process()

            process = Process.objects.create(
                machine=Machine.current(),
                parent=worker_process,  # NEW: link to worker
                process_type=Process.TypeChoices.HOOK,  # Will become HOOK when run
                pwd=str(Path(self.snapshot.output_dir) / self.plugin),
                cmd=[],
                status='queued',
                timeout=120,
                env={},
            )
            self.process = process

        # ... rest of save ...
```

---

## Phase 6: Migration

### 6.1 Create Migration File

```python
# archivebox/machine/migrations/XXXX_add_process_parent_and_type.py

from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('machine', 'XXXX_previous_migration'),
    ]

    operations = [
        # Add parent FK
        migrations.AddField(
            model_name='process',
            name='parent',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='children',
                to='machine.process',
            ),
        ),

        # Add process_type field
        migrations.AddField(
            model_name='process',
            name='process_type',
            field=models.CharField(
                choices=[
                    ('cli', 'CLI Command'),
                    ('supervisord', 'Supervisord Daemon'),
                    ('orchestrator', 'Orchestrator'),
                    ('worker', 'Worker Process'),
                    ('hook', 'Hook Script'),
                    ('binary', 'Binary Execution'),
                ],
                default='binary',
                max_length=16,
                db_index=True,
            ),
        ),

        # Add index for parent queries
        migrations.AddIndex(
            model_name='process',
            index=models.Index(
                fields=['parent', 'status'],
                name='machine_pro_parent__idx',
            ),
        ),
    ]
```

---

## Phase 7: Admin UI Updates

### 7.1 Update Process Admin

**File:** `archivebox/machine/admin.py`

```python
@admin.register(Process)
class ProcessAdmin(admin.ModelAdmin):
    list_display = ['id', 'process_type', 'cmd_summary', 'status', 'parent_link', 'started_at', 'duration']
    list_filter = ['process_type', 'status', 'machine']
    search_fields = ['cmd', 'stdout', 'stderr']
    readonly_fields = ['parent', 'children_count', 'depth', 'tree_view']

    def cmd_summary(self, obj):
        """Show first 50 chars of command."""
        cmd_str = ' '.join(obj.cmd[:3]) if obj.cmd else ''
        return cmd_str[:50] + '...' if len(cmd_str) > 50 else cmd_str

    def parent_link(self, obj):
        if obj.parent:
            url = reverse('admin:machine_process_change', args=[obj.parent.pk])
            return format_html('<a href="{}">{}</a>', url, obj.parent.process_type)
        return '-'

    def children_count(self, obj):
        return obj.children.count()

    def depth(self, obj):
        return obj.depth

    def duration(self, obj):
        if obj.started_at and obj.ended_at:
            delta = obj.ended_at - obj.started_at
            return f'{delta.total_seconds():.1f}s'
        elif obj.started_at:
            delta = timezone.now() - obj.started_at
            return f'{delta.total_seconds():.1f}s (running)'
        return '-'

    def tree_view(self, obj):
        """Show process tree from root to this process."""
        ancestors = obj.ancestors[::-1]  # Reverse to show root first
        lines = []
        for i, ancestor in enumerate(ancestors):
            prefix = '  ' * i + '└── ' if i > 0 else ''
            lines.append(f'{prefix}{ancestor.process_type}: {ancestor.cmd[0] if ancestor.cmd else "?"} (pid={ancestor.pid})')
        prefix = '  ' * len(ancestors) + '└── ' if ancestors else ''
        lines.append(f'{prefix}[CURRENT] {obj.process_type}: {obj.cmd[0] if obj.cmd else "?"} (pid={obj.pid})')
        return format_html('<pre>{}</pre>', '\n'.join(lines))
```

---

## Files to Modify Summary

| File | Changes |
|------|---------|
| `archivebox/machine/models.py` | Add `parent` FK, `process_type` field, `Process.current()`, lifecycle methods |
| `archivebox/machine/migrations/XXXX_*.py` | New migration for schema changes |
| `archivebox/machine/admin.py` | Update admin with tree visualization |
| `archivebox/hooks.py` | Update `run_hook()` to create/use Process records |
| `archivebox/workers/worker.py` | Simplify: just call `Process.current()` in `on_startup()` |
| `archivebox/workers/orchestrator.py` | Simplify: just call `Process.current()` in `on_startup()` |
| `archivebox/workers/supervisord_util.py` | Add `Process.current()` call when starting supervisord |
| `archivebox/core/models.py` | Update ArchiveResult to use `Process.current()` as parent |
| `archivebox/__main__.py` or CLI entry | Call `Process.current()` at startup, update on exit |
| `archivebox/misc/process_utils.py` | Keep as low-level utilities (called by Process methods) |

**Note:** `archivebox/machine/context.py` is NOT needed - `Process.current()` uses PPID lookup instead of thread-local context.

---

## Testing Plan

### Unit Tests

1. **Process hierarchy creation**
   - Create nested Process records
   - Verify `parent`, `ancestors`, `depth`, `root` properties
   - Test `get_descendants()` query

2. **Process lifecycle**
   - Test `launch()` for foreground and background processes
   - Test `is_alive()`, `poll()`, `wait()`, `kill()`
   - Verify status transitions

3. **Hook integration**
   - Mock hook execution
   - Verify hook Process and binary Process records created
   - Test parent-child relationships

### Integration Tests

1. **Full CLI flow**
   - Run `archivebox add https://example.com`
   - Verify complete Process tree from CLI → workers → hooks → binaries
   - Check all status fields updated correctly

2. **Worker lifecycle**
   - Start orchestrator
   - Verify orchestrator and worker Process records
   - Stop and verify cleanup

---

## Rollout Strategy

1. **Phase 1-2**: Model changes + migration (backwards compatible, new fields nullable)
2. **Phase 3**: Worker tracking (can be feature-flagged)
3. **Phase 4**: CLI entry point (can be feature-flagged)
4. **Phase 5-6**: Full integration (requires all previous phases)
5. **Phase 7**: Admin UI (depends on model changes only)

---

## Open Questions

1. **Performance**: Deep hierarchies with many children could slow queries. Consider:
   - Adding `root_id` denormalized field for fast root lookup
   - Using django-mptt or django-treebeard for efficient tree queries
   - Limiting depth to prevent runaway recursion

2. **Cleanup**: How long to retain Process records?
   - Add `archivebox manage cleanup_processes --older-than=30d`
   - Or automatic cleanup via Django management command

3. **Stdout/Stderr storage**: For large outputs, consider:
   - Storing in files and keeping path in DB
   - Truncating to first/last N bytes
   - Compressing before storage

4. **Cross-machine hierarchies**: If processes span machines (distributed setup):
   - Parent could be on different machine
   - May need to relax FK constraint or use soft references
