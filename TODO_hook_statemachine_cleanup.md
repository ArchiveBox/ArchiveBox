# Hook & State Machine Cleanup - Unified Pattern

## Goal
Implement a **consistent pattern** across all models (Crawl, Snapshot, ArchiveResult, Dependency) for:
1. Running hooks
2. Processing JSONL records
3. Managing background hooks
4. State transitions

## Current State Analysis (ALL COMPLETE ✅)

### ✅ Crawl (archivebox/crawls/)
**Status**: COMPLETE
- ✅ Has state machine: `CrawlMachine`
- ✅ `Crawl.run()` - runs hooks, processes JSONL via `process_hook_records()`, creates snapshots
- ✅ `Crawl.cleanup()` - kills background hooks, runs on_CrawlEnd hooks
- ✅ Uses `OUTPUT_DIR/plugin_name/` for PWD
- ✅ State machine calls model methods:
  - `queued -> started`: calls `crawl.run()`
  - `started -> sealed`: calls `crawl.cleanup()`

### ✅ Snapshot (archivebox/core/)
**Status**: COMPLETE
- ✅ Has state machine: `SnapshotMachine`
- ✅ `Snapshot.run()` - creates pending ArchiveResults
- ✅ `Snapshot.cleanup()` - kills background ArchiveResult hooks, calls `update_from_output()`
- ✅ `Snapshot.has_running_background_hooks()` - checks PID files using `process_is_alive()`
- ✅ `Snapshot.from_jsonl()` - simplified, filtering moved to caller
- ✅ State machine calls model methods:
  - `queued -> started`: calls `snapshot.run()`
  - `started -> sealed`: calls `snapshot.cleanup()`
  - `is_finished()`: uses `has_running_background_hooks()`

### ✅ ArchiveResult (archivebox/core/)
**Status**: COMPLETE - Major refactor completed
- ✅ Has state machine: `ArchiveResultMachine`
- ✅ `ArchiveResult.run()` - runs hook, calls `update_from_output()` for foreground hooks
- ✅ `ArchiveResult.update_from_output()` - unified method for foreground and background hooks
- ✅ Uses PWD `snapshot.OUTPUT_DIR/plugin_name`
- ✅ JSONL processing via `process_hook_records()` with URL/depth filtering
- ✅ **DELETED** special background hook methods:
  - ❌ `check_background_completed()` - replaced by `process_is_alive()` helper
  - ❌ `finalize_background_hook()` - replaced by `update_from_output()`
  - ❌ `_populate_output_fields()` - merged into `update_from_output()`
- ✅ State machine transitions:
  - `queued -> started`: calls `archiveresult.run()`
  - `started -> succeeded/failed/skipped`: status set by `update_from_output()`

### ✅ Binary (archivebox/machine/) - NEW!
**Status**: COMPLETE - Replaced Dependency model entirely
- ✅ Has state machine: `BinaryMachine`
- ✅ `Binary.run()` - runs on_Binary__install_* hooks, processes JSONL
- ✅ `Binary.cleanup()` - kills background installation hooks (for consistency)
- ✅ `Binary.from_jsonl()` - handles both binaries.jsonl and hook output
- ✅ Uses PWD `data/machines/{machine_id}/binaries/{name}/{id}/plugin_name/`
- ✅ Configuration via static `plugins/*/binaries.jsonl` files
- ✅ State machine calls model methods:
  - `queued -> started`: calls `binary.run()`
  - `started -> succeeded/failed`: status set by hooks via JSONL
- ✅ Perfect symmetry with Crawl/Snapshot/ArchiveResult pattern

### ❌ Dependency Model - ELIMINATED
**Status**: Deleted entirely (replaced by Binary state machine)
- Static configuration now lives in `plugins/*/binaries.jsonl`
- Per-machine state tracked by Binary records
- No global singleton conflicts
- Hooks renamed from `on_Dependency__install_*` to `on_Binary__install_*`

## Unified Pattern (Target Architecture)

### Pattern for ALL models:

