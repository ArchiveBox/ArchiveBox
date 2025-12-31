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

### 1.5 Add `Process.proc` Property for Validated psutil Access

The `proc` property provides a validated `psutil.Process` object, ensuring the PID matches our recorded process (not a recycled PID):

```python
class Process(ModelWithHealthStats):
    # ... existing fields ...

    @property
    def proc(self) -> 'psutil.Process | None':
        """
        Get validated psutil.Process for this record.

        Returns psutil.Process ONLY if:
        1. Process with this PID exists in OS
        2. OS process start time matches our started_at (within tolerance)
        3. Process is on current machine

        Returns None if:
        - PID doesn't exist (process exited)
        - PID was reused by a different process (start times don't match)
        - We're on a different machine than where process ran

        This prevents accidentally matching a stale/recycled PID.
        """
        import psutil
        from archivebox.machine.models import Machine

        # Can't get psutil.Process if we don't have a PID
        if not self.pid:
            return None

        # Can't validate processes on other machines
        if self.machine_id != Machine.current().id:
            return None

        try:
            os_proc = psutil.Process(self.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None  # Process no longer exists

        # Validate start time matches to prevent PID reuse confusion
        if self.started_at:
            os_start_time = os_proc.create_time()
            db_start_time = self.started_at.timestamp()

            if abs(os_start_time - db_start_time) > START_TIME_TOLERANCE:
                # PID has been reused by a different process!
                return None

        # Optionally validate command matches (extra safety)
        # This catches edge cases where start times are within tolerance
        # but it's actually a different process
        if self.cmd:
            try:
                os_cmdline = os_proc.cmdline()
                # Check if first arg (binary) matches
                if os_cmdline and self.cmd:
                    os_binary = os_cmdline[0] if os_cmdline else ''
                    db_binary = self.cmd[0] if self.cmd else ''
                    # Match by basename (handles /usr/bin/python3 vs python3)
                    if os_binary and db_binary:
                        from pathlib import Path
                        if Path(os_binary).name != Path(db_binary).name:
                            return None  # Different binary, PID reused
            except (psutil.AccessDenied, psutil.ZombieProcess):
                pass  # Can't check cmdline, trust start time match

        return os_proc

    @property
    def is_running(self) -> bool:
        """
        Check if process is currently running via psutil.

        More reliable than checking status field since it validates
        the actual OS process exists and matches our record.
        """
        return self.proc is not None and self.proc.is_running()

    def is_alive(self) -> bool:
        """
        Alias for is_running, for compatibility with subprocess.Popen API.
        """
        return self.is_running

    def get_memory_info(self) -> dict | None:
        """Get memory usage if process is running."""
        if self.proc:
            try:
                mem = self.proc.memory_info()
                return {'rss': mem.rss, 'vms': mem.vms}
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def get_cpu_percent(self) -> float | None:
        """Get CPU usage percentage if process is running."""
        if self.proc:
            try:
                return self.proc.cpu_percent(interval=0.1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return None

    def get_children_pids(self) -> list[int]:
        """Get PIDs of child processes from OS (not DB)."""
        if self.proc:
            try:
                return [child.pid for child in self.proc.children(recursive=True)]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return []
```

**Key Safety Features:**

1. **Start time validation**: `psutil.Process.create_time()` must match `self.started_at` within `START_TIME_TOLERANCE` (5 seconds)
2. **Machine check**: Only returns `proc` if on the same machine where process ran
3. **Command validation**: Optional extra check that binary name matches
4. **Returns None on mismatch**: Never returns a stale/wrong psutil.Process

**Usage:**
```python
process = Process.objects.get(id=some_id)

# Safe - returns None if PID was recycled
if process.proc:
    print(f"Memory: {process.proc.memory_info().rss}")
    print(f"CPU: {process.proc.cpu_percent()}")
    process.proc.terminate()  # Safe to kill - we validated it's OUR process

# Convenience properties
if process.is_running:
    print("Still running!")
```

