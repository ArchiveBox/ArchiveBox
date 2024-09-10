__package__ = 'archivebox.plugantic'

import importlib

from typing import Dict, List, TYPE_CHECKING
from pydantic import Field, InstanceOf

if TYPE_CHECKING:
    from huey.api import TaskWrapper

from .base_hook import BaseHook, HookType
from .base_binary import BaseBinary
from ..config_stubs import AttrDict



class BaseQueue(BaseHook):
    hook_type: HookType = 'QUEUE'

    name: str = Field()       # e.g. 'singlefile'

    binaries: List[InstanceOf[BaseBinary]] = Field()

    @property
    def tasks(self) -> Dict[str, 'TaskWrapper']:
        """Return an AttrDict of all the background worker tasks defined in the plugin's tasks.py file."""
        tasks = importlib.import_module(f"{self.plugin_module}.tasks")

        all_tasks = {}

        for task_name, task in tasks.__dict__.items():
            # if attr is a Huey task and its queue_name matches our hook's queue name
            if hasattr(task, "task_class") and task.huey.name == self.name:
                all_tasks[task_name] = task

        return AttrDict(all_tasks)

    def get_huey_config(self, settings) -> dict:
        return {
            "huey_class": "huey.SqliteHuey",
            "filename": settings.QUEUE_DATABASE_NAME,
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
        
    def get_supervisor_config(self, settings) -> dict:
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
        worker = start_worker(supervisor, self.get_supervisor_config(settings), lazy=lazy)
        return worker

    def register(self, settings, parent_plugin=None):
        # self._plugin = parent_plugin                                      # for debugging only, never rely on this!

        # Side effect: register queue with django-huey multiqueue dict
        settings.DJANGO_HUEY = getattr(settings, "DJANGO_HUEY", None) or AttrDict({"queues": {}})
        settings.DJANGO_HUEY["queues"][self.name] = self.get_huey_config(settings)

        # Side effect: register some extra tasks with huey
        # on_startup(queue=self.name)(self.on_startup_task)
        # db_periodic_task(crontab(minute='*/5'))(self.on_periodic_task)

        # Side effect: start consumer worker process under supervisord
        settings.WORKERS = getattr(settings, "WORKERS", None) or AttrDict({})
        settings.WORKERS[self.id] = self.start_supervisord_worker(settings, lazy=True)

        # Install queue into settings.QUEUES
        settings.QUEUES = getattr(settings, "QUEUES", None) or AttrDict({})
        settings.QUEUES[self.id] = self

        # Record installed hook into settings.HOOKS
        super().register(settings, parent_plugin=parent_plugin)


# class WgetToggleConfig(ConfigSet):
#     section: ConfigSectionName = 'ARCHIVE_METHOD_TOGGLES'

#     SAVE_WGET: bool = True
#     SAVE_WARC: bool = True

# class WgetDependencyConfig(ConfigSet):
#     section: ConfigSectionName = 'DEPENDENCY_CONFIG'

#     WGET_BINARY: str = Field(default='wget')
#     WGET_ARGS: Optional[List[str]] = Field(default=None)
#     WGET_EXTRA_ARGS: List[str] = []
#     WGET_DEFAULT_ARGS: List[str] = ['--timeout={TIMEOUT-10}']

# class WgetOptionsConfig(ConfigSet):
#     section: ConfigSectionName = 'ARCHIVE_METHOD_OPTIONS'

#     # loaded from shared config
#     WGET_AUTO_COMPRESSION: bool = Field(default=True)
#     SAVE_WGET_REQUISITES: bool = Field(default=True)
#     WGET_USER_AGENT: str = Field(default='', alias='USER_AGENT')
#     WGET_TIMEOUT: int = Field(default=60, alias='TIMEOUT')
#     WGET_CHECK_SSL_VALIDITY: bool = Field(default=True, alias='CHECK_SSL_VALIDITY')
#     WGET_RESTRICT_FILE_NAMES: str = Field(default='windows', alias='RESTRICT_FILE_NAMES')
#     WGET_COOKIES_FILE: Optional[Path] = Field(default=None, alias='COOKIES_FILE')


# CONFIG = {
#     'CHECK_SSL_VALIDITY': False,
#     'SAVE_WARC': False,
#     'TIMEOUT': 999,
# }


# WGET_CONFIG = [
#     WgetToggleConfig(**CONFIG),
#     WgetDependencyConfig(**CONFIG),
#     WgetOptionsConfig(**CONFIG),
# ]
