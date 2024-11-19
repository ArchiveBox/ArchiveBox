__package__ = 'archivebox.workers'

import os
import time
import traceback
from typing import ClassVar, Generic, TypeVar, Any, Literal, Type, Iterable, cast, get_args
from datetime import timedelta
import multiprocessing
from multiprocessing import Process, cpu_count

import psutil
from rich import print
from statemachine import State, StateMachine

from django import db
from django.db.models import QuerySet, sql, Q
from django.db.models import Model as DjangoModel
from django.utils import timezone
from django.utils.functional import classproperty

# from archivebox.logging_util import TimedProgress

from .models import ModelWithStateMachine


multiprocessing.set_start_method('fork', force=True)


class ActorObjectAlreadyClaimed(Exception):
    """Raised when the Actor tries to claim the next object from the queue but it's already been claimed by another Actor"""
    pass

class ActorQueueIsEmpty(Exception):
    """Raised when the Actor tries to get the next object from the queue but it's empty"""
    pass

CPU_COUNT = cpu_count()
DEFAULT_MAX_TICK_TIME = 60
DEFAULT_MAX_CONCURRENT_ACTORS = min(max(2, int(CPU_COUNT * 0.6)), 8)   # 2 < (60% * num available cpu cores) < 8

limit = lambda n, max: min(n, max)

LaunchKwargs = dict[str, Any]
ObjectState = State | str
ObjectStateList = Iterable[ObjectState]

ModelType = TypeVar('ModelType', bound=ModelWithStateMachine)

