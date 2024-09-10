__package__ = 'archivebox.queues'

import time

from django.core.cache import cache

from huey import crontab
from django_huey import db_task, on_startup, db_periodic_task
from huey_monitor.models import TaskModel
from huey_monitor.tqdm import ProcessInfo

@db_task(queue="singlefile", context=True)
def extract(url, out_dir, config, task=None, parent_task_id=None):
    if task and parent_task_id:
        TaskModel.objects.set_parent_task(main_task_id=parent_task_id, sub_task_id=task.id)

    process_info = ProcessInfo(task, desc="extract_singlefile", parent_task_id=parent_task_id, total=1)

    time.sleep(5)

    process_info.update(n=1)
    return {'output': 'singlefile.html', 'status': 'succeeded'}


# @on_startup(queue='singlefile')
# def start_singlefile_queue():
#     print("[+] Starting singlefile worker...")
#     update_version.call_local()


# @db_periodic_task(crontab(minute='*/5'), queue='singlefile')
# def update_version():
#     print('[*] Updating singlefile version... 5 minute interval')
#     from django.conf import settings
    
#     bin = settings.BINARIES.SinglefileBinary.load()
#     if bin.version:
#         cache.set(f"bin:abspath:{bin.name}", bin.abspath)
#         cache.set(f"bin:version:{bin.name}:{bin.abspath}", bin.version)
#         print('[√] Updated singlefile version:', bin.version, bin.abspath)