```python
# 1. State Machine orchestrates transitions
class ModelMachine(StateMachine):
    @started.enter
    def enter_started(self):
        self.model.run()  # Do the work
        # Update status

    def is_finished(self):
        # Check if background hooks still running
        if self.model.has_running_background_hooks():
            return False
        # Check if children finished
        if self.model.has_pending_children():
            return False
        return True

    @sealed.enter
    def enter_sealed(self):
        self.model.cleanup()  # Clean up background hooks
        # Update status

# 2. Model methods do the actual work
class Model:
    def run(self):
        """Run hooks, process JSONL, create children."""
        hooks = discover_hooks('ModelName')
        for hook in hooks:
            output_dir = self.OUTPUT_DIR / hook.parent.name
            result = run_hook(hook, output_dir=output_dir, ...)

            if result is None:  # Background hook
                continue

            # Process JSONL records
            records = result.get('records', [])
            overrides = {'model': self, 'created_by_id': self.created_by_id}
            process_hook_records(records, overrides=overrides)

        # Create children (e.g., ArchiveResults, Snapshots)
        self.create_children()

    def cleanup(self):
        """Kill background hooks, run cleanup hooks."""
        # Kill any background hooks
        if self.OUTPUT_DIR.exists():
            for pid_file in self.OUTPUT_DIR.glob('*/hook.pid'):
                kill_process(pid_file)

        # Run cleanup hooks (e.g., on_ModelEnd)
        cleanup_hooks = discover_hooks('ModelEnd')
        for hook in cleanup_hooks:
            run_hook(hook, ...)

    def has_running_background_hooks(self) -> bool:
        """Check if any background hooks still running."""
        if not self.OUTPUT_DIR.exists():
            return False
        for pid_file in self.OUTPUT_DIR.glob('*/hook.pid'):
            if process_is_alive(pid_file):
                return True
        return False
```

### PWD Standard:
```
model.OUTPUT_DIR/plugin_name/
```
- Crawl: `users/{user}/crawls/{date}/{crawl_id}/plugin_name/`
- Snapshot: `users/{user}/snapshots/{date}/{domain}/{snapshot_id}/plugin_name/`
- ArchiveResult: `users/{user}/snapshots/{date}/{domain}/{snapshot_id}/plugin_name/` (same as Snapshot)
- Dependency: `dependencies/{dependency_id}/plugin_name/` (set output_dir field directly)

## Implementation Plan

### Phase 1: Add unified helpers to hooks.py ✅ DONE

**File**: `archivebox/hooks.py`

**Status**: COMPLETE - Added three helper functions:
- `process_hook_records(records, overrides)` - lines 1258-1323
- `process_is_alive(pid_file)` - lines 1326-1344
- `kill_process(pid_file, sig)` - lines 1347-1362

```python
def process_hook_records(records: List[Dict], overrides: Dict = None) -> Dict[str, int]:
    """
    Process JSONL records from hook output.
    Dispatches to Model.from_jsonl() for each record type.

    Args:
        records: List of JSONL record dicts from result['records']
        overrides: Dict with 'snapshot', 'crawl', 'dependency', 'created_by_id', etc.

    Returns:
        Dict with counts by record type
    """
    stats = {}
    for record in records:
        record_type = record.get('type')

        # Dispatch to appropriate model
        if record_type == 'Snapshot':
            from core.models import Snapshot
            Snapshot.from_jsonl(record, overrides)
            stats['Snapshot'] = stats.get('Snapshot', 0) + 1
        elif record_type == 'Tag':
            from core.models import Tag
            Tag.from_jsonl(record, overrides)
            stats['Tag'] = stats.get('Tag', 0) + 1
        elif record_type == 'Binary':
            from machine.models import Binary
            Binary.from_jsonl(record, overrides)
            stats['Binary'] = stats.get('Binary', 0) + 1
        # ... etc
    return stats

def process_is_alive(pid_file: Path) -> bool:
    """Check if process in PID file is still running."""
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # Signal 0 = check if exists
        return True
    except (OSError, ValueError):
        return False

def kill_process(pid_file: Path, signal=SIGTERM):
    """Kill process in PID file."""
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal)
    except (OSError, ValueError):
        pass
```

