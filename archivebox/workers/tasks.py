__package__ = 'archivebox.workers'

from functools import wraps
# from django.utils import timezone

from django_huey import db_task, task

from huey_monitor.models import TaskModel
from huey_monitor.tqdm import ProcessInfo

from .supervisord_util import get_or_create_supervisord_process

# @db_task(queue="commands", context=True, schedule=1)
# def scheduler_tick():
#     print('SCHEDULER TICK', timezone.now().isoformat())
#     # abx.archivebox.events.on_scheduler_runloop_start(timezone.now(), machine=Machine.objects.get_current_machine())

#     # abx.archivebox.events.on_scheduler_tick_start(timezone.now(), machine=Machine.objects.get_current_machine())
    
#     scheduled_crawls = CrawlSchedule.objects.filter(is_enabled=True)
#     scheduled_crawls_due = scheduled_crawls.filter(next_run_at__lte=timezone.now())
    
#     for scheduled_crawl in scheduled_crawls_due:
#         try:
#             abx.archivebox.events.on_crawl_schedule_tick(scheduled_crawl)
#         except Exception as e:
#             abx.archivebox.events.on_crawl_schedule_failure(timezone.now(), machine=Machine.objects.get_current_machine(), error=e, schedule=scheduled_crawl)
    
#     # abx.archivebox.events.on_scheduler_tick_end(timezone.now(), machine=Machine.objects.get_current_machine(), tasks=scheduled_tasks_due)

def db_task_with_parent(func):
    """Decorator for db_task that sets the parent task for the db_task"""
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        task = kwargs.get('task')
        parent_task_id = kwargs.get('parent_task_id')
        
        if task and parent_task_id:
            TaskModel.objects.set_parent_task(main_task_id=parent_task_id, sub_task_id=task.id)

        return func(*args, **kwargs)
    
    return wrapper

@db_task(queue="commands", context=True)
def bg_add(add_kwargs, task=None, parent_task_id=None):
    get_or_create_supervisord_process(daemonize=False)
    
    from ..main import add
    
    if task and parent_task_id:
        TaskModel.objects.set_parent_task(main_task_id=parent_task_id, sub_task_id=task.id)

    assert add_kwargs and add_kwargs.get("urls")
    rough_url_count = add_kwargs["urls"].count("://")

    process_info = ProcessInfo(task, desc="add", parent_task_id=parent_task_id, total=rough_url_count)

    result = add(**add_kwargs)
    process_info.update(n=rough_url_count)
    return result


@task(queue="commands", context=True)
def bg_archive_snapshots(snapshots, kwargs=None, task=None, parent_task_id=None):
    """
    Queue multiple snapshots for archiving via the state machine system.

    This sets snapshots to 'queued' status so the orchestrator workers pick them up.
    The actual archiving happens through ArchiveResult.run().
    """
    get_or_create_supervisord_process(daemonize=False)

    from django.utils import timezone
    from core.models import Snapshot

    if task and parent_task_id:
        TaskModel.objects.set_parent_task(main_task_id=parent_task_id, sub_task_id=task.id)

    assert snapshots
    kwargs = kwargs or {}

    rough_count = len(snapshots) if hasattr(snapshots, '__len__') else snapshots.count()
    process_info = ProcessInfo(task, desc="archive_snapshots", parent_task_id=parent_task_id, total=rough_count)

    # Queue snapshots by setting status to queued with immediate retry_at
    queued_count = 0
    for snapshot in snapshots:
        if hasattr(snapshot, 'id'):
            # Update snapshot to queued state so workers pick it up
            Snapshot.objects.filter(id=snapshot.id).update(
                status=Snapshot.StatusChoices.QUEUED,
                retry_at=timezone.now(),
            )
            queued_count += 1

    process_info.update(n=queued_count)
    return queued_count


@task(queue="commands", context=True)
def bg_archive_snapshot(snapshot, overwrite=False, methods=None, task=None, parent_task_id=None):
    """
    Queue a single snapshot for archiving via the state machine system.

    This sets the snapshot to 'queued' status so the orchestrator workers pick it up.
    The actual archiving happens through ArchiveResult.run().
    """
    get_or_create_supervisord_process(daemonize=False)

    from django.utils import timezone
    from core.models import Snapshot

    if task and parent_task_id:
        TaskModel.objects.set_parent_task(main_task_id=parent_task_id, sub_task_id=task.id)

    process_info = ProcessInfo(task, desc="archive_snapshot", parent_task_id=parent_task_id, total=1)

    # Queue the snapshot by setting status to queued
    if hasattr(snapshot, 'id'):
        Snapshot.objects.filter(id=snapshot.id).update(
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        process_info.update(n=1)
        return 1

    return 0

