__package__ = 'archivebox.actors'

import os
import time
from abc import ABC, abstractmethod
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

LaunchKwargs = dict[str, Any]

ModelType = TypeVar('ModelType', bound=models.Model)

class ActorType(ABC, Generic[ModelType]):
    """
    Base class for all actors. Usage:
    class FaviconActor(ActorType[ArchiveResult]):
        QUERYSET: ClassVar[QuerySet] = ArchiveResult.objects.filter(status='queued', extractor='favicon')
        CLAIM_WHERE: ClassVar[str] = 'status = "queued" AND extractor = "favicon"'
        CLAIM_ORDER: ClassVar[str] = 'created_at DESC'
        ATOMIC: ClassVar[bool] = True

        def claim_sql_set(self, obj: ArchiveResult) -> str:
            # SQL fields to update atomically while claiming an object from the queue
            retry_at = datetime.now() + timedelta(seconds=self.MAX_TICK_TIME)
            return f"status = 'started', locked_by = {self.pid}, retry_at = {retry_at}"

        def tick(self, obj: ArchiveResult) -> None:
            run_favicon_extractor(obj)
            ArchiveResult.objects.filter(pk=obj.pk, status='started').update(status='success')
    """
    pid: int
    idle_count: int = 0
    launch_kwargs: LaunchKwargs = {}
    mode: Literal['thread', 'process'] = 'process'
    
    MAX_CONCURRENT_ACTORS: ClassVar[int] = min(max(2, int(cpu_count() * 0.6)), 8)   # min 2, max 8, up to 60% of available cpu cores
    MAX_TICK_TIME: ClassVar[int] = 60                          # maximum duration in seconds to process a single object
    
    QUERYSET: ClassVar[QuerySet]                      # the QuerySet to claim objects from
    CLAIM_WHERE: ClassVar[str] = 'status = "queued"'  # the WHERE clause to filter the objects when atomically getting the next object from the queue
    CLAIM_SET: ClassVar[str] = 'status = "started"'   # the SET clause to claim the object when atomically getting the next object from the queue
    CLAIM_ORDER: ClassVar[str] = 'created_at DESC'    # the ORDER BY clause to sort the objects with when atomically getting the next object from the queue
    CLAIM_FROM_TOP: ClassVar[int] = MAX_CONCURRENT_ACTORS * 10  # the number of objects to consider when atomically getting the next object from the queue
    ATOMIC: ClassVar[bool] = True                     # whether to atomically fetch+claim the nextobject in one step, or fetch and lock it in two steps
    
    # model_type: Type[ModelType]
    
    _SPAWNED_ACTOR_PIDS: ClassVar[list[psutil.Process]] = []   # record all the pids of Actors spawned by this class
    
    def __init__(self, mode: Literal['thread', 'process']|None=None, **launch_kwargs: LaunchKwargs):
        self.mode = mode or self.mode
        self.launch_kwargs = launch_kwargs or dict(self.launch_kwargs)
    
    @classproperty
    def name(cls) -> str:
        return cls.__name__  # type: ignore
    
    def __str__(self) -> str:
        return self.__repr__()
    
    def __repr__(self) -> str:
        """FaviconActor[pid=1234]"""
        label = 'pid' if self.mode == 'process' else 'tid'
        return f'[underline]{self.name}[/underline]\\[{label}={self.pid}]'
    
    ### Class Methods: Called by Orchestrator on ActorType class before it has been spawned
    
    @classmethod
    def get_running_actors(cls) -> list[int]:
        """returns a list of pids of all running actors of this type"""
        # WARNING: only works for process actors, not thread actors
        if cls.mode == 'thread':
            raise NotImplementedError('get_running_actors() is not implemented for thread actors')
        return [
            proc.pid for proc in cls._SPAWNED_ACTOR_PIDS
            if proc.is_running() and proc.status() != 'zombie'
        ]
        
    @classmethod
    def get_actors_to_spawn(cls, queue: QuerySet, running_actors: list[int]) -> list[LaunchKwargs]:
        """Get a list of launch kwargs for the number of actors to spawn based on the queue and currently running actors"""
        queue_length = queue.count()
        if not queue_length:                                      # queue is empty, spawn 0 actors
            return []
        
        actors_to_spawn: list[LaunchKwargs] = []
        max_spawnable = cls.MAX_CONCURRENT_ACTORS - len(running_actors)
        
        # spawning new actors is expensive, avoid spawning all the actors at once. To stagger them,
        # let the next orchestrator tick handle starting another 2 on the next tick()
        # if queue_length > 10:                                   # queue is long, spawn as many as possible
        #   actors_to_spawn += max_spawnable * [{}]
        
        if queue_length > 4:                                    # queue is medium, spawn 1 or 2 actors
            actors_to_spawn += min(2, max_spawnable) * [{**cls.launch_kwargs}]
        else:                                                     # queue is short, spawn 1 actor
            actors_to_spawn += min(1, max_spawnable) * [{**cls.launch_kwargs}]
        return actors_to_spawn
        
    @classmethod
    def start(cls, mode: Literal['thread', 'process']='process', **launch_kwargs: LaunchKwargs) -> int:
        if mode == 'thread':
            return cls.fork_actor_as_thread(**launch_kwargs)
        elif mode == 'process':
            return cls.fork_actor_as_process(**launch_kwargs)
        raise ValueError(f'Invalid actor mode: {mode} must be "thread" or "process"')
        
    @classmethod
    def fork_actor_as_thread(cls, **launch_kwargs: LaunchKwargs) -> int:
        """Spawn a new background thread running the actor's runloop"""
        actor = cls(mode='thread', **launch_kwargs)
        bg_actor_thread = Thread(target=actor.runloop)
        bg_actor_thread.start()
        assert bg_actor_thread.native_id is not None
        return bg_actor_thread.native_id
    
    @classmethod
    def fork_actor_as_process(cls, **launch_kwargs: LaunchKwargs) -> int:
        """Spawn a new background process running the actor's runloop"""
        actor = cls(mode='process', **launch_kwargs)
        bg_actor_process = Process(target=actor.runloop)
        bg_actor_process.start()
        assert bg_actor_process.pid is not None
        cls._SPAWNED_ACTOR_PIDS.append(psutil.Process(pid=bg_actor_process.pid))
        return bg_actor_process.pid
    
    @classmethod
    def get_model(cls) -> Type[ModelType]:
        # wish this was a @classproperty but Generic[ModelType] return type cant be statically inferred for @classproperty
        return cls.QUERYSET.model
    
    @classmethod
    def get_queue(cls) -> QuerySet:
        """override this to provide your queryset as the queue"""
        # return ArchiveResult.objects.filter(status='queued', extractor__in=('pdf', 'dom', 'screenshot'))
        return cls.QUERYSET
    
    ### Instance Methods: Called by Actor after it has been spawned (i.e. forked as a thread or process)
    
    def runloop(self):
        """The main runloop that starts running when the actor is spawned (as subprocess or thread) and exits when the queue is empty"""
        self.on_startup()
        try:
            while True:
                obj_to_process: ModelType | None = None
                try:
                    obj_to_process = cast(ModelType, self.get_next(atomic=self.atomic))
                except Exception:
                    pass
                
                if obj_to_process:
                    self.idle_count = 0   # reset idle count if we got an object
                else:
                    if self.idle_count >= 30:
                        break             # stop looping and exit if queue is empty and we have idled for 30sec
                    else:
                        # print('Actor runloop()', f'pid={self.pid}', 'queue empty, rechecking...')
                        self.idle_count += 1
                        time.sleep(1)
                        continue
                
                self.on_tick_start(obj_to_process)
                
                # Process the object
                try:
                    self.tick(obj_to_process)
                except Exception as err:
                    print(f'[red]🏃‍♂️ ERROR: {self}.tick()[/red]', err)
                    db.connections.close_all()                         # always reset the db connection after an exception to clear any pending transactions
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
    
    def get_next(self, atomic: bool | None=None) -> ModelType | None:
        """get the next object from the queue, atomically locking it if self.atomic=True"""
        if atomic is None:
            atomic = self.ATOMIC

        if atomic:
            # fetch and claim the next object from in the queue in one go atomically
            obj = self.get_next_atomic()
        else:
            # two-step claim: fetch the next object and lock it in a separate query
            obj = self.get_queue().last()
            assert obj and self.lock_next(obj), f'Unable to fetch+lock the next {self.get_model().__name__} ojbect from {self}.QUEUE'
        return obj
    
    def lock_next(self, obj: ModelType) -> bool:
        """override this to implement a custom two-step (non-atomic)lock mechanism"""
        # For example:
        # assert obj._model.objects.filter(pk=obj.pk, status='queued').update(status='started', locked_by=self.pid)
        # Not needed if using get_next_and_lock() to claim the object atomically
        # print(f'[blue]🏃‍♂️ {self}.lock()[/blue]', obj.abid or obj.id)
        return True
    
    def claim_sql_where(self) -> str:
        """override this to implement a custom WHERE clause for the atomic claim step e.g. "status = 'queued' AND locked_by = NULL" """
        return self.CLAIM_WHERE
    
    def claim_sql_set(self) -> str:
        """override this to implement a custom SET clause for the atomic claim step e.g. "status = 'started' AND locked_by = {self.pid}" """
        return self.CLAIM_SET
    
    def claim_sql_order(self) -> str:
        """override this to implement a custom ORDER BY clause for the atomic claim step e.g. "created_at DESC" """
        return self.CLAIM_ORDER
    
    def claim_from_top(self) -> int:
        """override this to implement a custom number of objects to consider when atomically claiming the next object from the top of the queue"""
        return self.CLAIM_FROM_TOP
        
    def get_next_atomic(self, shallow: bool=True) -> ModelType | None:
        """
        claim a random object from the top n=50 objects in the queue (atomically updates status=queued->started for claimed object)
        optimized for minimizing contention on the queue with other actors selecting from the same list
        slightly faster than claim_any_obj() which selects randomly from the entire queue but needs to know the total count
        """
        Model = self.get_model()                                     # e.g. ArchiveResult
        table = f'{Model._meta.app_label}_{Model._meta.model_name}'  # e.g. core_archiveresult
        
        where_sql = self.claim_sql_where()
        set_sql = self.claim_sql_set()
        order_by_sql = self.claim_sql_order()
        choose_from_top = self.claim_from_top()
        
        with db.connection.cursor() as cursor:
            # subquery gets the pool of the top 50 candidates sorted by sort and order
            # main query selects a random one from that pool
            cursor.execute(f"""
                UPDATE {table} 
                SET {set_sql}
                WHERE {where_sql} and id = (
                    SELECT id FROM (
                        SELECT id FROM {table}
                        WHERE {where_sql}
                        ORDER BY {order_by_sql}
                        LIMIT {choose_from_top}
                    ) candidates
                    ORDER BY RANDOM()
                    LIMIT 1
                )
                RETURNING id;
            """)
            result = cursor.fetchone()
            
            if result is None:
                return None           # If no rows were claimed, return None

            if shallow:
                # shallow: faster, returns potentially incomplete object instance missing some django auto-populated fields:
                columns = [col[0] for col in cursor.description or ['id']]
                return Model(**dict(zip(columns, result)))

            # if not shallow do one extra query to get a more complete object instance (load it fully from scratch)
            return Model.objects.get(id=result[0])

    @abstractmethod
    def tick(self, obj: ModelType) -> None:
        """override this to process the object"""
        print(f'[blue]🏃‍♂️ {self}.tick()[/blue]', obj.abid or obj.id)
        # For example:
        # do_some_task(obj)
        # do_something_else(obj)
        # obj._model.objects.filter(pk=obj.pk, status='started').update(status='success')
        raise NotImplementedError('tick() must be implemented by the Actor subclass')
    
    def on_startup(self) -> None:
        if self.mode == 'thread':
            self.pid = get_native_id()  # thread id
            print(f'[green]🏃‍♂️ {self}.on_startup() STARTUP (THREAD)[/green]')
        else:
            self.pid = os.getpid()      # process id
            print(f'[green]🏃‍♂️ {self}.on_startup() STARTUP (PROCESS)[/green]')
        # abx.pm.hook.on_actor_startup(self)
        
    def on_shutdown(self, err: BaseException | None=None) -> None:
        print(f'[grey53]🏃‍♂️ {self}.on_shutdown() SHUTTING DOWN[/grey53]', err or '[green](gracefully)[/green]')
        # abx.pm.hook.on_actor_shutdown(self)
        
    def on_tick_start(self, obj: ModelType) -> None:
        # print(f'🏃‍♂️ {self}.on_tick_start()', obj.abid or obj.id)
        # abx.pm.hook.on_actor_tick_start(self, obj_to_process)
        # self.timer = TimedProgress(self.MAX_TICK_TIME, prefix='      ')
        pass
    
    def on_tick_end(self, obj: ModelType) -> None:
        # print(f'🏃‍♂️ {self}.on_tick_end()', obj.abid or obj.id)
        # abx.pm.hook.on_actor_tick_end(self, obj_to_process)
        # self.timer.end()
        pass
    
    def on_tick_exception(self, obj: ModelType, err: BaseException) -> None:
        print(f'[red]🏃‍♂️ {self}.on_tick_exception()[/red]', obj.abid or obj.id, err)
        # abx.pm.hook.on_actor_tick_exception(self, obj_to_process, err)
