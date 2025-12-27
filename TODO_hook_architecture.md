# ArchiveBox Hook Architecture

## Core Design Pattern

**CRITICAL**: All hooks must follow this unified architecture. This pattern applies to ALL models: Crawl, Dependency, Snapshot, ArchiveResult, etc.

### The Flow

```
1. Model.run() discovers and executes hooks
2. Hooks emit JSONL to stdout
3. Model.run() parses JSONL and creates DB records
4. New DB records trigger their own Model.run()
5. Cycle repeats
```

**Example Flow:**
```
Crawl.run()
  → runs on_Crawl__* hooks
  → hooks emit JSONL: {type: 'Dependency', bin_name: 'wget', ...}
  → Crawl.run() creates Dependency record in DB
  → Dependency.run() is called automatically
    → runs on_Dependency__* hooks
    → hooks emit JSONL: {type: 'InstalledBinary', name: 'wget', ...}
    → Dependency.run() creates InstalledBinary record in DB
```

### Golden Rules

1. **Model.run() executes hooks directly** - No helper methods in statemachines. Statemachine just calls Model.run().

2. **Hooks emit JSONL** - Any line starting with `{` that has a `type` field creates/updates that model.
   ```python
   print(json.dumps({'type': 'Dependency', 'bin_name': 'wget', ...}))
   print(json.dumps({'type': 'InstalledBinary', 'name': 'wget', ...}))
   ```

3. **JSONL fields = Model fields** - JSONL keys must match Django model field names exactly. No transformation.
   ```python
   # ✅ CORRECT - matches Dependency model
   {'type': 'Dependency', 'bin_name': 'wget', 'bin_providers': 'apt,brew', 'overrides': {...}}

   # ❌ WRONG - uses different field names
   {'type': 'Dependency', 'name': 'wget', 'providers': 'apt,brew', 'custom_cmds': {...}}
   ```

4. **No hardcoding** - Never hardcode binary names, provider names, or anything else. Use discovery.
   ```python
   # ✅ CORRECT - discovers all on_Dependency hooks dynamically
   run_hooks(event_name='Dependency', ...)

   # ❌ WRONG - hardcodes provider list
   for provider in ['pip', 'npm', 'apt', 'brew']:
       run_hooks(event_name=f'Dependency__install_using_{provider}_provider', ...)
   ```

5. **Trust abx-pkg** - Never use `shutil.which()`, `subprocess.run([bin, '--version'])`, or manual hash calculation.
   ```python
   # ✅ CORRECT - abx-pkg handles everything
   from abx_pkg import Binary, PipProvider, EnvProvider
   binary = Binary(name='wget', binproviders=[PipProvider(), EnvProvider()]).load()
   # binary.abspath, binary.version, binary.sha256 are all populated automatically

   # ❌ WRONG - manual detection
   abspath = shutil.which('wget')
   version = subprocess.run(['wget', '--version'], ...).stdout
   ```

6. **Hooks check if they can handle requests** - Each hook decides internally if it can handle the dependency.
   ```python
   # In on_Dependency__install_using_pip_provider.py
   if bin_providers != '*' and 'pip' not in bin_providers.split(','):
       sys.exit(0)  # Can't handle this, exit cleanly
   ```

7. **Minimal transformation** - Statemachine/Model.run() should do minimal JSONL parsing, just create records.
   ```python
   # ✅ CORRECT - simple JSONL parsing
   obj = json.loads(line)
   if obj.get('type') == 'Dependency':
       Dependency.objects.create(**obj)

   # ❌ WRONG - complex transformation logic
   if obj.get('type') == 'Dependency':
       dep = Dependency.objects.create(name=obj['bin_name'])  # renaming fields
       dep.custom_commands = transform_overrides(obj['overrides'])  # transforming data
   ```

### Pattern Consistency

Follow the same pattern as `ArchiveResult.run()` (archivebox/core/models.py:1030):

```python
def run(self):
    """Execute this Model by running hooks and processing JSONL output."""

    # 1. Discover hooks
    hook = discover_hook_for_model(self)

    # 2. Run hook
    results = run_hook(hook, output_dir=..., ...)

    # 3. Parse JSONL and update self
    for line in results['stdout'].splitlines():
        obj = json.loads(line)
        if obj.get('type') == self.__class__.__name__:
            self.status = obj.get('status')
            self.output = obj.get('output')
            # ... apply other fields

    # 4. Create side-effect records
    for line in results['stdout'].splitlines():
        obj = json.loads(line)
        if obj.get('type') != self.__class__.__name__:
            create_record_from_jsonl(obj)  # Creates InstalledBinary, etc.

    self.save()
```

### Validation Hook Pattern (on_Crawl__00_validate_*.py)

**Purpose**: Check if binary exists, emit Dependency if not found.

```python
#!/usr/bin/env python3
import sys
import json

def find_wget() -> dict | None:
    """Find wget binary using abx-pkg."""
    try:
        from abx_pkg import Binary, AptProvider, BrewProvider, EnvProvider

        binary = Binary(name='wget', binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
        loaded = binary.load()
        if loaded and loaded.abspath:
            return {
                'name': 'wget',
                'abspath': str(loaded.abspath),
                'version': str(loaded.version) if loaded.version else None,
                'sha256': loaded.sha256 if hasattr(loaded, 'sha256') else None,
                'binprovider': loaded.binprovider.name if loaded.binprovider else 'env',
            }
    except Exception:
        pass

    return None

def main():
    result = find_wget()

    if result and result.get('abspath'):
        # Binary found - emit InstalledBinary and Machine config
        print(json.dumps({
            'type': 'InstalledBinary',
            'name': result['name'],
            'abspath': result['abspath'],
            'version': result['version'],
            'sha256': result['sha256'],
            'binprovider': result['binprovider'],
        }))

        print(json.dumps({
            'type': 'Machine',
            '_method': 'update',
            'key': 'config/WGET_BINARY',
            'value': result['abspath'],
        }))

        sys.exit(0)
    else:
        # Binary not found - emit Dependency
        print(json.dumps({
            'type': 'Dependency',
            'bin_name': 'wget',
            'bin_providers': 'apt,brew,env',
            'overrides': {},  # Empty if no special install requirements
        }))
        print(f"wget binary not found", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
```

**Rules:**
- ✅ Use `Binary(...).load()` from abx-pkg - handles finding binary, version, hash automatically
- ✅ Emit `InstalledBinary` JSONL if found
- ✅ Emit `Dependency` JSONL if not found
- ✅ Use `overrides` field matching abx-pkg format: `{'pip': {'packages': ['pkg']}, 'apt': {'packages': ['pkg']}}`
- ❌ NEVER use `shutil.which()`, `subprocess.run()`, manual version detection, or hash calculation
- ❌ NEVER call package managers (apt, brew, pip, npm) directly

