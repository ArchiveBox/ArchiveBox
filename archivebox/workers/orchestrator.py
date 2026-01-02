"""
Orchestrator for managing worker processes.

The Orchestrator polls queues for each model type (Crawl, Snapshot, ArchiveResult)
and lazily spawns worker processes when there is work to be done.

Architecture:
    Orchestrator (main loop, polls queues)
    ├── CrawlWorker subprocess(es)
    ├── SnapshotWorker subprocess(es)
    └── ArchiveResultWorker subprocess(es)
        └── Each worker spawns task subprocesses via CLI

Usage:
    # Default: runs forever (for use as subprocess of server)
    orchestrator = Orchestrator(exit_on_idle=False)
    orchestrator.runloop()

    # Exit when done (for embedded use in other commands)
    orchestrator = Orchestrator(exit_on_idle=True)
    orchestrator.runloop()

    # Or run via CLI
    archivebox manage orchestrator              # runs forever
    archivebox manage orchestrator --exit-on-idle  # exits when done
"""

__package__ = 'archivebox.workers'

import os
import time
from typing import Type
from multiprocessing import Process as MPProcess

from django.utils import timezone

from rich import print

from archivebox.misc.logging_util import log_worker_event
from .worker import Worker, CrawlWorker, SnapshotWorker, ArchiveResultWorker


def _run_orchestrator_process(exit_on_idle: bool) -> None:
    """Top-level function for multiprocessing (must be picklable)."""
    from archivebox.config.django import setup_django
    setup_django()
    orchestrator = Orchestrator(exit_on_idle=exit_on_idle)
    orchestrator.runloop()


