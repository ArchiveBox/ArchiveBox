"""
Orchestrator for managing worker processes.

The Orchestrator polls the Crawl queue and spawns CrawlWorkers as needed.

Architecture:
    Orchestrator (polls Crawl queue)
    └── CrawlWorker(s) (one per active Crawl)
        └── SnapshotWorker(s) (one per Snapshot, up to limit)
            └── Hook Processes (sequential, forked by SnapshotWorker)

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
from datetime import timedelta
from multiprocessing import Process as MPProcess

from django.utils import timezone

from rich import print

from archivebox.misc.logging_util import log_worker_event
from .worker import Worker, CrawlWorker


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
    1. Polls Crawl queue
    2. If crawls exist and fewer than MAX_CRAWL_WORKERS are running, spawns CrawlWorkers
    3. Monitors worker health and cleans up stale PIDs
    4. Exits when queue is empty (unless daemon mode)

    Architecture:
    - Orchestrator spawns CrawlWorkers (one per active Crawl)
    - Each CrawlWorker spawns SnapshotWorkers (one per Snapshot, up to limit)
    - Each SnapshotWorker runs hooks sequentially for its snapshot
    """

    # Only CrawlWorker - SnapshotWorkers are spawned by CrawlWorker subprocess, not by Orchestrator
    WORKER_TYPES: list[Type[Worker]] = [CrawlWorker]

    # Configuration
    POLL_INTERVAL: float = 2.0  # How often to check for new work (seconds)
    IDLE_TIMEOUT: int = 3  # Exit after N idle ticks (0 = never exit)
    MAX_CRAWL_WORKERS: int = 8  # Max crawls processing simultaneously

    def __init__(self, exit_on_idle: bool = True, crawl_id: str | None = None):
        self.exit_on_idle = exit_on_idle
        self.crawl_id = crawl_id  # If set, only process work for this crawl
        self.pid: int = os.getpid()
        self.pid_file = None
        self.idle_count: int = 0
        self._last_cleanup_time: float = 0.0  # For throttling cleanup_stale_running()

        # In foreground mode (exit_on_idle=True), limit to 1 CrawlWorker
        if self.exit_on_idle:
            self.MAX_CRAWL_WORKERS = 1
    
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

        # Clean up orphaned Chrome processes from previous crashes
        chrome_count = Process.cleanup_orphaned_chrome()

        # Collect startup metadata
        metadata = {
            'max_crawl_workers': self.MAX_CRAWL_WORKERS,
            'poll_interval': self.POLL_INTERVAL,
        }
        if stale_count:
            metadata['cleaned_stale_pids'] = stale_count
        if chrome_count:
            metadata['cleaned_orphaned_chrome'] = chrome_count

        log_worker_event(
            worker_type='Orchestrator',
            event='Starting...',
            indent_level=0,
            pid=self.pid,
            metadata=metadata,
        )

    def terminate_all_workers(self) -> None:
        """Terminate all running worker processes."""
        from archivebox.machine.models import Process
        import signal

        # Get all running worker processes
        running_workers = Process.objects.filter(
            process_type=Process.TypeChoices.WORKER,
            status__in=['running', 'started']
        )

        for worker_process in running_workers:
            try:
                # Send SIGTERM to gracefully terminate the worker
                os.kill(worker_process.pid, signal.SIGTERM)
            except ProcessLookupError:
                # Process already dead
                pass
            except Exception:
                # Ignore other errors during shutdown
                pass

    def on_shutdown(self, error: BaseException | None = None) -> None:
        """Called when orchestrator shuts down."""
        # Terminate all worker processes in exit_on_idle mode
        if self.exit_on_idle:
            self.terminate_all_workers()

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

    def get_running_workers_for_type(self, WorkerClass: Type[Worker]) -> int:
        """Get count of running workers for a specific worker type."""
        return len(WorkerClass.get_running_workers())
    
    def should_spawn_worker(self, WorkerClass: Type[Worker], queue_count: int) -> bool:
        """Determine if we should spawn a new CrawlWorker."""
        if queue_count == 0:
            return False

        # Check CrawlWorker limit
        running_workers = WorkerClass.get_running_workers()
        running_count = len(running_workers)

        if running_count >= self.MAX_CRAWL_WORKERS:
            return False

        # Check if we already have enough workers for the queue size
        # Spawn more gradually - don't flood with workers
        if running_count > 0 and queue_count <= running_count * WorkerClass.MAX_CONCURRENT_TASKS:
            return False

        return True
    
    def spawn_worker(self, WorkerClass: Type[Worker]) -> int | None:
        """Spawn a new worker process. Returns PID or None if spawn failed."""
        try:
            print(f'[yellow]DEBUG: Spawning {WorkerClass.name} worker with crawl_id={self.crawl_id}...[/yellow]')
            pid = WorkerClass.start(crawl_id=self.crawl_id)
            print(f'[yellow]DEBUG: Spawned {WorkerClass.name} worker with PID={pid}[/yellow]')

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

                # Debug: Check all processes with this PID first
                if elapsed < 0.5:
                    all_procs = list(Process.objects.filter(pid=pid))
                    print(f'[yellow]DEBUG spawn_worker: elapsed={elapsed:.1f}s pid={pid} orchestrator_id={self.db_process.id}[/yellow]')
                    print(f'[yellow]  Found {len(all_procs)} Process records for pid={pid}[/yellow]')
                    for p in all_procs:
                        print(f'[yellow]  -> type={p.process_type} status={p.status} parent_id={p.parent_id} match={p.parent_id == self.db_process.id}[/yellow]')

                worker_process = Process.objects.filter(
                    pid=pid,
                    process_type=Process.TypeChoices.WORKER,
                    status=Process.StatusChoices.RUNNING,
                    parent_id=self.db_process.id,
                    started_at__gte=spawn_time - timedelta(seconds=10),
                ).first()

                if worker_process:
                    # Worker successfully registered!
                    print(f'[green]DEBUG spawn_worker: Worker registered! Returning pid={pid}[/green]')
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
        Check Crawl queue and spawn CrawlWorkers as needed.
        Returns dict of queue sizes.
        """
        from archivebox.crawls.models import Crawl

        queue_sizes = {}

        # Only check Crawl queue
        crawl_queue = Crawl.objects.filter(
            retry_at__lte=timezone.now()
        ).exclude(
            status__in=Crawl.FINAL_STATES
        )

        # Apply crawl_id filter if set
        if self.crawl_id:
            crawl_queue = crawl_queue.filter(id=self.crawl_id)

        crawl_queue = crawl_queue.order_by('retry_at')
        crawl_count = crawl_queue.count()
        queue_sizes['crawl'] = crawl_count

        # Spawn CrawlWorker if needed
        if self.should_spawn_worker(CrawlWorker, crawl_count):
            # Claim next crawl
            crawl = crawl_queue.first()
            if crawl and self._claim_crawl(crawl):
                CrawlWorker.start(crawl_id=str(crawl.id))

        return queue_sizes

    def _claim_crawl(self, crawl) -> bool:
        """Atomically claim a crawl using optimistic locking."""
        from archivebox.crawls.models import Crawl

        updated = Crawl.objects.filter(
            pk=crawl.pk,
            retry_at=crawl.retry_at,
        ).update(
            retry_at=timezone.now() + timedelta(hours=24),  # Long lock (crawls take time)
        )

        return updated == 1
    
    def has_pending_work(self, queue_sizes: dict[str, int]) -> bool:
        """Check if any queue has pending work."""
        return any(count > 0 for count in queue_sizes.values())
    
    def has_running_workers(self) -> bool:
        """Check if any workers are still running."""
        return self.get_total_worker_count() > 0
    
    def has_future_work(self) -> bool:
        """Check if there's work scheduled for the future (retry_at > now) in Crawl queue."""
        from archivebox.crawls.models import Crawl

        # Build filter for future work, respecting crawl_id if set
        qs = Crawl.objects.filter(
            retry_at__gt=timezone.now()
        ).exclude(
            status__in=Crawl.FINAL_STATES
        )

        # Apply crawl_id filter if set
        if self.crawl_id:
            qs = qs.filter(id=self.crawl_id)

        return qs.count() > 0
    
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
        from rich.live import Live
        from archivebox.misc.logging import IS_TTY
        from archivebox.misc.progress_layout import ArchiveBoxProgressLayout
        import sys
        import os

        # Enable progress layout only in TTY + foreground mode
        show_progress = IS_TTY and self.exit_on_idle

        self.on_startup()

        if not show_progress:
            # No progress layout - just run normally
            self._run_orchestrator_loop(None)
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

                # Create layout and run with Live display
                progress_layout = ArchiveBoxProgressLayout(crawl_id=self.crawl_id)

                with Live(
                    progress_layout.get_layout(),
                    refresh_per_second=4,
                    screen=True,
                    console=orchestrator_console,
                ):
                    self._run_orchestrator_loop(progress_layout)

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

    def _run_orchestrator_loop(self, progress_layout):
        """Run the main orchestrator loop with optional progress display."""
        last_queue_sizes = {}
        last_snapshot_count = None
        tick_count = 0

        # Track snapshot progress to detect changes
        snapshot_progress = {}  # snapshot_id -> (total, completed, current_plugin)

        try:
            while True:
                tick_count += 1

                # Check queues and spawn workers
                queue_sizes = self.check_queues_and_spawn_workers()

                # Get worker counts for each type
                worker_counts = {
                    WorkerClass.name: len(WorkerClass.get_running_workers())
                    for WorkerClass in self.WORKER_TYPES
                }

                # Update layout if enabled
                if progress_layout:
                    # Get crawl queue and worker counts
                    crawl_queue_count = queue_sizes.get('crawl', 0)
                    crawl_workers_count = worker_counts.get('crawl', 0)

                    # Determine orchestrator status
                    if crawl_workers_count > 0:
                        status = "Working"
                    elif crawl_queue_count > 0:
                        status = "Spawning"
                    else:
                        status = "Idle"

                    # Update orchestrator status
                    progress_layout.update_orchestrator_status(
                        status=status,
                        crawl_queue_count=crawl_queue_count,
                        crawl_workers_count=crawl_workers_count,
                        max_crawl_workers=self.MAX_CRAWL_WORKERS,
                    )

                    # Log queue size changes
                    if queue_sizes != last_queue_sizes:
                        for worker_type, count in queue_sizes.items():
                            old_count = last_queue_sizes.get(worker_type, 0)
                            if count != old_count:
                                if count > old_count:
                                    progress_layout.log_event(
                                        f"{worker_type.capitalize()} queue: {old_count} → {count}",
                                        style="yellow"
                                    )
                                else:
                                    progress_layout.log_event(
                                        f"{worker_type.capitalize()} queue: {old_count} → {count}",
                                        style="green"
                                    )
                        last_queue_sizes = queue_sizes.copy()

                    # Update snapshot progress
                    from archivebox.core.models import Snapshot

                    # Get all started snapshots (optionally filtered by crawl_id)
                    snapshot_filter = {'status': 'started'}
                    if self.crawl_id:
                        snapshot_filter['crawl_id'] = self.crawl_id
                    else:
                        # Only if processing all crawls, filter by recent modified_at to avoid stale snapshots
                        recent_cutoff = timezone.now() - timedelta(minutes=5)
                        snapshot_filter['modified_at__gte'] = recent_cutoff

                    active_snapshots = list(Snapshot.objects.filter(**snapshot_filter))

                    # Log snapshot count changes and details
                    if len(active_snapshots) != last_snapshot_count:
                        if last_snapshot_count is not None:
                            if len(active_snapshots) > last_snapshot_count:
                                progress_layout.log_event(
                                    f"Active snapshots: {last_snapshot_count} → {len(active_snapshots)}",
                                    style="cyan"
                                )
                                # Log which snapshots started
                                for snapshot in active_snapshots[-1:]:  # Just show the newest one
                                    progress_layout.log_event(
                                        f"Started: {snapshot.url[:60]}",
                                        style="green"
                                    )

                                # Log SnapshotWorker count
                                from archivebox.machine.models import Process
                                all_workers = Process.objects.filter(
                                    process_type=Process.TypeChoices.WORKER,
                                    status__in=['running', 'started']
                                ).count()
                                progress_layout.log_event(
                                    f"Workers running: {all_workers} ({crawl_workers_count} CrawlWorkers)",
                                    style="grey53"
                                )
                            else:
                                progress_layout.log_event(
                                    f"Active snapshots: {last_snapshot_count} → {len(active_snapshots)}",
                                    style="blue"
                                )
                        last_snapshot_count = len(active_snapshots)

                    # Track which snapshots are still active
                    active_ids = set()

                    for snapshot in active_snapshots:
                        active_ids.add(snapshot.id)

                        total = snapshot.archiveresult_set.count()
                        completed = snapshot.archiveresult_set.filter(
                            status__in=['succeeded', 'skipped', 'failed']
                        ).count()

                        # Count hooks by status for debugging
                        queued = snapshot.archiveresult_set.filter(status='queued').count()
                        started = snapshot.archiveresult_set.filter(status='started').count()

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
                                current_plugin = clean_name
                        elif total == 0:
                            # Snapshot just started, hooks not created yet
                            current_plugin = "initializing"
                        elif queued > 0:
                            # Hooks created but none started yet
                            current_plugin = "waiting"

                        # Update snapshot worker (show even if no hooks yet)
                        # Debug: Log first time we see this snapshot
                        if snapshot.id not in progress_layout.snapshot_to_worker:
                            progress_layout.log_event(
                                f"Assigning to worker: {snapshot.url[:50]}",
                                style="grey53"
                            )

                        # Track progress changes
                        prev_progress = snapshot_progress.get(snapshot.id, (0, 0, ''))
                        curr_progress = (total, completed, current_plugin)

                        if prev_progress != curr_progress:
                            prev_total, prev_completed, prev_plugin = prev_progress

                            # Log hooks created
                            if total > prev_total:
                                progress_layout.log_event(
                                    f"Hooks created: {total} for {snapshot.url[:40]}",
                                    style="cyan"
                                )

                            # Log hook completion
                            if completed > prev_completed:
                                progress_layout.log_event(
                                    f"Hook completed: {completed}/{total} for {snapshot.url[:40]}",
                                    style="green"
                                )

                            # Log plugin change
                            if current_plugin and current_plugin != prev_plugin:
                                progress_layout.log_event(
                                    f"Running: {current_plugin} ({snapshot.url[:40]})",
                                    style="yellow"
                                )

                            snapshot_progress[snapshot.id] = curr_progress

                        # Debug: Every 10 ticks, log detailed status if stuck at initializing
                        if tick_count % 10 == 0 and total == 0 and current_plugin == "initializing":
                            progress_layout.log_event(
                                f"DEBUG: Snapshot stuck at initializing (status={snapshot.status})",
                                style="red"
                            )

                        progress_layout.update_snapshot_worker(
                            snapshot_id=snapshot.id,
                            url=snapshot.url,
                            total=max(total, 1),  # Show at least 1 to avoid division by zero
                            completed=completed,
                            current_plugin=current_plugin,
                        )

                    # Remove snapshots that are no longer active
                    for snapshot_id in list(progress_layout.snapshot_to_worker.keys()):
                        if snapshot_id not in active_ids:
                            progress_layout.log_event(
                                f"Snapshot completed/removed",
                                style="blue"
                            )
                            progress_layout.remove_snapshot_worker(snapshot_id)
                            # Also clean up progress tracking
                            if snapshot_id in snapshot_progress:
                                del snapshot_progress[snapshot_id]

                # Track idle state
                has_pending = self.has_pending_work(queue_sizes)
                has_running = self.has_running_workers()
                if has_pending or has_running:
                    self.idle_count = 0
                    self.on_tick(queue_sizes)
                else:
                    self.idle_count += 1
                    self.on_idle()

                # Check if we should exit
                if self.should_exit(queue_sizes):
                    if progress_layout:
                        progress_layout.log_event("All work complete", style="green")
                    log_worker_event(
                        worker_type='Orchestrator',
                        event='All work complete',
                        indent_level=0,
                        pid=self.pid,
                    )
                    break

                time.sleep(self.POLL_INTERVAL)

        except KeyboardInterrupt:
            if progress_layout:
                progress_layout.log_event("Interrupted by user", style="red")
            print()  # Newline after ^C
        except BaseException as e:
            if progress_layout:
                progress_layout.log_event(f"Error: {e}", style="red")
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
