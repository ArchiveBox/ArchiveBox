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
from multiprocessing import Process, cpu_count

from django.db.models import QuerySet
from django.utils import timezone
from django.conf import settings

from rich import print

from .pid_utils import (
    write_pid_file,
    remove_pid_file,
    get_all_worker_pids,
    get_next_worker_id,
    cleanup_stale_pid_files,
)


CPU_COUNT = cpu_count()

# Registry of worker types by name (defined at bottom, referenced here for _run_worker)
WORKER_TYPES: dict[str, type['Worker']] = {}


def _run_worker(worker_class_name: str, worker_id: int, daemon: bool, **kwargs):
    """
    Module-level function to run a worker. Must be at module level for pickling.
    """
    from archivebox.config.django import setup_django
    setup_django()

    # Get worker class by name to avoid pickling class objects
    worker_cls = WORKER_TYPES[worker_class_name]
    worker = worker_cls(worker_id=worker_id, daemon=daemon, **kwargs)
    worker.runloop()


class Worker:
    """
    Base worker class that polls a queue and processes items directly.

    Each item is processed by calling its state machine tick() method.
    Workers exit when idle for too long (unless daemon mode).
    """

    name: ClassVar[str] = 'worker'

    # Configuration (can be overridden by subclasses)
    MAX_TICK_TIME: ClassVar[int] = 60
    POLL_INTERVAL: ClassVar[float] = 0.5
    IDLE_TIMEOUT: ClassVar[int] = 3  # Exit after N idle iterations (set to 0 to never exit)

    def __init__(self, worker_id: int = 0, daemon: bool = False, **kwargs: Any):
        self.worker_id = worker_id
        self.daemon = daemon
        self.pid: int = os.getpid()
        self.pid_file: Path | None = None
        self.idle_count: int = 0

    def __repr__(self) -> str:
        return f'[underline]{self.__class__.__name__}[/underline]\\[id={self.worker_id}, pid={self.pid}]'

    def get_model(self):
        """Get the Django model class. Subclasses must override this."""
        raise NotImplementedError("Subclasses must implement get_model()")

    def get_queue(self) -> QuerySet:
        """Get the queue of objects ready for processing."""
        Model = self.get_model()
        return Model.objects.filter(
            retry_at__lte=timezone.now()
        ).exclude(
            status__in=Model.FINAL_STATES
        ).order_by('retry_at')

    def claim_next(self):
        """
        Atomically claim the next object from the queue.
        Returns the claimed object or None if queue is empty or claim failed.
        """
        Model = self.get_model()
        obj = self.get_queue().first()
        if obj is None:
            return None

        # Atomic claim using optimistic locking on retry_at
        claimed = Model.objects.filter(
            pk=obj.pk,
            retry_at=obj.retry_at,
        ).update(
            retry_at=timezone.now() + timedelta(seconds=self.MAX_TICK_TIME)
        )

        if claimed == 1:
            obj.refresh_from_db()
            return obj

        return None  # Someone else claimed it

    def process_item(self, obj) -> bool:
        """
        Process a single item by calling its state machine tick().
        Returns True on success, False on failure.
        Subclasses can override for custom processing.
        """
        try:
            obj.sm.tick()
            return True
        except Exception as e:
            print(f'[red]{self} error processing {obj.pk}:[/red] {e}')
            traceback.print_exc()
            return False

    def on_startup(self) -> None:
        """Called when worker starts."""
        self.pid = os.getpid()
        self.pid_file = write_pid_file(self.name, self.worker_id)
        print(f'[green]{self} STARTED[/green] pid_file={self.pid_file}')

    def on_shutdown(self, error: BaseException | None = None) -> None:
        """Called when worker shuts down."""
        # Remove PID file
        if self.pid_file:
            remove_pid_file(self.pid_file)

        if error and not isinstance(error, KeyboardInterrupt):
            print(f'[red]{self} SHUTDOWN with error:[/red] {type(error).__name__}: {error}')
        else:
            print(f'[grey53]{self} SHUTDOWN[/grey53]')

    def should_exit(self) -> bool:
        """Check if worker should exit due to idle timeout."""
        if self.daemon:
            return False

        if self.IDLE_TIMEOUT == 0:
            return False

        return self.idle_count >= self.IDLE_TIMEOUT

    def runloop(self) -> None:
        """Main worker loop - polls queue, processes items."""
        self.on_startup()

        try:
            while True:
                # Try to claim and process an item
                obj = self.claim_next()

                if obj is not None:
                    self.idle_count = 0
                    print(f'[blue]{self} processing:[/blue] {obj.pk}')

                    start_time = time.time()
                    success = self.process_item(obj)
                    elapsed = time.time() - start_time

                    if success:
                        print(f'[green]{self} completed ({elapsed:.1f}s):[/green] {obj.pk}')
                    else:
                        print(f'[red]{self} failed ({elapsed:.1f}s):[/red] {obj.pk}')
                else:
                    # No work available
                    self.idle_count += 1
                    if self.idle_count == 1:
                        print(f'[grey53]{self} idle, waiting for work...[/grey53]')

                # Check if we should exit
                if self.should_exit():
                    print(f'[grey53]{self} idle timeout reached, exiting[/grey53]')
                    break

                time.sleep(self.POLL_INTERVAL)

        except KeyboardInterrupt:
            pass
        except BaseException as e:
            self.on_shutdown(error=e)
            raise
        else:
            self.on_shutdown()

    @classmethod
    def start(cls, worker_id: int | None = None, daemon: bool = False, **kwargs: Any) -> int:
        """
        Fork a new worker as a subprocess.
        Returns the PID of the new process.
        """
        if worker_id is None:
            worker_id = get_next_worker_id(cls.name)

        # Use module-level function for pickling compatibility
        proc = Process(
            target=_run_worker,
            args=(cls.name, worker_id, daemon),
            kwargs=kwargs,
            name=f'{cls.name}_worker_{worker_id}',
        )
        proc.start()

        assert proc.pid is not None
        return proc.pid

    @classmethod
    def get_running_workers(cls) -> list[dict]:
        """Get info about all running workers of this type."""
        cleanup_stale_pid_files()
        return get_all_worker_pids(cls.name)

    @classmethod
    def get_worker_count(cls) -> int:
        """Get count of running workers of this type."""
        return len(cls.get_running_workers())


