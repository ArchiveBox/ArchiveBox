__package__ = 'archivebox.workers'

import os
import time
import sys
import itertools
from typing import Dict, Type, Literal, TYPE_CHECKING
from django.utils.functional import classproperty
from django.utils import timezone

import multiprocessing



from rich import print

# from django.db.models import QuerySet

from django.apps import apps

if TYPE_CHECKING:
    from .actor import ActorType


multiprocessing.set_start_method('fork', force=True)


class Orchestrator:
    pid: int
    idle_count: int = 0
    actor_types: Dict[str, Type['ActorType']] = {}
    mode: Literal['thread', 'process'] = 'process'
    exit_on_idle: bool = True
    max_concurrent_actors: int = 20
    
    def __init__(self, actor_types: Dict[str, Type['ActorType']] | None = None, mode: Literal['thread', 'process'] | None=None, exit_on_idle: bool=True, max_concurrent_actors: int=max_concurrent_actors):
        self.actor_types = actor_types or self.actor_types or self.autodiscover_actor_types()
        self.mode = mode or self.mode
        self.exit_on_idle = exit_on_idle
        self.max_concurrent_actors = max_concurrent_actors

    def __repr__(self) -> str:
        label = 'tid' if self.mode == 'thread' else 'pid'
        return f'[underline]{self.name}[/underline]\\[{label}={self.pid}]'
    
    def __str__(self) -> str:
        return self.__repr__()
    
    @classproperty
    def name(cls) -> str:
        return cls.__name__   # type: ignore
    
    # def _fork_as_thread(self):
    #     self.thread = Thread(target=self.runloop)
    #     self.thread.start()
    #     assert self.thread.native_id is not None
    #     return self.thread.native_id
    
    def _fork_as_process(self):
        self.process = multiprocessing.Process(target=self.runloop)
        self.process.start()
        assert self.process.pid is not None
        return self.process.pid

    def start(self) -> int:
        if self.mode == 'thread':
            # return self._fork_as_thread()
            raise NotImplementedError('Thread-based orchestrators are disabled for now to reduce codebase complexity')
        elif self.mode == 'process':
            return self._fork_as_process()
        raise ValueError(f'Invalid orchestrator mode: {self.mode}')
    
    @classmethod
    def autodiscover_actor_types(cls) -> Dict[str, Type['ActorType']]:
        from archivebox.config.django import setup_django
        setup_django()
        
        # returns a Dict of all discovered {actor_type_id: ActorType} across the codebase
        # override this method in a subclass to customize the actor types that are used
        # return {'Snapshot': SnapshotWorker, 'ArchiveResult_chrome': ChromeActorType, ...}
        from crawls.statemachines import CrawlWorker
        from core.statemachines import SnapshotWorker, ArchiveResultWorker   
        return {
            'CrawlWorker': CrawlWorker,
            'SnapshotWorker': SnapshotWorker,
            'ArchiveResultWorker': ArchiveResultWorker,
            # look through all models and find all classes that inherit from ActorType
            # actor_type.__name__: actor_type
            # for actor_type in abx.pm.hook.get_all_ACTORS_TYPES().values()
        }
    
    @classmethod
    def get_orphaned_objects(cls, all_queues) -> list:
        # returns a list of objects that are in the queues of all actor types but not in the queues of any other actor types
        all_queued_ids = itertools.chain(*[queue.values('id', flat=True) for queue in all_queues.values()])
        orphaned_objects = []
        for model in apps.get_models():
            if hasattr(model, 'retry_at'):
                orphaned_objects.extend(model.objects.filter(retry_at__lt=timezone.now()).exclude(id__in=all_queued_ids))
        return orphaned_objects
    
    @classmethod
    def has_future_objects(cls, all_queues) -> bool:
        # returns a list of objects that are in the queues of all actor types but not in the queues of any other actor types

        return any(
            queue.filter(retry_at__gte=timezone.now()).exists()
            for queue in all_queues.values()
        )
    
    def on_startup(self):
        if self.mode == 'thread':
            # self.pid = get_native_id()
            print(f'[green]👨‍✈️ {self}.on_startup() STARTUP (THREAD)[/green]')
            raise NotImplementedError('Thread-based orchestrators are disabled for now to reduce codebase complexity')
        elif self.mode == 'process':
            self.pid = os.getpid()
            print(f'[green]👨‍✈️ {self}.on_startup() STARTUP (PROCESS)[/green]')
        # abx.pm.hook.on_orchestrator_startup(self)
    
    def on_shutdown(self, err: BaseException | None = None):
        print(f'[grey53]👨‍✈️ {self}.on_shutdown() SHUTTING DOWN[/grey53]', err or '[green](gracefully)[/green]')
        # abx.pm.hook.on_orchestrator_shutdown(self)
        
    def on_tick_started(self, all_queues):
        # total_pending = sum(queue.count() for queue in all_queues.values())
        # if total_pending:
        #     print(f'👨‍✈️ {self}.on_tick_started()', f'total_pending={total_pending}')
        # abx.pm.hook.on_orchestrator_tick_started(self, actor_types, all_queues)
        pass
    
    def on_tick_finished(self, all_queues, all_existing_actors, all_spawned_actors):
        # if all_spawned_actors:
        #     total_queue_length = sum(queue.count() for queue in all_queues.values())
        #     print(f'[grey53]👨‍✈️ {self}.on_tick_finished() queue={total_queue_length} existing_actors={len(all_existing_actors)} spawned_actors={len(all_spawned_actors)}[/grey53]')
        # abx.pm.hook.on_orchestrator_tick_finished(self, actor_types, all_queues)
        pass

    def on_idle(self, all_queues):
        # print(f'👨‍✈️ {self}.on_idle()', f'idle_count={self.idle_count}')
        print('.', end='', flush=True, file=sys.stderr)
        # abx.pm.hook.on_orchestrator_idle(self)
        # check for orphaned objects left behind
        if self.idle_count == 60:
            orphaned_objects = self.get_orphaned_objects(all_queues)
            if orphaned_objects:
                print('[red]👨‍✈️ WARNING: some objects may not be processed, no actor has claimed them after 30s:[/red]', orphaned_objects)
        if self.idle_count > 3 and self.exit_on_idle and not self.has_future_objects(all_queues):
            raise KeyboardInterrupt('✅ All tasks completed, exiting')

    def runloop(self):
        from archivebox.config.django import setup_django
        setup_django()
        
        self.on_startup()
        try:
            while True:
                all_queues = {
                    actor_type: actor_type.get_queue()
                    for actor_type in self.actor_types.values()
                }
                if not all_queues:
                    raise Exception('Failed to find any actor_types to process')

                self.on_tick_started(all_queues)

                all_existing_actors = []
                all_spawned_actors = []

                for actor_type, queue in all_queues.items():
                    if not queue.exists():
                        continue
        
                    next_obj = queue.first()
                    print()
                    print(f'🏃‍♂️ {self}.runloop() {actor_type.__name__.ljust(20)} queue={str(queue.count()).ljust(3)} next={next_obj.abid if next_obj else "None"} {next_obj.status if next_obj else "None"} {(timezone.now() - next_obj.retry_at).total_seconds() if next_obj and next_obj.retry_at else "None"}')
                    self.idle_count = 0
                    try:
                        existing_actors = actor_type.get_running_actors()
                        all_existing_actors.extend(existing_actors)
                        actors_to_spawn = actor_type.get_actors_to_spawn(queue, existing_actors)
                        can_spawn_num_remaining = self.max_concurrent_actors - len(all_existing_actors)  # set max_concurrent_actors=1 to disable multitasking
                        for launch_kwargs in actors_to_spawn[:can_spawn_num_remaining]:
                            new_actor_pid = actor_type.start(mode='process', **launch_kwargs)
                            all_spawned_actors.append(new_actor_pid)
                    except Exception as err:
                        print(f'🏃‍♂️ ERROR: {self} Failed to get {actor_type} queue & running actors', err)
                    except BaseException:
                        raise

                if not any(queue.exists() for queue in all_queues.values()):
                    self.on_idle(all_queues)
                    self.idle_count += 1
                    time.sleep(0.5)
                else:
                    self.idle_count = 0
                    
                self.on_tick_finished(all_queues, all_existing_actors, all_spawned_actors)
                time.sleep(1)

        except BaseException as err:
            if isinstance(err, KeyboardInterrupt):
                print()
            else:
                print(f'\n[red]🏃‍♂️ {self}.runloop() FATAL:[/red]', err.__class__.__name__, err)
            self.on_shutdown(err=err)