### Dependency Installation Pattern (on_Dependency__install_*.py)

**Purpose**: Install binary if not already installed.

```python
#!/usr/bin/env python3
import json
import sys
import rich_click as click
from abx_pkg import Binary, PipProvider

@click.command()
@click.option('--dependency-id', required=True)
@click.option('--bin-name', required=True)
@click.option('--bin-providers', default='*')
@click.option('--overrides', default=None, help="JSON-encoded overrides dict")
def main(dependency_id: str, bin_name: str, bin_providers: str, overrides: str | None):
    """Install binary using pip."""

    # Check if this hook can handle this dependency
    if bin_providers != '*' and 'pip' not in bin_providers.split(','):
        click.echo(f"pip provider not allowed for {bin_name}", err=True)
        sys.exit(0)  # Exit cleanly - not an error, just can't handle

    # Parse overrides
    overrides_dict = None
    if overrides:
        try:
            full_overrides = json.loads(overrides)
            overrides_dict = full_overrides.get('pip', {})  # Extract pip section
        except json.JSONDecodeError:
            pass

    # Install using abx-pkg
    provider = PipProvider()
    try:
        binary = Binary(name=bin_name, binproviders=[provider], overrides=overrides_dict or {}).install()
    except Exception as e:
        click.echo(f"pip install failed: {e}", err=True)
        sys.exit(1)

    if not binary.abspath:
        sys.exit(1)

    # Emit InstalledBinary JSONL
    print(json.dumps({
        'type': 'InstalledBinary',
        'name': bin_name,
        'abspath': str(binary.abspath),
        'version': str(binary.version) if binary.version else '',
        'sha256': binary.sha256 or '',
        'binprovider': 'pip',
        'dependency_id': dependency_id,
    }))

    sys.exit(0)

if __name__ == '__main__':
    main()
```

**Rules:**
- ✅ Check `bin_providers` parameter - exit cleanly (code 0) if can't handle
- ✅ Parse `overrides` parameter as full dict, extract your provider's section
- ✅ Use `Binary(...).install()` from abx-pkg - handles actual installation
- ✅ Emit `InstalledBinary` JSONL on success
- ❌ NEVER hardcode provider names in Model.run() or anywhere else
- ❌ NEVER skip the bin_providers check

### Model.run() Pattern

```python
class Dependency(models.Model):
    def run(self):
        """Execute dependency installation by running all on_Dependency hooks."""
        import json
        from pathlib import Path
        from django.conf import settings

        # Check if already installed
        if self.is_installed:
            return self.installed_binaries.first()

        from archivebox.hooks import run_hooks

        # Create output directory
        DATA_DIR = getattr(settings, 'DATA_DIR', Path.cwd())
        output_dir = Path(DATA_DIR) / 'tmp' / f'dependency_{self.id}'
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build kwargs for hooks
        hook_kwargs = {
            'dependency_id': str(self.id),
            'bin_name': self.bin_name,
            'bin_providers': self.bin_providers,
            'overrides': json.dumps(self.overrides) if self.overrides else None,
        }

        # Run ALL on_Dependency hooks - each decides if it can handle this
        results = run_hooks(
            event_name='Dependency',
            output_dir=output_dir,
            timeout=600,
            **hook_kwargs
        )

        # Process results - parse JSONL and create InstalledBinary records
        for result in results:
            if result['returncode'] != 0:
                continue

            for line in result['stdout'].strip().split('\n'):
                if not line.strip():
                    continue

                try:
                    obj = json.loads(line)
                    if obj.get('type') == 'InstalledBinary':
                        # Create InstalledBinary record - fields match JSONL exactly
                        if not obj.get('name') or not obj.get('abspath') or not obj.get('version'):
                            continue

                        machine = Machine.current()
                        installed_binary, _ = InstalledBinary.objects.update_or_create(
                            machine=machine,
                            name=obj['name'],
                            defaults={
                                'abspath': obj['abspath'],
                                'version': obj['version'],
                                'sha256': obj.get('sha256') or '',
                                'binprovider': obj.get('binprovider') or 'env',
                                'dependency': self,
                            }
                        )

                        if self.is_installed:
                            return installed_binary

                except json.JSONDecodeError:
                    continue

        return None
```

**Rules:**
- ✅ Use `run_hooks(event_name='ModelName', ...)` with model name
- ✅ Pass all relevant data as kwargs (will become --cli-args for hooks)
- ✅ Parse JSONL output directly - each line is a potential record
- ✅ Create records using JSONL fields directly - no transformation
- ✅ Let hooks decide if they can handle the request
- ❌ NEVER hardcode hook names or provider lists
- ❌ NEVER create helper methods for hook execution - just call run_hooks()
- ❌ NEVER transform JSONL data - use it as-is

---

# Background Hooks Implementation Plan

## Overview

This plan implements support for long-running background hooks that run concurrently with other extractors, while maintaining proper result collection, cleanup, and state management.

**Key Changes:**
- Background hooks use `.bg.js`/`.bg.py`/`.bg.sh` suffix
- Hooks output **JSONL** (any line with `{type: 'ModelName', ...}`)
- `run_hook()` is **generic** - just parses JSONL, doesn't know about specific models
- Each `Model.run()` extends records of its own type with computed fields
- ArchiveResult.run() extends ArchiveResult records with `output_files`, `output_size`, etc.
- **No HookResult TypedDict** - just list of dicts with 'type' field
- Binary FK is optional and only set when hook reports cmd
- Split `output` field into `output_str` (human-readable) and `output_json` (structured)
- Add fields: `output_files` (dict), `output_size` (bytes), `output_mimetypes` (CSV)
- External tools (fdupes, ZFS, Btrfs) handle deduplication via filesystem

**New ArchiveResult Fields:**
```python
# Output fields (replace old 'output' field)
output_str = TextField()           # Human-readable summary: "Downloaded 5 files"
output_json = JSONField()          # Structured metadata (headers, redirects, etc.)
output_files = JSONField()         # Dict: {'index.html': {}, 'style.css': {}}
output_size = BigIntegerField()    # Total bytes across all files
output_mimetypes = CharField()     # CSV sorted by size: "text/html,text/css,image/png"
```