class ActorType(Generic[ModelType]):
    """
    Base class for all actors. Usage:
    
    class FaviconActor(ActorType[FaviconArchiveResult]):
        ACTIVE_STATE: ClassVar[str] = 'started'
        
        @classmethod
        def qs(cls) -> QuerySet[FaviconArchiveResult]:
            return ArchiveResult.objects.filter(extractor='favicon')   # or leave the default: FaviconArchiveResult.objects.all()
    """
    
    ### Class attributes (defined on the class at compile-time when ActorType[MyModel] is defined)
    Model: Type[ModelType]
    StateMachineClass: Type[StateMachine]
    
    ACTIVE_STATE: ClassVar[ObjectState] = 'started'
    EVENT_NAME: ClassVar[str] = 'tick'                                    # the event name to trigger on the obj.sm: StateMachine (usually 'tick')
    
    CLAIM_ORDER: ClassVar[tuple[str, ...]] = ('-retry_at',)                # the .order(*args) to claim the queue objects in, use ('?',) for random order
    CLAIM_FROM_TOP_N: ClassVar[int] = CPU_COUNT * 10                      # the number of objects to consider when atomically getting the next object from the queue
    CLAIM_ATOMIC: ClassVar[bool] = True                                   # whether to atomically fetch+claim the next object in one query, or fetch and lock it in two queries
    
    MAX_TICK_TIME: ClassVar[int] = DEFAULT_MAX_TICK_TIME                  # maximum duration in seconds to process a single object
    MAX_CONCURRENT_ACTORS: ClassVar[int] = DEFAULT_MAX_CONCURRENT_ACTORS  # maximum number of concurrent actors that can be running at once
    
    _SPAWNED_ACTOR_PIDS: ClassVar[list[psutil.Process]] = []      # used to record all the pids of Actors spawned on the class
    
    ### Instance attributes (only used within an actor instance inside a spawned actor thread/process)
    pid: int = os.getpid()
    idle_count: int = 0
    launch_kwargs: LaunchKwargs = {}
    mode: Literal['thread', 'process'] = 'process'
    
    def __init_subclass__(cls) -> None:
        """
        Executed at class definition time (i.e. during import of any file containing class MyActor(ActorType[MyModel]): ...).
        Loads the django Model from the Generic[ModelType] TypeVar arg and populates any missing class-level config using it.
        """
        if getattr(cls, 'Model', None) is None:
            cls.Model = cls._get_model_from_generic_typevar()
        cls._populate_missing_classvars_from_model(cls.Model)
    
    def __init__(self, mode: Literal['thread', 'process']|None=None, **launch_kwargs: LaunchKwargs):
        """
        Executed right before the Actor is spawned to create a unique Actor instance for that thread/process.
        actor_instance.runloop() is then executed from inside the newly spawned thread/process.
        """
        self.mode = mode or self.mode
        self.launch_kwargs = launch_kwargs or dict(self.launch_kwargs)
    

    ### Private Helper Methods: Not desiged to be overridden by subclasses or called by anything outside of this class
    
    @classproperty
    def name(cls) -> str:
        return cls.__name__  # type: ignore
    
    def __str__(self) -> str:
        return repr(self)
    
    def __repr__(self) -> str:
        """-> FaviconActor[pid=1234]"""
        label = 'pid' if self.mode == 'process' else 'tid'
        # return f'[underline]{self.name}[/underline]\\[{label}={self.pid}]'
        return f'[underline]Worker[/underline]\\[{label}={self.pid}]'
    
    @staticmethod
    def _state_to_str(state: ObjectState) -> str:
        """Convert a statemachine.State, models.TextChoices.choices value, or Enum value to a str"""
        return str(state.value) if isinstance(state, State) else str(state)
    
    @staticmethod
    def _sql_for_select_top_n_candidates(qs: QuerySet, claim_from_top_n: int=CLAIM_FROM_TOP_N) -> tuple[str, tuple[Any, ...]]:
        """Get the SQL for selecting the top N candidates from the queue (to claim one from)"""
        queryset = qs.only('id')[:claim_from_top_n]
        select_sql, select_params = compile_sql_select(queryset)
        return select_sql, select_params
    
    @staticmethod
    def _sql_for_update_claimed_obj(qs: QuerySet, update_kwargs: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
        """Get the SQL for updating a claimed object to mark it as ACTIVE"""
        # qs.update(status='started', retry_at=<now + MAX_TICK_TIME>)
        update_sql, update_params = compile_sql_update(qs, update_kwargs=update_kwargs)
        # e.g. UPDATE core_archiveresult SET status='%s', retry_at='%s' WHERE status NOT IN ('succeeded', 'failed', 'sealed', 'started') AND retry_at <= '2024-11-04 10:14:33.240903'
        return update_sql, update_params
    
    @classmethod
    def _get_model_from_generic_typevar(cls) -> Type[ModelType]:
        """Get the django Model from the Generic[ModelType] TypeVar arg (and check that it inherits from django.db.models.Model)"""
        # cls.__orig_bases__ is non-standard and may be removed in the future! if this breaks,
        # we can just require the inerited class to define the Model as a classvar manually, e.g.:
        #     class SnapshotActor(ActorType[Snapshot]):
        #         Model: ClassVar[Type[Snapshot]] = Snapshot
        # https://stackoverflow.com/questions/57706180/generict-base-class-how-to-get-type-of-t-from-within-instance
        Model = get_args(cls.__orig_bases__[0])[0]   # type: ignore
        assert issubclass(Model, DjangoModel), f'{cls.__name__}.Model must be a valid django Model'
        return cast(Type[ModelType], Model)
    

    @classmethod
    def _get_state_machine_instance(cls, obj: ModelType) -> StateMachine:
        """Get the StateMachine instance for the given django Model instance (and check that it is a valid instance of cls.StateMachineClass)"""
        obj_statemachine = None
        state_machine_attr = getattr(obj, 'state_machine_attr', 'sm')
        try:
            obj_statemachine = getattr(obj, state_machine_attr)
        except Exception:
            pass
        
        if not isinstance(obj_statemachine, cls.StateMachineClass):
            raise Exception(f'{cls.__name__}: Failed to find a valid StateMachine instance at {type(obj).__name__}.{state_machine_attr}')
            
        return obj_statemachine
    
    @classmethod
    def _populate_missing_classvars_from_model(cls, Model: Type[ModelType]):
        """Check that the class variables are set correctly based on the ModelType"""
        
        # check that Model is the same as the Generic[ModelType] parameter in the class definition
        cls.Model = getattr(cls, 'Model', None) or Model
        if cls.Model != Model:
            raise ValueError(f'{cls.__name__}.Model must be set to the same Model as the Generic[ModelType] parameter in the class definition')
        
        # check that Model has a valid StateMachine with the required event defined on it
        cls.StateMachineClass = getattr(cls, 'StateMachineClass', None)      # type: ignore
        assert isinstance(cls.EVENT_NAME, str), f'{cls.__name__}.EVENT_NAME must be a str, got: {type(cls.EVENT_NAME).__name__} instead'
        assert hasattr(cls.StateMachineClass, cls.EVENT_NAME), f'StateMachine {cls.StateMachineClass.__name__} must define a {cls.EVENT_NAME} event ({cls.__name__}.EVENT_NAME = {cls.EVENT_NAME})'
        
        # check that Model uses .id as its primary key field
        primary_key_field = cls.Model._meta.pk.name
        if primary_key_field != 'id':
            raise NotImplementedError(f'Actors currently only support models that use .id as their primary key field ({cls.__name__} uses {cls.__name__}.{primary_key_field} as primary key)')
        
        # check that ACTIVE_STATE is defined and that it exists on the StateMachineClass
        if not getattr(cls, 'ACTIVE_STATE', None):
            raise NotImplementedError(f'{cls.__name__} must define an ACTIVE_STATE: ClassVar[State] (e.g. SnapshotMachine.started) ({cls.Model.__name__}.{cls.Model.state_field_name} gets set to this value to mark objects as actively processing)')
        assert isinstance(cls.ACTIVE_STATE, (State, str)) and hasattr(cls.StateMachineClass, cls._state_to_str(cls.ACTIVE_STATE)), f'{cls.__name__}.ACTIVE_STATE must be a statemachine.State | str that exists on {cls.StateMachineClass.__name__}, got: {type(cls.ACTIVE_STATE).__name__} instead'
        
        # check the other ClassVar attributes for valid values
        assert cls.CLAIM_ORDER and isinstance(cls.CLAIM_ORDER, tuple) and all(isinstance(order, str) for order in cls.CLAIM_ORDER), f'{cls.__name__}.CLAIM_ORDER must be a non-empty tuple[str, ...], got: {type(cls.CLAIM_ORDER).__name__} instead'
        assert cls.CLAIM_FROM_TOP_N > 0, f'{cls.__name__}.CLAIM_FROM_TOP_N must be a positive int, got: {cls.CLAIM_FROM_TOP_N} instead'
        assert cls.MAX_TICK_TIME >= 1, f'{cls.__name__}.MAX_TICK_TIME must be a positive int > 1, got: {cls.MAX_TICK_TIME} instead'
        assert cls.MAX_CONCURRENT_ACTORS >= 1, f'{cls.__name__}.MAX_CONCURRENT_ACTORS must be a positive int >=1, got: {cls.MAX_CONCURRENT_ACTORS} instead'
        assert isinstance(cls.CLAIM_ATOMIC, bool), f'{cls.__name__}.CLAIM_ATOMIC must be a bool, got: {cls.CLAIM_ATOMIC} instead'

    # @classmethod
    # def _fork_actor_as_thread(cls, **launch_kwargs: LaunchKwargs) -> int:
    #     """Spawn a new background thread running the actor's runloop"""
    #     actor = cls(mode='thread', **launch_kwargs)
    #     bg_actor_thread = Thread(target=actor.runloop)
    #     bg_actor_thread.start()
    #     assert bg_actor_thread.native_id is not None
    #     return bg_actor_thread.native_id
    
    @classmethod
    def _fork_actor_as_process(cls, **launch_kwargs: LaunchKwargs) -> int:
        """Spawn a new background process running the actor's runloop"""
        actor = cls(mode='process', **launch_kwargs)
        bg_actor_process = Process(target=actor.runloop)
        bg_actor_process.start()
        assert bg_actor_process.pid is not None
        cls._SPAWNED_ACTOR_PIDS.append(psutil.Process(pid=bg_actor_process.pid))
        return bg_actor_process.pid
    
    @classmethod
    def _obj_repr(cls, obj: ModelType | Any) -> str:
        """Get a string representation of the given django Model instance"""
        return f'[grey53]{type(obj).__name__}\\[{obj.ABID}][/grey53]'
    
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
        
        # WARNING:
        # spawning new actors processes is slow/expensive, avoid spawning many actors at once in a single orchestrator tick.
        # limit to spawning 1 or 2 at a time per orchestrator tick, and let the next tick handle starting another couple.
        # DONT DO THIS:
        # if queue_length > 20:                      # queue is extremely long, spawn maximum actors at once!
        #   num_to_spawn_this_tick = cls.MAX_CONCURRENT_ACTORS
        
        if queue_length > 10:    
            num_to_spawn_this_tick = 2  # spawn more actors per tick if queue is long
        else:
            num_to_spawn_this_tick = 1  # spawn fewer actors per tick if queue is short
        
        num_remaining = cls.MAX_CONCURRENT_ACTORS - len(running_actors)
        num_to_spawn_now: int = limit(num_to_spawn_this_tick, num_remaining)
        
        actors_launch_kwargs: list[LaunchKwargs] = num_to_spawn_now * [{**cls.launch_kwargs}]
        return actors_launch_kwargs
        
    @classmethod
    def start(cls, mode: Literal['thread', 'process']='process', **launch_kwargs: LaunchKwargs) -> int:
        if mode == 'thread':
            raise NotImplementedError('Thread-based actors are disabled to reduce codebase complexity. Please use processes for everything')
            # return cls._fork_actor_as_thread(**launch_kwargs)
        elif mode == 'process':
            return cls._fork_actor_as_process(**launch_kwargs)
        raise ValueError(f'Invalid actor mode: {mode} must be "thread" or "process"')
    
    @classproperty
    def qs(cls) -> QuerySet[ModelType]:
        """
        Get the unfiltered and unsorted QuerySet of all objects that this Actor might care about.
        Override this in the subclass to define the QuerySet of objects that the Actor is going to poll for new work.
        (don't limit, order, or filter this by retry_at or status yet, Actor.get_queue() handles that part)
        """
        return cls.Model.objects.filter()
    
    @classproperty
    def final_q(cls) -> Q:
        """Get the filter for objects that are already completed / in a final state"""
        return Q(**{
            f'{cls.Model.state_field_name}__in': [cls._state_to_str(s) for s in cls.StateMachineClass.final_states],
        })  # status__in=('sealed', 'failed', 'succeeded')
    
    @classproperty
    def active_q(cls) -> Q:
        """Get the filter for objects that are marked active (and are still running / not timed out)"""
        return Q(retry_at__gte=timezone.now(), **{cls.Model.state_field_name: cls._state_to_str(cls.ACTIVE_STATE)})   # e.g. Q(status='started')
    
    @classproperty
    def stalled_q(cls) -> Q:
        """Get the filter for objects that are marked active but are timed out"""
        return Q(retry_at__lte=timezone.now(), **{cls.Model.state_field_name: cls._state_to_str(cls.ACTIVE_STATE)})                     # e.g. Q(status='started') AND Q(<retry_at is in the past>)
    
    @classproperty
    def future_q(cls) -> Q:
        """Get the filter for objects that have a retry_at in the future"""
        return Q(retry_at__gt=timezone.now(), **{cls.Model.state_field_name: 'QUEUED'})
    
    @classproperty
    def pending_q(cls) -> Q:
        """Get the filter for objects that are ready for processing."""
        return ~Q(**{
            f'{cls.Model.state_field_name}__in': (*[cls._state_to_str(s) for s in cls.StateMachineClass.final_states], cls._state_to_str(cls.ACTIVE_STATE))
        })  # status__not_in=('sealed', 'failed', 'succeeded', 'started')
    
    @classmethod
    def get_queue(cls, sort: bool=True) -> QuerySet[ModelType]:
        """
        Get the sorted and filtered QuerySet of objects that are ready for processing.
        e.g. qs.exclude(status__in=('sealed', 'started'), retry_at__gt=timezone.now()).order_by('retry_at')
        """
        unsorted_qs = cls.qs.filter(cls.pending_q) | cls.qs.filter(cls.stalled_q)
        return unsorted_qs.order_by(*cls.CLAIM_ORDER) if sort else unsorted_qs

    ### Instance Methods: Only called from within Actor instance after it has been spawned (i.e. forked as a thread or process)
    
    def runloop(self):
        """The main runloop that starts running when the actor is spawned (as subprocess or thread) and exits when the queue is empty"""
        self.on_startup()
        obj_to_process: ModelType | None = None
        last_error: BaseException | None = None
        try:
            while True:
                # Get the next object to process from the queue
                try:
                    obj_to_process = cast(ModelType, self.get_next(atomic=self.CLAIM_ATOMIC))
                except (ActorQueueIsEmpty, ActorObjectAlreadyClaimed) as err:
                    last_error = err
                    obj_to_process = None
                
                # Handle the case where there is no next object to process
                if obj_to_process:
                    self.idle_count = 0   # reset idle count if we got an object
                else:
                    if self.idle_count >= 3:
                        break             # stop looping and exit if queue is empty and we have idled for 30sec
                    else:
                        # print('Actor runloop()', f'pid={self.pid}', 'queue empty, rechecking...')
                        self.idle_count += 1
                        time.sleep(1)
                        continue
                
                # Process the object by triggering its StateMachine.tick() method
                self.on_tick_start(obj_to_process)
                try:
                    self.tick(obj_to_process)
                except Exception as err:
                    last_error = err
                    print(f'[red]{self._obj_repr(obj_to_process)} 🏃‍♂️ {self}.tick()[/red] ERROR: [red]{type(err).__name__}: {err}[/red]')
                    db.connections.close_all()                         # always reset the db connection after an exception to clear any pending transactions
                    self.on_tick_exception(obj_to_process, err)
                    traceback.print_exc()
                finally:
                    self.on_tick_end(obj_to_process)

        except BaseException as err:
            last_error = err
            if isinstance(err, KeyboardInterrupt):
                print()
            else:
                print(f'\n[red]{self._obj_repr(obj_to_process)} 🏃‍♂️ {self}.runloop() FATAL:[/red] {type(err).__name__}: {err}')
                print(f'    Last processed object: {obj_to_process}')
                raise
        finally:
            self.on_shutdown(last_obj=obj_to_process, last_error=last_error)
    
    @classmethod
    def get_update_kwargs_to_claim_obj(cls) -> dict[str, Any]:
        """
        Get the field values needed to mark an pending obj_to_process as being actively processing (aka claimed)
        by the current Actor. returned kwargs will be applied using: qs.filter(id=obj_to_process.id).update(**kwargs).
        F() expressions are allowed in field values if you need to update a field based on its current value.
        Can be a defined as a normal method (instead of classmethod) on subclasses if it needs to access instance vars.
        """
        return {
            # cls.Model.state_field_name: cls._state_to_str(cls.ACTIVE_STATE),   # do this manually in the state machine enter hooks
            'retry_at': timezone.now() + timedelta(seconds=cls.MAX_TICK_TIME),
        }
    
    def get_next(self, atomic: bool | None=None) -> ModelType | None:
        """get the next object from the queue, atomically locking it if self.CLAIM_ATOMIC=True"""
        atomic = self.CLAIM_ATOMIC if atomic is None else atomic
        if atomic:
            # fetch and claim the next object from in the queue in one go atomically
            obj = self.get_next_atomic()
        else:
            # two-step claim: fetch the next object and lock it in a separate query
            obj = self.get_next_non_atomic()
        return obj
    
    def get_next_non_atomic(self) -> ModelType:
        """
        Naiively selects the top/first object from self.get_queue().order_by(*self.CLAIM_ORDER),
        then claims it by running .update(status='started', retry_at=<now + MAX_TICK_TIME>).
        
        Do not use this method if there is more than one Actor racing to get objects from the same queue,
        it will be slow/buggy as they'll compete to lock the same object at the same time (TOCTTOU race).
        """
        obj = self.get_queue().first()
        if obj is None:
            raise ActorQueueIsEmpty(f'No next object available in {self}.get_queue()')
        
        locked = self.get_queue().filter(id=obj.id).update(**self.get_update_kwargs_to_claim_obj())
        if not locked:
            raise ActorObjectAlreadyClaimed(f'Unable to lock the next {self.Model.__name__} object from {self}.get_queue().first()')
        return obj
        
    def get_next_atomic(self) -> ModelType | None:
        """
        Selects the top n=50 objects from the queue and atomically claims a random one from that set.
        This approach safely minimizes contention with other Actors trying to select from the same Queue.

        The atomic query is roughly equivalent to the following:  (all done in one SQL query to avoid a TOCTTOU race)
            top_candidates are selected from:   qs.order_by(*CLAIM_ORDER).only('id')[:CLAIM_FROM_TOP_N]
            a single candidate is chosen using: qs.filter(id__in=top_n_candidates).order_by('?').first()
            the chosen obj is claimed using:    qs.filter(id=chosen_obj).update(status=ACTIVE_STATE, retry_at=<now + MAX_TICK_TIME>)
        """
        # TODO: if we switch from SQLite to PostgreSQL in the future, we should change this
        # to use SELECT FOR UPDATE instead of a subquery + ORDER BY RANDOM() LIMIT 1
        
        # e.g. SELECT id FROM core_archiveresult WHERE status NOT IN (...) AND retry_at <= '...' ORDER BY retry_at ASC LIMIT 50
        qs = self.get_queue()
        select_top_canidates_sql, select_params = self._sql_for_select_top_n_candidates(qs=qs)
        assert select_top_canidates_sql.startswith('SELECT ')
        
        # e.g. UPDATE core_archiveresult SET status='%s', retry_at='%s' WHERE status NOT IN (...) AND retry_at <= '...'
        update_claimed_obj_sql, update_params = self._sql_for_update_claimed_obj(qs=self.qs.all(), update_kwargs=self.get_update_kwargs_to_claim_obj())
        assert update_claimed_obj_sql.startswith('UPDATE ') and 'WHERE' not in update_claimed_obj_sql
        db_table = self.Model._meta.db_table  # e.g. core_archiveresult
        
        # subquery gets the pool of the top candidates e.g. self.get_queue().only('id')[:CLAIM_FROM_TOP_N]
        # main query selects a random one from that pool, and claims it using .update(status=ACTIVE_STATE, retry_at=<now + MAX_TICK_TIME>)
        # this is all done in one atomic SQL query to avoid TOCTTOU race conditions (as much as possible)
        atomic_select_and_update_sql = f"""
            with top_candidates AS ({select_top_canidates_sql})
            {update_claimed_obj_sql}
            WHERE "{db_table}"."id" IN (
                SELECT id FROM top_candidates
                ORDER BY RANDOM()
                LIMIT 1
            )
            RETURNING *;
        """
        
        # import ipdb; ipdb.set_trace()

        try:
            updated = qs.raw(atomic_select_and_update_sql, (*select_params, *update_params))
            assert len(updated) <= 1, f'Expected to claim at most 1 object, but Django modified {len(updated)} objects!'
            return updated[0]
        except IndexError:
            if self.get_queue().exists():
                raise ActorObjectAlreadyClaimed(f'Unable to lock the next {self.Model.__name__} object from {self}.get_queue().first()')
            else:
                raise ActorQueueIsEmpty(f'No next object available in {self}.get_queue()')

    def tick(self, obj_to_process: ModelType) -> None:
        """Call the object.sm.tick() method to process the object"""
        print(f'\n[grey53]{self._obj_repr(obj_to_process)} 🏃‍♂️ {self}.tick()[/grey53] [blue]{obj_to_process.status.upper()}[/blue] ➡️ ...  +{(obj_to_process.retry_at - timezone.now()).total_seconds() if obj_to_process.retry_at else "-"}s')
        
        # get the StateMachine instance from the object
        obj_statemachine = self._get_state_machine_instance(obj_to_process)
        starting_state = obj_statemachine.current_state
        
        # trigger the event on the StateMachine instance
        obj_tick_method = getattr(obj_statemachine, self.EVENT_NAME)  # e.g. obj_statemachine.tick()
        obj_tick_method()
        
        ending_state = obj_statemachine.current_state
        if starting_state != ending_state:
            self.on_state_change(obj_to_process, starting_state, ending_state)
        
        # save the object to persist any state changes
        obj_to_process.save()
        
    def on_startup(self) -> None:
        if self.mode == 'thread':
            # self.pid = get_native_id()  # thread id
            print(f'[green]🏃‍♂️ {self}.on_startup() STARTUP (THREAD)[/green]')
            raise NotImplementedError('Thread-based actors are disabled to reduce codebase complexity. Please use processes for everything')
        else:
            self.pid = os.getpid()      # process id
            print(f'[green]🏃‍♂️ {self}.on_startup() STARTUP (PROCESS)[/green]')
        # abx.pm.hook.on_actor_startup(actor=self)
        
    def on_shutdown(self, last_obj: ModelType | None=None, last_error: BaseException | None=None) -> None:
        # if isinstance(last_error, KeyboardInterrupt) or last_error is None:
        #     last_error_str = '[green](CTRL-C)[/green]'
        # elif isinstance(last_error, ActorQueueIsEmpty):
        #     last_error_str = '[green](queue empty)[/green]'
        # elif isinstance(last_error, ActorObjectAlreadyClaimed):
        #     last_error_str = '[green](queue race)[/green]'
        # else:
        #     last_error_str = f'[red]{type(last_error).__name__}: {last_error}[/red]'

        # print(f'[grey53]🏃‍♂️ {self}.on_shutdown() SHUTTING DOWN[/grey53] {last_error_str}')
        # abx.pm.hook.on_actor_shutdown(actor=self, last_obj=last_obj, last_error=last_error)
        pass
        
    def on_tick_start(self, obj_to_process: ModelType) -> None:
        # print(f'🏃‍♂️ {self}.on_tick_start() {obj_to_process.ABID} {obj_to_process.status} {obj_to_process.retry_at}')
        # abx.pm.hook.on_actor_tick_start(actor=self, obj_to_process=obj)
        # self.timer = TimedProgress(self.MAX_TICK_TIME, prefix='      ')
        pass
    
    def on_tick_end(self, obj_to_process: ModelType) -> None:
        # print(f'🏃‍♂️ {self}.on_tick_end() {obj_to_process.ABID} {obj_to_process.status} {obj_to_process.retry_at}')
        # abx.pm.hook.on_actor_tick_end(actor=self, obj_to_process=obj_to_process)
        # self.timer.end()
        pass
        
        # import ipdb; ipdb.set_trace()

    
    def on_tick_exception(self, obj_to_process: ModelType, error: Exception) -> None:
        print(f'[red]{self._obj_repr(obj_to_process)} 🏃‍♂️ {self}.on_tick_exception()[/red] [blue]{obj_to_process.status}[/blue] +{(obj_to_process.retry_at - timezone.now()).total_seconds() if obj_to_process.retry_at else "-"}s: [red]{type(error).__name__}: {error}[/red]')
        # abx.pm.hook.on_actor_tick_exception(actor=self, obj_to_process=obj_to_process, error=error)

    def on_state_change(self, obj_to_process: ModelType, starting_state, ending_state) -> None:
        print(f'[blue]{self._obj_repr(obj_to_process)} 🏃‍♂️ {self}.on_state_change() {starting_state} ➡️ {ending_state}[/blue] +{(obj_to_process.retry_at - timezone.now()).total_seconds() if obj_to_process.retry_at else "-"}s')
        # abx.pm.hook.on_actor_state_change(actor=self, obj_to_process=obj_to_process, starting_state=starting_state, ending_state=ending_state)


def compile_sql_select(queryset: QuerySet, filter_kwargs: dict[str, Any] | None=None, order_args: tuple[str, ...]=(), limit: int | None=None) -> tuple[str, tuple[Any, ...]]:
    """
    Compute the SELECT query SQL for a queryset.filter(**filter_kwargs).order_by(*order_args)[:limit] call
    Returns a tuple of (sql, params) where sql is a template string containing %s (unquoted) placeholders for the params
    
    WARNING:
    final_sql = sql % params  DOES NOT WORK to assemble the final SQL string because the %s placeholders are not quoted/escaped
    they should always passed separately to the DB driver so it can do its own quoting/escaping to avoid SQL injection and syntax errors
    """
    assert isinstance(queryset, QuerySet), f'compile_sql_select(...) first argument must be a QuerySet, got: {type(queryset).__name__} instead'
    assert filter_kwargs is None or isinstance(filter_kwargs, dict), f'compile_sql_select(...) filter_kwargs argument must be a dict[str, Any], got: {type(filter_kwargs).__name__} instead'
    assert isinstance(order_args, tuple) and all(isinstance(arg, str) for arg in order_args), f'compile_sql_select(...) order_args argument must be a tuple[str, ...] got: {type(order_args).__name__} instead'
    assert limit is None or isinstance(limit, int), f'compile_sql_select(...) limit argument must be an int, got: {type(limit).__name__} instead'
    
    queryset = queryset._chain()                      # type: ignore   # copy queryset to avoid modifying the original
    if filter_kwargs:
        queryset = queryset.filter(**filter_kwargs)
    if order_args:
        queryset = queryset.order_by(*order_args)
    if limit is not None:
        queryset = queryset[:limit]
    query = queryset.query
    
    # e.g. SELECT id FROM core_archiveresult WHERE status NOT IN (%s, %s, %s) AND retry_at <= %s ORDER BY retry_at ASC LIMIT 50
    select_sql, select_params = query.get_compiler(queryset.db).as_sql()
    return select_sql, select_params


def compile_sql_update(queryset: QuerySet, update_kwargs: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """
    Compute the UPDATE query SQL for a queryset.filter(**filter_kwargs).update(**update_kwargs) call
    Returns a tuple of (sql, params) where sql is a template string containing %s (unquoted) placeholders for the params
    
    Based on the django.db.models.QuerySet.update() source code, but modified to return the SQL instead of executing the update
    https://github.com/django/django/blob/611bf6c2e2a1b4ab93273980c45150c099ab146d/django/db/models/query.py#L1217
    
    WARNING:
    final_sql = sql % params  DOES NOT WORK to assemble the final SQL string because the %s placeholders are not quoted/escaped
    they should always passed separately to the DB driver so it can do its own quoting/escaping to avoid SQL injection and syntax errors
    """
    assert isinstance(queryset, QuerySet), f'compile_sql_update(...) first argument must be a QuerySet, got: {type(queryset).__name__} instead'
    assert isinstance(update_kwargs, dict), f'compile_sql_update(...) update_kwargs argument must be a dict[str, Any], got: {type(update_kwargs).__name__} instead'
    
    queryset = queryset._chain().all()                # type: ignore   # copy queryset to avoid modifying the original and clear any filters
    queryset.query.clear_ordering(force=True)                          # clear any ORDER BY clauses
    queryset.query.clear_limits()                                      # clear any LIMIT clauses aka slices[:n]
    queryset._for_write = True                        # type: ignore
    query = queryset.query.chain(sql.UpdateQuery)     # type: ignore
    query.add_update_values(update_kwargs)            # type: ignore
    query.annotations = {}                                             # clear any annotations
    
    # e.g. UPDATE core_archiveresult SET status='%s', retry_at='%s' WHERE status NOT IN (%s, %s, %s) AND retry_at <= %s
    update_sql, update_params = query.get_compiler(queryset.db).as_sql()
    
    # make sure you only pass a raw queryset with no .filter(...) clauses applied to it, the return value is designed to used
    # in a manually assembled SQL query with its own WHERE clause later on
    assert 'WHERE' not in update_sql, f'compile_sql_update(...) should only contain a SET statement but it tried to return a query with a WHERE clause: {update_sql}'
    
    # print(update_sql, update_params)

    return update_sql, update_params

