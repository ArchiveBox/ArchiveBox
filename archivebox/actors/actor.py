__package__ = 'archivebox.actors'

import os
import time
from typing import ClassVar, Generic, TypeVar, Any, cast, Literal, Type
from django.utils.functional import classproperty

from rich import print
import psutil

from django import db
from django.db import models
from django.db.models import QuerySet
from multiprocessing import Process, cpu_count
from threading import Thread, get_native_id

# from archivebox.logging_util import TimedProgress

ALL_SPAWNED_ACTORS: list[psutil.Process] = []


LaunchKwargs = dict[str, Any]

ModelType = TypeVar('ModelType', bound=models.Model)

class ActorType(Generic[ModelType]):
    pid: int
    idle_count: int = 0
    launch_kwargs: LaunchKwargs = {}
    
    # model_type: Type[ModelType]
    MAX_CONCURRENT_ACTORS: ClassVar[int] = min(max(2, int(cpu_count() * 0.6)), 8)   # min 2, max 8
    MAX_TICK_TIME: ClassVar[int] = 60
    
    def __init__(self, mode: Literal['thread', 'process']='process', **launch_kwargs: LaunchKwargs):
        self.mode = mode
        self.launch_kwargs = launch_kwargs or dict(self.launch_kwargs)
    
    def __repr__(self) -> str:
        label = 'pid' if self.mode == 'process' else 'tid'
        return f'[underline]{self.name}[/underline]\\[{label}={self.pid}]'
    
    def __str__(self) -> str:
        return self.__repr__()
    
    @classproperty
    def name(cls) -> str:
        return cls.__name__  # type: ignore
    
    @classmethod
    def get_running_actors(cls) -> list[int]:
        """returns a list of pids of all running actors of this type"""
        # WARNING: only works for process actors, not thread actors
        return [
            proc.pid for proc in ALL_SPAWNED_ACTORS
            if proc.is_running() and proc.status() != 'zombie'
        ]
        
    @classmethod
    def fork_actor_as_thread(cls, **launch_kwargs: LaunchKwargs) -> int:
        actor = cls(mode='thread', **launch_kwargs)
        bg_actor_thread = Thread(target=actor.runloop)
        bg_actor_thread.start()
        assert bg_actor_thread.native_id is not None
        return bg_actor_thread.native_id
    
    @classmethod
    def fork_actor_as_process(cls, **launch_kwargs: LaunchKwargs) -> int:
        actor = cls(mode='process', **launch_kwargs)
        bg_actor_process = Process(target=actor.runloop)
        bg_actor_process.start()
        assert bg_actor_process.pid is not None
        ALL_SPAWNED_ACTORS.append(psutil.Process(pid=bg_actor_process.pid))
        return bg_actor_process.pid
    
    @classmethod
    def start(cls, mode: Literal['thread', 'process']='process', **launch_kwargs: LaunchKwargs) -> int:
        if mode == 'thread':
            return cls.fork_actor_as_thread(**launch_kwargs)
        elif mode == 'process':
            return cls.fork_actor_as_process(**launch_kwargs)
        raise ValueError(f'Invalid actor mode: {mode}')
    
    @classmethod
    def get_queue(cls) -> QuerySet:
        """override this to provide your queryset as the queue"""
        # return ArchiveResult.objects.filter(status='queued', extractor__in=('pdf', 'dom', 'screenshot'))
        raise NotImplementedError
    
    @classmethod
    def get_next(cls, atomic: bool=True) -> ModelType | None:
        if atomic:
            return cls.get_next_atomic(model=cls.get_queue().model)
        return cls.get_queue().last()
    
    @classmethod
    def get_random(cls, model: Type[ModelType], where='status = "queued"', set='status = "started"', choose_from_top=50) -> ModelType | None:
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        
        with db.connection.cursor() as cursor:
            # subquery gets the pool of the top 50 candidates sorted by sort and order
            # main query selects a random one from that pool
            cursor.execute(f"""
                UPDATE {app_label}_{model_name} 
                SET {set}
                WHERE {where} and id = (
                    SELECT id FROM {app_label}_{model_name}
                    WHERE {where}
                    LIMIT 1
                    OFFSET ABS(RANDOM()) % {choose_from_top}
                )
                RETURNING id;
            """)
            result = cursor.fetchone()
            
            # If no rows were claimed, return None
            if result is None:
                return None

            return model.objects.get(id=result[0])
        
        
    @classmethod
    def get_next_atomic(cls, model: Type[ModelType], where='status = "queued"', set='status = "started"', order_by='created_at DESC', choose_from_top=50) -> ModelType | None:
        """
        atomically claim a random object from the top n=50 objects in the queue by updating status=queued->started
        optimized for minimizing contention on the queue with other actors selecting from the same list
        """
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        
        with db.connection.cursor() as cursor:
            # subquery gets the pool of the top 50 candidates sorted by sort and order
            # main query selects a random one from that pool
            cursor.execute(f"""
                UPDATE {app_label}_{model_name} 
                SET {set}
                WHERE {where} and id = (
                    SELECT id FROM (
                        SELECT id FROM {app_label}_{model_name}
                        WHERE {where}
                        ORDER BY {order_by}
                        LIMIT {choose_from_top}
                    ) candidates
                    ORDER BY RANDOM()
                    LIMIT 1
                )
                RETURNING id;
            """)
            result = cursor.fetchone()
            
            # If no rows were claimed, return None
            if result is None:
                return None
                
            return model.objects.get(id=result[0])
    
    @classmethod
    def get_actors_to_spawn(cls, queue, running_actors) -> list[LaunchKwargs]:
        """Get a list of launch kwargs for the number of actors to spawn based on the queue and currently running actors"""
        actors_to_spawn: list[LaunchKwargs] = []
        max_spawnable = cls.MAX_CONCURRENT_ACTORS - len(running_actors)
        queue_length = queue.count()
        
        # spawning new actors is expensive, avoid spawning all the actors at once. To stagger them,
        # let the next orchestrator tick handle starting another 2 on the next tick()
        # if queue_length > 10:                                   # queue is long, spawn as many as possible
        #   actors_to_spawn += max_spawnable * [{}]
        
        if not queue_length:                                      # queue is empty, spawn 0 actors
            return actors_to_spawn
        elif queue_length > 4:                                    # queue is medium, spawn 1 or 2 actors
            actors_to_spawn += min(2, max_spawnable) * [{**cls.launch_kwargs}]
        else:                                                     # queue is short, spawn 1 actor
            actors_to_spawn += min(1, max_spawnable) * [{**cls.launch_kwargs}]
        return actors_to_spawn

    def on_startup(self):
        if self.mode == 'thread':
            self.pid = get_native_id()  # thread id
            print(f'[green]🏃‍♂️ {self}.on_startup() STARTUP (THREAD)[/green]')
        else:
            self.pid = os.getpid()      # process id
            print(f'[green]🏃‍♂️ {self}.on_startup() STARTUP (PROCESS)[/green]')
        # abx.pm.hook.on_actor_startup(self)
        
    def on_shutdown(self, err: BaseException | None=None):
        print(f'[grey53]🏃‍♂️ {self}.on_shutdown() SHUTTING DOWN[/grey53]', err or '[green](gracefully)[/green]')
        # abx.pm.hook.on_actor_shutdown(self)
        
    def on_tick_start(self, obj: ModelType):
        # print(f'🏃‍♂️ {self}.on_tick_start()', obj.abid or obj.id)
        # abx.pm.hook.on_actor_tick_start(self, obj_to_process)
        # self.timer = TimedProgress(self.MAX_TICK_TIME, prefix='      ')
        pass
    
    def on_tick_end(self, obj: ModelType):
        # print(f'🏃‍♂️ {self}.on_tick_end()', obj.abid or obj.id)
        # abx.pm.hook.on_actor_tick_end(self, obj_to_process)
        # self.timer.end()
        pass
    
    def on_tick_exception(self, obj: ModelType, err: BaseException):
        print(f'[red]🏃‍♂️ {self}.on_tick_exception()[/red]', obj.abid or obj.id, err)
        # abx.pm.hook.on_actor_tick_exception(self, obj_to_process, err)
    
    def runloop(self):
        self.on_startup()
        try:
            while True:
                obj_to_process: ModelType | None = None
                try:
                    obj_to_process = cast(ModelType, self.get_next())
                except Exception:
                    pass
                
                if obj_to_process:
                    self.idle_count = 0
                else:
                    if self.idle_count >= 30:
                        break          # stop looping and exit if queue is empty and we have rechecked it 30 times
                    else:
                        # print('Actor runloop()', f'pid={self.pid}', 'queue empty, rechecking...')
                        self.idle_count += 1
                        time.sleep(1)
                        continue
                
                if not self.lock(obj_to_process):
                    # we are unable to lock the object, some other actor got it first. skip it and get the next object
                    continue
                
                self.on_tick_start(obj_to_process)
                
                try:
                    # run the tick function on the object
                    self.tick(obj_to_process)
                except Exception as err:
                    print(f'[red]🏃‍♂️ ERROR: {self}.tick()[/red]', err)
                    db.connections.close_all()
                    self.on_tick_exception(obj_to_process, err)
                finally:
                    self.on_tick_end(obj_to_process)
            
            self.on_shutdown(err=None)
        except BaseException as err:
            if isinstance(err, KeyboardInterrupt):
                print()
            else:
                print(f'\n[red]🏃‍♂️ {self}.runloop() FATAL:[/red]', err.__class__.__name__, err)
            self.on_shutdown(err=err)

    def tick(self, obj: ModelType) -> None:
        print(f'[blue]🏃‍♂️ {self}.tick()[/blue]', obj.abid or obj.id)
        
    def lock(self, obj: ModelType) -> bool:
        print(f'[blue]🏃‍♂️ {self}.lock()[/blue]', obj.abid or obj.id)
        return True


