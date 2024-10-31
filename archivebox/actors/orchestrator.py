__package__ = 'archivebox.actors'

import os
import time
from typing import Dict

from multiprocessing import Process

from django.db.models import QuerySet

from .actor import ActorType

class Orchestrator:
    pid: int

    @classmethod
    def spawn_orchestrator(cls) -> int:
        orchestrator = cls()
        orchestrator_bg_proc = Process(target=orchestrator.runloop)
        orchestrator_bg_proc.start()
        assert orchestrator_bg_proc.pid is not None
        return orchestrator_bg_proc.pid
    
    @classmethod
    def get_all_actor_types(cls) -> Dict[str, ActorType]:
        # returns a Dict of all discovered {actor_type_id: ActorType} ...
        # return {'Snapshot': SnapshotActorType, 'ArchiveResult_chrome': ChromeActorType, ...}
        return {
            'TestActor': TestActor(),
        }
    
    @classmethod
    def get_orphaned_objects(cls, all_queues) -> list:
        # returns a list of objects that are in the queues of all actor types but not in the queues of any other actor types
        return []
    
    def on_startup(self):
        self.pid = os.getpid()
        print('Orchestrator startup', self.pid)
        # abx.pm.hook.on_orchestrator_startup(self)
    
    def on_shutdown(self, err: BaseException | None = None):
        print('Orchestrator shutdown', self.pid, err)
        # abx.pm.hook.on_orchestrator_shutdown(self)
        
    def on_tick_started(self, actor_types, all_queues):
        total_pending = sum(queue.count() for queue in all_queues.values())
        print('Orchestrator tick +', self.pid, f'total_pending={total_pending}')
        # abx.pm.hook.on_orchestrator_tick_started(self, actor_types, all_queues)
    
    def on_tick_finished(self, actor_types, all_queues):
        # print('Orchestrator tick √', self.pid)
        # abx.pm.hook.on_orchestrator_tick_finished(self, actor_types, all_queues)
        pass
    
    def on_idle(self):
        # print('Orchestrator idle', self.pid)
        # abx.pm.hook.on_orchestrator_idle(self)
        pass
    
    def runloop(self):
        self.pid = os.getpid()
        
        try:
            while True:
                actor_types = self.get_all_actor_types()
                all_queues = {
                    actor_type: actor_type.get_queue()
                    for actor_type in actor_types.values()
                }
                self.on_tick_started(actor_types, all_queues)

                all_existing_actors = []
                all_spawned_actors = []

                for actor_type, queue in all_queues.items():
                    existing_actors = actor_type.get_running_actors()
                    all_existing_actors.extend(existing_actors)
                    actors_to_spawn = actor_type.get_actors_to_spawn(queue, existing_actors)
                    for launch_kwargs in actors_to_spawn:
                        all_spawned_actors.append(actor_type.spawn_actor(**launch_kwargs))
                
                if all_spawned_actors:
                    print(f'Found {len(all_existing_actors)} existing actors, Spawned {len(all_spawned_actors)} new actors')
                else:
                    # print(f'No actors to spawn, currently_running: {len(all_existing_actors)}')
                    time.sleep(1)

                orphaned_objects = self.get_orphaned_objects(all_queues)
                if orphaned_objects:
                    print('WARNING: some objects may will not be processed', orphaned_objects)

                if not any(queue.exists() for queue in all_queues.values()):
                    # we are idle
                    self.on_idle()
                    # time.sleep(0.250)
                    time.sleep(2)
                    
                self.on_tick_finished(actor_types, all_queues)

        except (KeyboardInterrupt, SystemExit) as err:
            self.on_shutdown(err)



from archivebox.config.django import setup_django

setup_django()

from core.models import ArchiveResult, Snapshot

from django.utils import timezone

from django import db
from django.db import connection

def get_next_archiveresult_atomically() -> ArchiveResult | None:
    with connection.cursor() as cursor:
        # select a random archiveresult out of the next 50 pending ones
        # (to avoid clashing with another actor thats also selecting from the same list)
        cursor.execute("""
            UPDATE core_archiveresult 
            SET status = 'started'
            WHERE status = 'failed' and id = (
                SELECT id FROM (
                    SELECT id FROM core_archiveresult
                    WHERE status = 'failed'
                    ORDER BY start_ts DESC
                    LIMIT 50
                ) candidates
                ORDER BY RANDOM()
                LIMIT 1
            )
            RETURNING *;
        """)
        result = cursor.fetchone()
        
        # If no rows were updated, return None
        if result is None:
            return None
            
        # Convert the row tuple into a dict matching column names
        columns = [col[0] for col in cursor.description]
        return ArchiveResult(**dict(zip(columns, result)))


class TestActor(ActorType[ArchiveResult]):
    @classmethod
    def get_queue(cls) -> QuerySet[ArchiveResult]:
        return ArchiveResult.objects.filter(status='failed', extractor='favicon')
    
    @classmethod
    def get_next(cls) -> ArchiveResult | None:
        return get_next_archiveresult_atomically()
        # return cls.get_queue().last()
    
    def tick(self, obj: ArchiveResult):
        # print(f'TestActor[{self.pid}] tick({obj.id})', 'remaining:', self.get_queue().count())
        updated = ArchiveResult.objects.filter(id=obj.id, status='started').update(status='success')
        if not updated:
            raise Exception('Failed to update object status, likely being processed by another actor')
        
    def lock(self, obj: ArchiveResult) -> bool:
        locked = True
        # locked = ArchiveResult.objects.select_for_update(skip_locked=True).filter(id=obj.id, status='pending').update(status='started') == 1
        # if locked:
        #     print(f'TestActor[{self.pid}] lock({obj.id}) 🔒')
        # else:
        #     print(f'TestActor[{self.pid}] lock({obj.id}) X')
        return locked
        
if __name__ == '__main__':    
    snap = Snapshot.objects.last()
    assert snap is not None
        
    orchestrator = Orchestrator()
    orchestrator.spawn_orchestrator()
    
    for _ in range(50_000):
        try:
            ar = ArchiveResult.objects.create(
                snapshot=snap,
                status='failed',
                extractor='favicon',
                cmd=['echo', '"hello"'],
                cmd_version='1.0',
                pwd='.',
                start_ts=timezone.now(),
                end_ts=timezone.now(),
            )
        except Exception as err:
            print(err)
            db.connections.close_all()
        if _ % 1000 == 0:
            print('Created', _, 'snapshots...')
        time.sleep(0.001)
        # time.sleep(3)
    
    # test_queue = TestActor.get_queue()
    # thread_actors = []
    # print('Actor queue:', test_queue)
    # actors_to_spawn = TestActor.get_actors_to_spawn(test_queue, thread_actors)
    # print('Actors to spawn:', actors_to_spawn)
    # # thread_actors = [TestActor.spawn_actor(mode='thread') for _ in actors_to_spawn]
    # # print('Thread Actors spawned:', thread_actors)
    # process_actors = [TestActor.spawn_actor(mode='process') for _ in actors_to_spawn]
    # print('Process Actors spawned:', process_actors)
