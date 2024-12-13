__package__ = 'archivebox.workers'

import uuid
import json

from typing import ClassVar, Type, Iterable, TypedDict
from datetime import datetime, timedelta
from statemachine.mixins import MachineMixin

from django.db import models
from django.db.models import QuerySet
from django.core import checks
from django.utils import timezone
from django.utils.functional import classproperty

from base_models.models import ABIDModel, ABIDField
from machine.models import Process

from statemachine import registry, StateMachine, State


class DefaultStatusChoices(models.TextChoices):
    QUEUED = 'queued', 'Queued'
    STARTED = 'started', 'Started'
    SEALED = 'sealed', 'Sealed'


default_status_field: models.CharField = models.CharField(choices=DefaultStatusChoices.choices, max_length=15, default=DefaultStatusChoices.QUEUED, null=False, blank=False, db_index=True)
default_retry_at_field: models.DateTimeField = models.DateTimeField(default=timezone.now, null=True, blank=True, db_index=True)

ObjectState = State | str
ObjectStateList = Iterable[ObjectState]


class BaseModelWithStateMachine(models.Model, MachineMixin):
    id: models.UUIDField
    
    StatusChoices: ClassVar[Type[models.TextChoices]]
    
    # status: models.CharField
    # retry_at: models.DateTimeField
    
    state_machine_name: ClassVar[str]
    state_field_name: ClassVar[str]
    state_machine_attr: ClassVar[str] = 'sm'
    bind_events_as_methods: ClassVar[bool] = True
    
    active_state: ClassVar[ObjectState]
    retry_at_field_name: ClassVar[str]
    
    class Meta:
        abstract = True
        
    @classmethod
    def check(cls, sender=None, **kwargs):
        errors = super().check(**kwargs)
        
        found_id_field = False
        found_status_field = False
        found_retry_at_field = False
        
        for field in cls._meta.get_fields():
            if getattr(field, '_is_state_field', False):
                if cls.state_field_name == field.name:
                    found_status_field = True
                    if getattr(field, 'choices', None) != cls.StatusChoices.choices:
                        errors.append(checks.Error(
                            f'{cls.__name__}.{field.name} must have choices set to {cls.__name__}.StatusChoices.choices',
                            hint=f'{cls.__name__}.{field.name}.choices = {getattr(field, "choices", None)!r}',
                            obj=cls,
                            id='workers.E011',
                        ))
            if getattr(field, '_is_retry_at_field', False):
                if cls.retry_at_field_name == field.name:
                    found_retry_at_field = True
            if field.name == 'id' and getattr(field, 'primary_key', False):
                found_id_field = True
                    
        if not found_status_field:
            errors.append(checks.Error(
                f'{cls.__name__}.state_field_name must be defined and point to a StatusField()',
                hint=f'{cls.__name__}.state_field_name = {cls.state_field_name!r} but {cls.__name__}.{cls.state_field_name!r} was not found or does not refer to StatusField',
                obj=cls,
                id='workers.E012',
            ))
        if not found_retry_at_field:
            errors.append(checks.Error(
                f'{cls.__name__}.retry_at_field_name must be defined and point to a RetryAtField()',
                hint=f'{cls.__name__}.retry_at_field_name = {cls.retry_at_field_name!r} but {cls.__name__}.{cls.retry_at_field_name!r} was not found or does not refer to RetryAtField',
                obj=cls,
                id='workers.E013',
            ))
            
        if not found_id_field:
            errors.append(checks.Error(
                f'{cls.__name__} must have an id field that is a primary key',
                hint=f'{cls.__name__}.id = {cls.id!r}',
                obj=cls,
                id='workers.E014',
            ))
            
        if not isinstance(cls.state_machine_name, str):
            errors.append(checks.Error(
                f'{cls.__name__}.state_machine_name must be a dotted-import path to a StateMachine class',
                hint=f'{cls.__name__}.state_machine_name = {cls.state_machine_name!r}',
                obj=cls,
                id='workers.E015',
            ))
        
        try:
            cls.StateMachineClass
        except Exception as err:
            errors.append(checks.Error(
                f'{cls.__name__}.state_machine_name must point to a valid StateMachine class, but got {type(err).__name__} {err} when trying to access {cls.__name__}.StateMachineClass',
                hint=f'{cls.__name__}.state_machine_name = {cls.state_machine_name!r}',
                obj=cls,
                id='workers.E016',
            ))
        
        if cls.INITIAL_STATE not in cls.StatusChoices.values:
            errors.append(checks.Error(
                f'{cls.__name__}.StateMachineClass.initial_state must be present within {cls.__name__}.StatusChoices',
                hint=f'{cls.__name__}.StateMachineClass.initial_state = {cls.StateMachineClass.initial_state!r}',
                obj=cls,
                id='workers.E017',
            ))
            
        if cls.ACTIVE_STATE not in cls.StatusChoices.values:
            errors.append(checks.Error(
                f'{cls.__name__}.active_state must be set to a valid State present within {cls.__name__}.StatusChoices',
                hint=f'{cls.__name__}.active_state = {cls.active_state!r}',
                obj=cls,
                id='workers.E018',
            ))
            
        
        for state in cls.FINAL_STATES:
            if state not in cls.StatusChoices.values:
                errors.append(checks.Error(
                    f'{cls.__name__}.StateMachineClass.final_states must all be present within {cls.__name__}.StatusChoices',
                    hint=f'{cls.__name__}.StateMachineClass.final_states = {cls.StateMachineClass.final_states!r}',
                    obj=cls,
                    id='workers.E019',
                ))
                break
        return errors
    
    @staticmethod
    def _state_to_str(state: ObjectState) -> str:
        """Convert a statemachine.State, models.TextChoices.choices value, or Enum value to a str"""
        return str(state.value) if isinstance(state, State) else str(state)
    
    
    @property
    def RETRY_AT(self) -> datetime:
        return getattr(self, self.retry_at_field_name)
    
    @RETRY_AT.setter
    def RETRY_AT(self, value: datetime):
        setattr(self, self.retry_at_field_name, value)
        
    @property
    def STATE(self) -> str:
        return getattr(self, self.state_field_name)
    
    @STATE.setter
    def STATE(self, value: str):
        setattr(self, self.state_field_name, value)
        
    def bump_retry_at(self, seconds: int = 10):
        self.RETRY_AT = timezone.now() + timedelta(seconds=seconds)
        
    @classproperty
    def ACTIVE_STATE(cls) -> str:
        return cls._state_to_str(cls.active_state)
        
    @classproperty
    def INITIAL_STATE(cls) -> str:
        return cls._state_to_str(cls.StateMachineClass.initial_state)
    
    @classproperty
    def FINAL_STATES(cls) -> list[str]:
        return [cls._state_to_str(state) for state in cls.StateMachineClass.final_states]
    
    @classproperty
    def FINAL_OR_ACTIVE_STATES(cls) -> list[str]:
        return [*cls.FINAL_STATES, cls.ACTIVE_STATE]
        
    @classmethod
    def extend_choices(cls, base_choices: Type[models.TextChoices]):
        """
        Decorator to extend the base choices with extra choices, e.g.:
        
        class MyModel(ModelWithStateMachine):
        
            @ModelWithStateMachine.extend_choices(ModelWithStateMachine.StatusChoices)
            class StatusChoices(models.TextChoices):
                SUCCEEDED = 'succeeded'
                FAILED = 'failed'
                SKIPPED = 'skipped'
        """
        assert issubclass(base_choices, models.TextChoices), f'@extend_choices(base_choices) must be a TextChoices class, not {base_choices.__name__}'
        def wrapper(extra_choices: Type[models.TextChoices]) -> Type[models.TextChoices]:
            joined = {}
            for item in base_choices.choices:
                joined[item[0]] = item[1]
            for item in extra_choices.choices:
                joined[item[0]] = item[1]
            return models.TextChoices('StatusChoices', joined)
        return wrapper
        
    @classmethod
    def StatusField(cls, **kwargs) -> models.CharField:
        """
        Used on subclasses to extend/modify the status field with updated kwargs. e.g.:
        
        class MyModel(ModelWithStateMachine):
            class StatusChoices(ModelWithStateMachine.StatusChoices):
                QUEUED = 'queued', 'Queued'
                STARTED = 'started', 'Started'
                SEALED = 'sealed', 'Sealed'
                BACKOFF = 'backoff', 'Backoff'
                FAILED = 'failed', 'Failed'
                SKIPPED = 'skipped', 'Skipped'
        
            status = ModelWithStateMachine.StatusField(choices=StatusChoices.choices, default=StatusChoices.QUEUED)
        """
        default_kwargs = default_status_field.deconstruct()[3]
        updated_kwargs = {**default_kwargs, **kwargs}
        field = models.CharField(**updated_kwargs)
        field._is_state_field = True                    # type: ignore
        return field

    @classmethod
    def RetryAtField(cls, **kwargs) -> models.DateTimeField:
        """
        Used on subclasses to extend/modify the retry_at field with updated kwargs. e.g.:
        
        class MyModel(ModelWithStateMachine):
            retry_at = ModelWithStateMachine.RetryAtField(editable=False)
        """
        default_kwargs = default_retry_at_field.deconstruct()[3]
        updated_kwargs = {**default_kwargs, **kwargs}
        field = models.DateTimeField(**updated_kwargs)
        field._is_retry_at_field = True                 # type: ignore
        return field
    
    @classproperty
    def StateMachineClass(cls) -> Type[StateMachine]:
        """Get the StateMachine class for the given django Model that inherits from MachineMixin"""

        model_state_machine_name = getattr(cls, 'state_machine_name', None)
        if model_state_machine_name:
            StateMachineCls = registry.get_machine_cls(model_state_machine_name)
            assert issubclass(StateMachineCls, StateMachine)
            return StateMachineCls
        raise NotImplementedError(f'ActorType[{cls.__name__}] must define .state_machine_name: str that points to a valid StateMachine')
    
    # @classproperty
    # def final_q(cls) -> Q:
    #     """Get the filter for objects that are in a final state"""
    #     return Q(**{f'{cls.state_field_name}__in': cls.final_states})
    
    # @classproperty
    # def active_q(cls) -> Q:
    #     """Get the filter for objects that are actively processing right now"""
    #     return Q(**{cls.state_field_name: cls._state_to_str(cls.active_state)})   # e.g. Q(status='started')
    
    # @classproperty
    # def stalled_q(cls) -> Q:
    #     """Get the filter for objects that are marked active but have timed out"""
    #     return cls.active_q & Q(retry_at__lte=timezone.now())                     # e.g. Q(status='started') AND Q(<retry_at is in the past>)
    
    # @classproperty
    # def future_q(cls) -> Q:
    #     """Get the filter for objects that have a retry_at in the future"""
    #     return Q(retry_at__gt=timezone.now())
    
    # @classproperty
    # def pending_q(cls) -> Q:
    #     """Get the filter for objects that are ready for processing."""
    #     return ~(cls.active_q) & ~(cls.final_q) & ~(cls.future_q)
    
    # @classmethod
    # def get_queue(cls) -> QuerySet:
    #     """
    #     Get the sorted and filtered QuerySet of objects that are ready for processing.
    #     e.g. qs.exclude(status__in=('sealed', 'started'), retry_at__gt=timezone.now()).order_by('retry_at')
    #     """
    #     return cls.objects.filter(cls.pending_q)


