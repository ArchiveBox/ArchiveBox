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
from pathlib import Path

from django.utils import timezone

from rich import print

from archivebox.misc.logging_util import log_worker_event
from .worker import Worker, BinaryWorker, CrawlWorker


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

    # BinaryWorker (singleton daemon) and CrawlWorker - SnapshotWorkers are spawned by CrawlWorker subprocess, not by Orchestrator
    WORKER_TYPES: list[Type[Worker]] = [BinaryWorker, CrawlWorker]

    # Configuration
    POLL_INTERVAL: float = 2.0  # How often to check for new work (seconds)
    IDLE_TIMEOUT: int = 3  # Exit after N idle ticks (0 = never exit)
    MAX_CRAWL_WORKERS: int = 8  # Max crawls processing simultaneously
    MAX_BINARY_WORKERS: int = 1  # Max binaries installing simultaneously (sequential only)

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
            # Faster UI updates for interactive runs
            self.POLL_INTERVAL = 0.25
            # Exit quickly once idle in foreground mode
            self.IDLE_TIMEOUT = 1
    
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

        # Foreground runs should start fast; skip expensive orphan cleanup unless in daemon mode.
        chrome_count = 0
        orphaned_workers = 0
        if not self.exit_on_idle:
            # Clean up orphaned Chrome processes from previous crashes
            chrome_count = Process.cleanup_orphaned_chrome()
            # Clean up orphaned workers from previous crashes
            orphaned_workers = Process.cleanup_orphaned_workers()

        # Collect startup metadata
        metadata = {
            'max_crawl_workers': self.MAX_CRAWL_WORKERS,
            'poll_interval': self.POLL_INTERVAL,
        }
        if stale_count:
            metadata['cleaned_stale_pids'] = stale_count
        if chrome_count:
            metadata['cleaned_orphaned_chrome'] = chrome_count
        if orphaned_workers:
            metadata['cleaned_orphaned_workers'] = orphaned_workers

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
        # Get running worker processes scoped to this orchestrator when possible
        if getattr(self, 'db_process', None):
            running_workers = self._get_scoped_running_workers()
        else:
            running_workers = Process.objects.filter(
                process_type=Process.TypeChoices.WORKER,
                status=Process.StatusChoices.RUNNING,
            )

        for worker_process in running_workers:
            try:
                # Gracefully terminate the worker and update Process status
                worker_process.terminate(graceful_timeout=5.0)
            except Exception:
                pass

    def on_shutdown(self, error: BaseException | None = None) -> None:
        """Called when orchestrator shuts down."""
        # Terminate all worker processes on shutdown
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

        if self.crawl_id and getattr(self, 'db_process', None):
            return self._get_scoped_running_workers().count()

        return sum(len(W.get_running_workers()) for W in self.WORKER_TYPES)

    def get_running_workers_for_type(self, WorkerClass: Type[Worker]) -> int:
        """Get count of running workers for a specific worker type."""
        if self.crawl_id and getattr(self, 'db_process', None):
            return self._get_scoped_running_workers().filter(worker_type=WorkerClass.name).count()
        return len(WorkerClass.get_running_workers())

    def _get_scoped_running_workers(self):
        """Get running workers scoped to this orchestrator process tree."""
        from archivebox.machine.models import Process

        descendants = self.db_process.get_descendants(include_self=False)
        return descendants.filter(
            process_type=Process.TypeChoices.WORKER,
            status=Process.StatusChoices.RUNNING,
        )
    
    def should_spawn_worker(self, WorkerClass: Type[Worker], queue_count: int) -> bool:
        """Determine if we should spawn a new worker."""
        if queue_count == 0:
            return False

        # Get appropriate limit based on worker type
        if WorkerClass.name == 'crawl':
            max_workers = self.MAX_CRAWL_WORKERS
        elif WorkerClass.name == 'binary':
            max_workers = self.MAX_BINARY_WORKERS  # Force sequential: only 1 binary at a time
        else:
            max_workers = 1  # Default for unknown types

        # Check worker limit
        if self.crawl_id and getattr(self, 'db_process', None) and WorkerClass.name != 'binary':
            running_count = self._get_scoped_running_workers().filter(worker_type=WorkerClass.name).count()
        else:
            running_workers = WorkerClass.get_running_workers()
            running_count = len(running_workers)

        if running_count >= max_workers:
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
            pid = WorkerClass.start(parent=self.db_process, crawl_id=self.crawl_id)
            print(f'[yellow]DEBUG: Spawned {WorkerClass.name} worker with PID={pid}[/yellow]')

            if self.exit_on_idle:
                # Foreground runs have MAX_CRAWL_WORKERS=1; avoid blocking startup on registration.
                return pid

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
        Check Binary and Crawl queues and spawn workers as needed.
        Returns dict of queue sizes.
        """
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Binary, Machine

        queue_sizes = {}

        # Check Binary queue
        machine = Machine.current()
        binary_queue = Binary.objects.filter(
            machine=machine,
            status=Binary.StatusChoices.QUEUED,
            retry_at__lte=timezone.now()
        ).order_by('retry_at')
        binary_count = binary_queue.count()
        queue_sizes['binary'] = binary_count

        # Spawn BinaryWorker if needed (singleton - max 1 BinaryWorker, processes ALL binaries)
        if binary_count > 0:
            running_binary_workers_list = BinaryWorker.get_running_workers()
            if len(running_binary_workers_list) == 0:
                BinaryWorker.start(parent=self.db_process)

        # Check if any BinaryWorkers are still running
        running_binary_workers = len(BinaryWorker.get_running_workers())

        # Check Crawl queue
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

        # CRITICAL: Only spawn CrawlWorkers if binary queue is empty AND no BinaryWorkers running
        # This ensures all binaries are installed before snapshots start processing
        if binary_count == 0 and running_binary_workers == 0:
            # Spawn CrawlWorker if needed
            if self.should_spawn_worker(CrawlWorker, crawl_count):
                # Claim next crawl
                crawl = crawl_queue.first()
                if crawl and self._claim_crawl(crawl):
                    CrawlWorker.start(parent=self.db_process, crawl_id=str(crawl.id))

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
        plain_output = not IS_TTY
        self.on_startup()

        if not show_progress:
            # No progress layout - optionally emit plain lines for non-TTY output
            progress_layout = ArchiveBoxProgressLayout(crawl_id=self.crawl_id) if plain_output else None
            self._run_orchestrator_loop(progress_layout, plain_output=plain_output)
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
                    refresh_per_second=8,
                    screen=True,
                    console=orchestrator_console,
                ):
                    self._run_orchestrator_loop(progress_layout, plain_output=False)

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

    def _run_orchestrator_loop(self, progress_layout, plain_output: bool = False):
        """Run the main orchestrator loop with optional progress display."""
        last_snapshot_count = None
        tick_count = 0
        last_plain_lines: set[tuple[str, str]] = set()

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

                    binary_workers_count = worker_counts.get('binary', 0)
                    # Update orchestrator status
                    progress_layout.update_orchestrator_status(
                        status=status,
                        crawl_queue_count=crawl_queue_count,
                        crawl_workers_count=crawl_workers_count,
                        binary_queue_count=queue_sizes.get('binary', 0),
                        binary_workers_count=binary_workers_count,
                        max_crawl_workers=self.MAX_CRAWL_WORKERS,
                    )

                    # Update crawl queue tree (active + recently completed)
                    from archivebox.crawls.models import Crawl
                    from archivebox.core.models import Snapshot, ArchiveResult
                    recent_cutoff = timezone.now() - timedelta(minutes=5)
                    pending_snapshot_candidates: list[Snapshot] = []
                    hooks_by_snapshot: dict[str, list] = {}

                    active_qs = Crawl.objects.exclude(status__in=Crawl.FINAL_STATES)
                    if self.crawl_id:
                        active_qs = active_qs.filter(id=self.crawl_id)
                    active_qs = active_qs.order_by('retry_at')

                    recent_done_qs = Crawl.objects.filter(
                        status__in=Crawl.FINAL_STATES,
                        modified_at__gte=recent_cutoff,
                    )
                    if self.crawl_id:
                        recent_done_qs = recent_done_qs.filter(id=self.crawl_id)
                    recent_done_qs = recent_done_qs.order_by('-modified_at')

                    crawls = list(active_qs)
                    active_ids = {c.id for c in crawls}
                    for crawl in recent_done_qs:
                        if crawl.id not in active_ids:
                            crawls.append(crawl)

                    def _abbrev(text: str, max_len: int = 80) -> str:
                        return text if len(text) <= max_len else f"{text[:max_len - 3]}..."

                    def _format_size(num_bytes: int | None) -> str:
                        if not num_bytes:
                            return ''
                        size = float(num_bytes)
                        for unit in ('b', 'kb', 'mb', 'gb', 'tb'):
                            if size < 1024 or unit == 'tb':
                                return f"{size:.1f}{unit}"
                            size /= 1024
                        return ''

                    def _format_seconds(total_seconds: float | None) -> str:
                        if total_seconds is None:
                            return ''
                        seconds = max(0.0, float(total_seconds))
                        return f"{seconds:.1f}s"

                    def _tail_stderr_line(proc) -> str:
                        try:
                            path = getattr(proc, 'stderr_file', None)
                            if not path or not path.exists():
                                return ''
                            with open(path, 'rb') as f:
                                f.seek(0, os.SEEK_END)
                                size = f.tell()
                                f.seek(max(0, size - 4096))
                                data = f.read().decode('utf-8', errors='ignore')
                            lines = [ln.strip() for ln in data.splitlines() if ln.strip()]
                            return lines[-1] if lines else ''
                        except Exception:
                            return ''

                    tree_data: list[dict] = []
                    for crawl in crawls:
                        urls = crawl.get_urls_list()
                        url_count = len(urls)
                        label = f"{url_count} url" + ("s" if url_count != 1 else "")
                        label = _abbrev(label)

                        snapshots = []
                        snap_qs = Snapshot.objects.filter(crawl_id=crawl.id)
                        active_snaps = list(
                            snap_qs.filter(status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED])
                            .order_by('created_at')[:16]
                        )
                        recent_snaps = list(
                            snap_qs.filter(status__in=Snapshot.FINAL_STATES)
                            .order_by('-modified_at')[:8]
                        )
                        snap_ids = {s.id for s in active_snaps}
                        for s in recent_snaps:
                            if s.id not in snap_ids:
                                active_snaps.append(s)

                        for snap in active_snaps:
                            try:
                                from archivebox.config.configset import get_config
                                from archivebox.hooks import discover_hooks
                                snap_config = get_config(snapshot=snap)
                                hooks_list = discover_hooks('Snapshot', config=snap_config)
                                hooks_by_snapshot[str(snap.id)] = hooks_list
                                from archivebox.hooks import get_plugin_special_config
                                hook_timeouts = {}
                                for hook_path in hooks_list:
                                    plugin_name = hook_path.parent.name
                                    try:
                                        hook_timeouts[hook_path.name] = int(get_plugin_special_config(plugin_name, snap_config)['timeout'])
                                    except Exception:
                                        pass
                            except Exception:
                                hooks_list = []
                                hook_timeouts = {}

                            try:
                                from archivebox import DATA_DIR
                                data_dir = Path(DATA_DIR)
                                snap_path = snap.output_dir
                                try:
                                    rel = Path(snap_path)
                                    if rel.is_absolute():
                                        rel = rel.relative_to(data_dir)
                                    snap_path = f"./{rel}" if not str(rel).startswith("./") else str(rel)
                                except Exception:
                                    snap_path = str(snap_path)

                                ars = list(
                                    snap.archiveresult_set.select_related('process').order_by('start_ts')
                                )
                                ar_by_hook = {ar.hook_name: ar for ar in ars if ar.hook_name}
                            except Exception:
                                snap_path = ''
                                ar_by_hook = {}

                            plugin_hooks: dict[str, list[dict]] = {}
                            now = timezone.now()
                            for hook_path in hooks_list:
                                hook_name = hook_path.name
                                is_bg = '.bg.' in hook_name
                                ar = ar_by_hook.get(hook_name)
                                status = 'pending'
                                is_running = False
                                is_pending = True
                                elapsed = ''
                                timeout = ''
                                size = ''
                                stderr_tail = ''
                                if ar:
                                    if ar.process_id and ar.process:
                                        stderr_tail = _tail_stderr_line(ar.process)
                                    if ar.status == ArchiveResult.StatusChoices.STARTED:
                                        status = 'started'
                                        is_running = True
                                        is_pending = False
                                        start_ts = ar.start_ts or (ar.process.started_at if ar.process_id and ar.process else None)
                                        if start_ts:
                                            elapsed = _format_seconds((now - start_ts).total_seconds())
                                        hook_timeout = None
                                        if ar.process_id and ar.process and ar.process.timeout:
                                            hook_timeout = ar.process.timeout
                                        hook_timeout = hook_timeout or hook_timeouts.get(hook_name)
                                        if hook_timeout:
                                            timeout = _format_seconds(hook_timeout)
                                    else:
                                        status = ar.status
                                        if ar.process_id and ar.process and ar.process.exit_code == 137:
                                            status = 'failed'
                                        is_pending = False
                                        start_ts = ar.start_ts or (ar.process.started_at if ar.process_id and ar.process else None)
                                        end_ts = ar.end_ts or (ar.process.ended_at if ar.process_id and ar.process else None)
                                        if start_ts and end_ts:
                                            elapsed = _format_seconds((end_ts - start_ts).total_seconds())
                                        size = _format_size(getattr(ar, 'output_size', None))
                                else:
                                    hook_timeout = hook_timeouts.get(hook_name)
                                    if hook_timeout:
                                        timeout = _format_seconds(hook_timeout)
                                        elapsed = _format_seconds(0)

                                plugin_name = hook_path.parent.name
                                if plugin_name in ('plugins', '.'):
                                    plugin_name = hook_name.split('__')[-1].split('.')[0]
                                plugin_hooks.setdefault(plugin_name, []).append({
                                    'status': status,
                                    'size': size,
                                    'elapsed': elapsed,
                                    'timeout': timeout,
                                    'is_bg': is_bg,
                                    'is_running': is_running,
                                    'is_pending': is_pending,
                                    'hook_name': hook_name,
                                    'stderr': stderr_tail,
                                })

                            hooks = []
                            for plugin_name, hook_entries in plugin_hooks.items():
                                running = next((h for h in hook_entries if h['is_running']), None)
                                pending = next((h for h in hook_entries if h['is_pending']), None)
                                any_failed = any(h['status'] == ArchiveResult.StatusChoices.FAILED for h in hook_entries)
                                any_succeeded = any(h['status'] == ArchiveResult.StatusChoices.SUCCEEDED for h in hook_entries)
                                any_skipped = any(h['status'] == ArchiveResult.StatusChoices.SKIPPED for h in hook_entries)

                                stderr_tail = ''
                                if running:
                                    status = 'started'
                                    is_running = True
                                    is_pending = False
                                    is_bg = running['is_bg']
                                    elapsed = running.get('elapsed', '')
                                    timeout = running.get('timeout', '')
                                    stderr_tail = running.get('stderr', '')
                                    size = ''
                                elif pending:
                                    status = 'pending'
                                    is_running = False
                                    is_pending = True
                                    is_bg = pending['is_bg']
                                    elapsed = pending.get('elapsed', '') or _format_seconds(0)
                                    timeout = pending.get('timeout', '')
                                    stderr_tail = pending.get('stderr', '')
                                    size = ''
                                else:
                                    is_running = False
                                    is_pending = False
                                    is_bg = any(h['is_bg'] for h in hook_entries)
                                    if any_failed:
                                        status = 'failed'
                                    elif any_succeeded:
                                        status = 'succeeded'
                                    elif any_skipped:
                                        status = 'skipped'
                                    else:
                                        status = 'skipped'
                                    for h in hook_entries:
                                        if h.get('stderr'):
                                            stderr_tail = h['stderr']
                                            break
                                    total_elapsed = 0.0
                                    has_elapsed = False
                                    for h in hook_entries:
                                        if h.get('elapsed'):
                                            try:
                                                total_elapsed += float(h['elapsed'].rstrip('s'))
                                                has_elapsed = True
                                            except Exception:
                                                pass
                                    elapsed = _format_seconds(total_elapsed) if has_elapsed else ''
                                    max_output = 0
                                    # Use the largest output_size we already computed on ArchiveResult
                                    ar_sizes = [
                                        ar_by_hook[h['hook_name']].output_size
                                        for h in hook_entries
                                        if h.get('hook_name') in ar_by_hook and getattr(ar_by_hook[h['hook_name']], 'output_size', 0)
                                    ]
                                    if ar_sizes:
                                        max_output = max(ar_sizes)
                                    size = _format_size(max_output) if max_output else ''
                                    timeout = ''

                                hooks.append({
                                    'status': status,
                                    'path': f"./{plugin_name}",
                                    'size': size,
                                    'elapsed': elapsed,
                                    'timeout': timeout,
                                    'is_bg': is_bg,
                                    'is_running': is_running,
                                    'is_pending': is_pending,
                                    'stderr': stderr_tail,
                                })

                            snap_label = _abbrev(f"{str(snap.id)[-8:]} {snap.url or ''}".strip(), max_len=80)
                            snapshots.append({
                                'id': str(snap.id),
                                'status': snap.status,
                                'label': snap_label,
                                'output_path': snap_path,
                                'hooks': hooks,
                            })
                            pending_snapshot_candidates.append(snap)

                        tree_data.append({
                            'id': str(crawl.id),
                            'status': crawl.status,
                            'label': label,
                            'snapshots': snapshots,
                        })

                    progress_layout.update_crawl_tree(tree_data)

                    # Update running process panels (tail stdout/stderr for each running process)
                    from archivebox.machine.models import Process
                    if self.crawl_id and getattr(self, 'db_process', None):
                        process_qs = self.db_process.get_descendants(include_self=False)
                        process_qs = process_qs.filter(status=Process.StatusChoices.RUNNING)
                    else:
                        process_qs = Process.objects.filter(
                            status=Process.StatusChoices.RUNNING,
                        ).exclude(process_type=Process.TypeChoices.ORCHESTRATOR)

                    running_processes = [
                        proc for proc in process_qs.order_by('process_type', 'worker_type', 'started_at')
                        if proc.is_running
                    ]
                    pending_processes = []
                    try:
                        from types import SimpleNamespace
                        for snap in pending_snapshot_candidates:
                            hooks_list = hooks_by_snapshot.get(str(snap.id), [])
                            if not hooks_list:
                                continue
                            existing = set(
                                snap.archiveresult_set.exclude(hook_name='').values_list('hook_name', flat=True)
                            )
                            for hook_path in hooks_list:
                                if hook_path.name in existing:
                                    continue
                                pending_processes.append(SimpleNamespace(
                                    process_type='hook',
                                    worker_type='',
                                    pid=None,
                                    cmd=['', str(hook_path)],
                                    url=snap.url,
                                    status='queued',
                                    started_at=None,
                                    timeout=None,
                                    pwd=None,
                                ))
                    except Exception:
                        pending_processes = []

                    progress_layout.update_process_panels(running_processes, pending=pending_processes)

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

                        # Debug: Log first time we see this snapshot
                        if snapshot.id not in snapshot_progress:
                            progress_layout.log_event(
                                f"Tracking snapshot: {snapshot.url[:50]}",
                                style="grey53"
                            )

                        # Track progress changes
                        prev_progress = snapshot_progress.get(snapshot.id, (0, 0, ''))
                        curr_progress = (total, completed, current_plugin)

                        if prev_progress != curr_progress:
                            prev_total, prev_completed, prev_plugin = prev_progress

                            # Log hook completion
                            if completed > prev_completed:
                                completed_ar = snapshot.archiveresult_set.filter(
                                    status__in=['succeeded', 'skipped', 'failed']
                                ).order_by('-end_ts', '-modified_at').first()
                                hook_label = ''
                                if completed_ar:
                                    hook_name = completed_ar.hook_name or completed_ar.plugin or ''
                                    if hook_name:
                                        hook_label = hook_name.split('__')[-1] if '__' in hook_name else hook_name
                                        hook_label = hook_label.replace('.py', '').replace('.js', '').replace('.sh', '').replace('.bg', '')
                                if not hook_label:
                                    hook_label = f"{completed}/{total}"
                                progress_layout.log_event(
                                    f"Hook completed: {hook_label}",
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

                        # No per-snapshot panels; logs only

                    # Cleanup progress tracking for completed snapshots
                    for snapshot_id in list(snapshot_progress.keys()):
                        if snapshot_id not in active_ids:
                            progress_layout.log_event(
                                f"Snapshot completed/removed",
                                style="blue"
                            )
                            if snapshot_id in snapshot_progress:
                                del snapshot_progress[snapshot_id]

                    if plain_output:
                        plain_lines = progress_layout.plain_lines()
                        new_lines = [line for line in plain_lines if line not in last_plain_lines]
                        if new_lines:
                            ts = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
                            for panel, line in new_lines:
                                if line:
                                    print(f"[{ts}] [{panel}] {line}")
                        last_plain_lines = set(plain_lines)

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
            self.on_shutdown(error=KeyboardInterrupt())
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
