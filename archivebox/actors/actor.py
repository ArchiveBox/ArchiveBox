__package__ = 'archivebox.actors'

import os
import time
import psutil
from typing import ClassVar, Generic, TypeVar, Any, cast, Literal

from django.db.models import QuerySet
from multiprocessing import Process, cpu_count
from threading import Thread, get_native_id

# from archivebox.logging_util import TimedProgress

ALL_SPAWNED_ACTORS: list[psutil.Process] = []


LaunchKwargs = dict[str, Any]

ObjectType = TypeVar('ObjectType')

class ActorType(Generic[ObjectType]):
    pid: int
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = min(max(2, int(cpu_count() * 0.7)), 8)   # min 2, max 8
    MAX_TICK_TIME: ClassVar[int] = 60
    
    def __init__(self, mode: Literal['thread', 'process']='process', **launch_kwargs: LaunchKwargs):
        self.mode = mode
        self.launch_kwargs = launch_kwargs
    
    @classmethod
    def get_running_actors(cls) -> list[int]:
        # returns a list of pids of all running actors of this type
        return [
            proc.pid for proc in ALL_SPAWNED_ACTORS
            if proc.is_running() and proc.status() != 'zombie'
        ]
    
    @classmethod
    def spawn_actor(cls, mode: Literal['thread', 'process']='process', **launch_kwargs: LaunchKwargs) -> int:
        actor = cls(mode=mode, **launch_kwargs)
        # bg_actor_proccess = Process(target=actor.runloop)
        if mode == 'thread':
            bg_actor_thread = Thread(target=actor.runloop)
            bg_actor_thread.start()
            assert bg_actor_thread.native_id is not None
            return bg_actor_thread.native_id
        else:
            bg_actor_process = Process(target=actor.runloop)
            bg_actor_process.start()
            assert bg_actor_process.pid is not None
            ALL_SPAWNED_ACTORS.append(psutil.Process(pid=bg_actor_process.pid))
            return bg_actor_process.pid
    
    @classmethod
    def get_queue(cls) -> QuerySet:
        # return ArchiveResult.objects.filter(status='queued', extractor__in=('pdf', 'dom', 'screenshot'))
        raise NotImplementedError
    
    @classmethod
    def get_next(cls) -> ObjectType | None:
        return cls.get_queue().last()
    
    @classmethod
    def get_actors_to_spawn(cls, queue, running_actors) -> list[LaunchKwargs]:
        actors_to_spawn: list[LaunchKwargs] = []
        max_spawnable = cls.MAX_CONCURRENT_ACTORS - len(running_actors)
        queue_length = queue.count()
        
        if not queue_length:                                           # queue is empty, spawn 0 actors
            return actors_to_spawn
        elif queue_length > 10:                                   # queue is long, spawn as many as possible
            actors_to_spawn += max_spawnable * [{}]
        elif queue_length > 5:                                    # queue is medium, spawn 1 or 2 actors
            actors_to_spawn += min(2, max_spawnable) * [{}]
        else:                                                   # queue is short, spawn 1 actor
            actors_to_spawn += min(1, max_spawnable) * [{}]
        return actors_to_spawn
            
    def on_startup(self):
        if self.mode == 'thread':
            self.pid = get_native_id()
        else:
            self.pid = os.getpid()
        print('Actor on_startup()', f'pid={self.pid}')
        # abx.pm.hook.on_actor_startup(self)
        
    def on_shutdown(self):
        print('Actor on_shutdown()', f'pid={self.pid}')
        # abx.pm.hook.on_actor_shutdown(self)
    
    def runloop(self):
        self.on_startup()
        
        rechecks = 30
        
        while True:
            obj_to_process: ObjectType | None = None
            try:
                obj_to_process = cast(ObjectType, self.get_next())
            except Exception:
                pass
            
            if obj_to_process:
                rechecks = 30
            else:
                if rechecks == 0:
                    break          # stop looping and exit if queue is empty
                else:
                    # print('Actor runloop()', f'pid={self.pid}', 'queue empty, rechecking...')
                    rechecks -= 1
                    time.sleep(1)
                    continue
            
            if not self.lock(obj_to_process):
                continue
            
            # abx.pm.hook.on_actor_tick_start(self, obj_to_process)
            try:
                # timer = TimedProgress(self.MAX_TICK_TIME, prefix='      ')
                
                # run the tick function on the object
                self.tick(obj_to_process)
            except Exception as err:
                # abx.pm.hook.on_actor_tick_exception(self, obj_to_process, err)
                print('ERROR: actor tick failed', err)
                # refresh the db connection
                from django import db
                db.connections.close_all()
            finally:
                # timer.end()
                pass
            # abx.pm.hook.on_actor_tick_end(self, obj_to_process)
        
        self.on_shutdown()
        
    def tick(self, obj: ObjectType) -> None:
        print('Actor Processing tick()', obj)
        
    def lock(self, obj: ObjectType) -> bool:
        print('Actor lock()', obj)
        return True


