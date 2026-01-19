"""
Worker classes for processing queue items.

Workers poll the database for items to process, claim them atomically,
and run the state machine tick() to process each item.

Architecture:
    Orchestrator (spawns workers)
    └── Worker (claims items from queue, processes them directly)
"""

__package__ = 'archivebox.workers'

import os
import time
import traceback
from typing import ClassVar, Any
from datetime import timedelta
from pathlib import Path
from multiprocessing import cpu_count

from django.db.models import QuerySet
from django.utils import timezone
from django.conf import settings

from statemachine.exceptions import TransitionNotAllowed
from rich import print

from archivebox.misc.logging_util import log_worker_event


CPU_COUNT = cpu_count()

# Registry of worker types by name (defined at bottom, referenced here for _run_worker)
WORKER_TYPES: dict[str, type['Worker']] = {}


def _run_worker(worker_class_name: str, worker_id: int, **kwargs):
    """
    Module-level function to run a worker. Must be at module level for pickling.
    """
    from archivebox.config.django import setup_django
    setup_django()

    # Get worker class by name to avoid pickling class objects
    worker_cls = WORKER_TYPES[worker_class_name]
    worker = worker_cls(worker_id=worker_id, **kwargs)
    worker.runloop()


def _run_snapshot_worker(snapshot_id: str, worker_id: int, **kwargs):
    """
    Module-level function to run a SnapshotWorker for a specific snapshot.
    Must be at module level for pickling compatibility.
    """
    from archivebox.config.django import setup_django
    setup_django()

    worker = SnapshotWorker(snapshot_id=snapshot_id, worker_id=worker_id, **kwargs)
    worker.runloop()


