__package__ = 'archivebox.actors'

import os
import time
import itertools
from typing import Dict, Type, Literal, TYPE_CHECKING
from django.utils.functional import classproperty
from django.utils import timezone

import multiprocessing


from threading import Thread, get_native_id


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
    
    def __init__(self, actor_types: Dict[str, Type['ActorType']] | None = None, mode: Literal['thread', 'process'] | None=None, exit_on_idle: bool=True):
        self.actor_types = actor_types or self.actor_types or self.autodiscover_actor_types()
        self.mode = mode or self.mode
        self.exit_on_idle = exit_on_idle

    def __repr__(self) -> str:
        label = 'tid' if self.mode == 'thread' else 'pid'
        return f'[underline]{self.name}[/underline]\\[{label}={self.pid}]'
    
    def __str__(self) -> str:
        return self.__repr__()
    
    @classproperty
    def name(cls) -> str:
        return cls.__name__   # type: ignore
    
    def fork_as_thread(self):
        self.thread = Thread(target=self.runloop)
        self.thread.start()
        assert self.thread.native_id is not None
        return self.thread.native_id
    
    def fork_as_process(self):
        self.process = multiprocessing.Process(target=self.runloop)
        self.process.start()
        assert self.process.pid is not None
        return self.process.pid

    def start(self) -> int:
        if self.mode == 'thread':
            return self.fork_as_thread()
        elif self.mode == 'process':
            return self.fork_as_process()
        raise ValueError(f'Invalid orchestrator mode: {self.mode}')
    
    @classmethod
    def autodiscover_actor_types(cls) -> Dict[str, Type['ActorType']]:
        from archivebox.config.django import setup_django
        setup_django()
        
        # returns a Dict of all discovered {actor_type_id: ActorType} across the codebase
        # override this method in a subclass to customize the actor types that are used
        # return {'Snapshot': SnapshotActorType, 'ArchiveResult_chrome': ChromeActorType, ...}
        from crawls.actors import CrawlActor
        from core.actors import SnapshotActor, ArchiveResultActor   
        return {
            'CrawlActor': CrawlActor,
            'SnapshotActor': SnapshotActor,
            'ArchiveResultActor': ArchiveResultActor,
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
            queue.filter(retry_at__gt=timezone.now()).exists()
            for queue in all_queues.values()
        )
    
    def on_startup(self):
        if self.mode == 'thread':
            self.pid = get_native_id()
            print(f'[green]👨‍✈️ {self}.on_startup() STARTUP (THREAD)[/green]')
        elif self.mode == 'process':
            self.pid = os.getpid()
            print(f'[green]👨‍✈️ {self}.on_startup() STARTUP (PROCESS)[/green]')
        # abx.pm.hook.on_orchestrator_startup(self)
    
    def on_shutdown(self, err: BaseException | None = None):
        print(f'[grey53]👨‍✈️ {self}.on_shutdown() SHUTTING DOWN[/grey53]', err or '[green](gracefully)[/green]')
        # abx.pm.hook.on_orchestrator_shutdown(self)
        
    def on_tick_started(self, all_queues):
        total_pending = sum(queue.count() for queue in all_queues.values())
        print(f'👨‍✈️ {self}.on_tick_started()', f'total_pending={total_pending}')
        # abx.pm.hook.on_orchestrator_tick_started(self, actor_types, all_queues)
        pass
    
    def on_tick_finished(self, all_queues, all_existing_actors, all_spawned_actors):
        if all_spawned_actors:
            total_queue_length = sum(queue.count() for queue in all_queues.values())
            print(f'[grey53]👨‍✈️ {self}.on_tick_finished() queue={total_queue_length} existing_actors={len(all_existing_actors)} spawned_actors={len(all_spawned_actors)}[/grey53]')
        # abx.pm.hook.on_orchestrator_tick_finished(self, actor_types, all_queues)

    def on_idle(self, all_queues):
        print(f'👨‍✈️ {self}.on_idle()', f'idle_count={self.idle_count}')
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
                    next_obj = queue.first()
                    print(f'🏃‍♂️ {self}.runloop() {actor_type.__name__.ljust(20)} queue={str(queue.count()).ljust(3)} next={next_obj.abid if next_obj else "None"} {next_obj.status if next_obj else "None"} {(timezone.now() - next_obj.retry_at).total_seconds() if next_obj else "None"}')
                    try:
                        existing_actors = actor_type.get_running_actors()
                        all_existing_actors.extend(existing_actors)
                        actors_to_spawn = actor_type.get_actors_to_spawn(queue, existing_actors)
                        for launch_kwargs in actors_to_spawn:
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



