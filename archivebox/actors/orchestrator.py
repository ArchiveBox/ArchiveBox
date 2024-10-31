__package__ = 'archivebox.actors'

import os
import time
import itertools
import uuid
from typing import Dict, Type

from multiprocessing import Process, cpu_count

from rich import print

from django.db.models import QuerySet

from django.apps import apps
from .actor import ActorType

class Orchestrator:
    pid: int
    idle_count: int = 0
    actor_types: Dict[str, Type[ActorType]]

    def __init__(self, actor_types: Dict[str, Type[ActorType]] | None = None):
        self.actor_types = actor_types or self.actor_types or self.autodiscover_actor_types()

    def __repr__(self) -> str:
        return f'[underline]{self.__class__.__name__}[/underline]\\[pid={self.pid}]'
    
    def __str__(self) -> str:
        return self.__repr__()

    def start(self) -> int:
        orchestrator_bg_proc = Process(target=self.runloop)
        orchestrator_bg_proc.start()
        assert orchestrator_bg_proc.pid is not None
        return orchestrator_bg_proc.pid
    
    @classmethod
    def autodiscover_actor_types(cls) -> Dict[str, Type[ActorType]]:
        # returns a Dict of all discovered {actor_type_id: ActorType} across the codebase
        # override this method in a subclass to customize the actor types that are used
        # return {'Snapshot': SnapshotActorType, 'ArchiveResult_chrome': ChromeActorType, ...}
        return {
            # look through all models and find all classes that inherit from ActorType
            # ...
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
    
    def on_startup(self):
        self.pid = os.getpid()
        print(f'[green]👨‍✈️ {self}.on_startup() STARTUP (PROCESS)[/green]')
        # abx.pm.hook.on_orchestrator_startup(self)
    
    def on_shutdown(self, err: BaseException | None = None):
        print(f'[grey53]👨‍✈️ {self}.on_shutdown() SHUTTING DOWN[/grey53]', err or '[green](gracefully)[/green]')
        # abx.pm.hook.on_orchestrator_shutdown(self)
        
    def on_tick_started(self, all_queues):
        # total_pending = sum(queue.count() for queue in all_queues.values())
        # print(f'👨‍✈️ {self}.on_tick_started()', f'total_pending={total_pending}')
        # abx.pm.hook.on_orchestrator_tick_started(self, actor_types, all_queues)
        pass
    
    def on_tick_finished(self, all_queues, all_existing_actors, all_spawned_actors):
        if all_spawned_actors:
            total_queue_length = sum(queue.count() for queue in all_queues.values())
            print(f'[grey53]👨‍✈️ {self}.on_tick_finished() queue={total_queue_length} existing_actors={len(all_existing_actors)} spawned_actors={len(all_spawned_actors)}[/grey53]')
        # abx.pm.hook.on_orchestrator_tick_finished(self, actor_types, all_queues)

    def on_idle(self, all_queues):
        # print(f'👨‍✈️ {self}.on_idle()')
        # abx.pm.hook.on_orchestrator_idle(self)
        # check for orphaned objects left behind
        if self.idle_count == 60:
            orphaned_objects = self.get_orphaned_objects(all_queues)
            if orphaned_objects:
                print('[red]👨‍✈️ WARNING: some objects may not be processed, no actor has claimed them after 60s:[/red]', orphaned_objects)

    def runloop(self):
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
                    try:
                        existing_actors = actor_type.get_running_actors()
                        all_existing_actors.extend(existing_actors)
                        actors_to_spawn = actor_type.get_actors_to_spawn(queue, existing_actors)
                        for launch_kwargs in actors_to_spawn:
                            new_actor_pid = actor_type.start(mode='process', **launch_kwargs)
                            all_spawned_actors.append(new_actor_pid)
                    except BaseException as err:
                        print(f'🏃‍♂️ ERROR: {self} Failed to get {actor_type} queue & running actors', err)

                if not any(queue.exists() for queue in all_queues.values()):
                    self.on_idle(all_queues)
                    self.idle_count += 1
                    time.sleep(1)
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



from archivebox.config.django import setup_django

setup_django()

from core.models import ArchiveResult, Snapshot

from django.utils import timezone

from django import db
from django.db import connection




class FaviconActor(ActorType[ArchiveResult]):
    @classmethod
    def get_queue(cls) -> QuerySet[ArchiveResult]:
        return ArchiveResult.objects.filter(status='failed', extractor='favicon')
    
    @classmethod
    def get_next(cls) -> ArchiveResult | None:
        return cls.get_next_atomic(
            model=ArchiveResult,
            filter=('status', 'failed'),
            update=('status', 'started'),
            sort='created_at',
            order='DESC',
            choose_from_top=cpu_count() * 10
        )
    
    def tick(self, obj: ArchiveResult):
        print(f'[grey53]{self}.tick({obj.id}) remaining:[/grey53]', self.get_queue().count())
        updated = ArchiveResult.objects.filter(id=obj.id, status='started').update(status='success') == 1
        if not updated:
            raise Exception(f'Failed to update {obj.abid}, interrupted by another actor writing to the same object')
        
    def lock(self, obj: ArchiveResult) -> bool:
        """As an alternative to self.get_next_atomic(), we can use select_for_update() or manually update a semaphore field here"""

        # locked = ArchiveResult.objects.select_for_update(skip_locked=True).filter(id=obj.id, status='pending').update(status='started') == 1
        # if locked:
        #     print(f'FaviconActor[{self.pid}] lock({obj.id}) 🔒')
        # else:
        #     print(f'FaviconActor[{self.pid}] lock({obj.id}) X')
        return True


class ExtractorsOrchestrator(Orchestrator):
    actor_types = {
        'FaviconActor': FaviconActor,
    }


if __name__ == '__main__':    
    orchestrator = ExtractorsOrchestrator()
    orchestrator.start()
    
    snap = Snapshot.objects.last()
    assert snap is not None
    created = 0
    while True:
        time.sleep(0.005)
        try:
            ArchiveResult.objects.bulk_create([
                ArchiveResult(
                    id=uuid.uuid4(),
                    snapshot=snap,
                    status='failed',
                    extractor='favicon',
                    cmd=['echo', '"hello"'],
                    cmd_version='1.0',
                    pwd='.',
                    start_ts=timezone.now(),
                    end_ts=timezone.now(),
                    created_at=timezone.now(),
                    modified_at=timezone.now(),
                    created_by_id=1,
                )
                for _ in range(100)
            ])
            created += 100
            if created % 1000 == 0:
                print(f'[blue]Created {created} ArchiveResults...[/blue]')
                time.sleep(25)
        except Exception as err:
            print(err)
            db.connections.close_all()
        except BaseException as err:
            print(err)
            break
