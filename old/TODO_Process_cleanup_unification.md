# Process Model Integration Plan

## Current Architecture

### Hook Execution Flow
```
Orchestrator
  ├─> CrawlWorker
  │     └─> Crawl.run() [state machine @started.enter]
  │           └─> run_hook() for on_Crawl__* hooks
  │                 └─> subprocess.Popen (NOT using Process model)
  │
  └─> SnapshotWorker
        └─> Snapshot.run() [planned - doesn't exist yet]
              └─> ArchiveResult.run() [state machine @started.enter]
                    └─> run_hook() for on_Snapshot__* hooks
                          └─> subprocess.Popen (NOT using Process model)
```

### Problem
1. **No Process tracking**: `run_hook()` uses `subprocess.Popen` directly, never creates Process records
2. **Orphaned Process model**: Process model has `.launch()`, `.wait()`, `.terminate()` methods that are NEVER used
3. **Manual process management**: SnapshotWorker manually uses psutil for waiting/killing
4. **Duplicate logic**: Process model and run_hook() both do subprocess management independently

## Unified Architecture

### Goal
Make Process model the **single source of truth** for all subprocess operations:
- Hook execution
- PID tracking
- stdout/stderr capture
- Process lifecycle (launch, wait, terminate)

### Design

```python
# hooks.py - Thin wrapper
def run_hook(...) -> Process:
    """
    Run a hook using Process model (THIN WRAPPER).

    Returns Process model instance for tracking and control.
    """
    from archivebox.machine.models import Process

    # Build command
    cmd = build_hook_cmd(script, kwargs)

    # Use Process.launch() - handles everything
    process = Process.objects.create(
        machine=Machine.current(),
        process_type=Process.TypeChoices.HOOK,
        pwd=str(output_dir),
        cmd=cmd,
        env=build_hook_env(config),
        timeout=timeout,
    )

    # Launch subprocess
    process.launch(background=is_background_hook(script.name))

    return process  # Return Process, not dict


# worker.py - Use Process methods
class SnapshotWorker:
    def _run_hook(self, hook_path, ar) -> Process:
        """Fork hook using Process model."""
        process = run_hook(
            hook_path,
            ar.create_output_dir(),
            self.snapshot.config,
            url=self.snapshot.url,
            snapshot_id=str(self.snapshot.id),
        )

        # Link ArchiveResult to Process
        ar.process = process
        ar.save()

        return process

    def _wait_for_hook(self, process, ar):
        """Wait using Process.wait() method."""
        exit_code = process.wait(timeout=None)

        # Update AR from hook output
        ar.update_from_output()
        ar.status = ar.StatusChoices.SUCCEEDED if exit_code == 0 else ar.StatusChoices.FAILED
        ar.save()

    def on_shutdown(self):
        """
        Terminate all background hooks in parallel with per-plugin timeouts.

        Phase 1: Send SIGTERM to all in parallel (polite request to wrap up)
        Phase 2: Wait for all in parallel, respecting individual plugin timeouts
        Phase 3: SIGKILL any that exceed their timeout

        Each plugin has its own timeout (SCREENSHOT_TIMEOUT=60, YTDLP_TIMEOUT=300, etc.)
        Some hooks (consolelog, responses) exit immediately on SIGTERM.
        Others (ytdlp, wget) need their full timeout to finish actual work.
        """
        # Send SIGTERM to all processes in parallel
        for hook_name, process in self.background_processes.items():
            os.kill(process.pid, signal.SIGTERM)

        # Build per-process deadlines based on plugin-specific timeouts
        deadlines = {
            name: (proc, time.time() + max(0, proc.timeout - (time.time() - proc.started_at.timestamp())))
            for name, proc in self.background_processes.items()
        }

        # Poll all processes in parallel - no head-of-line blocking
        still_running = set(deadlines.keys())
        while still_running:
            time.sleep(0.1)
            for name in list(still_running):
                proc, deadline = deadlines[name]
                if not proc.is_running():
                    still_running.remove(name)
                elif time.time() >= deadline:
                    os.kill(proc.pid, signal.SIGKILL)  # Timeout exceeded
                    still_running.remove(name)


# models.py - Process becomes active
class Process:
    def launch(self, background=False):
        """Spawn subprocess and track it."""
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

            if not background:
                # Foreground - wait inline
                proc.wait()
                self.exit_code = proc.returncode
                self.ended_at = timezone.now()
                self.status = self.StatusChoices.EXITED
                self.save()

        return self

    def wait(self, timeout=None):
        """Wait for process to exit, polling DB."""
        while True:
            self.refresh_from_db()
            if self.status == self.StatusChoices.EXITED:
                return self.exit_code

            # Check via psutil if Process died without updating DB
            if not self.is_running():
                self._reap()  # Update status from OS
                return self.exit_code

            time.sleep(0.1)

    def terminate(self, sig=signal.SIGTERM):
        """Gracefully terminate: SIGTERM → wait → SIGKILL."""
        if not self.is_running():
            return True

        os.kill(self.pid, sig)

        # Wait for graceful shutdown
        for _ in range(50):  # 5 seconds
            if not self.is_running():
                self._reap()
                return True
            time.sleep(0.1)

        # Escalate to SIGKILL
        os.kill(self.pid, signal.SIGKILL)
        self._reap()
        return True
```