class Worker:
    """
    Base worker class for CrawlWorker and SnapshotWorker.

    Workers are spawned as subprocesses to process crawls and snapshots.
    Each worker type has its own custom runloop implementation.
    """

    name: ClassVar[str] = 'worker'

    # Configuration (can be overridden by subclasses)
    MAX_TICK_TIME: ClassVar[int] = 60
    MAX_CONCURRENT_TASKS: ClassVar[int] = 1

    def __init__(self, worker_id: int = 0, **kwargs: Any):
        self.worker_id = worker_id
        self.pid: int = os.getpid()

    def __repr__(self) -> str:
        return f'[underline]{self.__class__.__name__}[/underline]\\[id={self.worker_id}, pid={self.pid}]'

    def get_model(self):
        """Get the Django model class. Subclasses must override this."""
        raise NotImplementedError("Subclasses must implement get_model()")

    def on_startup(self) -> None:
        """Called when worker starts."""
        from archivebox.machine.models import Process

        self.pid = os.getpid()
        # Register this worker process in the database
        self.db_process = Process.current()
        # Explicitly set process_type to WORKER and store worker type name
        update_fields = []
        if self.db_process.process_type != Process.TypeChoices.WORKER:
            self.db_process.process_type = Process.TypeChoices.WORKER
            update_fields.append('process_type')
        # Store worker type name (crawl/snapshot) in worker_type field
        if not self.db_process.worker_type:
            self.db_process.worker_type = self.name
            update_fields.append('worker_type')
        if update_fields:
            self.db_process.save(update_fields=update_fields)

        # Determine worker type for logging
        worker_type_name = self.__class__.__name__
        indent_level = 1  # Default for CrawlWorker

        # SnapshotWorker gets indent level 2
        if 'Snapshot' in worker_type_name:
            indent_level = 2

        log_worker_event(
            worker_type=worker_type_name,
            event='Starting...',
            indent_level=indent_level,
            pid=self.pid,
            worker_id=str(self.worker_id),
        )

    def on_shutdown(self, error: BaseException | None = None) -> None:
        """Called when worker shuts down."""
        # Update Process record status
        if hasattr(self, 'db_process') and self.db_process:
            self.db_process.exit_code = 1 if error else 0
            self.db_process.status = self.db_process.StatusChoices.EXITED
            self.db_process.ended_at = timezone.now()
            self.db_process.save()

        # Determine worker type for logging
        worker_type_name = self.__class__.__name__
        indent_level = 1  # CrawlWorker

        if 'Snapshot' in worker_type_name:
            indent_level = 2

        log_worker_event(
            worker_type=worker_type_name,
            event='Shutting down',
            indent_level=indent_level,
            pid=self.pid,
            worker_id=str(self.worker_id),
            error=error if error and not isinstance(error, KeyboardInterrupt) else None,
        )

    def _terminate_background_hooks(
        self,
        background_processes: dict[str, 'Process'],
        worker_type: str,
        indent_level: int,
    ) -> None:
        """
        Terminate background hooks in 3 phases (shared logic for Crawl/Snapshot workers).

        Phase 1: Send SIGTERM to all bg hooks + children in parallel (polite request to wrap up)
        Phase 2: Wait for each hook's remaining timeout before SIGKILL
        Phase 3: SIGKILL any stragglers that exceeded their timeout

        Args:
            background_processes: Dict mapping hook name -> Process instance
            worker_type: Worker type name for logging (e.g., 'CrawlWorker', 'SnapshotWorker')
            indent_level: Logging indent level (1 for Crawl, 2 for Snapshot)
        """
        import signal
        import time

        if not background_processes:
            return

        now = time.time()

        # Phase 1: Send SIGTERM to ALL background processes + children in parallel
        log_worker_event(
            worker_type=worker_type,
            event=f'Sending SIGTERM to {len(background_processes)} background hooks (+ children)',
            indent_level=indent_level,
            pid=self.pid,
        )

        # Build deadline map first (before killing, to get accurate remaining time)
        deadlines = {}
        for hook_name, process in background_processes.items():
            elapsed = now - process.started_at.timestamp()
            remaining = max(0, process.timeout - elapsed)
            deadline = now + remaining
            deadlines[hook_name] = (process, deadline)

        # Send SIGTERM to all process trees in parallel (non-blocking)
        for hook_name, process in background_processes.items():
            try:
                # Get chrome children (renderer processes etc) before sending signal
                children_pids = process.get_children_pids()
                if children_pids:
                    # Chrome hook with children - kill tree
                    os.kill(process.pid, signal.SIGTERM)
                    for child_pid in children_pids:
                        try:
                            os.kill(child_pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    log_worker_event(
                        worker_type=worker_type,
                        event=f'Sent SIGTERM to {hook_name} + {len(children_pids)} children',
                        indent_level=indent_level,
                        pid=self.pid,
                    )
                else:
                    # No children - normal kill
                    os.kill(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass  # Already dead
            except Exception as e:
                log_worker_event(
                    worker_type=worker_type,
                    event=f'Failed to SIGTERM {hook_name}: {e}',
                    indent_level=indent_level,
                    pid=self.pid,
                )

        # Phase 2: Wait for all processes in parallel, respecting individual timeouts
        for hook_name, (process, deadline) in deadlines.items():
            remaining = deadline - now
            log_worker_event(
                worker_type=worker_type,
                event=f'Waiting up to {remaining:.1f}s for {hook_name}',
                indent_level=indent_level,
                pid=self.pid,
            )

        # Poll all processes in parallel using Process.poll()
        still_running = set(deadlines.keys())

        while still_running:
            time.sleep(0.1)
            now = time.time()

            for hook_name in list(still_running):
                process, deadline = deadlines[hook_name]

                # Check if process exited using Process.poll()
                exit_code = process.poll()
                if exit_code is not None:
                    # Process exited
                    still_running.remove(hook_name)
                    log_worker_event(
                        worker_type=worker_type,
                        event=f'✓ {hook_name} exited with code {exit_code}',
                        indent_level=indent_level,
                        pid=self.pid,
                    )
                    continue

                # Check if deadline exceeded
                if now >= deadline:
                    # Timeout exceeded - SIGKILL process tree
                    try:
                        # Get children before killing (chrome may have spawned more)
                        children_pids = process.get_children_pids()
                        if children_pids:
                            # Kill children first
                            for child_pid in children_pids:
                                try:
                                    os.kill(child_pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                        # Then kill parent
                        process.kill(signal_num=signal.SIGKILL)
                        log_worker_event(
                            worker_type=worker_type,
                            event=f'⚠ Sent SIGKILL to {hook_name} + {len(children_pids) if children_pids else 0} children (exceeded timeout)',
                            indent_level=indent_level,
                            pid=self.pid,
                        )
                    except Exception as e:
                        log_worker_event(
                            worker_type=worker_type,
                            event=f'Failed to SIGKILL {hook_name}: {e}',
                            indent_level=indent_level,
                            pid=self.pid,
                        )
                    still_running.remove(hook_name)

    @classmethod
    def start(cls, parent: Any = None, **kwargs: Any) -> int:
        """
        Fork a new worker as a subprocess using Process.launch().

        Args:
            parent: Parent Process record (for hierarchy tracking)
            **kwargs: Worker-specific args (crawl_id or snapshot_id)

        Returns the PID of the new process.
        """
        from archivebox.machine.models import Process, Machine
        from archivebox.config.configset import get_config
        from pathlib import Path
        from django.conf import settings
        import sys

        # Build command and get config for the appropriate scope
        if cls.name == 'crawl':
            crawl_id = kwargs.get('crawl_id')
            if not crawl_id:
                raise ValueError("CrawlWorker requires crawl_id")

            from archivebox.crawls.models import Crawl
            crawl = Crawl.objects.get(id=crawl_id)

            cmd = [sys.executable, '-m', 'archivebox', 'run', '--crawl-id', str(crawl_id)]
            pwd = Path(crawl.output_dir)  # Run in crawl's output directory
            env = get_config(crawl=crawl)

        elif cls.name == 'snapshot':
            snapshot_id = kwargs.get('snapshot_id')
            if not snapshot_id:
                raise ValueError("SnapshotWorker requires snapshot_id")

            from archivebox.core.models import Snapshot
            snapshot = Snapshot.objects.get(id=snapshot_id)

            cmd = [sys.executable, '-m', 'archivebox', 'run', '--snapshot-id', str(snapshot_id)]
            pwd = Path(snapshot.output_dir)  # Run in snapshot's output directory
            env = get_config(snapshot=snapshot)

        elif cls.name == 'binary':
            # BinaryWorker supports two modes:
            # 1. Singleton daemon (no binary_id) - processes ALL pending binaries
            # 2. Specific binary (with binary_id) - processes just that one binary
            binary_id = kwargs.get('binary_id')

            if binary_id:
                # Specific binary mode
                from archivebox.machine.models import Binary
                binary = Binary.objects.get(id=binary_id)

                cmd = [sys.executable, '-m', 'archivebox', 'run', '--binary-id', str(binary_id)]
                pwd = Path(settings.DATA_DIR) / 'machines' / str(Machine.current().id) / 'binaries' / binary.name / str(binary.id)
                pwd.mkdir(parents=True, exist_ok=True)
            else:
                # Singleton daemon mode - processes all pending binaries
                cmd = [sys.executable, '-m', 'archivebox', 'run', '--worker-type', 'binary']
                pwd = Path(settings.DATA_DIR) / 'machines' / str(Machine.current().id) / 'binaries'
                pwd.mkdir(parents=True, exist_ok=True)

            env = get_config()

        else:
            raise ValueError(f"Unknown worker type: {cls.name}")

        # Ensure output directory exists
        pwd.mkdir(parents=True, exist_ok=True)

        # Convert config to JSON-serializable format for storage
        import json
        env_serializable = {
            k: json.loads(json.dumps(v, default=str))
            for k, v in env.items()
            if v is not None
        }

        # Create Process record with full config as environment
        # pwd = where stdout/stderr/pid/cmd files are written (snapshot/crawl output dir)
        # cwd (passed to launch) = where subprocess runs from (DATA_DIR)
        # parent = parent Process for hierarchy tracking (CrawlWorker -> SnapshotWorker)
        process = Process.objects.create(
            machine=Machine.current(),
            parent=parent,
            process_type=Process.TypeChoices.WORKER,
            worker_type=cls.name,
            pwd=str(pwd),
            cmd=cmd,
            env=env_serializable,
            timeout=3600,  # 1 hour default timeout for workers
        )

        # Launch in background with DATA_DIR as working directory
        process.launch(background=True, cwd=str(settings.DATA_DIR))

        return process.pid

    @classmethod
    def get_running_workers(cls) -> list:
        """Get info about all running workers of this type."""
        from archivebox.machine.models import Process

        Process.cleanup_stale_running()
        # Convert Process objects to dicts to match the expected API contract
        # Filter by worker_type to get only workers of this specific type (crawl/snapshot/archiveresult)
        processes = Process.objects.filter(
            process_type=Process.TypeChoices.WORKER,
            worker_type=cls.name,  # Filter by specific worker type
            status__in=['running', 'started']
        )
        # Note: worker_id is not stored on Process model, it's dynamically generated
        # We return process_id (UUID) and pid (OS process ID) instead
        return [
            {
                'pid': p.pid,
                'process_id': str(p.id),  # UUID of Process record
                'started_at': p.started_at.isoformat() if p.started_at else None,
                'status': p.status,
            }
            for p in processes
        ]

    @classmethod
    def get_worker_count(cls) -> int:
        """Get count of running workers of this type."""
        from archivebox.machine.models import Process

        return Process.objects.filter(
            process_type=Process.TypeChoices.WORKER,
            worker_type=cls.name,  # Filter by specific worker type
            status__in=['running', 'started']
        ).count()


class CrawlWorker(Worker):
    """
    Worker for processing Crawl objects.

    Responsibilities:
    1. Run on_Crawl__* hooks (e.g., chrome launcher)
    2. Create Snapshots from URLs
    3. Spawn SnapshotWorkers (up to MAX_SNAPSHOT_WORKERS)
    4. Monitor snapshots and seal crawl when all done
    """

    name: ClassVar[str] = 'crawl'
    MAX_TICK_TIME: ClassVar[int] = 60
    MAX_SNAPSHOT_WORKERS: ClassVar[int] = 8  # Per crawl limit

    def __init__(self, crawl_id: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.crawl_id = crawl_id
        self.crawl = None

    def get_model(self):
        from archivebox.crawls.models import Crawl
        return Crawl

    def on_startup(self) -> None:
        """Load crawl."""
        super().on_startup()

        from archivebox.crawls.models import Crawl
        self.crawl = Crawl.objects.get(id=self.crawl_id)

    def runloop(self) -> None:
        """Run crawl state machine, spawn SnapshotWorkers."""
        import sys
        from archivebox.crawls.models import Crawl
        self.on_startup()

        try:
            print(f'🔄 CrawlWorker starting for crawl {self.crawl_id}', file=sys.stderr)

            if self.crawl.status == Crawl.StatusChoices.SEALED:
                print(
                    '✅ This crawl has already completed and there are no tasks remaining.\n'
                    '   To re-crawl it, create a new crawl with the same URLs, e.g.\n'
                    '   archivebox crawl create <urls> | archivebox run',
                    file=sys.stderr,
                )
                return

            # Advance state machine: QUEUED → STARTED (triggers run() via @started.enter)
            try:
                self.crawl.sm.tick()
            except TransitionNotAllowed:
                if self.crawl.status == Crawl.StatusChoices.SEALED:
                    print(
                        '✅ This crawl has already completed and there are no tasks remaining.\n'
                        '   To re-crawl it, create a new crawl with the same URLs, e.g.\n'
                        '   archivebox crawl create <urls> | archivebox run',
                        file=sys.stderr,
                    )
                    return
                raise
            self.crawl.refresh_from_db()
            print(f'🔄 tick() complete, crawl status={self.crawl.status}', file=sys.stderr)

            # Now spawn SnapshotWorkers and monitor progress
            while True:
                # Check if crawl is done
                if self._is_crawl_finished():
                    print(f'🔄 Crawl finished, sealing...', file=sys.stderr)
                    self.crawl.sm.seal()
                    break

                # Spawn workers for queued snapshots
                self._spawn_snapshot_workers()

                time.sleep(2)  # Check every 2s

        finally:
            self.on_shutdown()

    def _spawn_snapshot_workers(self) -> None:
        """Spawn SnapshotWorkers for queued snapshots (up to limit)."""
        from pathlib import Path
        from archivebox.core.models import Snapshot
        from archivebox.machine.models import Process
        import sys
        import threading

        debug_log = Path('/tmp/archivebox_crawl_worker_debug.log')

        # Count running SnapshotWorkers for this crawl
        running_count = Process.objects.filter(
            process_type=Process.TypeChoices.WORKER,
            worker_type='snapshot',
            parent_id=self.db_process.id,  # Children of this CrawlWorker
            status__in=['running', 'started'],
        ).count()

        with open(debug_log, 'a') as f:
            f.write(f'  _spawn_snapshot_workers: running={running_count}/{self.MAX_SNAPSHOT_WORKERS}\n')
            f.flush()

        if running_count >= self.MAX_SNAPSHOT_WORKERS:
            return  # At limit

        # Get snapshots that need workers spawned
        # Find all running SnapshotWorker processes for this crawl
        running_processes = Process.objects.filter(
            parent_id=self.db_process.id,
            worker_type='snapshot',
            status__in=['running', 'started'],
        )

        # Extract snapshot IDs from worker cmd args (more reliable than pwd paths)
        running_snapshot_ids = []
        for proc in running_processes:
            cmd = proc.cmd or []
            snapshot_id = None
            for i, part in enumerate(cmd):
                if part == '--snapshot-id' and i + 1 < len(cmd):
                    snapshot_id = cmd[i + 1]
                    break
                if part.startswith('--snapshot-id='):
                    snapshot_id = part.split('=', 1)[1]
                    break
            if snapshot_id:
                running_snapshot_ids.append(snapshot_id)

        # Find snapshots that don't have a running worker
        all_snapshots = Snapshot.objects.filter(
            crawl_id=self.crawl_id,
            status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED],
        ).order_by('created_at')

        # Filter out snapshots that already have workers
        pending_snapshots = [
            snap for snap in all_snapshots
            if str(snap.id) not in running_snapshot_ids
        ][:self.MAX_SNAPSHOT_WORKERS - running_count]

        with open(debug_log, 'a') as f:
            f.write(f'  Found {len(pending_snapshots)} snapshots needing workers for crawl {self.crawl_id}\n')
            f.flush()

        # Spawn workers
        for snapshot in pending_snapshots:
            with open(debug_log, 'a') as f:
                f.write(f'  Spawning worker for {snapshot.url} (status={snapshot.status})\n')
                f.flush()

            pid = SnapshotWorker.start(parent=self.db_process, snapshot_id=str(snapshot.id))

            log_worker_event(
                worker_type='CrawlWorker',
                event=f'Spawned SnapshotWorker for {snapshot.url}',
                indent_level=1,
                pid=self.pid,
            )

            # Pipe the SnapshotWorker's stderr to our stderr so we can see what's happening
            # Get the Process record that was just created
            worker_process = Process.objects.filter(pid=pid).first()
            if worker_process:
                # Pipe stderr in background thread so it doesn't block
                def pipe_worker_stderr():
                    for line in worker_process.tail_stderr(lines=0, follow=True):
                        print(f'  [SnapshotWorker] {line}', file=sys.stderr, flush=True)

                thread = threading.Thread(target=pipe_worker_stderr, daemon=True)
                thread.start()

    def _is_crawl_finished(self) -> bool:
        """Check if all snapshots are sealed."""
        from pathlib import Path
        from archivebox.core.models import Snapshot

        debug_log = Path('/tmp/archivebox_crawl_worker_debug.log')

        total = Snapshot.objects.filter(crawl_id=self.crawl_id).count()
        pending = Snapshot.objects.filter(
            crawl_id=self.crawl_id,
            status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED],
        ).count()

        queued = Snapshot.objects.filter(crawl_id=self.crawl_id, status=Snapshot.StatusChoices.QUEUED).count()
        started = Snapshot.objects.filter(crawl_id=self.crawl_id, status=Snapshot.StatusChoices.STARTED).count()
        sealed = Snapshot.objects.filter(crawl_id=self.crawl_id, status=Snapshot.StatusChoices.SEALED).count()

        with open(debug_log, 'a') as f:
            f.write(f'  _is_crawl_finished: total={total}, queued={queued}, started={started}, sealed={sealed}, pending={pending}\n')
            f.flush()

        return pending == 0

    def on_shutdown(self, error: BaseException | None = None) -> None:
        """
        Terminate all background Crawl hooks when crawl finishes.

        Background hooks (e.g., chrome launcher) should only be killed when:
        - All snapshots are done (crawl is sealed)
        - Worker is shutting down
        """
        from archivebox.machine.models import Process

        # Query for all running hook processes that are children of this CrawlWorker
        background_hooks = Process.objects.filter(
            parent_id=self.db_process.id,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
        ).select_related('machine')

        # Build dict for shared termination logic
        background_processes = {
            hook.cmd[0] if hook.cmd else f'hook-{hook.pid}': hook
            for hook in background_hooks
        }

        # Use shared termination logic from Worker base class
        self._terminate_background_hooks(
            background_processes=background_processes,
            worker_type='CrawlWorker',
            indent_level=1,
        )

        super().on_shutdown(error)


class SnapshotWorker(Worker):
    """
    Worker that owns sequential hook execution for ONE snapshot.

    Unlike other workers, SnapshotWorker doesn't poll a queue - it's given
    a specific snapshot_id and runs all hooks for that snapshot sequentially.

    Execution flow:
    1. Mark snapshot as STARTED
    2. Discover hooks for snapshot
    3. For each hook (sorted by name):
        a. Fork hook Process
        b. If foreground: wait for completion
        c. If background: track but continue to next hook
        d. Update ArchiveResult status
    4. When all hooks done: seal snapshot
    5. On shutdown: SIGTERM all background hooks
    """

    name: ClassVar[str] = 'snapshot'

    def __init__(self, snapshot_id: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.snapshot_id = snapshot_id
        self.snapshot = None
        self.background_processes: dict[str, Any] = {}  # hook_name -> Process

    def get_model(self):
        """Not used - SnapshotWorker doesn't poll queues."""
        from archivebox.core.models import Snapshot
        return Snapshot

    def on_startup(self) -> None:
        """Load snapshot and mark as STARTED using state machine."""
        super().on_startup()

        from archivebox.core.models import Snapshot
        self.snapshot = Snapshot.objects.get(id=self.snapshot_id)

        # Use state machine to transition queued -> started (triggers enter_started())
        self.snapshot.sm.tick()
        self.snapshot.refresh_from_db()

    def runloop(self) -> None:
        """Execute all hooks sequentially."""
        from archivebox.hooks import discover_hooks, is_background_hook
        from archivebox.core.models import ArchiveResult
        from archivebox.config.configset import get_config

        self.on_startup()

        try:
            # Get merged config (includes env vars passed via Process.env, snapshot.config, defaults, etc.)
            config = get_config(snapshot=self.snapshot, crawl=self.snapshot.crawl)

            # Discover all hooks for this snapshot
            hooks = discover_hooks('Snapshot', config=config)
            hooks = sorted(hooks, key=lambda h: h.name)  # Sort by name (includes step prefix)

            # Execute each hook sequentially
            for hook_path in hooks:
                hook_name = hook_path.name
                plugin = self._extract_plugin_name(hook_path, hook_name)
                is_background = is_background_hook(hook_name)

                # Create ArchiveResult for THIS HOOK (not per plugin)
                # One plugin can have multiple hooks (e.g., chrome/on_Snapshot__20_launch_chrome.js, chrome/on_Snapshot__21_navigate_chrome.js)
                # Unique key = (snapshot, plugin, hook_name) for idempotency
                ar, created = ArchiveResult.objects.get_or_create(
                    snapshot=self.snapshot,
                    plugin=plugin,
                    hook_name=hook_name,
                    defaults={
                        'status': ArchiveResult.StatusChoices.STARTED,
                        'start_ts': timezone.now(),
                    }
                )

                if not created:
                    # Update existing AR to STARTED
                    ar.status = ArchiveResult.StatusChoices.STARTED
                    ar.start_ts = timezone.now()
                    ar.save(update_fields=['status', 'start_ts', 'modified_at'])

                # Fork and run the hook
                process = self._run_hook(hook_path, ar, config)

                if is_background:
                    # Track but don't wait
                    self.background_processes[hook_name] = process
                    log_worker_event(
                        worker_type='SnapshotWorker',
                        event=f'Started background hook: {hook_name} (timeout={process.timeout}s)',
                        indent_level=2,
                        pid=self.pid,
                    )
                else:
                    # Wait for foreground hook to complete
                    self._wait_for_hook(process, ar)
                    log_worker_event(
                        worker_type='SnapshotWorker',
                        event=f'Completed hook: {hook_name}',
                        indent_level=2,
                        pid=self.pid,
                    )

                # Reap any background hooks that finished while we worked
                self._reap_background_hooks()

            # All hooks launched (or completed) - terminate bg hooks and seal
            self._finalize_background_hooks()
            # This triggers enter_sealed() which calls cleanup() and checks parent crawl sealing
            self.snapshot.sm.seal()
            self.snapshot.refresh_from_db()

        except Exception as e:
            # Mark snapshot as sealed even on error (still triggers cleanup)
            self._finalize_background_hooks()
            self.snapshot.sm.seal()
            self.snapshot.refresh_from_db()
            raise
        finally:
            self.on_shutdown()

    def _run_hook(self, hook_path: Path, ar: Any, config: dict) -> Any:
        """Fork and run a hook using Process model, return Process."""
        from archivebox.hooks import run_hook

        # Create output directory
        output_dir = ar.create_output_dir()

        # Run hook using Process.launch() - returns Process model directly
        # Pass self.db_process as parent to track SnapshotWorker -> Hook hierarchy
        process = run_hook(
            script=hook_path,
            output_dir=output_dir,
            config=config,
            parent=self.db_process,
            url=str(self.snapshot.url),
            snapshot_id=str(self.snapshot.id),
        )

        # Link ArchiveResult to Process for tracking
        ar.process = process
        ar.save(update_fields=['process_id', 'modified_at'])

        return process

    def _wait_for_hook(self, process: Any, ar: Any) -> None:
        """Wait for hook using Process.wait(), update AR status."""
        # Use Process.wait() helper instead of manual polling
        try:
            exit_code = process.wait(timeout=process.timeout)
        except TimeoutError:
            # Hook exceeded timeout - kill it
            process.kill(signal_num=9)
            exit_code = process.exit_code or 137

        # Update ArchiveResult from hook output
        ar.update_from_output()
        ar.end_ts = timezone.now()

        # Apply hook-emitted JSONL records regardless of exit code
        from archivebox.hooks import extract_records_from_process, process_hook_records

        records = extract_records_from_process(process)
        if records:
            process_hook_records(
                records,
                overrides={'snapshot': self.snapshot, 'crawl': self.snapshot.crawl},
            )

        # Determine final status from hook exit code
        if exit_code == 0:
            ar.status = ar.StatusChoices.SUCCEEDED
        else:
            ar.status = ar.StatusChoices.FAILED

        ar.save(update_fields=['status', 'end_ts', 'modified_at'])

    def _finalize_background_hooks(self) -> None:
        """Gracefully terminate background hooks and update their ArchiveResults."""
        if getattr(self, '_background_hooks_finalized', False):
            return

        self._background_hooks_finalized = True

        # Send SIGTERM and wait up to each hook's remaining timeout
        self._terminate_background_hooks(
            background_processes=self.background_processes,
            worker_type='SnapshotWorker',
            indent_level=2,
        )

        # Clear to avoid double-termination during on_shutdown
        self.background_processes = {}

        # Update background results now that hooks are done
        from archivebox.core.models import ArchiveResult

        bg_results = self.snapshot.archiveresult_set.filter(
            hook_name__contains='.bg.',
        )
        for ar in bg_results:
            ar.update_from_output()

    def _reap_background_hooks(self) -> None:
        """Update ArchiveResults for background hooks that already exited."""
        if getattr(self, '_background_hooks_finalized', False):
            return
        if not self.background_processes:
            return

        from archivebox.core.models import ArchiveResult

        for hook_name, process in list(self.background_processes.items()):
            exit_code = process.poll()
            if exit_code is None:
                continue

            ar = self.snapshot.archiveresult_set.filter(hook_name=hook_name).first()
            if ar:
                ar.update_from_output()

            # Remove completed hook from tracking
            self.background_processes.pop(hook_name, None)

    def on_shutdown(self, error: BaseException | None = None) -> None:
        """
        Terminate all background Snapshot hooks when snapshot finishes.

        Background hooks should only be killed when:
        - All foreground hooks are done (snapshot is sealed)
        - Worker is shutting down
        """
        # Use shared termination logic from Worker base class
        self._terminate_background_hooks(
            background_processes=self.background_processes,
            worker_type='SnapshotWorker',
            indent_level=2,
        )

        super().on_shutdown(error)

    @staticmethod
    def _extract_plugin_name(hook_path: Path, hook_name: str) -> str:
        """Extract plugin name from hook path (fallback to filename)."""
        plugin_dir = hook_path.parent.name
        if plugin_dir not in ('plugins', '.'):
            return plugin_dir
        # Fallback: on_Snapshot__50_wget.py -> wget
        name = hook_name.split('__')[-1]
        name = name.replace('.py', '').replace('.js', '').replace('.sh', '')
        name = name.replace('.bg', '')
        return name


class BinaryWorker(Worker):
    """
    Worker that processes Binary installations.

    Two modes:
    1. Specific binary mode (binary_id provided):
       - Processes one specific binary
       - Exits when done

    2. Daemon mode (no binary_id):
       - Polls queue every 0.5s and processes ALL pending binaries
       - Exits after 5 seconds idle
       - Used by Orchestrator to ensure binaries installed before snapshots start
    """

    name: ClassVar[str] = 'binary'
    MAX_TICK_TIME: ClassVar[int] = 600  # 10 minutes for binary installations
    MAX_CONCURRENT_TASKS: ClassVar[int] = 1  # One binary per worker
    POLL_INTERVAL: ClassVar[float] = 0.5  # Check every 500ms (daemon mode only)

    def __init__(self, binary_id: str = None, worker_id: int = 0):
        self.binary_id = binary_id  # Optional - None means daemon mode
        super().__init__(worker_id=worker_id)

    def get_model(self):
        from archivebox.machine.models import Binary
        return Binary

    def get_next_item(self):
        """Get binary to install (specific or next queued)."""
        from archivebox.machine.models import Binary, Machine

        if self.binary_id:
            # Specific binary mode
            try:
                return Binary.objects.get(id=self.binary_id)
            except Binary.DoesNotExist:
                return None
        else:
            # Daemon mode - get all queued binaries for current machine
            machine = Machine.current()
            return Binary.objects.filter(
                machine=machine,
                status=Binary.StatusChoices.QUEUED,
                retry_at__lte=timezone.now()
            ).order_by('retry_at', 'created_at', 'name')

    def runloop(self) -> None:
        """Install binary(ies)."""
        import sys

        self.on_startup()

        if self.binary_id:
            # Specific binary mode - process once and exit
            self._process_single_binary()
        else:
            # Daemon mode - poll and process all pending binaries
            self._daemon_loop()

        self.on_shutdown()

    def _process_single_binary(self):
        """Process a single specific binary."""
        import sys

        try:
            binary = self.get_next_item()

            if not binary:
                log_worker_event(
                    worker_type='BinaryWorker',
                    event=f'Binary {self.binary_id} not found',
                    indent_level=1,
                    pid=self.pid,
                )
                return

            print(f'[cyan]🔧 BinaryWorker installing: {binary.name}[/cyan]', file=sys.stderr)
            binary.sm.tick()

            binary.refresh_from_db()
            if binary.status == Binary.StatusChoices.INSTALLED:
                log_worker_event(
                    worker_type='BinaryWorker',
                    event=f'Installed: {binary.name} -> {binary.abspath}',
                    indent_level=1,
                    pid=self.pid,
                )
            else:
                log_worker_event(
                    worker_type='BinaryWorker',
                    event=f'Installation pending: {binary.name} (status={binary.status})',
                    indent_level=1,
                    pid=self.pid,
                )

        except Exception as e:
            log_worker_event(
                worker_type='BinaryWorker',
                event=f'Failed to install binary',
                indent_level=1,
                pid=self.pid,
                error=e,
            )

    def _daemon_loop(self):
        """Poll and process all pending binaries until idle."""
        import sys

        idle_count = 0
        max_idle_ticks = 10  # Exit after 5 seconds idle (10 ticks * 0.5s)

        try:
            while True:
                # Get all pending binaries
                pending_binaries = list(self.get_next_item())

                if not pending_binaries:
                    idle_count += 1
                    if idle_count >= max_idle_ticks:
                        log_worker_event(
                            worker_type='BinaryWorker',
                            event='No work for 5 seconds, exiting',
                            indent_level=1,
                            pid=self.pid,
                        )
                        break
                    time.sleep(self.POLL_INTERVAL)
                    continue

                # Reset idle counter - we have work
                idle_count = 0

                # Process ALL pending binaries
                for binary in pending_binaries:
                    try:
                        print(f'[cyan]🔧 BinaryWorker processing: {binary.name}[/cyan]', file=sys.stderr)
                        binary.sm.tick()

                        binary.refresh_from_db()
                        if binary.status == Binary.StatusChoices.INSTALLED:
                            log_worker_event(
                                worker_type='BinaryWorker',
                                event=f'Installed: {binary.name} -> {binary.abspath}',
                                indent_level=1,
                                pid=self.pid,
                            )
                        else:
                            log_worker_event(
                                worker_type='BinaryWorker',
                                event=f'Installation pending: {binary.name} (status={binary.status})',
                                indent_level=1,
                                pid=self.pid,
                            )

                    except Exception as e:
                        log_worker_event(
                            worker_type='BinaryWorker',
                            event=f'Failed to install {binary.name}',
                            indent_level=1,
                            pid=self.pid,
                            error=e,
                        )
                        continue

                # Brief sleep before next poll
                time.sleep(self.POLL_INTERVAL)

        except Exception as e:
            log_worker_event(
                worker_type='BinaryWorker',
                event='Daemon loop error',
                indent_level=1,
                pid=self.pid,
                error=e,
            )


# Populate the registry
WORKER_TYPES.update({
    'binary': BinaryWorker,
    'crawl': CrawlWorker,
    'snapshot': SnapshotWorker,
})


def get_worker_class(name: str) -> type[Worker]:
    """Get worker class by name."""
    if name not in WORKER_TYPES:
        raise ValueError(f'Unknown worker type: {name}. Valid types: {list(WORKER_TYPES.keys())}')
    return WORKER_TYPES[name]