### Phase 2: Add Model.from_jsonl() static methods ✅ DONE

**Files**: `archivebox/core/models.py`, `archivebox/machine/models.py`, `archivebox/crawls/models.py`

**Status**: COMPLETE - Added from_jsonl() to:
- ✅ `Tag.from_jsonl()` - core/models.py lines 93-116
- ✅ `Snapshot.from_jsonl()` - core/models.py lines 1144-1189
- ✅ `Machine.from_jsonl()` - machine/models.py lines 66-89
- ✅ `Dependency.from_jsonl()` - machine/models.py lines 203-227
- ✅ `Binary.from_jsonl()` - machine/models.py lines 401-434

Example implementations added:

```python
class Snapshot:
    @staticmethod
    def from_jsonl(record: Dict, overrides: Dict = None):
        """Create/update Snapshot from JSONL record."""
        from archivebox.misc.jsonl import get_or_create_snapshot
        overrides = overrides or {}

        # Apply overrides (crawl, parent_snapshot, depth limits)
        crawl = overrides.get('crawl')
        snapshot = overrides.get('snapshot')  # parent

        if crawl:
            depth = record.get('depth', (snapshot.depth + 1 if snapshot else 1))
            if depth > crawl.max_depth:
                return None
            record.setdefault('crawl_id', str(crawl.id))
            record.setdefault('depth', depth)
            if snapshot:
                record.setdefault('parent_snapshot_id', str(snapshot.id))

        created_by_id = overrides.get('created_by_id')
        new_snapshot = get_or_create_snapshot(record, created_by_id=created_by_id)
        new_snapshot.status = Snapshot.StatusChoices.QUEUED
        new_snapshot.retry_at = timezone.now()
        new_snapshot.save()
        return new_snapshot

class Tag:
    @staticmethod
    def from_jsonl(record: Dict, overrides: Dict = None):
        """Create/update Tag from JSONL record."""
        from archivebox.misc.jsonl import get_or_create_tag
        tag = get_or_create_tag(record)
        # Auto-attach to snapshot if in overrides
        if overrides and 'snapshot' in overrides:
            overrides['snapshot'].tags.add(tag)
        return tag

class Binary:
    @staticmethod
    def from_jsonl(record: Dict, overrides: Dict = None):
        """Create/update Binary from JSONL record."""
        # Implementation similar to existing create_model_record()
        ...

# Etc for other models
```

### Phase 3: Update ArchiveResult to use unified pattern ✅ DONE

**File**: `archivebox/core/models.py`

**Status**: COMPLETE

**Changes made**:

1. ✅ **Replaced inline JSONL processing** (lines 1912-1950):
   - Pre-filter Snapshot records for depth/URL constraints in ArchiveResult.run()
   - Use `self._url_passes_filters(url)` with parent snapshot's config for proper hierarchy
   - Replaced inline Tag/Snapshot/other record creation with `process_hook_records()`
   - Removed ~60 lines of duplicate code

2. ✅ **Simplified Snapshot.from_jsonl()** (lines 1144-1189):
   - Removed depth checking (now done in caller)
   - Just applies crawl metadata and creates snapshot
   - Added docstring note: "Filtering should be done by caller BEFORE calling this method"

3. ✅ **Preserved ArchiveResult self-update logic**:
   - Status/output fields still updated from ArchiveResult JSONL record (lines 1856-1910)
   - Special title extractor logic preserved (line 1952+)
   - Search indexing trigger preserved (line 1957+)

4. ✅ **Key insight**: Filtering happens in ArchiveResult.run() where we have parent snapshot context, NOT in from_jsonl() where we'd lose config hierarchy

**Note**: Did NOT delete special background hook methods (`check_background_completed`, `finalize_background_hook`) - that's Phase 6

### Phase 4: Add Snapshot.cleanup() method ✅ DONE

**File**: `archivebox/core/models.py`

**Status**: COMPLETE

**Changes made**:

1. ✅ **Added Snapshot.cleanup()** (lines 1144-1175):
   - Kills background ArchiveResult hooks by scanning for `*/hook.pid` files
   - Finalizes background ArchiveResults using `finalize_background_hook()` (temporary until Phase 6)
   - Called by state machine when entering sealed state

2. ✅ **Added Snapshot.has_running_background_hooks()** (lines 1177-1195):
   - Checks if any background hooks still running using `process_is_alive()`
   - Used by state machine in `is_finished()` check

### Phase 5: Update SnapshotMachine to use cleanup() ✅ DONE

**File**: `archivebox/core/statemachines.py`

**Status**: COMPLETE

**Changes made**:

1. ✅ **Simplified is_finished()** (lines 58-72):
   - Removed inline background hook checking and finalization (lines 67-76 deleted)
   - Now uses `self.snapshot.has_running_background_hooks()` (line 68)
   - Removed ~12 lines of duplicate logic

2. ✅ **Added cleanup() to sealed.enter** (lines 102-111):
   - Calls `self.snapshot.cleanup()` to kill background hooks (line 105)
   - Follows unified pattern: cleanup happens on seal, not in is_finished()

### Phase 6: Add ArchiveResult.update_from_output() and simplify run() ✅ DONE

**File**: `archivebox/core/models.py`

**Status**: COMPLETE - The BIG refactor (removed ~200 lines of duplication)

**Changes made**:

1. ✅ **Added `ArchiveResult.update_from_output()`** (lines 1908-2061):
   - Unified method for both foreground and background hooks
   - Reads stdout.log and parses JSONL records
   - Updates status/output_str/output_json from ArchiveResult JSONL record
   - Walks filesystem to populate output_files/output_size/output_mimetypes
   - Filters Snapshot records for depth/URL constraints (same as run())
   - Processes side-effect records via `process_hook_records()`
   - Updates snapshot title if title extractor
   - Triggers search indexing if succeeded
   - Cleans up PID files and empty logs
   - ~160 lines of comprehensive logic

2. ✅ **Simplified `ArchiveResult.run()`** (lines 1841-1906):
   - Removed ~120 lines of duplicate filesystem reading logic
   - Now just sets start_ts/pwd and calls `update_from_output()`
   - Background hooks: return immediately after saving status=STARTED
   - Foreground hooks: call `update_from_output()` to do all the work
   - Removed ~10 lines of duplicate code

3. ✅ **Updated `Snapshot.cleanup()`** (line 1172):
   - Changed from `ar.finalize_background_hook()` to `ar.update_from_output()`
   - Uses the unified method instead of the old special-case method

4. ✅ **Deleted `_populate_output_fields()`** (was ~45 lines):
   - Logic merged into `update_from_output()`
   - Eliminates duplication of filesystem walking code

5. ✅ **Deleted `check_background_completed()`** (was ~20 lines):
   - Replaced by `process_is_alive(pid_file)` from hooks.py
   - Generic helper used by Snapshot.has_running_background_hooks()

6. ✅ **Deleted `finalize_background_hook()`** (was ~85 lines):
   - Completely replaced by `update_from_output()`
   - Was duplicate of foreground hook finalization logic

**Total lines removed**: ~280 lines of duplicate code
**Total lines added**: ~160 lines of unified code
**Net reduction**: ~120 lines (-43%)

### Phase 7-8: Dependency State Machine ❌ NOT NEEDED

**Status**: Intentionally skipped - Dependency doesn't need a state machine

**Why no state machine for Dependency?**

1. **Wrong Granularity**: Dependency is a GLOBAL singleton (one record per binary name)
   - Multiple machines would race to update the same `status`/`retry_at` fields
   - No clear semantics: "started" on which machine? "failed" on Machine A but "succeeded" on Machine B?

2. **Wrong Timing**: Installation should be SYNCHRONOUS, not queued
   - When a worker needs wget, it should install wget NOW, not queue it for later
   - No benefit to async state machine transitions

3. **State Lives Elsewhere**: Binary records are the actual state
   - Each machine has its own Binary records (one per machine per binary)
   - Binary.machine FK provides proper per-machine state tracking