## Migration Steps

### Step 1: Update Process.launch() (DONE - already exists)
Process model already has `.launch()`, `.wait()`, `.terminate()` methods implemented in machine/models.py:1295-1593

### Step 2: Refactor run_hook() to use Process.launch()
**File**: `archivebox/hooks.py`

Change signature from:
```python
def run_hook(...) -> HookResult:  # Returns dict
```

To:
```python
def run_hook(...) -> Process:  # Returns Process model
```

**Implementation**:
```python
def run_hook(script, output_dir, config, timeout=None, **kwargs) -> Process:
    from archivebox.machine.models import Process, Machine

    # Build command
    cmd = build_hook_cmd(script, kwargs)
    env = build_hook_env(config)
    is_bg = is_background_hook(script.name)

    # Create Process record
    process = Process.objects.create(
        machine=Machine.current(),
        process_type=Process.TypeChoices.HOOK,
        pwd=str(output_dir),
        cmd=cmd,
        env=env,
        timeout=timeout or 120,
    )

    # Launch subprocess
    process.launch(background=is_bg)

    return process
```

### Step 3: Update SnapshotWorker to use Process methods
**File**: `archivebox/workers/worker.py`

Replace manual psutil code with Process model methods (shown above in Design section).

### Step 4: Update ArchiveResult.run() to use new run_hook()
**File**: `archivebox/core/models.py:2559`

Change from:
```python
result = run_hook(...)  # Returns HookResult dict
if result is None:
    is_bg_hook = True
```

To:
```python
process = run_hook(...)  # Returns Process
self.process = process
self.save()

if process.status == Process.StatusChoices.RUNNING:
    # Background hook - still running
    return
else:
    # Foreground hook - completed
    self.update_from_output()
```

### Step 5: Update Crawl.run() similarly
**File**: `archivebox/crawls/models.py:374`

Same pattern as ArchiveResult.run()

## Benefits

### 1. Single Source of Truth
- Process model owns ALL subprocess operations
- No duplicate logic between run_hook(), Process, and workers
- Consistent PID tracking, stdout/stderr handling

### 2. Proper Hierarchy
```
Process.parent_id creates tree:
Orchestrator (PID 1000)
  └─> CrawlWorker (PID 1001, parent=1000)
        └─> on_Crawl__01_chrome.js (PID 1010, parent=1001)
  └─> SnapshotWorker (PID 1020, parent=1000)
        └─> on_Snapshot__50_wget.py (PID 1021, parent=1020)
        └─> on_Snapshot__63_ytdlp.bg.py (PID 1022, parent=1020)
```

### 3. Better Observability
- Query all hook processes: `snapshot.process_set.all()`
- Count running: `Process.objects.filter(status='running').count()`
- Track resource usage via Process.get_memory_info()

### 4. Cleaner Code
- SnapshotWorker._wait_for_hook: 25 lines → 8 lines
- SnapshotWorker.on_shutdown: 12 lines → 7 lines
- run_hook(): ~200 lines → ~50 lines
- Total: ~100 LoC saved

## Risks & Mitigation

### Risk 1: Breaking existing run_hook() callers
**Mitigation**: Two-phase rollout
1. Phase 1: Add run_hook_v2() that returns Process
2. Phase 2: Migrate callers to run_hook_v2()
3. Phase 3: Rename run_hook → run_hook_legacy, run_hook_v2 → run_hook

### Risk 2: Background hook tracking changes
**Mitigation**:
- Process.launch(background=True) handles async launches
- Process.wait() already polls for completion
- Behavior identical to current subprocess.Popen

### Risk 3: Performance overhead (extra DB writes)
**Mitigation**:
- Process records already being created (just not used)
- Batch updates where possible
- Monitor via metrics

## Timeline

### Immediate (This PR)
- [x] State machine fixes (completed)
- [x] Step advancement optimization (completed)
- [x] Document unified architecture (this file)

### Next PR (Process Integration)
1. Add run_hook_v2() returning Process
2. Update SnapshotWorker to use Process methods
3. Migrate ArchiveResult.run() and Crawl.run()
4. Deprecate old run_hook()

### Future
- Remove run_hook_legacy after migration complete
- Add Process.get_tree() for hierarchy visualization
- Add ProcessMachine state machine for lifecycle management