class Orchestrator:
    """
    Manages worker processes by polling queues and spawning workers as needed.
    
    The orchestrator:
    1. Polls each model queue (Crawl, Snapshot, ArchiveResult)
    2. If items exist and fewer than MAX_CONCURRENT workers are running, spawns workers
    3. Monitors worker health and cleans up stale PIDs
    4. Exits when all queues are empty (unless daemon mode)
    """
    
    WORKER_TYPES: list[Type[Worker]] = [CrawlWorker, SnapshotWorker, ArchiveResultWorker]

    # Configuration
    POLL_INTERVAL: float = 2.0  # How often to check for new work (seconds)
    IDLE_TIMEOUT: int = 3  # Exit after N idle ticks (0 = never exit)
    MAX_WORKERS_PER_TYPE: int = 8  # Max workers per model type
    MAX_TOTAL_WORKERS: int = 24  # Max workers across all types
    
    def __init__(self, exit_on_idle: bool = True):
        self.exit_on_idle = exit_on_idle
        self.pid: int = os.getpid()
        self.pid_file = None
        self.idle_count: int = 0
        self._last_cleanup_time: float = 0.0  # For throttling cleanup_stale_running()
    
    def __repr__(self) -> str:
        return f'[underline]Orchestrator[/underline]\\[pid={self.pid}]'
    
    @classmethod
    def is_running(cls) -> bool:
        """Check if an orchestrator is already running."""
        from archivebox.machine.models import Process

        # Clean up stale processes before counting
        Process.cleanup_stale_running()
        return Process.get_running_count(process_type=Process.TypeChoices.ORCHESTRATOR) > 0

    def on_startup(self) -> None:
        """Called when orchestrator starts."""
        from archivebox.machine.models import Process

        self.pid = os.getpid()
        # Register orchestrator process in database with explicit type
        self.db_process = Process.current()
        # Ensure the process type is correctly set to ORCHESTRATOR
        if self.db_process.process_type != Process.TypeChoices.ORCHESTRATOR:
            self.db_process.process_type = Process.TypeChoices.ORCHESTRATOR
            self.db_process.save(update_fields=['process_type'])

        # Clean up any stale Process records from previous runs
        stale_count = Process.cleanup_stale_running()

        # Collect startup metadata
        metadata = {
            'max_workers_per_type': self.MAX_WORKERS_PER_TYPE,
            'max_total_workers': self.MAX_TOTAL_WORKERS,
            'poll_interval': self.POLL_INTERVAL,
        }
        if stale_count:
            metadata['cleaned_stale_pids'] = stale_count

        log_worker_event(
            worker_type='Orchestrator',
            event='Starting...',
            indent_level=0,
            pid=self.pid,
            metadata=metadata,
        )

    def on_shutdown(self, error: BaseException | None = None) -> None:
        """Called when orchestrator shuts down."""
        # Update Process record status
        if hasattr(self, 'db_process') and self.db_process:
            # KeyboardInterrupt is a graceful shutdown, not an error
            self.db_process.exit_code = 1 if error and not isinstance(error, KeyboardInterrupt) else 0
            self.db_process.status = self.db_process.StatusChoices.EXITED
            self.db_process.ended_at = timezone.now()
            self.db_process.save()

        log_worker_event(
            worker_type='Orchestrator',
            event='Shutting down',
            indent_level=0,
            pid=self.pid,
            error=error if error and not isinstance(error, KeyboardInterrupt) else None,
        )

    def get_total_worker_count(self) -> int:
        """Get total count of running workers across all types."""
        from archivebox.machine.models import Process
        import time

        # Throttle cleanup to once every 30 seconds to avoid performance issues
        CLEANUP_THROTTLE_SECONDS = 30
        now = time.time()
        if now - self._last_cleanup_time > CLEANUP_THROTTLE_SECONDS:
            Process.cleanup_stale_running()
            self._last_cleanup_time = now

        return sum(len(W.get_running_workers()) for W in self.WORKER_TYPES)
    
    def should_spawn_worker(self, WorkerClass: Type[Worker], queue_count: int) -> bool:
        """Determine if we should spawn a new worker of the given type."""
        if queue_count == 0:
            return False
        
        # Check per-type limit
        running_workers = WorkerClass.get_running_workers()
        if len(running_workers) >= self.MAX_WORKERS_PER_TYPE:
            return False
        
        # Check total limit
        if self.get_total_worker_count() >= self.MAX_TOTAL_WORKERS:
            return False
        
        # Check if we already have enough workers for the queue size
        # Spawn more gradually - don't flood with workers
        if len(running_workers) > 0 and queue_count <= len(running_workers) * WorkerClass.MAX_CONCURRENT_TASKS:
            return False
        
        return True
    
    def spawn_worker(self, WorkerClass: Type[Worker]) -> int | None:
        """Spawn a new worker process. Returns PID or None if spawn failed."""
        try:
            pid = WorkerClass.start(daemon=False)

            # CRITICAL: Block until worker registers itself in Process table
            # This prevents race condition where orchestrator spawns multiple workers
            # before any of them finish on_startup() and register
            from archivebox.machine.models import Process
            import time

            timeout = 5.0  # seconds to wait for worker registration
            poll_interval = 0.1  # check every 100ms
            elapsed = 0.0
            spawn_time = timezone.now()

            while elapsed < timeout:
                # Check if worker process is registered with strict criteria:
                # 1. Correct PID
                # 2. WORKER process type
                # 3. RUNNING status
                # 4. Parent is this orchestrator
                # 5. Started recently (within last 10 seconds)
                worker_process = Process.objects.filter(
                    pid=pid,
                    process_type=Process.TypeChoices.WORKER,
                    status=Process.StatusChoices.RUNNING,
                    parent_id=self.db_process.id,
                    started_at__gte=spawn_time - timedelta(seconds=10),
                ).first()

                if worker_process:
                    # Worker successfully registered!
                    return pid

                time.sleep(poll_interval)
                elapsed += poll_interval

            # Timeout - worker failed to register
            log_worker_event(
                worker_type='Orchestrator',
                event='Worker failed to register in time',
                indent_level=0,
                pid=self.pid,
                metadata={'worker_type': WorkerClass.name, 'worker_pid': pid, 'timeout': timeout},
            )
            return None

        except Exception as e:
            log_worker_event(
                worker_type='Orchestrator',
                event='Failed to spawn worker',
                indent_level=0,
                pid=self.pid,
                metadata={'worker_type': WorkerClass.name},
                error=e,
            )
            return None
    
    def check_queues_and_spawn_workers(self) -> dict[str, int]:
        """
        Check all queues and spawn workers as needed.
        Returns dict of queue sizes by worker type.
        """
        queue_sizes = {}
        
        for WorkerClass in self.WORKER_TYPES:
            # Get queue for this worker type
            # Need to instantiate worker to get queue (for model access)
            worker = WorkerClass(worker_id=-1)  # temp instance just for queue access
            queue = worker.get_queue()
            queue_count = queue.count()
            queue_sizes[WorkerClass.name] = queue_count
            
            # Spawn worker if needed
            if self.should_spawn_worker(WorkerClass, queue_count):
                self.spawn_worker(WorkerClass)
        
        return queue_sizes
    
    def has_pending_work(self, queue_sizes: dict[str, int]) -> bool:
        """Check if any queue has pending work."""
        return any(count > 0 for count in queue_sizes.values())
    
    def has_running_workers(self) -> bool:
        """Check if any workers are still running."""
        return self.get_total_worker_count() > 0
    
    def has_future_work(self) -> bool:
        """Check if there's work scheduled for the future (retry_at > now)."""
        for WorkerClass in self.WORKER_TYPES:
            worker = WorkerClass(worker_id=-1)
            Model = worker.get_model()
            # Check for items not in final state with future retry_at
            future_count = Model.objects.filter(
                retry_at__gt=timezone.now()
            ).exclude(
                status__in=Model.FINAL_STATES
            ).count()
            if future_count > 0:
                return True
        return False
    
    def on_tick(self, queue_sizes: dict[str, int]) -> None:
        """Called each orchestrator tick. Override for custom behavior."""
        # Tick logging suppressed to reduce noise
        pass
    
    def on_idle(self) -> None:
        """Called when orchestrator is idle (no work, no workers)."""
        # Idle logging suppressed to reduce noise
        pass
    
    def should_exit(self, queue_sizes: dict[str, int]) -> bool:
        """Determine if orchestrator should exit."""
        if not self.exit_on_idle:
            return False
        
        if self.IDLE_TIMEOUT == 0:
            return False
        
        # Don't exit if there's pending or future work
        if self.has_pending_work(queue_sizes):
            return False
        
        if self.has_running_workers():
            return False
        
        if self.has_future_work():
            return False
        
        # Exit after idle timeout
        return self.idle_count >= self.IDLE_TIMEOUT
    
    def runloop(self) -> None:
        """Main orchestrator loop."""
        from rich.progress import Progress, BarColumn, TextColumn, TaskProgressColumn
        from archivebox.misc.logging import IS_TTY, CONSOLE
        import sys
        import os

        # Enable progress bars only in TTY + foreground mode
        show_progress = IS_TTY and self.exit_on_idle

        # Debug
        print(f"[yellow]DEBUG: IS_TTY={IS_TTY}, exit_on_idle={self.exit_on_idle}, show_progress={show_progress}[/yellow]")

        self.on_startup()
        task_ids = {}

        if not show_progress:
            # No progress bars - just run normally
            self._run_orchestrator_loop(None, task_ids, None, None)
        else:
            # Redirect worker subprocess output to /dev/null
            devnull_fd = os.open(os.devnull, os.O_WRONLY)

            # Save original stdout/stderr (make 2 copies - one for Console, one for restoring)
            original_stdout = sys.stdout.fileno()
            original_stderr = sys.stderr.fileno()
            stdout_for_console = os.dup(original_stdout)
            stdout_for_restore = os.dup(original_stdout)
            stderr_for_restore = os.dup(original_stderr)

            try:
                # Redirect stdout/stderr to /dev/null (workers will inherit this)
                os.dup2(devnull_fd, original_stdout)
                os.dup2(devnull_fd, original_stderr)

                # Create Console using saved stdout (not the redirected one)
                from rich.console import Console
                import archivebox.misc.logging as logging_module
                orchestrator_console = Console(file=os.fdopen(stdout_for_console, 'w'), force_terminal=True)

                # Update global CONSOLE so orchestrator logs appear too
                original_console = logging_module.CONSOLE
                logging_module.CONSOLE = orchestrator_console

                # Now create Progress and run loop (DON'T restore stdout/stderr - workers need /dev/null)
                with Progress(
                    TextColumn("[cyan]{task.description}"),
                    BarColumn(bar_width=40),
                    TaskProgressColumn(),
                    console=orchestrator_console,
                ) as progress:
                    self._run_orchestrator_loop(progress, task_ids, None, None)

                # Restore original console
                logging_module.CONSOLE = original_console
            finally:
                # Restore stdout/stderr
                os.dup2(stdout_for_restore, original_stdout)
                os.dup2(stderr_for_restore, original_stderr)

                # Cleanup
                try:
                    os.close(devnull_fd)
                    os.close(stdout_for_restore)
                    os.close(stderr_for_restore)
                except:
                    pass
                # stdout_for_console is closed by orchestrator_console

    def _run_orchestrator_loop(self, progress, task_ids, read_fd, console):
        """Run the main orchestrator loop with optional progress display."""
        try:
            while True:
                # Check queues and spawn workers
                queue_sizes = self.check_queues_and_spawn_workers()

                # Update progress bars
                if progress:
                    from archivebox.core.models import Snapshot

                    # Get all started snapshots
                    active_snapshots = list(Snapshot.objects.filter(status='started'))

                    # Track which snapshots are still active
                    active_ids = set()

                    for snapshot in active_snapshots:
                        active_ids.add(snapshot.id)

                        total = snapshot.archiveresult_set.count()
                        if total == 0:
                            continue

                        completed = snapshot.archiveresult_set.filter(
                            status__in=['succeeded', 'skipped', 'failed']
                        ).count()

                        # Find currently running hook (ordered by hook_name to get lowest step number)
                        current_ar = snapshot.archiveresult_set.filter(status='started').order_by('hook_name').first()
                        if not current_ar:
                            # If nothing running, show next queued item (ordered to get next in sequence)
                            current_ar = snapshot.archiveresult_set.filter(status='queued').order_by('hook_name').first()

                        current_plugin = ''
                        if current_ar:
                            # Use hook_name if available, otherwise plugin name
                            hook_name = current_ar.hook_name or current_ar.plugin or ''
                            # Extract just the hook name without path (e.g., "on_Snapshot__50_wget.py" -> "wget")
                            if hook_name:
                                # Clean up the name: remove prefix and extension
                                clean_name = hook_name.split('__')[-1] if '__' in hook_name else hook_name
                                clean_name = clean_name.replace('.py', '').replace('.sh', '').replace('.bg', '')
                                current_plugin = f" • {clean_name}"

                        # Build description with URL + current plugin
                        url = snapshot.url[:50] + '...' if len(snapshot.url) > 50 else snapshot.url
                        description = f"{url}{current_plugin}"

                        # Create or update task
                        if snapshot.id not in task_ids:
                            task_ids[snapshot.id] = progress.add_task(description, total=total, completed=completed)
                        else:
                            # Update both progress and description
                            progress.update(task_ids[snapshot.id], description=description, completed=completed)

                    # Remove tasks for snapshots that are no longer active
                    for snapshot_id in list(task_ids.keys()):
                        if snapshot_id not in active_ids:
                            progress.remove_task(task_ids[snapshot_id])
                            del task_ids[snapshot_id]

                # Track idle state
                if self.has_pending_work(queue_sizes) or self.has_running_workers():
                    self.idle_count = 0
                    self.on_tick(queue_sizes)
                else:
                    self.idle_count += 1
                    self.on_idle()

                # Check if we should exit
                if self.should_exit(queue_sizes):
                    log_worker_event(
                        worker_type='Orchestrator',
                        event='All work complete',
                        indent_level=0,
                        pid=self.pid,
                    )
                    break

                time.sleep(self.POLL_INTERVAL)

        except KeyboardInterrupt:
            print()  # Newline after ^C
        except BaseException as e:
            self.on_shutdown(error=e)
            raise
        else:
            self.on_shutdown()
    
    def start(self) -> int:
        """
        Fork orchestrator as a background process.
        Returns the PID of the new process.
        """
        # Use module-level function to avoid pickle errors with local functions
        proc = MPProcess(
            target=_run_orchestrator_process,
            args=(self.exit_on_idle,),
            name='orchestrator'
        )
        proc.start()

        assert proc.pid is not None
        log_worker_event(
            worker_type='Orchestrator',
            event='Started in background',
            indent_level=0,
            pid=proc.pid,
        )
        return proc.pid
    
    @classmethod
    def get_or_start(cls, exit_on_idle: bool = True) -> 'Orchestrator':
        """
        Get running orchestrator or start a new one.
        Used by commands like 'add' to ensure orchestrator is running.
        """
        if cls.is_running():
            print('[grey53]👨‍✈️ Orchestrator already running[/grey53]')
            # Return a placeholder - actual orchestrator is in another process
            return cls(exit_on_idle=exit_on_idle)
        
        orchestrator = cls(exit_on_idle=exit_on_idle)
        return orchestrator
