__package__ = 'abx.archivebox'

import importlib

from typing import Dict, List, TYPE_CHECKING
from pydantic import Field, InstanceOf
from benedict import benedict

if TYPE_CHECKING:
    from huey.api import TaskWrapper

import abx

from .base_hook import BaseHook, HookType
from .base_binary import BaseBinary



class BaseQueue(BaseHook):
    hook_type: HookType = 'QUEUE'

    name: str = Field()       # e.g. 'singlefile'

    binaries: List[InstanceOf[BaseBinary]] = Field()

    @property
    def tasks(self) -> Dict[str, 'TaskWrapper']:
        """Return an dict of all the background worker tasks defined in the plugin's tasks.py file."""
        tasks = importlib.import_module(f"{self.plugin_module}.tasks")

        all_tasks = {}

        for task_name, task in tasks.__dict__.items():
            # if attr is a Huey task and its queue_name matches our hook's queue name
            if hasattr(task, "task_class") and task.huey.name == self.name:
                all_tasks[task_name] = task

        return benedict(all_tasks)

    def get_django_huey_config(self, QUEUE_DATABASE_NAME) -> dict:
        """Get the config dict to insert into django.conf.settings.DJANGO_HUEY['queues']."""
        return {
            "huey_class": "huey.SqliteHuey",
            "filename": QUEUE_DATABASE_NAME,
            "name": self.name,
            "results": True,
            "store_none": True,
            "immediate": False,
            "utc": True,
            "consumer": {
                "workers": 1,
                "worker_type": "thread",
                "initial_delay": 0.1,  # Smallest polling interval, same as -d.
                "backoff": 1.15,  # Exponential backoff using this rate, -b.
                "max_delay": 10.0,  # Max possible polling interval, -m.
                "scheduler_interval": 1,  # Check schedule every second, -s.
                "periodic": True,  # Enable crontab feature.
                "check_worker_health": True,  # Enable worker health checks.
                "health_check_interval": 1,  # Check worker health every second.
            },
        }
        
    def get_supervisord_config(self, settings) -> dict:
        """Ge the config dict used to tell sueprvisord to start a huey consumer for this queue."""
        return {
            "name": f"worker_{self.name}",
            "command": f"archivebox manage djangohuey --queue {self.name}",
            "stdout_logfile": f"logs/worker_{self.name}.log",
            "redirect_stderr": "true",
            "autorestart": "true",
            "autostart": "false",
        }
        
    def start_supervisord_worker(self, settings, lazy=True):
        from queues.supervisor_util import get_or_create_supervisord_process, start_worker
        print()
        try:
            supervisor = get_or_create_supervisord_process(daemonize=False)
        except Exception as e:
            print(f"Error starting worker for queue {self.name}: {e}")
            return None
        print()
        worker = start_worker(supervisor, self.get_supervisord_config(settings), lazy=lazy)

        # Update settings.WORKERS to include this worker
        settings.WORKERS = getattr(settings, "WORKERS", None) or benedict({})
        settings.WORKERS[self.id] = self.start_supervisord_worker(settings, lazy=True)

        return worker

    @abx.hookimpl
    def get_QUEUES(self):
        return [self]

    @abx.hookimpl
    def get_DJANGO_HUEY_QUEUES(self, QUEUE_DATABASE_NAME):
        """queue configs to be added to django.conf.settings.DJANGO_HUEY['queues']"""
        return {
            self.name: self.get_django_huey_config(QUEUE_DATABASE_NAME)
        }
        
        
    # @abx.hookimpl
    # def ready(self, settings):
    #     self.start_supervisord_worker(settings, lazy=True)
    #     super().ready(settings)
