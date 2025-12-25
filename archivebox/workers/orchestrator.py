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
    # Embedded in other commands (exits when done)
    orchestrator = Orchestrator(exit_on_idle=True)
    orchestrator.runloop()
    
    # Daemon mode (runs forever)
    orchestrator = Orchestrator(exit_on_idle=False)
    orchestrator.start()  # fork and return
    
    # Or run via CLI
    archivebox orchestrator [--daemon]
"""

__package__ = 'archivebox.workers'

import os
import time
from typing import Type
from multiprocessing import Process

from django.utils import timezone

from rich import print

from .worker import Worker, CrawlWorker, SnapshotWorker, ArchiveResultWorker
from .pid_utils import (
    write_pid_file,
    remove_pid_file,
    get_all_worker_pids,
    cleanup_stale_pid_files,
)


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
    POLL_INTERVAL: float = 1.0
    IDLE_TIMEOUT: int = 3  # Exit after N idle ticks (0 = never exit)
    MAX_WORKERS_PER_TYPE: int = 4  # Max workers per model type
    MAX_TOTAL_WORKERS: int = 12  # Max workers across all types
    
    def __init__(self, exit_on_idle: bool = True):
        self.exit_on_idle = exit_on_idle
        self.pid: int = os.getpid()
        self.pid_file = None
        self.idle_count: int = 0
    
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
        print(f'[green]👨‍✈️ {self} STARTED[/green]')
        
        # Clean up any stale PID files from previous runs
        stale_count = cleanup_stale_pid_files()
        if stale_count:
            print(f'[yellow]👨‍✈️ {self} cleaned up {stale_count} stale PID files[/yellow]')
    
    def on_shutdown(self, error: BaseException | None = None) -> None:
        """Called when orchestrator shuts down."""
        if self.pid_file:
            remove_pid_file(self.pid_file)
        
        if error and not isinstance(error, KeyboardInterrupt):
            print(f'[red]👨‍✈️ {self} SHUTDOWN with error:[/red] {type(error).__name__}: {error}')
        else:
            print(f'[grey53]👨‍✈️ {self} SHUTDOWN[/grey53]')
    
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
            print(f'[blue]👨‍✈️ {self} spawned {WorkerClass.name} worker[/blue] pid={pid}')
            return pid
        except Exception as e:
            print(f'[red]👨‍✈️ {self} failed to spawn {WorkerClass.name} worker:[/red] {e}')
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
        total_queued = sum(queue_sizes.values())
        total_workers = self.get_total_worker_count()
        
        if total_queued > 0 or total_workers > 0:
            # Build status line
            status_parts = []
            for WorkerClass in self.WORKER_TYPES:
                name = WorkerClass.name
                queued = queue_sizes.get(name, 0)
                workers = len(WorkerClass.get_running_workers())
                if queued > 0 or workers > 0:
                    status_parts.append(f'{name}={queued}q/{workers}w')
            
            if status_parts:
                print(f'[grey53]👨‍✈️ {self} tick:[/grey53] {" ".join(status_parts)}')
    
    def on_idle(self) -> None:
        """Called when orchestrator is idle (no work, no workers)."""
        if self.idle_count == 1:
            print(f'[grey53]👨‍✈️ {self} idle, waiting for work...[/grey53]')
    
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
                    print(f'[green]👨‍✈️ {self} all work complete, exiting[/green]')
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
        def run_orchestrator():
            from archivebox.config.django import setup_django
            setup_django()
            self.runloop()
        
        proc = Process(target=run_orchestrator, name='orchestrator')
        proc.start()
        
        assert proc.pid is not None
        print(f'[green]👨‍✈️ Orchestrator started in background[/green] pid={proc.pid}')
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