### 1.6 Add Process Lifecycle Methods

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

        Uses self.proc for safe killing - only kills if PID matches
        our recorded process (prevents killing recycled PIDs).

        Args:
            signal_num: Signal to send (default SIGTERM=15)

        Returns:
            True if killed successfully, False otherwise
        """
        from django.utils import timezone

        # Use validated psutil.Process to ensure we're killing the right process
        proc = self.proc
        if proc is None:
            # Process doesn't exist or PID was recycled - just update status
            if self.status != self.StatusChoices.EXITED:
                self.status = self.StatusChoices.EXITED
                self.ended_at = self.ended_at or timezone.now()
                self.save()
            return False

        try:
            # Safe to kill - we validated it's our process via start time match
            proc.send_signal(signal_num)

            # Update our record
            self.exit_code = -signal_num
            self.ended_at = timezone.now()
            self.status = self.StatusChoices.EXITED
            self.save()

            # Clean up PID file
            self.pid_file.unlink(missing_ok=True)

            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            # Process already exited between proc check and kill
            self.status = self.StatusChoices.EXITED
            self.ended_at = self.ended_at or timezone.now()
            self.save()
            return False

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

## Phase 2: Hook System Changes (Detailed)

This section provides a line-by-line mapping of current code to required changes.

### 2.1 Current Architecture Overview

**Current Flow:**
```
ArchiveResult.run() [core/models.py:2463]
    └── run_hook() [hooks.py:238]
            └── subprocess.Popen() [hooks.py:381]
                    └── writes: stdout.log, stderr.log, hook.pid, cmd.sh
```

**Target Flow:**
```
ArchiveResult.run()
    └── run_hook(parent_process=self.process)  # Pass existing Process FK
            └── hook_process = Process.objects.create(parent=parent_process, type=HOOK)
            └── hook_process.launch(background=is_bg)  # Uses Process methods
                    └── writes: stdout.log, stderr.log via Process.stdout_file/stderr_file
                    └── Process handles PID file internally
            └── parse JSONL for {"type": "Process"} records → create child binary Processes
```

### 2.2 Changes to `hooks.py`

#### 2.2.1 Update `run_hook()` Signature and Body

**File:** `archivebox/hooks.py` lines 238-483

**CURRENT CODE (lines 374-398):**
```python
# Set up output files for ALL hooks (useful for debugging)
stdout_file = output_dir / 'stdout.log'
stderr_file = output_dir / 'stderr.log'
pid_file = output_dir / 'hook.pid'
cmd_file = output_dir / 'cmd.sh'

try:
    # Write command script for validation
    from archivebox.misc.process_utils import write_cmd_file
    write_cmd_file(cmd_file, cmd)

    # Open log files for writing
    with open(stdout_file, 'w') as out, open(stderr_file, 'w') as err:
        process = subprocess.Popen(
            cmd,
            cwd=str(output_dir),
            stdout=out,
            stderr=err,
            env=env,
        )

        # Write PID with mtime set to process start time for validation
        from archivebox.misc.process_utils import write_pid_file_with_mtime
        process_start_time = time.time()
        write_pid_file_with_mtime(pid_file, process.pid, process_start_time)

        if is_background:
            # Background hook - return None immediately, don't wait
            return None
```

**NEW CODE:**
```python
def run_hook(
    script: Path,
    output_dir: Path,
    config: Dict[str, Any],
    timeout: Optional[int] = None,
    parent_process: Optional['Process'] = None,  # NEW: from ArchiveResult.process
    **kwargs: Any
) -> HookResult:
    from archivebox.machine.models import Process, Machine

    # ... existing setup (lines 270-372) ...

    # Create Process record for this hook execution
    # Parent is the ArchiveResult's Process (passed from ArchiveResult.run())
    hook_process = Process.objects.create(
        machine=Machine.current(),
        parent=parent_process,
        process_type=Process.TypeChoices.HOOK,
        cmd=cmd,
        pwd=str(output_dir),
        env={k: v for k, v in env.items() if k not in os.environ},  # Only store non-default env
        timeout=timeout,
        status=Process.StatusChoices.QUEUED,
    )

    # Use Process.launch() which handles:
    # - subprocess.Popen
    # - PID file with mtime validation
    # - cmd.sh script
    # - stdout/stderr capture
    # - status transitions
    if is_background:
        hook_process.launch(background=True)
        # Return None for background hooks (existing behavior)
        # HookResult not returned - caller uses hook_process.id to track
        return None
    else:
        hook_process.launch(background=False)  # Blocks until completion

    # Read output from Process (instead of files directly)
    stdout = hook_process.stdout
    stderr = hook_process.stderr
    returncode = hook_process.exit_code

    # ... existing JSONL parsing (lines 427-448) ...

    # NEW: Create child Process records for binaries reported in JSONL
    for record in records:
        if record.get('type') == 'Process':
            Process.objects.create(
                machine=hook_process.machine,
                parent=hook_process,
                process_type=Process.TypeChoices.BINARY,
                cmd=record.get('cmd', []),
                pwd=record.get('pwd', str(output_dir)),
                pid=record.get('pid'),
                exit_code=record.get('exit_code'),
                started_at=parse_ts(record.get('started_at')),
                ended_at=parse_ts(record.get('ended_at')),
                status=Process.StatusChoices.EXITED,
            )

    return HookResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        # ... existing fields ...
        process_id=str(hook_process.id),  # NEW
    )
```

#### 2.2.2 Update `process_is_alive()` to Use Process Model

**CURRENT CODE (lines 1238-1256):**
```python
def process_is_alive(pid_file: Path) -> bool:
    """Check if process in PID file is still running."""
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False
```

**NEW CODE:**
```python
def process_is_alive(pid_file_or_process: 'Path | Process') -> bool:
    """
    Check if process is still running.

    Accepts either:
    - Path to hook.pid file (legacy)
    - Process model instance (new)
    """
    from archivebox.machine.models import Process

    if isinstance(pid_file_or_process, Process):
        return pid_file_or_process.is_alive()

    # Legacy path-based check (for backwards compatibility)
    pid_file = pid_file_or_process
    if not pid_file.exists():
        return False

    # Try to find matching Process record
    try:
        pid = int(pid_file.read_text().strip())
        process = Process.objects.get_by_pid(pid)
        if process:
            return process.is_alive()
    except (ValueError, Process.DoesNotExist):
        pass

    # Fallback to OS check
    from archivebox.misc.process_utils import validate_pid_file
    return validate_pid_file(pid_file)
```

#### 2.2.3 Update `kill_process()` to Use Process Model

**CURRENT CODE (lines 1259-1282):**
```python
def kill_process(pid_file: Path, sig: int = signal.SIGTERM, validate: bool = True):
    """Kill process in PID file with optional validation."""
    from archivebox.misc.process_utils import safe_kill_process

    if validate:
        cmd_file = pid_file.parent / 'cmd.sh'
        safe_kill_process(pid_file, cmd_file, signal_num=sig)
    else:
        # Legacy behavior
        ...
```

**NEW CODE:**
```python
def kill_process(
    pid_file_or_process: 'Path | Process',
    sig: int = signal.SIGTERM,
    validate: bool = True
):
    """
    Kill process with optional validation.

    Accepts either:
    - Path to hook.pid file (legacy)
    - Process model instance (new)
    """
    from archivebox.machine.models import Process

    if isinstance(pid_file_or_process, Process):
        pid_file_or_process.kill(signal_num=sig)
        return

    # Legacy path-based kill
    pid_file = pid_file_or_process

    # Try to find matching Process record first
    try:
        pid = int(pid_file.read_text().strip())
        process = Process.objects.get_by_pid(pid)
        if process:
            process.kill(signal_num=sig)
            return
    except (ValueError, Process.DoesNotExist, FileNotFoundError):
        pass

    # Fallback to file-based kill
    if validate:
        from archivebox.misc.process_utils import safe_kill_process
        cmd_file = pid_file.parent / 'cmd.sh'
        safe_kill_process(pid_file, cmd_file, signal_num=sig)
```

### 2.3 Changes to `core/models.py` - ArchiveResult

#### 2.3.1 Update `ArchiveResult.run()` to Pass Parent Process

**File:** `archivebox/core/models.py` lines 2463-2565

**CURRENT CODE (lines 2527-2535):**
```python
result = run_hook(
    hook,
    output_dir=plugin_dir,
    config=config,
    url=self.snapshot.url,
    snapshot_id=str(self.snapshot.id),
    crawl_id=str(self.snapshot.crawl.id),
    depth=self.snapshot.depth,
)
```

**NEW CODE:**
```python
result = run_hook(
    hook,
    output_dir=plugin_dir,
    config=config,
    parent_process=self.process,  # NEW: Pass our Process as parent for hook's Process
    url=self.snapshot.url,
    snapshot_id=str(self.snapshot.id),
    crawl_id=str(self.snapshot.crawl.id),
    depth=self.snapshot.depth,
)
```

#### 2.3.2 Update `ArchiveResult.update_from_output()` to Use Process

**File:** `archivebox/core/models.py` lines 2568-2700

**CURRENT CODE (lines 2598-2600):**
```python
# Read and parse JSONL output from stdout.log
stdout_file = plugin_dir / 'stdout.log'
stdout = stdout_file.read_text() if stdout_file.exists() else ''
```

**NEW CODE:**
```python
# Read output from Process record (populated by Process.launch())
if self.process_id:
    # Process already has stdout/stderr from launch()
    stdout = self.process.stdout
    stderr = self.process.stderr
else:
    # Fallback to file-based read (legacy)
    stdout_file = plugin_dir / 'stdout.log'
    stdout = stdout_file.read_text() if stdout_file.exists() else ''
```

### 2.4 Changes to `core/models.py` - Snapshot

#### 2.4.1 Update `Snapshot.cleanup()` to Use Process Model

**File:** `archivebox/core/models.py` lines 1381-1401

**CURRENT CODE:**
```python
def cleanup(self):
    from archivebox.hooks import kill_process

    if not self.OUTPUT_DIR.exists():
        return

    # Find all .pid files in this snapshot's output directory
    for pid_file in self.OUTPUT_DIR.glob('**/*.pid'):
        kill_process(pid_file, validate=True)

    # Update all STARTED ArchiveResults from filesystem
    results = self.archiveresult_set.filter(status=ArchiveResult.StatusChoices.STARTED)
    for ar in results:
        ar.update_from_output()
```

**NEW CODE:**
```python
def cleanup(self):
    """
    Clean up background ArchiveResult hooks.

    Uses Process model to find and kill running hooks.
    Falls back to PID file scanning for legacy compatibility.
    """
    from archivebox.machine.models import Process

    # Kill running hook Processes for this snapshot's ArchiveResults
    for ar in self.archiveresult_set.filter(status=ArchiveResult.StatusChoices.STARTED):
        if ar.process_id:
            # Get hook Processes that are children of this AR's Process
            hook_processes = Process.objects.filter(
                parent=ar.process,
                process_type=Process.TypeChoices.HOOK,
                status=Process.StatusChoices.RUNNING,
            )
            for hook_proc in hook_processes:
                hook_proc.kill()

        # Also kill any child binary processes
        if ar.process_id:
            for child in ar.process.children.filter(status=Process.StatusChoices.RUNNING):
                child.kill()

    # Legacy fallback: scan for .pid files not tracked in DB
    if self.OUTPUT_DIR.exists():
        from archivebox.hooks import kill_process
        for pid_file in self.OUTPUT_DIR.glob('**/*.pid'):
            kill_process(pid_file, validate=True)

    # Update all STARTED ArchiveResults from filesystem/Process
    for ar in self.archiveresult_set.filter(status=ArchiveResult.StatusChoices.STARTED):
        ar.update_from_output()
```

#### 2.4.2 Update `Snapshot.has_running_background_hooks()` to Use Process Model

**CURRENT CODE (lines 1403-1420):**
```python
def has_running_background_hooks(self) -> bool:
    from archivebox.hooks import process_is_alive

    if not self.OUTPUT_DIR.exists():
        return False

    for plugin_dir in self.OUTPUT_DIR.iterdir():
        if not plugin_dir.is_dir():
            continue
        pid_file = plugin_dir / 'hook.pid'
        if process_is_alive(pid_file):
            return True

    return False
```

**NEW CODE:**
```python
def has_running_background_hooks(self) -> bool:
    """
    Check if any ArchiveResult background hooks are still running.

    Uses Process model for tracking, falls back to PID file check.
    """
    from archivebox.machine.models import Process

    # Check via Process model (preferred)
    for ar in self.archiveresult_set.filter(status=ArchiveResult.StatusChoices.STARTED):
        if ar.process_id:
            # Check if hook Process children are running
            running_hooks = Process.objects.filter(
                parent=ar.process,
                process_type=Process.TypeChoices.HOOK,
                status=Process.StatusChoices.RUNNING,
            ).exists()
            if running_hooks:
                return True

            # Also check the AR's own process
            if ar.process.is_alive():
                return True

    # Legacy fallback: check PID files
    if self.OUTPUT_DIR.exists():
        from archivebox.hooks import process_is_alive
        for plugin_dir in self.OUTPUT_DIR.iterdir():
            if plugin_dir.is_dir():
                pid_file = plugin_dir / 'hook.pid'
                if process_is_alive(pid_file):
                    return True

    return False
```

### 2.5 Hook JSONL Output Contract Update

Hooks should now output `{"type": "Process", ...}` records for any binaries they run:

```jsonl
{"type": "ArchiveResult", "status": "succeeded", "output_str": "Downloaded page"}
{"type": "Process", "cmd": ["/usr/bin/wget", "-p", "https://example.com"], "pid": 12345, "exit_code": 0, "started_at": "2024-01-15T10:30:00Z", "ended_at": "2024-01-15T10:30:05Z"}
{"type": "Process", "cmd": ["/usr/bin/curl", "-O", "image.png"], "pid": 12346, "exit_code": 0}
```

This allows full tracking of the process hierarchy:
```
Process(archivebox add, type=CLI)
    └── Process(orchestrator, type=ORCHESTRATOR)
            └── Process(archiveresult_worker, type=WORKER)
                    └── Process(on_Snapshot__50_wget.py, type=HOOK)  # ArchiveResult.process
                            └── Process(wget -p ..., type=BINARY)   # from JSONL
                            └── Process(curl -O ..., type=BINARY)   # from JSONL
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

### 3.3 Track Supervisord Process (Detailed)

**File:** `archivebox/workers/supervisord_util.py`

Supervisord is special: it's spawned by `subprocess.Popen` (not through Process.current()).
We create its Process record manually after spawning.

#### 3.3.1 Update Module-Level Variables

**CURRENT CODE (line 31):**
```python
# Global reference to supervisord process for cleanup
_supervisord_proc = None
```

**NEW CODE:**
```python
# Global references for cleanup
_supervisord_proc = None
_supervisord_db_process = None  # NEW: Database Process record
```

#### 3.3.2 Update `start_new_supervisord_process()`

**CURRENT CODE (lines 263-278):**
```python
proc = subprocess.Popen(
    f"supervisord --configuration={CONFIG_FILE}",
    stdin=None,
    stdout=log_handle,
    stderr=log_handle,
    shell=True,
    start_new_session=False,
)

global _supervisord_proc
_supervisord_proc = proc

time.sleep(2)
return get_existing_supervisord_process()
```

**NEW CODE:**
```python
from archivebox.machine.models import Process, Machine
import psutil

proc = subprocess.Popen(
    f"supervisord --configuration={CONFIG_FILE}",
    stdin=None,
    stdout=log_handle,
    stderr=log_handle,
    shell=True,
    start_new_session=False,
)

global _supervisord_proc, _supervisord_db_process
_supervisord_proc = proc

# Create Process record for supervisord
# Parent is Process.current() (the CLI command that started it)
try:
    os_proc = psutil.Process(proc.pid)
    started_at = datetime.fromtimestamp(os_proc.create_time(), tz=timezone.utc)
except (psutil.NoSuchProcess, psutil.AccessDenied):
    started_at = timezone.now()

_supervisord_db_process = Process.objects.create(
    machine=Machine.current(),
    parent=Process.current(),  # CLI process that spawned supervisord
    process_type=Process.TypeChoices.SUPERVISORD,
    cmd=['supervisord', f'--configuration={CONFIG_FILE}'],
    pwd=str(CONSTANTS.DATA_DIR),
    pid=proc.pid,
    started_at=started_at,
    status=Process.StatusChoices.RUNNING,
)

time.sleep(2)
return get_existing_supervisord_process()
```

#### 3.3.3 Update `stop_existing_supervisord_process()`

**ADD at end of function (after line 217):**
```python
# Update database Process record
global _supervisord_db_process
if _supervisord_db_process:
    _supervisord_db_process.status = Process.StatusChoices.EXITED
    _supervisord_db_process.ended_at = timezone.now()
    _supervisord_db_process.exit_code = 0
    _supervisord_db_process.save()
    _supervisord_db_process = None
```

#### 3.3.4 Diagram: Supervisord Process Hierarchy

```
Process(archivebox server, type=CLI)          # Created by Process.current() in main()
    │
    └── Process(supervisord, type=SUPERVISORD)  # Created manually in start_new_supervisord_process()
            │
            ├── Process(orchestrator, type=ORCHESTRATOR)  # Created by Process.current() in Orchestrator.on_startup()
            │       │
            │       └── Process(crawl_worker, type=WORKER)
            │               │
            │               └── Process(snapshot_worker, type=WORKER)
            │                       │
            │                       └── Process(archiveresult_worker, type=WORKER)
            │                               │
            │                               └── Process(hook, type=HOOK)  # ArchiveResult.process
            │                                       │
            │                                       └── Process(binary, type=BINARY)
            │
            └── Process(daphne, type=WORKER)  # Web server worker
```

Note: Workers spawned BY supervisord (like orchestrator, daphne) are NOT tracked as supervisord's children
in Process hierarchy - they appear as children of the orchestrator because that's where `Process.current()`
is called (in `Worker.on_startup()` / `Orchestrator.on_startup()`).

The PPID-based linking works because:
1. Supervisord spawns orchestrator process
2. Orchestrator calls `Process.current()` in `on_startup()`
3. `Process.current()` looks up PPID → finds supervisord's Process → sets as parent

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