**Correct Architecture:**
```
Dependency (global, no state machine):
  ├─ Configuration: bin_name, bin_providers, overrides
  ├─ run() method: synchronous installation attempt
  └─ NO status, NO retry_at, NO state_machine_name

Binary (per-machine, has machine FK):
  ├─ State: is this binary installed on this specific machine?
  ├─ Created via JSONL output from on_Dependency hooks
  └─ unique_together = (machine, name, abspath, version, sha256)
```

**What was implemented:**
- ✅ **Refactored `Dependency.run()`** (lines 249-324):
  - Uses `discover_hooks()` and `process_hook_records()` for consistency
  - Added comprehensive docstring explaining why no state machine
  - Synchronous execution: returns Binary or None immediately
  - Uses unified JSONL processing pattern
- ✅ **Kept Dependency simple**: Just configuration fields, no state fields
- ✅ **Multi-machine support**: Each machine independently runs Dependency.run() and creates its own Binary

## Summary of Changes

### Progress: 6/6 Core Phases Complete ✅ + 2 Phases Skipped (Intentionally)

**ALL core functionality is now complete!** The unified pattern is consistently implemented across Crawl, Snapshot, and ArchiveResult. Dependency intentionally kept simple (no state machine needed).

### Files Modified:

1. ✅ **DONE** `archivebox/hooks.py` - Add unified helpers:
   - ✅ `process_hook_records(records, overrides)` - dispatcher (lines 1258-1323)
   - ✅ `process_is_alive(pid_file)` - check if PID still running (lines 1326-1344)
   - ✅ `kill_process(pid_file)` - kill process (lines 1347-1362)

2. ✅ **DONE** `archivebox/crawls/models.py` - Already updated:
   - ✅ `Crawl.run()` - runs hooks, processes JSONL, creates snapshots
   - ✅ `Crawl.cleanup()` - kills background hooks, runs on_CrawlEnd

3. ✅ **DONE** `archivebox/core/models.py`:
   - ✅ `Tag.from_jsonl()` - lines 93-116
   - ✅ `Snapshot.from_jsonl()` - lines 1197-1234 (simplified, removed filtering)
   - ✅ `Snapshot.cleanup()` - lines 1144-1172 (kill background hooks, calls ar.update_from_output())
   - ✅ `Snapshot.has_running_background_hooks()` - lines 1174-1193 (check PIDs)
   - ✅ `ArchiveResult.run()` - simplified, uses `update_from_output()` (lines 1841-1906)
   - ✅ `ArchiveResult.update_from_output()` - unified filesystem reading (lines 1908-2061)
   - ✅ **DELETED** `ArchiveResult.check_background_completed()` - replaced by `process_is_alive()`
   - ✅ **DELETED** `ArchiveResult.finalize_background_hook()` - replaced by `update_from_output()`
   - ✅ **DELETED** `ArchiveResult._populate_output_fields()` - merged into `update_from_output()`

4. ✅ **DONE** `archivebox/core/statemachines.py`:
   - ✅ Simplified `SnapshotMachine.is_finished()` - uses `has_running_background_hooks()` (line 68)
   - ✅ Added cleanup call to `SnapshotMachine.sealed.enter` (line 105)

5. ✅ **DONE** `archivebox/machine/models.py`:
   - ✅ `Machine.from_jsonl()` - lines 66-89
   - ✅ `Dependency.from_jsonl()` - lines 203-227
   - ✅ `Binary.from_jsonl()` - lines 401-434
   - ✅ Refactored `Dependency.run()` to use unified pattern (lines 249-324)
   - ✅ Added comprehensive docstring explaining why Dependency doesn't need state machine
   - ✅ Kept Dependency simple: no state fields, synchronous execution only

### Code Metrics:
- **Lines removed**: ~280 lines of duplicate code
- **Lines added**: ~160 lines of unified code
- **Net reduction**: ~120 lines total (-43%)
- **Files created**: 0 (no new files needed)

### Key Benefits:

1. **Consistency**: All stateful models (Crawl, Snapshot, ArchiveResult) follow the same unified state machine pattern
2. **Simplicity**: Eliminated special-case background hook handling (~280 lines of duplicate code)
3. **Correctness**: Background hooks are properly cleaned up on seal transition
4. **Maintainability**: Unified `process_hook_records()` dispatcher for all JSONL processing
5. **Testability**: Consistent pattern makes testing easier
6. **Clear Separation**: Stateful work items (Crawl/Snapshot/ArchiveResult) vs stateless config (Dependency)
7. **Multi-Machine Support**: Dependency remains simple synchronous config, Binary tracks per-machine state

## Final Unified Pattern

All models now follow this consistent architecture:

### State Machine Structure
```python
class ModelMachine(StateMachine):
    queued = State(initial=True)
    started = State()
    sealed/succeeded/failed = State(final=True)

    @started.enter
    def enter_started(self):
        self.model.run()  # Execute the work

    @sealed.enter  # or @succeeded.enter
    def enter_sealed(self):
        self.model.cleanup()  # Clean up background hooks
```

### Model Methods
```python
class Model:
    # State machine fields
    status = CharField(default='queued')
    retry_at = DateTimeField(default=timezone.now)
    output_dir = CharField(default='', blank=True)
    state_machine_name = 'app.statemachines.ModelMachine'

    def run(self):
        """Run hooks, process JSONL, create children."""
        hooks = discover_hooks('EventName')
        for hook in hooks:
            output_dir = self.OUTPUT_DIR / hook.parent.name
            result = run_hook(hook, output_dir=output_dir, ...)

            if result is None:  # Background hook
                continue

            # Process JSONL records
            overrides = {'model': self, 'created_by_id': self.created_by_id}
            process_hook_records(result['records'], overrides=overrides)

    def cleanup(self):
        """Kill background hooks, run cleanup hooks."""
        for pid_file in self.OUTPUT_DIR.glob('*/hook.pid'):
            kill_process(pid_file)
            # Update children from filesystem
            child.update_from_output()

    def update_for_workers(self, **fields):
        """Update fields and bump modified_at."""
        for field, value in fields.items():
            setattr(self, field, value)
        self.save(update_fields=[*fields.keys(), 'modified_at'])

    @staticmethod
    def from_jsonl(record: dict, overrides: dict = None):
        """Create/update model from JSONL record."""
        # Implementation specific to model
        # Called by process_hook_records()
```

### Hook Processing Flow
```
1. Model.run() discovers hooks
2. Hooks execute and output JSONL to stdout
3. JSONL records dispatched via process_hook_records()
4. Each record type handled by Model.from_jsonl()
5. Background hooks tracked via hook.pid files
6. Model.cleanup() kills background hooks on seal
7. Children updated via update_from_output()
```

### Multi-Machine Coordination
- **Work Items** (Crawl, Snapshot, ArchiveResult): No machine FK, any worker can claim
- **Resources** (Binary): Machine FK, one per machine per binary
- **Configuration** (Dependency): No machine FK, global singleton, synchronous execution
- **Execution Tracking** (ArchiveResult.iface): FK to NetworkInterface for observability

## Testing Checklist

- [ ] Test Crawl → Snapshot creation with hooks
- [ ] Test Snapshot → ArchiveResult creation
- [ ] Test ArchiveResult foreground hooks (JSONL processing)
- [ ] Test ArchiveResult background hooks (PID tracking, cleanup)
- [ ] Test Dependency.run() synchronous installation
- [ ] Test background hook cleanup on seal transition
- [ ] Test multi-machine Crawl execution
- [ ] Test Binary creation per machine (one per machine per binary)
- [ ] Verify Dependency.run() can be called concurrently from multiple machines safely

## FINAL ARCHITECTURE (Phases 1-8 Complete)

### ✅ Phases 1-6: Core Models Unified
All core models (Crawl, Snapshot, ArchiveResult) now follow the unified pattern:
- State machines orchestrate transitions
- `.run()` methods execute hooks and process JSONL
- `.cleanup()` methods kill background hooks
- `.update_for_workers()` methods update state for worker coordination
- Consistent use of `process_hook_records()` for JSONL dispatching

