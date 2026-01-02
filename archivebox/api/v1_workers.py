__package__ = 'archivebox.api'

from uuid import UUID
from typing import List, Any
from datetime import datetime

from ninja import Router, Schema


router = Router(tags=['Workers and Tasks'])


class QueueItemSchema(Schema):
    """Schema for a single item in a worker's queue."""
    TYPE: str
    id: UUID
    status: str
    retry_at: datetime | None
    created_at: datetime
    modified_at: datetime
    description: str

    @staticmethod
    def resolve_TYPE(obj) -> str:
        return f'{obj._meta.app_label}.{obj._meta.model_name}'

    @staticmethod
    def resolve_description(obj) -> str:
        return str(obj)


class WorkerSchema(Schema):
    """Schema for a Worker type."""
    name: str
    model: str
    max_tick_time: int
    max_concurrent_tasks: int
    running_count: int
    running_workers: List[dict[str, Any]]

    @staticmethod
    def resolve_model(obj) -> str:
        Model = obj.get_model()
        return f'{Model._meta.app_label}.{Model._meta.model_name}'

    @staticmethod
    def resolve_max_tick_time(obj) -> int:
        return obj.MAX_TICK_TIME

    @staticmethod
    def resolve_max_concurrent_tasks(obj) -> int:
        return obj.MAX_CONCURRENT_TASKS

    @staticmethod
    def resolve_running_count(obj) -> int:
        return obj.get_worker_count()

    @staticmethod
    def resolve_running_workers(obj) -> List[dict[str, Any]]:
        return obj.get_running_workers()


class OrchestratorSchema(Schema):
    """Schema for the Orchestrator."""
    is_running: bool
    poll_interval: float
    idle_timeout: int
    max_crawl_workers: int
    total_worker_count: int
    workers: List[WorkerSchema]


@router.get("/orchestrator", response=OrchestratorSchema, url_name="get_orchestrator")
def get_orchestrator(request):
    """Get the orchestrator status and all worker queues."""
    from archivebox.workers.orchestrator import Orchestrator
    from archivebox.workers.worker import CrawlWorker

    orchestrator = Orchestrator()

    # Create temporary worker instances to query their queues
    workers = [
        CrawlWorker(worker_id=-1),
    ]

    return {
        'is_running': orchestrator.is_running(),
        'poll_interval': orchestrator.POLL_INTERVAL,
        'idle_timeout': orchestrator.IDLE_TIMEOUT,
        'max_crawl_workers': orchestrator.MAX_CRAWL_WORKERS,
        'total_worker_count': orchestrator.get_total_worker_count(),
        'workers': workers,
    }


@router.get("/workers", response=List[WorkerSchema], url_name="get_workers")
def get_workers(request):
    """List all worker types and their current status."""
    from archivebox.workers.worker import CrawlWorker

    # Create temporary instances to query their queues
    return [
        CrawlWorker(worker_id=-1),
    ]


# Progress endpoint moved to core.views.live_progress_view for simplicity
