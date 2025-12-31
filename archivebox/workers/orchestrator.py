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
from multiprocessing import Process

from django.utils import timezone

from rich import print

from archivebox.misc.logging_util import log_worker_event
from .worker import Worker, CrawlWorker, SnapshotWorker, ArchiveResultWorker
from .pid_utils import (
    write_pid_file,
    remove_pid_file,
    get_all_worker_pids,
    cleanup_stale_pid_files,
)


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

    Inline mode (inline=True):
    - Processes items directly in the same process (no subprocess spawn)
    - Much faster for small batches (avoids 2-3 sec subprocess overhead per worker)
    - Useful for CLI piping and tests
    """

    WORKER_TYPES: list[Type[Worker]] = [CrawlWorker, SnapshotWorker, ArchiveResultWorker]

    # Configuration
    POLL_INTERVAL: float = 2.0  # How often to check for new work (seconds)
    IDLE_TIMEOUT: int = 3  # Exit after N idle ticks (0 = never exit)
    MAX_WORKERS_PER_TYPE: int = 8  # Max workers per model type
    MAX_TOTAL_WORKERS: int = 24  # Max workers across all types

    def __init__(self, exit_on_idle: bool = True, inline: bool = False):
        self.exit_on_idle = exit_on_idle
        self.inline = inline  # Process items directly instead of spawning workers
        self.pid: int = os.getpid()
        self.pid_file = None
        self.idle_count: int = 0

        # Faster polling in inline mode
        if self.inline:
            self.POLL_INTERVAL = 0.1
            self.IDLE_TIMEOUT = 2
    
    def __repr__(self) -> str:
        return f'[underline]Orchestrator[/underline]\\[pid={self.pid}]'
    
    @classmethod
    def is_running(cls) -> bool:
        """Check if an orchestrator is already running."""
        workers = get_all_worker_pids('orchestrator')
        return len(workers) > 0
    
    def on_startup(self) -> None:
        """Called when orchestrator starts."""
        self.pid = os.getpid()
        self.pid_file = write_pid_file('orchestrator', worker_id=0)

        # Clean up any stale PID files from previous runs
        stale_count = cleanup_stale_pid_files()

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
        if self.pid_file:
            remove_pid_file(self.pid_file)

        log_worker_event(
            worker_type='Orchestrator',
            event='Shutting down',
            indent_level=0,
            pid=self.pid,
            error=error if error and not isinstance(error, KeyboardInterrupt) else None,
        )
    
    def get_total_worker_count(self) -> int:
        """Get total count of running workers across all types."""
        cleanup_stale_pid_files()
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
            # Worker spawning is logged by the worker itself in on_startup()
            return pid
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
    
    def process_inline(self, WorkerClass: Type[Worker]) -> int:
        """
        Process items inline (same process) instead of spawning workers.
        Returns number of items processed.
        """
        worker = WorkerClass(worker_id=0)
        processed = 0

        while True:
            obj = worker.claim_next()
            if obj is None:
                break

            worker.process_item(obj)
            processed += 1

        return processed

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

            if queue_count == 0:
                continue

            if self.inline:
                # Process items directly (fast, no subprocess overhead)
                self.process_inline(WorkerClass)
            elif self.should_spawn_worker(WorkerClass, queue_count):
                # Spawn worker subprocess (slow, but parallel)
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
        self.on_startup()
        
        try:
            while True:
                # Check queues and spawn workers
                queue_sizes = self.check_queues_and_spawn_workers()
                
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
        proc = Process(
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