class CrawlWorker(Worker):
    """Worker for processing Crawl objects."""

    name: ClassVar[str] = 'crawl'
    MAX_TICK_TIME: ClassVar[int] = 60

    def get_model(self):
        from crawls.models import Crawl
        return Crawl


class SnapshotWorker(Worker):
    """Worker for processing Snapshot objects."""

    name: ClassVar[str] = 'snapshot'
    MAX_TICK_TIME: ClassVar[int] = 60

    def get_model(self):
        from core.models import Snapshot
        return Snapshot


class ArchiveResultWorker(Worker):
    """Worker for processing ArchiveResult objects."""

    name: ClassVar[str] = 'archiveresult'
    MAX_TICK_TIME: ClassVar[int] = 120

    def __init__(self, extractor: str | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        self.extractor = extractor

    def get_model(self):
        from core.models import ArchiveResult
        return ArchiveResult

    def get_queue(self) -> QuerySet:
        """Get queue of ArchiveResults ready for processing."""
        from django.db.models import Exists, OuterRef
        from core.models import ArchiveResult

        qs = super().get_queue()

        if self.extractor:
            qs = qs.filter(extractor=self.extractor)

        # Exclude ArchiveResults whose Snapshot already has one in progress
        in_progress = ArchiveResult.objects.filter(
            snapshot_id=OuterRef('snapshot_id'),
            status=ArchiveResult.StatusChoices.STARTED,
        )
        qs = qs.exclude(Exists(in_progress))

        return qs

    def process_item(self, obj) -> bool:
        """Process an ArchiveResult by running its extractor."""
        try:
            obj.sm.tick()
            return True
        except Exception as e:
            print(f'[red]{self} error processing {obj.pk}:[/red] {e}')
            traceback.print_exc()
            return False

    @classmethod
    def start(cls, worker_id: int | None = None, daemon: bool = False, extractor: str | None = None, **kwargs: Any) -> int:
        """Fork a new worker as subprocess with optional extractor filter."""
        if worker_id is None:
            worker_id = get_next_worker_id(cls.name)

        # Use module-level function for pickling compatibility
        proc = Process(
            target=_run_worker,
            args=(cls.name, worker_id, daemon),
            kwargs={'extractor': extractor, **kwargs},
            name=f'{cls.name}_worker_{worker_id}',
        )
        proc.start()

        assert proc.pid is not None
        return proc.pid


# Populate the registry
WORKER_TYPES.update({
    'crawl': CrawlWorker,
    'snapshot': SnapshotWorker,
    'archiveresult': ArchiveResultWorker,
})


def get_worker_class(name: str) -> type[Worker]:
    """Get worker class by name."""
    if name not in WORKER_TYPES:
        raise ValueError(f'Unknown worker type: {name}. Valid types: {list(WORKER_TYPES.keys())}')
    return WORKER_TYPES[name]