### ✅ Phases 7-8: Binary State Machine (Dependency Model Eliminated)

**Key Decision**: Eliminated `Dependency` model entirely and made `Binary` the state machine.

#### New Architecture
- **Static Configuration**: `plugins/{plugin}/dependencies.jsonl` files define binary requirements
  ```jsonl
  {"type": "Binary", "name": "yt-dlp", "bin_providers": "pip,brew,apt,env"}
  {"type": "Binary", "name": "node", "bin_providers": "apt,brew,env", "overrides": {"apt": {"packages": ["nodejs"]}}}
  {"type": "Binary", "name": "ffmpeg", "bin_providers": "apt,brew,env"}
  ```

- **Dynamic State**: `Binary` model tracks per-machine installation state
  - Fields: `machine`, `name`, `bin_providers`, `overrides`, `abspath`, `version`, `sha256`, `binprovider`
  - State machine: `queued → started → succeeded/failed`
  - Output dir: `data/machines/{machine_id}/binaries/{binary_name}/{binary_id}/`

#### Binary State Machine Flow
```python
class BinaryMachine(StateMachine):
    queued → started → succeeded/failed

    @started.enter
    def enter_started(self):
        self.binary.run()  # Runs on_Binary__install_* hooks

class Binary(models.Model):
    def run(self):
        """
        Runs ALL on_Binary__install_* hooks.
        Each hook checks bin_providers and decides if it can handle this binary.
        First hook to succeed wins.
        Outputs JSONL with abspath, version, sha256, binprovider.
        """
        hooks = discover_hooks('Binary')
        for hook in hooks:
            result = run_hook(hook, output_dir=self.OUTPUT_DIR/plugin_name, 
                            binary_id=self.id, machine_id=self.machine_id,
                            name=self.name, bin_providers=self.bin_providers,
                            overrides=json.dumps(self.overrides))
            
            # Hook outputs: {"type": "Binary", "name": "wget", "abspath": "/usr/bin/wget", "version": "1.21", "binprovider": "apt"}
            # Binary.from_jsonl() updates self with installation results
```

#### Hook Naming Convention
- **Before**: `on_Dependency__install_using_pip_provider.py`
- **After**: `on_Binary__install_using_pip_provider.py`

Each hook checks `--bin-providers` CLI argument:
```python
if 'pip' not in bin_providers.split(','):
    sys.exit(0)  # Skip this binary
```

#### Perfect Symmetry Achieved
All models now follow identical patterns:
```python
Crawl(queued) → CrawlMachine → Crawl.run() → sealed
Snapshot(queued) → SnapshotMachine → Snapshot.run() → sealed  
ArchiveResult(queued) → ArchiveResultMachine → ArchiveResult.run() → succeeded/failed
Binary(queued) → BinaryMachine → Binary.run() → succeeded/failed
```

#### Benefits of Eliminating Dependency
1. **No global singleton conflicts**: Binary is per-machine, no race conditions
2. **Simpler data model**: One table instead of two (Dependency + InstalledBinary)
3. **Static configuration**: dependencies.jsonl in version control, not database
4. **Consistent state machine**: Binary follows same pattern as other models
5. **Cleaner hooks**: Hooks check bin_providers themselves instead of orchestrator parsing names

#### Multi-Machine Coordination
- **Work Items** (Crawl, Snapshot, ArchiveResult): No machine FK, any worker can claim
- **Resources** (Binary): Machine FK, one per machine per binary name
- **Configuration**: Static files in `plugins/*/dependencies.jsonl`
- **Execution Tracking**: ArchiveResult.iface FK to NetworkInterface for observability

### Testing Checklist (Updated)
- [x] Core models use unified hook pattern (Phases 1-6)
- [ ] Binary installation via state machine
- [ ] Multiple machines can install same binary independently  
- [ ] Hook bin_providers filtering works correctly
- [ ] Binary.from_jsonl() handles both dependencies.jsonl and hook output
- [ ] Binary OUTPUT_DIR structure: data/machines/{machine_id}/binaries/{name}/{id}/

