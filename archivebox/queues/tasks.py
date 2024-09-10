__package__ = 'archivebox.queues'

from django_huey import db_task, task

from huey_monitor.models import TaskModel
from huey_monitor.tqdm import ProcessInfo

@db_task(queue="system_tasks", context=True)
def bg_add(add_kwargs, task=None, parent_task_id=None):
    from ..main import add
    
    if task and parent_task_id:
        TaskModel.objects.set_parent_task(main_task_id=parent_task_id, sub_task_id=task.id)

    assert add_kwargs and add_kwargs.get("urls")
    rough_url_count = add_kwargs["urls"].count("://")

    process_info = ProcessInfo(task, desc="add", parent_task_id=parent_task_id, total=rough_url_count)

    result = add(**add_kwargs)
    process_info.update(n=rough_url_count)
    return result


@task(queue="system_tasks", context=True)
def bg_archive_links(args, kwargs=None, task=None, parent_task_id=None):
    from ..extractors import archive_links
    
    if task and parent_task_id:
        TaskModel.objects.set_parent_task(main_task_id=parent_task_id, sub_task_id=task.id)

    assert args and args[0]
    kwargs = kwargs or {}
    
    rough_count = len(args[0])
    
    process_info = ProcessInfo(task, desc="archive_links", parent_task_id=parent_task_id, total=rough_count)
    
    result = archive_links(*args, **kwargs)
    process_info.update(n=rough_count)
    return result