class ModelWithStateMachine(BaseModelWithStateMachine):
    StatusChoices: ClassVar[Type[DefaultStatusChoices]] = DefaultStatusChoices
    
    status: models.CharField = BaseModelWithStateMachine.StatusField()
    retry_at: models.DateTimeField = BaseModelWithStateMachine.RetryAtField()
    
    state_machine_name: ClassVar[str]      # e.g. 'core.statemachines.ArchiveResultMachine'
    state_field_name: ClassVar[str]        = 'status'
    state_machine_attr: ClassVar[str]      = 'sm'
    bind_events_as_methods: ClassVar[bool] = True
    
    active_state: ClassVar[str]            = StatusChoices.STARTED
    retry_at_field_name: ClassVar[str]     = 'retry_at'
    
    class Meta:
        abstract = True





class EventDict(TypedDict, total=False):
    name: str
    
    id: str | uuid.UUID
    path: str
    content: str
    status: str
    retry_at: datetime | None
    url: str
    seed_id: str | uuid.UUID
    crawl_id: str | uuid.UUID
    snapshot_id: str | uuid.UUID
    process_id: str | uuid.UUID
    extractor: str
    error: str
    on_success: dict | None
    on_failure: dict | None

class EventManager(models.Manager):
    pass

class EventQuerySet(models.QuerySet):
    def get_next_unclaimed(self) -> 'Event | None':
        return self.filter(claimed_at=None).order_by('deliver_at').first()
    
    def expired(self, older_than: int=60 * 10) -> QuerySet['Event']:
        return self.filter(claimed_at__lt=timezone.now() - timedelta(seconds=older_than))