# from archivebox.config.django import setup_django

# setup_django()

# from core.models import ArchiveResult, Snapshot

# from django.utils import timezone

# from django import db
# from django.db import connection


# from crawls.actors import CrawlActor
# from core.actors import SnapshotActor, ArchiveResultActor

# class ArchivingOrchestrator(Orchestrator):
#     actor_types = {
#         'CrawlActor': CrawlActor,
#         'SnapshotActor': SnapshotActor,
#         'ArchiveResultActor': ArchiveResultActor,
#         # 'FaviconActor': FaviconActor,
#         # 'SinglefileActor': SinglefileActor,
#     }

# from abx_plugin_singlefile.actors import SinglefileActor


# class FaviconActor(ActorType[ArchiveResult]):
#     CLAIM_ORDER: ClassVar[str] = 'created_at DESC'
#     CLAIM_WHERE: ClassVar[str] = 'status = "queued" AND extractor = "favicon"'
#     CLAIM_SET: ClassVar[str] = 'status = "started"'
    
#     @classproperty
#     def QUERYSET(cls) -> QuerySet:
#         return ArchiveResult.objects.filter(status='failed', extractor='favicon')

#     def tick(self, obj: ArchiveResult):
#         print(f'[grey53]{self}.tick({obj.abid or obj.id}, status={obj.status}) remaining:[/grey53]', self.get_queue().count())
#         updated = ArchiveResult.objects.filter(id=obj.id, status='started').update(status='success') == 1
#         if not updated:
#             raise Exception(f'Failed to update {obj.abid or obj.id}, interrupted by another actor writing to the same object')
#         obj.refresh_from_db()
#         obj.save()


# class ArchivingOrchestrator(Orchestrator):
#     actor_types = {
#         'CrawlActor': CrawlActor,
#         'SnapshotActor': SnapshotActor,
#         'ArchiveResultActor': ArchiveResultActor,
#         # 'FaviconActor': FaviconActor,
#         # 'SinglefileActor': SinglefileActor,
#     }


# if __name__ == '__main__':    
#     orchestrator = ExtractorsOrchestrator()
#     orchestrator.start()
    
#     snap = Snapshot.objects.last()
#     assert snap is not None
#     created = 0
#     while True:
#         time.sleep(0.05)
#         # try:
#         #     ArchiveResult.objects.bulk_create([
#         #         ArchiveResult(
#         #             id=uuid.uuid4(),
#         #             snapshot=snap,
#         #             status='failed',
#         #             extractor='favicon',
#         #             cmd=['echo', '"hello"'],
#         #             cmd_version='1.0',
#         #             pwd='.',
#         #             start_ts=timezone.now(),
#         #             end_ts=timezone.now(),
#         #             created_at=timezone.now(),
#         #             modified_at=timezone.now(),
#         #             created_by_id=1,
#         #         )
#         #         for _ in range(100)
#         #     ])
#         #     created += 100
#         #     if created % 1000 == 0:
#         #         print(f'[blue]Created {created} ArchiveResults...[/blue]')
#         #         time.sleep(25)
#         # except Exception as err:
#         #     print(err)
#         #     db.connections.close_all()
#         # except BaseException as err:
#         #     print(err)
#         #     break