**output_files Structure:**
- **Dict keyed by relative path** (not a list!)
- Values are empty dicts `{}` for now, extensible for future metadata
- Preserves insertion order (Python 3.7+)
- Easy to query: `ArchiveResult.objects.filter(output_files__has_key='index.html')`
- Easy to extend: Add `size`, `hash`, `mime_type` to values later without migration
- **Why not derive size/mimetypes from output_files?** Performance. Total size and mimetype summary are accessed frequently (admin views, sorting, filtering). Aggregating on every access would be slow. We keep summary fields (output_size, output_mimetypes) as denormalized cache for fast reads.

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
        # Add new fields (keep old 'output' temporarily for migration)
        migrations.AddField(
            model_name='archiveresult',
            name='output_str',
            field=models.TextField(
                blank=True,
                help_text='Human-readable output summary (e.g., "Downloaded 5 files")'
            ),
        ),

        migrations.AddField(
            model_name='archiveresult',
            name='output_json',
            field=models.JSONField(
                null=True,
                blank=True,
                help_text='Structured metadata (headers, redirects, etc.) - should NOT duplicate ArchiveResult fields'
            ),
        ),

        migrations.AddField(
            model_name='archiveresult',
            name='output_files',
            field=models.JSONField(
                default=dict,
                help_text='Dict of {relative_path: {metadata}} - values are empty dicts for now, extensible for future metadata'
            ),
        ),

        migrations.AddField(
            model_name='archiveresult',
            name='output_size',
            field=models.BigIntegerField(
                default=0,
                help_text='Total recursive size in bytes of all output files'
            ),
        ),

        migrations.AddField(
            model_name='archiveresult',
            name='output_mimetypes',
            field=models.CharField(
                max_length=512,
                blank=True,
                help_text='CSV of mimetypes sorted by size descending'
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

### Data Migration for Existing `.output` Field

```python
# archivebox/core/migrations/00XX_migrate_output_field.py

from django.db import migrations
import json

def migrate_output_field(apps, schema_editor):
    """
    Migrate existing 'output' field to new split fields.

    Logic:
    - If output contains JSON {...}, move to output_json
    - If output is a file path and exists in output_files, ensure it's first
    - Otherwise, move to output_str
    """
    ArchiveResult = apps.get_model('core', 'ArchiveResult')

    for ar in ArchiveResult.objects.all():
        old_output = ar.output or ''

        # Case 1: JSON output
        if old_output.strip().startswith('{'):
            try:
                parsed = json.loads(old_output)
                ar.output_json = parsed
                ar.output_str = ''
            except json.JSONDecodeError:
                # Not valid JSON, treat as string
                ar.output_str = old_output

        # Case 2: File path (check if it looks like a relative path)
        elif '/' in old_output or '.' in old_output:
            # Might be a file path - if it's in output_files, it's already there
            # output_files is now a dict, so no reordering needed
            ar.output_str = old_output  # Keep as string for display

        # Case 3: Plain string summary
        else:
            ar.output_str = old_output

        ar.save(update_fields=['output_str', 'output_json', 'output_files'])

def reverse_migrate(apps, schema_editor):
    """Reverse migration - copy output_str back to output."""
    ArchiveResult = apps.get_model('core', 'ArchiveResult')

    for ar in ArchiveResult.objects.all():
        ar.output = ar.output_str or ''
        ar.save(update_fields=['output'])

class Migration(migrations.Migration):
    dependencies = [
        ('core', '00XX_archiveresult_background_hooks'),
    ]

    operations = [
        migrations.RunPython(migrate_output_field, reverse_migrate),

        # Now safe to remove old 'output' field
        migrations.RemoveField(
            model_name='archiveresult',
            name='output',
        ),
    ]
```


---

## Phase 2: Hook Output Format Specification

### Hooks emit single JSON object to stdout

**Contract:**
- Hook scripts must be executable (chmod +x) and specify their interpreter at the top with a /usr/bin/env shebang line
- Hook emits ONE JSON object with `type: 'ArchiveResult'`
- Hook can provide: `status`, `output_str`, `output_json`, `cmd` (optional)
- Hook should NOT set: `output_files`, `output_size`, `output_mimetypes` (runner calculates these)
- `output_json` should NOT duplicate ArchiveResult fields (no `status`, `start_ts`, etc. in output_json)
- Runner calculates: `output_files`, `output_size`, `output_mimetypes`, `start_ts`, `end_ts`, `binary` FK

**Example outputs:**

```javascript
// Simple string output
console.log(JSON.stringify({
    type: 'ArchiveResult',
    output_str: 'This is the page title',
}));

// With structured metadata and optional fields (headers, redirects, etc.)
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',
    output_str: 'Got https://example.com headers',
    output_json: {'content-type': 'text/html', 'server': 'nginx', 'status-code': 200, 'content-length': 234235},
}));

// With explicit cmd (cmd first arg should match InstalledBinary.bin_abspath or XYZ_BINARY env var so ArchiveResult.run() can FK to the InstalledBinary)
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',
    output_str: 'Archived with wget',
    cmd: ['/some/abspath/to/wget', '-p', '-k', 'https://example.com']
}));

// BAD: Don't duplicate ArchiveResult fields in output_json
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',
    output_json: {
        status: 'succeeded',     // ❌ BAD - this should be up a level on ArchiveResult.status, not inside output_json
        title: 'the page title', // ❌ BAD - if the extractor's main output is just a string then it belongs in output_str
        custom_data: 1234,       // ✅ GOOD - custom fields only
    },
    output_files: {'index.html': {}},  // ❌ BAD - runner calculates this for us, no need to return it manually
}));
```

---

## Phase 3: Architecture - Generic run_hook()

`run_hook()` is a generic JSONL parser - it doesn't know about ArchiveResult, InstalledBinary, or any specific model. It just:
1. Executes the hook script
2. Parses JSONL output (any line starting with `{` that has a `type` field)
3. Adds metadata about plugin and hook path
4. Returns list of dicts

```python
# archivebox/hooks.py

def run_hook(
    script: Path,
    output_dir: Path,
    timeout: int = 300,
    config_objects: Optional[List[Any]] = None,
    **kwargs: Any
) -> Optional[List[dict]]:
    """
    Execute a hook script and parse JSONL output.

    This function is generic and doesn't know about specific model types.
    It just executes the script and parses any JSONL lines with 'type' field.

    Each Model.run() method handles its own record types differently:
    - ArchiveResult.run() extends ArchiveResult records with computed fields
    - Dependency.run() creates InstalledBinary records from hook output
    - Crawl.run() can create Dependency records, Snapshots, or InstalledBinary records from hook output

    Returns:
        List of dicts with 'type' field, each extended with metadata:
        [
            {
                'type': 'ArchiveResult',
                'status': 'succeeded',
                'plugin': 'wget',
                'plugin_hook': 'archivebox/plugins/wget/on_Snapshot__21_wget.py',
                'output_str': '...',
                # ... other hook-reported fields
            },
            {
                'type': 'InstalledBinary',
                'name': 'wget',
                'plugin': 'wget',
                'plugin_hook': 'archivebox/plugins/wget/on_Snapshot__21_wget.py',
                # ... other hook-reported fields
            }
        ]

        None if background hook (still running)
    """
```

**Key Insight:** Hooks output JSONL. Any line with `{type: 'ModelName', ...}` creates/updates that model. The `type` field determines what gets created. Each Model.run() method decides how to handle records of its own type.

### Helper: create_model_record()

```python
# archivebox/hooks.py

def create_model_record(record: dict) -> Any:
    """
    Generic helper to create/update model instances from hook output.

    Args:
        record: Dict with 'type' field and model data

    Returns:
        Created/updated model instance
    """
    from machine.models import InstalledBinary, Dependency

    model_type = record.pop('type')

    if model_type == 'InstalledBinary':
        obj, created = InstalledBinary.objects.get_or_create(**record)  # if model requires custom logic implement InstalledBinary.from_jsonl(**record)
        return obj
    elif model_type == 'Dependency':
        obj, created = Dependency.objects.get_or_create(**record)
        return obj
    # ... Snapshot, ArchiveResult, etc. add more types as needed
    else:
        raise ValueError(f"Unknown record type: {model_type}")
```

---

## Phase 4: Plugin Audit & Standardization

**CRITICAL:** This phase MUST be done FIRST, before updating core code. Do this manually, one plugin at a time. Do NOT batch-update multiple plugins at once. Do NOT skip any plugins or checks.

**Why First?** Updating plugins to output clean JSONL before changing core code means the transition is safe and incremental. The current run_hook() can continue to work during the plugin updates.

### 4.1 Install Hook Standardization

All plugins should follow a consistent pattern for checking and declaring dependencies.

#### Hook Naming Convention

**RENAME ALL HOOKS:**
- ❌ OLD: `on_Crawl__*_validate_*.{sh,py,js}`
- ✅ NEW: `on_Crawl__*_install_*.{sh,py,js}`

Rationale: "install" is clearer than "validate" for what these hooks actually do.

#### Standard Install Hook Pattern

**ALL install hooks MUST follow this pattern:**

1. ✅ Check if InstalledBinary already exists for the configured binary
2. ✅ If NOT found, emit a Dependency JSONL record, with overrides if you need to customize install process
3. ❌ NEVER directly call npm, apt, brew, pip, or any package manager
4. ✅ Let bin provider plugins handle actual installation

**Example Standard Pattern:**

```python
#!/usr/bin/env python3
"""
Check for wget binary and emit Dependency if not found.
"""
import os
import sys
import json
from pathlib import Path

def main():
    # 1. Get configured binary name/path from env
    binary_path = os.environ.get('WGET_BINARY', 'wget')

    # 2. Check if InstalledBinary exists for this binary
    # (In practice, this check happens via database query in the actual implementation)
    # For install hooks, we emit a Dependency that the system will process

    # 3. Emit Dependency JSONL if needed
    # The bin provider will check InstalledBinary and install if missing
    dependency = {
        'type': 'Dependency',
        'name': 'wget',
        'bin_name': Path(binary_path).name if '/' in binary_path else binary_path,
        'providers': ['apt', 'brew', 'pkg'],  # Priority order
        'abspath': binary_path if binary_path.startswith('/') else None,
    }

    print(json.dumps(dependency))
    return 0

if __name__ == '__main__':
    sys.exit(main())
```

#### Config Variable Handling

**ALL hooks MUST respect user-configured binary paths:**

- ✅ Read `XYZ_BINARY` env var (e.g., `WGET_BINARY`, `YTDLP_BINARY`, `CHROME_BINARY`)
- ✅ Support absolute paths: `WGET_BINARY=/usr/local/bin/wget2`
- ✅ Support bin names: `WGET_BINARY=wget2`
- ✅ Check for the CORRECT binary name in InstalledBinary
- ✅ If user provides `WGET_BINARY=wget2`, check for `wget2` not `wget`

**Example Config Handling:**

```python
# Get configured binary (could be path or name)
binary_path = os.environ.get('WGET_BINARY', 'wget')

# Extract just the binary name for InstalledBinary lookup
if '/' in binary_path:
    # Absolute path: /usr/local/bin/wget2 -> wget2
    bin_name = Path(binary_path).name
else:
    # Just a name: wget2 -> wget2
    bin_name = binary_path

# Now check InstalledBinary for bin_name (not hardcoded 'wget')
```

### 4.2 Snapshot Hook Standardization

All `on_Snapshot__*.*` hooks must follow the output format specified in **Phase 2**. Key points for implementation:

#### Output Format Requirements

**CRITICAL Legacy Issues to Fix:**

1. ❌ **Remove `RESULT_JSON=` prefix** - old hooks use `console.log('RESULT_JSON=' + ...)`
2. ❌ **Remove extra output lines** - old hooks print VERSION=, START_TS=, END_TS=, STATUS=, OUTPUT=
3. ❌ **Remove `--version` calls** - hooks should NOT run binary version checks
4. ✅ **Output clean JSONL only** - exactly ONE line: `console.log(JSON.stringify(result))`

**Before (WRONG):**
```javascript
console.log(`VERSION=${version}`);
console.log(`START_TS=${startTime.toISOString()}`);
console.log(`RESULT_JSON=${JSON.stringify(result)}`);
```

**After (CORRECT):**
```javascript
console.log(JSON.stringify({type: 'ArchiveResult', status: 'succeeded', output_str: 'Done'}));
```

> **See Phase 2 for complete JSONL format specification and examples.**

#### Using Configured Binaries

**ALL on_Snapshot hooks MUST:**

1. ✅ Read the correct `XYZ_BINARY` env var
2. ✅ Use that binary path/name in their commands
3. ✅ Pass cmd in JSONL output for binary FK lookup

**Example:**

```javascript
// ✅ CORRECT - uses env var
const wgetBinary = process.env.WGET_BINARY || 'wget';
const cmd = [wgetBinary, '-p', '-k', url];

// Execute command...
const result = execSync(cmd.join(' '));

// Report cmd in output for binary FK
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',
    output_str: 'Downloaded page',
    cmd: cmd,  // ✅ Includes configured binary
}));
```

```javascript
// ❌ WRONG - hardcoded binary name
const cmd = ['wget', '-p', '-k', url];  // Ignores WGET_BINARY
```

### 4.3 Per-Plugin Checklist

**For EACH plugin, verify ALL of these:**

#### Install Hook Checklist

- [ ] Renamed from `on_Crawl__*_validate_*` to `on_Crawl__*_install_*`
- [ ] Reads `XYZ_BINARY` env var and handles both absolute paths + bin names
- [ ] Emits `{"type": "Dependency", ...}` JSONL (NOT hardcoded to always check for 'wget')
- [ ] Does NOT call npm/apt/brew/pip directly
- [ ] Follows standard pattern from section 4.1

#### Snapshot Hook Checklist

- [ ] Reads correct `XYZ_BINARY` env var and uses it in cmd
- [ ] Outputs EXACTLY ONE JSONL line (NO `RESULT_JSON=` prefix)
- [ ] NO extra output lines (VERSION=, START_TS=, END_TS=, STATUS=, OUTPUT=)
- [ ] Does NOT run `--version` commands
- [ ] Only provides allowed fields (type, status, output_str, output_json, cmd)
- [ ] Does NOT include computed fields (see Phase 2 for forbidden fields list)
- [ ] Includes `cmd` array with configured binary path

### 4.4 Implementation Process

**MANDATORY PROCESS:**

1. ✅ List ALL plugins in archivebox/plugins/
2. ✅ For EACH plugin (DO NOT BATCH):
   a. Read ALL hook files in the plugin directory
   b. Check install hooks against checklist 4.3
   c. Check snapshot hooks against checklist 4.3
   d. Fix issues one by one
   e. Test the plugin hooks
   f. Move to next plugin
3. ❌ DO NOT skip any plugins
4. ❌ DO NOT batch-update multiple plugins
5. ❌ DO NOT assume plugins are similar enough to update together

**Why one-by-one?**
- Each plugin may have unique patterns
- Each plugin may use different languages (sh/py/js)
- Each plugin may have different edge cases
- Batch updates lead to copy-paste errors

### 4.5 Testing Each Plugin

After updating each plugin, verify:

1. ✅ Install hook can be executed: `python3 on_Crawl__01_install_wget.py`
2. ✅ Install hook outputs valid JSONL: `python3 ... | jq .`
3. ✅ Install hook respects `XYZ_BINARY` env var
4. ✅ Snapshot hook can be executed with test URL
5. ✅ Snapshot hook outputs EXACTLY ONE JSONL line
6. ✅ Snapshot hook JSONL parses correctly: `... | jq .type`
7. ✅ Snapshot hook uses configured binary from env

### 4.6 Common Pitfalls

When auditing plugins, watch for these common mistakes:

1. **Hardcoded binary names** - Check `InstalledBinary.filter(name='wget')` → should use configured name
2. **Old output format** - Look for `RESULT_JSON=`, `VERSION=`, `START_TS=` lines
3. **Computed fields in output** - Watch for `output_files`, `start_ts`, `duration` in JSONL
4. **Missing config variables** - Ensure hooks read `XYZ_BINARY` env vars
5. **Version checks** - Remove any `--version` command executions

> See sections 4.1 and 4.2 for detailed before/after examples.

---

## Phase 5: Update run_hook() Implementation

**Note:** Only do this AFTER Phase 4 (plugin standardization) is complete. By then, all plugins will output clean JSONL and this implementation will work smoothly.

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


def run_hook(
    script: Path,
    output_dir: Path,
    timeout: int = 300,
    config_objects: Optional[List[Any]] = None,
    **kwargs: Any
) -> Optional[List[dict]]:
    """
    Execute a hook script and parse JSONL output.

    This is a GENERIC function that doesn't know about specific model types.
    It just executes and parses JSONL (any line with {type: 'ModelName', ...}).

    Runner responsibilities:
    - Detect background hooks (.bg. in filename)
    - Capture stdout/stderr to log files
    - Parse JSONL output and add plugin metadata
    - Clean up log files and PID files

    Hook responsibilities:
    - Emit JSONL: {type: 'ArchiveResult', status, output_str, output_json, cmd}
    - Can emit multiple types: {type: 'InstalledBinary', ...}
    - Write actual output files

    Args:
        script: Path to hook script
        output_dir: Working directory (where output files go)
        timeout: Max execution time in seconds
        config_objects: Config override objects (Machine, Crawl, Snapshot)
        **kwargs: CLI arguments passed to script

    Returns:
        List of dicts with 'type' field for foreground hooks
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

        # Parse ALL JSONL output (any line with {type: 'ModelName', ...})
        records = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith('{'):
                continue
            try:
                data = json.loads(line)
                if 'type' in data:
                    # Add plugin metadata to every record
                    plugin_name = script.parent.name  # Directory name (e.g., 'wget')
                    data['plugin'] = plugin_name
                    data['plugin_hook'] = str(script.relative_to(Path.cwd()))
                    records.append(data)
            except json.JSONDecodeError:
                continue

        # 7. CLEANUP
        # Delete empty logs (keep non-empty for debugging)
        if stdout_file.exists() and stdout_file.stat().st_size == 0:
            stdout_file.unlink()
        if stderr_file.exists() and stderr_file.stat().st_size == 0:
            stderr_file.unlink()

        # Delete ALL .pid files on success
        if returncode == 0:
            for pf in output_dir.glob('*.pid'):
                pf.unlink(missing_ok=True)

        # 8. RETURN RECORDS
        # Returns list of dicts, each with 'type' field and plugin metadata
        return records

    except Exception as e:
        # On error, return empty list (hook failed, no records created)
        return []
```

---

## Phase 6: Update ArchiveResult.run()

**Note:** Only do this AFTER Phase 5 (run_hook() implementation) is complete.

### Location: `archivebox/core/models.py`

```python
def run(self):
    """
    Execute this ArchiveResult's extractor and update status.

    For foreground hooks: Waits for completion and updates immediately
    For background hooks: Returns immediately, leaves status='started'

    This method extends any ArchiveResult records from hook output with
    computed fields (output_files, output_size, binary FK, etc.).
    """
    from django.utils import timezone
    from archivebox.hooks import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR, run_hook, find_binary_for_cmd, create_model_record
    from machine.models import Machine

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

    start_ts = timezone.now()

    # Run the hook (returns list of JSONL records)
    records = run_hook(
        hook,
        output_dir=extractor_dir,
        config_objects=config_objects,
        url=self.snapshot.url,
        snapshot_id=str(self.snapshot.id),
    )

    # BACKGROUND HOOK - still running
    if records is None:
        self.status = self.StatusChoices.STARTED
        self.start_ts = start_ts
        self.pwd = str(extractor_dir)
        self.save()
        return

    # FOREGROUND HOOK - process records
    end_ts = timezone.now()

    # Find the ArchiveResult record (enforce single output)
    ar_records = [r for r in records if r.get('type') == 'ArchiveResult']
    assert len(ar_records) <= 1, f"Hook {hook} output {len(ar_records)} ArchiveResults, expected 0-1"

    if ar_records:
        hook_data = ar_records[0]

        # Apply hook's data
        status_str = hook_data.get('status', 'failed')
        status_map = {
            'succeeded': self.StatusChoices.SUCCEEDED,
            'failed': self.StatusChoices.FAILED,
            'skipped': self.StatusChoices.SKIPPED,
        }
        self.status = status_map.get(status_str, self.StatusChoices.FAILED)

        self.output_str = hook_data.get('output_str', '')
        self.output_json = hook_data.get('output_json')

        # Set extractor from plugin metadata
        self.extractor = hook_data['plugin']

        # Determine binary FK from cmd (ArchiveResult-specific logic)
        if 'cmd' in hook_data:
            self.cmd = json.dumps(hook_data['cmd'])
            machine = Machine.current()
            binary_id = find_binary_for_cmd(hook_data['cmd'], machine.id)
            if binary_id:
                self.binary_id = binary_id
    else:
        # No ArchiveResult output - hook didn't report, treat as failed
        self.status = self.StatusChoices.FAILED
        self.output_str = 'Hook did not output ArchiveResult'

    # Set timestamps and metadata
    self.start_ts = start_ts
    self.end_ts = end_ts
    self.pwd = str(extractor_dir)
    self.retry_at = None

    # POPULATE OUTPUT FIELDS FROM FILESYSTEM (ArchiveResult-specific)
    if extractor_dir.exists():
        self._populate_output_fields(extractor_dir)

    self.save()

    # Create any side-effect records (InstalledBinary, Dependency, etc.)
    for record in records:
        if record['type'] != 'ArchiveResult':
            create_model_record(record)  # Generic helper that dispatches by type

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


def _populate_output_fields(self, output_dir: Path) -> None:
    """
    Walk output directory and populate output_files, output_size, output_mimetypes fields.

    Args:
        output_dir: Directory containing output files
    """
    import mimetypes
    from collections import defaultdict

    exclude_names = {'stdout.log', 'stderr.log', 'hook.pid', 'listener.pid'}

    # Track mimetypes and sizes for aggregation
    mime_sizes = defaultdict(int)
    total_size = 0
    output_files = {}  # Dict keyed by relative path

    for file_path in output_dir.rglob('*'):
        # Skip non-files and infrastructure files
        if not file_path.is_file():
            continue
        if file_path.name in exclude_names:
            continue

        # Get file stats
        stat = file_path.stat()
        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or 'application/octet-stream'

        # Track for ArchiveResult fields
        relative_path = str(file_path.relative_to(output_dir))
        output_files[relative_path] = {}  # Empty dict, extensible for future metadata
        mime_sizes[mime_type] += stat.st_size
        total_size += stat.st_size

    # Populate ArchiveResult fields
    self.output_files = output_files  # Dict preserves insertion order (Python 3.7+)
    self.output_size = total_size

    # Build output_mimetypes CSV (sorted by size descending)
    sorted_mimes = sorted(mime_sizes.items(), key=lambda x: x[1], reverse=True)
    self.output_mimetypes = ','.join(mime for mime, _ in sorted_mimes)
```

### Querying output_files with Django

Since `output_files` is a dict keyed by relative path, you can use Django's JSON field lookups:

```python
# Check if a specific file exists
ArchiveResult.objects.filter(output_files__has_key='index.html')

# Check if any of multiple files exist (OR)
from django.db.models import Q
ArchiveResult.objects.filter(
    Q(output_files__has_key='index.html') |
    Q(output_files__has_key='index.htm')
)

# Get all results that have favicon
ArchiveResult.objects.filter(output_files__has_key='favicon.ico')

# Check in Python (after fetching)
if 'index.html' in archiveresult.output_files:
    print("Found index.html")

# Get list of all paths
paths = list(archiveresult.output_files.keys())

# Count files
file_count = len(archiveresult.output_files)

# Future: When we add metadata, query still works
# output_files = {'index.html': {'size': 4096, 'hash': 'abc...'}}
ArchiveResult.objects.filter(output_files__index_html__size__gt=1000)  # size > 1KB
```

**Structure for Future Extension:**

Current (empty metadata):
```python
{
    'index.html': {},
    'style.css': {},
    'images/logo.png': {}
}
```

Future (with optional metadata):
```python
{
    'index.html': {
        'size': 4096,
        'hash': 'abc123...',
        'mime_type': 'text/html'
    },
    'style.css': {
        'size': 2048,
        'hash': 'def456...',
        'mime_type': 'text/css'
    }
}
```

All existing queries continue to work unchanged - the dict structure is backward compatible.

---

## Phase 7: Background Hook Support

This phase adds support for long-running background hooks that don't block other extractors.

### 7.1 Background Hook Detection

Background hooks are identified by `.bg.` suffix in filename:
- `on_Snapshot__21_consolelog.bg.js` ← background
- `on_Snapshot__11_favicon.js` ← foreground

### 7.2 Rename Background Hooks

**Files to rename:**

```bash
# Use .bg. suffix (not __background)
mv archivebox/plugins/consolelog/on_Snapshot__21_consolelog.js \
   archivebox/plugins/consolelog/on_Snapshot__21_consolelog.bg.js

mv archivebox/plugins/ssl/on_Snapshot__23_ssl.js \
   archivebox/plugins/ssl/on_Snapshot__23_ssl.bg.js

mv archivebox/plugins/responses/on_Snapshot__24_responses.js \
   archivebox/plugins/responses/on_Snapshot__24_responses.bg.js
```

**Update hook content to emit proper JSON:**

Each hook should emit:
```javascript
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status: 'succeeded',  // or 'failed' or 'skipped'
    output_str: 'Captured 15 console messages',  // human-readable summary
    output_json: {  // optional structured metadata
        // ... specific to each hook
    }
}));
```

### 7.3 Finalization Helper Functions

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

    Same logic as ArchiveResult.run() but for background hooks that already started.

    Args:
        archiveresult: ArchiveResult instance to finalize
    """
    from django.utils import timezone
    from machine.models import Machine

    extractor_dir = Path(archiveresult.pwd)
    stdout_file = extractor_dir / 'stdout.log'
    stderr_file = extractor_dir / 'stderr.log'

    # Read logs
    stdout = stdout_file.read_text() if stdout_file.exists() else ''

    # Parse JSONL output (same as run_hook)
    records = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith('{'):
            continue
        try:
            data = json.loads(line)
            if 'type' in data:
                records.append(data)
        except json.JSONDecodeError:
            continue

    # Find the ArchiveResult record
    ar_records = [r for r in records if r.get('type') == 'ArchiveResult']
    assert len(ar_records) <= 1, f"Background hook output {len(ar_records)} ArchiveResults, expected 0-1"

    if ar_records:
        hook_data = ar_records[0]

        # Apply hook's data
        status_str = hook_data.get('status', 'failed')
        status_map = {
            'succeeded': ArchiveResult.StatusChoices.SUCCEEDED,
            'failed': ArchiveResult.StatusChoices.FAILED,
            'skipped': ArchiveResult.StatusChoices.SKIPPED,
        }
        archiveresult.status = status_map.get(status_str, ArchiveResult.StatusChoices.FAILED)

        archiveresult.output_str = hook_data.get('output_str', '')
        archiveresult.output_json = hook_data.get('output_json')

        # Determine binary FK from cmd
        if 'cmd' in hook_data:
            archiveresult.cmd = json.dumps(hook_data['cmd'])
            machine = Machine.current()
            binary_id = find_binary_for_cmd(hook_data['cmd'], machine.id)
            if binary_id:
                archiveresult.binary_id = binary_id
    else:
        # No output = failed
        archiveresult.status = ArchiveResult.StatusChoices.FAILED
        archiveresult.output_str = 'Background hook did not output ArchiveResult'

    archiveresult.end_ts = timezone.now()
    archiveresult.retry_at = None

    # POPULATE OUTPUT FIELDS FROM FILESYSTEM
    if extractor_dir.exists():
        archiveresult._populate_output_fields(extractor_dir)

    archiveresult.save()

    # Create any side-effect records
    for record in records:
        if record['type'] != 'ArchiveResult':
            create_model_record(record)

    # Cleanup
    for pf in extractor_dir.glob('*.pid'):
        pf.unlink(missing_ok=True)
    if stdout_file.exists() and stdout_file.stat().st_size == 0:
        stdout_file.unlink()
    if stderr_file.exists() and stderr_file.stat().st_size == 0:
        stderr_file.unlink()
```

### 7.4 Update SnapshotMachine

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

### 7.5 Deduplication

Deduplication is handled by external filesystem tools like `fdupes` (hardlinks), ZFS dedup, Btrfs duperemove, or rdfind. Users can run these tools periodically on the archive directory to identify and link duplicate files. ArchiveBox doesn't need to track hashes or manage deduplication itself - the filesystem layer handles it transparently.

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
    {"type": "ArchiveResult", "status": "succeeded", "output_str": "test"}
    More output
    '''
    result = parse_hook_output_json(stdout)
    assert result['status'] == 'succeeded'
    assert result['output_str'] == 'test'
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

### Step 2: **Plugin standardization (Phase 4)**
- Update ALL plugins to new JSONL format FIRST
- Test each plugin as you update it
- This ensures old run_hook() can still work during transition

### Step 3: Update run_hook() (Phase 5)
- Add background hook detection
- Add log file capture
- Parse JSONL output (any line with {type: 'ModelName', ...})
- Add plugin and plugin_hook metadata to each record

### Step 4: Update ArchiveResult.run() (Phase 6)
- Handle None result for background hooks (return immediately)
- Parse records list from run_hook()
- Assert only one ArchiveResult record per hook
- Extend ArchiveResult record with computed fields (output_files, output_size, binary FK)
- Call `_populate_output_fields()` to walk directory and populate summary fields
- Call `create_model_record()` for any side-effect records (InstalledBinary, etc.)

### Step 5: Add finalization helpers (Phase 7)
- `find_background_hooks()`
- `check_background_hook_completed()`
- `finalize_background_hook()`

### Step 6: Update SnapshotMachine.is_finished() (Phase 7)
- Check for background hooks
- Finalize completed ones

### Step 7: Rename background hooks (Phase 7)
- Rename 3 background hooks with .bg. suffix

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
- ✅ Clean separation between output_str (human) and output_json (structured)
- ✅ output_files stored as dict for easy querying and future extensibility
- ✅ Log files cleaned up on success, kept on failure
- ✅ PID files cleaned up after completion
- ✅ No plugin-specific code in core (generic polling mechanism)
- ✅ All plugins updated to clean JSONL format
- ✅ Safe incremental rollout (plugins first, then core code)

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

### 5. Per-file metadata in output_files
If needed, extend output_files values to include per-file metadata:
```python
output_files = {
    'index.html': {
        'size': 4096,
        'hash': 'abc123...',
        'mime_type': 'text/html',
        'modified_at': '2025-01-15T10:30:00Z'
    }
}
```
Can query with custom SQL for complex per-file queries (e.g., "find all results with any file > 50KB"). Summary fields (output_size, output_mimetypes) remain as denormalized cache for performance.

---

# Hook Architecture Implementation Report

## Date: 2025-12-27

## Summary

This report documents the Phase 4 plugin audit and Phase 1-7 implementation work.

---

## Implementation Status

### ✅ Phase 1: Database Migration (COMPLETE)

Created migrations:
- `archivebox/core/migrations/0029_archiveresult_hook_fields.py` - Adds new fields
- `archivebox/core/migrations/0030_migrate_output_field.py` - Migrates old `output` field

New ArchiveResult fields:
- [x] `output_str` (TextField) - human-readable summary
- [x] `output_json` (JSONField) - structured metadata
- [x] `output_files` (JSONField) - dict of {relative_path: {}}
- [x] `output_size` (BigIntegerField) - total bytes
- [x] `output_mimetypes` (CharField) - CSV of mimetypes sorted by size
- [x] `binary` (ForeignKey to InstalledBinary) - optional

### ✅ Phase 3: Generic run_hook() (COMPLETE)

Updated `archivebox/hooks.py`:
- [x] Parse JSONL output (any line with `{type: 'ModelName', ...}`)
- [x] Backwards compatible with `RESULT_JSON=` format
- [x] Add plugin metadata to each record
- [x] Detect background hooks with `.bg.` suffix
- [x] Added `find_binary_for_cmd()` helper
- [x] Added `create_model_record()` for InstalledBinary/Machine

### ✅ Phase 6: Update ArchiveResult.run() (COMPLETE)

Updated `archivebox/core/models.py`:
- [x] Handle background hooks (return immediately when result is None)
- [x] Process `records` from HookResult
- [x] Use new output fields
- [x] Added `_populate_output_fields()` method
- [x] Added `_set_binary_from_cmd()` method
- [x] Call `create_model_record()` for side-effect records

### ✅ Phase 7: Background Hook Support (COMPLETE)

Added to `archivebox/core/models.py`:
- [x] `is_background_hook()` method
- [x] `check_background_completed()` method
- [x] `finalize_background_hook()` method

Updated `archivebox/core/statemachines.py`:
- [x] `SnapshotMachine.is_finished()` checks/finalizes background hooks

---

## Phase 4: Plugin Audit

### Dependency Hooks (on_Dependency__*) - ALL COMPLIANT ✅

| Plugin | Hook | Status | Notes |
|--------|------|--------|-------|
| apt | `on_Dependency__install_using_apt_provider.py` | ✅ OK | Emits `{type: 'InstalledBinary'}` JSONL |
| brew | `on_Dependency__install_using_brew_provider.py` | ✅ OK | Emits `{type: 'InstalledBinary'}` JSONL |
| custom | `on_Dependency__install_using_custom_bash.py` | ✅ OK | Emits `{type: 'InstalledBinary'}` JSONL |
| env | `on_Dependency__install_using_env_provider.py` | ✅ OK | Emits `{type: 'InstalledBinary'}` JSONL |
| npm | `on_Dependency__install_using_npm_provider.py` | ✅ OK | Emits `{type: 'InstalledBinary'}` JSONL |
| pip | `on_Dependency__install_using_pip_provider.py` | ✅ OK | Emits `{type: 'InstalledBinary'}` JSONL |

### Crawl Validate Hooks (on_Crawl__00_validate_*) - ALL COMPLIANT ✅

| Plugin | Hook | Status | Notes |
|--------|------|--------|-------|
| chrome_session | `on_Crawl__00_validate_chrome.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| wget | `on_Crawl__00_validate_wget.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| singlefile | `on_Crawl__00_validate_singlefile.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| readability | `on_Crawl__00_validate_readability.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| media | `on_Crawl__00_validate_ytdlp.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| git | `on_Crawl__00_validate_git.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| forumdl | `on_Crawl__00_validate_forumdl.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| gallerydl | `on_Crawl__00_validate_gallerydl.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| mercury | `on_Crawl__00_validate_mercury.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| papersdl | `on_Crawl__00_validate_papersdl.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |
| search_backend_ripgrep | `on_Crawl__00_validate_ripgrep.py` | ✅ OK | Emits InstalledBinary/Dependency JSONL |

### Snapshot Hooks (on_Snapshot__*) - Python Hooks UPDATED ✅

| Plugin | Hook | Status | Notes |
|--------|------|--------|-------|
| favicon | `on_Snapshot__11_favicon.py` | ✅ UPDATED | Now outputs clean JSONL |
| git | `on_Snapshot__12_git.py` | ✅ UPDATED | Now outputs clean JSONL with cmd |
| archive_org | `on_Snapshot__13_archive_org.py` | ✅ UPDATED | Now outputs clean JSONL |
| title | `on_Snapshot__32_title.js` | ✅ UPDATED | Now outputs clean JSONL |
| singlefile | `on_Snapshot__37_singlefile.py` | ✅ UPDATED | Now outputs clean JSONL with cmd |
| wget | `on_Snapshot__50_wget.py` | ✅ UPDATED | Now outputs clean JSONL with cmd |
| media | `on_Snapshot__51_media.py` | ✅ UPDATED | Now outputs clean JSONL with cmd |
| readability | `on_Snapshot__52_readability.py` | ✅ UPDATED | Now outputs clean JSONL with cmd |

### Snapshot Hooks - JavaScript Hooks (REMAINING WORK)

The following JS hooks still use the old `RESULT_JSON=` format and need to be updated:

| Plugin | Hook | Current Issue |
|--------|------|---------------|
| chrome_session | `on_Snapshot__20_chrome_session.js` | Uses `RESULT_JSON=` prefix |
| consolelog | `on_Snapshot__21_consolelog.js` | Uses `RESULT_JSON=` prefix |
| ssl | `on_Snapshot__23_ssl.js` | Uses `RESULT_JSON=` prefix |
| responses | `on_Snapshot__24_responses.js` | Uses `RESULT_JSON=` prefix |
| chrome_navigate | `on_Snapshot__30_chrome_navigate.js` | Uses `RESULT_JSON=` prefix |
| redirects | `on_Snapshot__31_redirects.js` | Uses `RESULT_JSON=` prefix |
| headers | `on_Snapshot__33_headers.js` | Uses `RESULT_JSON=` prefix |
| screenshot | `on_Snapshot__34_screenshot.js` | Uses `RESULT_JSON=` prefix |
| pdf | `on_Snapshot__35_pdf.js` | Uses `RESULT_JSON=` prefix |
| dom | `on_Snapshot__36_dom.js` | Uses `RESULT_JSON=` prefix |
| seo | `on_Snapshot__38_seo.js` | Uses `RESULT_JSON=` prefix |
| accessibility | `on_Snapshot__39_accessibility.js` | Uses `RESULT_JSON=` prefix |
| parse_dom_outlinks | `on_Snapshot__40_parse_dom_outlinks.js` | Uses `RESULT_JSON=` prefix |

**Fix Required for Each JS Hook:**

Replace:
```javascript
console.log(`START_TS=${startTs.toISOString()}`);
console.log(`END_TS=${endTs.toISOString()}`);
console.log(`STATUS=${status}`);
console.log(`RESULT_JSON=${JSON.stringify(resultJson)}`);
```

With:
```javascript
console.log(JSON.stringify({
    type: 'ArchiveResult',
    status,
    output_str: output || error || '',
}));
```

---

## Files Modified

### Core Infrastructure
- `archivebox/hooks.py` - Updated run_hook() and added helpers
- `archivebox/core/models.py` - Updated ArchiveResult model and run() method
- `archivebox/core/statemachines.py` - Updated SnapshotMachine.is_finished()
- `archivebox/core/admin_archiveresults.py` - Updated to use output_str
- `archivebox/core/templatetags/core_tags.py` - Updated to use output_str

### Migrations
- `archivebox/core/migrations/0029_archiveresult_hook_fields.py` (new)
- `archivebox/core/migrations/0030_migrate_output_field.py` (new)

### Plugins Updated
- `archivebox/plugins/archive_org/on_Snapshot__13_archive_org.py`
- `archivebox/plugins/favicon/on_Snapshot__11_favicon.py`
- `archivebox/plugins/git/on_Snapshot__12_git.py`
- `archivebox/plugins/media/on_Snapshot__51_media.py`
- `archivebox/plugins/readability/on_Snapshot__52_readability.py`
- `archivebox/plugins/singlefile/on_Snapshot__37_singlefile.py`
- `archivebox/plugins/title/on_Snapshot__32_title.js`
- `archivebox/plugins/wget/on_Snapshot__50_wget.py`

---

## Remaining Work

1. **Update remaining JS hooks** (13 files) to output clean JSONL
2. **Rename background hooks** with `.bg.` suffix
3. **Write tests** for the hook architecture
4. **Run migrations** and test on real data