class Event(ABIDModel):
    abid_prefix = 'evn_'
    abid_ts_src = 'self.deliver_at'                  # e.g. 'self.created_at'
    abid_uri_src = 'self.name'                       # e.g. 'self.uri'                (MUST BE SET)
    abid_subtype_src = 'self.emitted_by'             # e.g. 'self.extractor'
    abid_rand_src = 'self.id'                        # e.g. 'self.uuid' or 'self.id'
    abid_drift_allowed: bool = False                 # set to True to allow abid_field values to change after a fixed ABID has been issued (NOT RECOMMENDED: means values can drift out of sync from original ABID)

    read_only_fields = ('id', 'deliver_at', 'name', 'kwargs', 'timeout', 'parent', 'emitted_by', 'on_success', 'on_failure')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, null=False, editable=False, unique=True, verbose_name='ID')
    
    # disable these fields from inherited models, they're not needed / take up too much room
    abid = None
    created_at = None
    created_by = None
    created_by_id = None
    
    # immutable fields
    deliver_at = models.DateTimeField(default=timezone.now, null=False, editable=False, unique=True, db_index=True)
    name = models.CharField(max_length=255, null=False, blank=False, db_index=True)
    kwargs = models.JSONField(default=dict)
    timeout = models.IntegerField(null=False, default=60)
    parent = models.ForeignKey('Event', null=True, on_delete=models.SET_NULL, related_name='child_events')
    emitted_by = models.ForeignKey(Process, null=False, on_delete=models.PROTECT, related_name='emitted_events')
    on_success = models.JSONField(null=True)
    on_failure = models.JSONField(null=True)

    # mutable fields
    modified_at = models.DateTimeField(auto_now=True)
    claimed_proc = models.ForeignKey(Process, null=True, on_delete=models.CASCADE, related_name='claimed_events')
    claimed_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    error = models.TextField(null=True)

    objects: EventManager = EventManager.from_queryset(EventQuerySet)()
    
    child_events: models.RelatedManager['Event']
    
    @classmethod
    def get_next_timestamp(cls):
        """Get the next monotonically increasing timestamp for the next event.dispatch_at"""
        latest_event = cls.objects.order_by('-deliver_at').first()
        ts = timezone.now()
        if latest_event:
            assert ts > latest_event.deliver_at, f'Event.deliver_at is not monotonically increasing: {latest_event.deliver_at} > {ts}'
        return ts
    
    @classmethod
    def dispatch(cls, name: str | EventDict | None = None, event: EventDict | None = None, **event_init_kwargs) -> 'Event':
        """
        Create a new Event and save it to the database.
        
        Can be called as either:
            >>> Event.dispatch(name, {**kwargs}, **event_init_kwargs)
            # OR 
            >>> Event.dispatch({name, **kwargs}, **event_init_kwargs)
        """
        event_kwargs: EventDict = event or {}
        if isinstance(name, dict):
            event_kwargs.update(name)
        assert isinstance(event_kwargs, dict), 'must be called as Event.dispatch(name, {**kwargs}) or Event.dispatch({name, **kwargs})'
        
        event_name: str = name if (isinstance(name, str) and name) else event_kwargs.pop('name')

        new_event = cls(
            name=event_name,
            kwargs=event_kwargs,
            emitted_by=Process.current(),
            **event_init_kwargs,
        )
        new_event.save()
        return new_event

    def clean(self, *args, **kwargs) -> None:
        """Fill and validate all the event fields"""
        
        # check uuid and deliver_at are set
        assert self.id, 'Event.id must be set to a valid v4 UUID'
        if not self.deliver_at:
            self.deliver_at = self.get_next_timestamp()
        assert self.deliver_at and (datetime(2024, 12, 8, 12, 0, 0, tzinfo=timezone.utc) < self.deliver_at < datetime(2100, 12, 31, 23, 59, 0, tzinfo=timezone.utc)), (
            f'Event.deliver_at must be set to a valid UTC datetime (got Event.deliver_at = {self.deliver_at})')
        
        # if name is not set but it's found in the kwargs, move it out of the kwargs to the name field
        if 'type' in self.kwargs and ((self.name == self.kwargs['type']) or not self.name):
            self.name = self.kwargs.pop('type')
        if 'name' in self.kwargs and ((self.name == self.kwargs['name']) or not self.name):
            self.name = self.kwargs.pop('name')
        
        # check name is set and is a valid identifier
        assert isinstance(self.name, str) and len(self.name) > 3, 'Event.name must be set to a non-empty string'
        assert self.name.isidentifier(), f'Event.name must be a valid identifier (got Event.name = {self.name})'
        assert self.name.isupper(), f'Event.name must be in uppercase (got Event.name = {self.name})'
        
        # check that kwargs keys and values are valid
        for key, value in self.kwargs.items():
            assert isinstance(key, str), f'Event kwargs keys can only be strings (got Event.kwargs[{key}: {type(key).__name__}])'
            assert key not in self._meta.get_fields(), f'Event.kwargs cannot contain "{key}" key (Event.kwargs[{key}] conflicts with with reserved attr Event.{key} = {getattr(self, key)})'
            assert json.dumps(value, sort_keys=True), f'Event can only contain JSON serializable values (got Event.kwargs[{key}]: {type(value).__name__} = {value})'
            
        # validate on_success and on_failure are valid event dicts if set
        if self.on_success:
            assert isinstance(self.on_success, dict) and self.on_success.get('name', '!invalid').isidentifier(), f'Event.on_success must be a valid event dict (got {self.on_success})'
        if self.on_failure:
            assert isinstance(self.on_failure, dict) and self.on_failure.get('name', '!invalid').isidentifier(), f'Event.on_failure must be a valid event dict (got {self.on_failure})'
            
        # validate mutable fields like claimed_at, claimed_proc, finished_at are set correctly
        if self.claimed_at:
            assert self.claimed_proc, f'Event.claimed_at and Event.claimed_proc must be set together (only found Event.claimed_at = {self.claimed_at})'
        if self.claimed_proc:
            assert self.claimed_at, f'Event.claimed_at and Event.claimed_proc must be set together (only found Event.claimed_proc = {self.claimed_proc})'
        if self.finished_at:
            assert self.claimed_at, f'If Event.finished_at is set, Event.claimed_at and Event.claimed_proc must also be set (Event.claimed_proc = {self.claimed_proc} and Event.claimed_at = {self.claimed_at})'
        
        # validate error is a non-empty string or None
        if isinstance(self.error, BaseException):
            self.error = f'{type(self.error).__name__}: {self.error}'
        if self.error:
            assert isinstance(self.error, str) and str(self.error).strip(), f'Event.error must be a non-empty string (got Event.error: {type(self.error).__name__} = {self.error})'
        else:
            assert self.error is None, f'Event.error must be None or a non-empty string (got Event.error: {type(self.error).__name__} = {self.error})'

    
    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)
    
    def reset(self):
        """Force-update an event to a pending/unclaimed state (without running any of its handlers or callbacks)"""
        self.claimed_proc = None
        self.claimed_at = None
        self.finished_at = None
        self.error = None
        self.save()

    def abort(self):
        """Force-update an event to a completed/failed state (without running any of its handlers or callbacks)"""
        self.claimed_proc = Process.current()
        self.claimed_at = timezone.now()
        self.finished_at = timezone.now()
        self.error = 'Aborted'
        self.save()


    def __repr__(self) -> str:
        label = f'[{self.name} {self.kwargs}]'
        if self.is_finished:
            label += f' ✅'
        elif self.claimed_proc:
            label += f' 🏃'
        return label
    
    def __str__(self) -> str:
        return repr(self)

    @property
    def type(self) -> str:
        return self.name

    @property
    def is_queued(self):
        return not self.is_claimed and not self.is_finished

    @property
    def is_claimed(self):
        return self.claimed_at is not None
    
    @property
    def is_expired(self):
        if not self.claimed_at:
            return False
        
        elapsed_time = timezone.now() - self.claimed_at
        return elapsed_time > timedelta(seconds=self.timeout)
    
    @property
    def is_processing(self):
        return self.is_claimed and not self.is_finished
    
    @property
    def is_finished(self):
        return self.finished_at is not None
    
    @property
    def is_failed(self):
        return self.is_finished and bool(self.error)
    
    @property
    def is_succeeded(self):
        return self.is_finished and not bool(self.error)

    def __getattr__(self, key: str):
        """
        Allow access to the event kwargs as attributes e.g. 
        Event(name='CRAWL_CREATE', kwargs={'some_key': 'some_val'}).some_key -> 'some_val'
        """
        return self.kwargs.get(key)
