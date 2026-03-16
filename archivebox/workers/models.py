__package__ = 'archivebox.workers'

from typing import ClassVar, Type, Iterable
from datetime import datetime, timedelta
from statemachine.mixins import MachineMixin

from django.db import models
from django.core import checks
from django.utils import timezone
from django.utils.functional import classproperty

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

    StatusChoices: ClassVar[Type[DefaultStatusChoices]]

    # status: models.CharField
    # retry_at: models.DateTimeField

    state_machine_name: str | None
    state_field_name: str
    state_machine_attr: str = 'sm'
    bind_events_as_methods: bool = True

    active_state: ObjectState
    retry_at_field_name: str

    class Meta:
        app_label = 'workers'
        abstract = True

    @classmethod
    def check(cls, sender=None, **kwargs):
        import sys

        # Skip state machine checks during makemigrations to avoid premature registry access
        if 'makemigrations' in sys.argv:
            return super().check(**kwargs)

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

    def update_and_requeue(self, **kwargs) -> bool:
        """
        Atomically update fields and schedule retry_at for next worker tick.
        Returns True if the update was successful, False if the object was modified by another worker.
        """
        # Get the current retry_at to use as optimistic lock
        current_retry_at = self.RETRY_AT

        # Apply the updates
        for key, value in kwargs.items():
            setattr(self, key, value)

        # Try to save with optimistic locking
        updated = type(self).objects.filter(
            pk=self.pk,
            retry_at=current_retry_at,
        ).update(**{k: getattr(self, k) for k in kwargs})

        if updated == 1:
            self.refresh_from_db()
            return True
        return False

    @classmethod
    def get_queue(cls):
        """
        Get the sorted and filtered QuerySet of objects that are ready for processing.
        Objects are ready if:
        - status is not in FINAL_STATES
        - retry_at is in the past (or now)
        """
        return cls.objects.filter(
            retry_at__lte=timezone.now()
        ).exclude(
            status__in=cls.FINAL_STATES
        ).order_by('retry_at')

    @classmethod
    def claim_for_worker(cls, obj: 'BaseModelWithStateMachine', lock_seconds: int = 60) -> bool:
        """
        Atomically claim a due object for processing using retry_at as the lock.

        Correct lifecycle for any state-machine-driven work item:
        1. Queue the item by setting retry_at <= now
        2. Exactly one owner claims it by moving retry_at into the future
        3. Only that owner may call .sm.tick() and perform side effects
        4. State-machine callbacks update retry_at again when the work completes,
           backs off, or is re-queued

        The critical rule is that future retry_at values are already owned.
        Callers must never "steal" those future timestamps and start another
        copy of the same work. That is what prevents duplicate installs, hook
        runs, and other concurrent side effects.

        Returns True if successfully claimed, False if another worker got it
        first or the object is not currently due.
        """
        updated = cls.objects.filter(
            pk=obj.pk,
            retry_at=obj.RETRY_AT,
            retry_at__lte=timezone.now(),
        ).update(
            retry_at=timezone.now() + timedelta(seconds=lock_seconds)
        )
        return updated == 1

    def claim_processing_lock(self, lock_seconds: int = 60) -> bool:
        """
        Claim this model instance immediately before executing one state-machine tick.

        This helper is the safe entrypoint for any direct state-machine driver
        (workers, synchronous crawl dependency installers, one-off CLI helpers).
        Calling `.sm.tick()` without claiming first turns retry_at into "just a
        schedule" instead of the ownership lock it is meant to be.

        Returns True only for the caller that successfully moved retry_at into
        the future. False means another process already owns the work item or it
        is not currently due.
        """
        if self.STATE in self.FINAL_STATES:
            return False
        if self.RETRY_AT is None:
            return False

        claimed = type(self).claim_for_worker(self, lock_seconds=lock_seconds)
        if claimed:
            self.refresh_from_db()
        return claimed

    def tick_claimed(self, lock_seconds: int = 60) -> bool:
        """
        Claim ownership via retry_at and then execute exactly one `.sm.tick()`.

        Future maintainers should prefer this helper over calling `.sm.tick()`
        directly whenever there is any chance another process could see the same
        queued row. If this method returns False, someone else already owns the
        work and the caller must not run side effects for it.
        """
        if not self.claim_processing_lock(lock_seconds=lock_seconds):
            return False

        tick = getattr(getattr(self, self.state_machine_attr, None), 'tick', None)
        if not callable(tick):
            raise TypeError(f'{type(self).__name__}.{self.state_machine_attr}.tick() must be callable')
        tick()
        self.refresh_from_db()
        return True

    @classproperty
    def ACTIVE_STATE(cls) -> str:
        return cls._state_to_str(cls.active_state)

    @classproperty
    def INITIAL_STATE(cls) -> str:
        initial_state = cls.StateMachineClass.initial_state
        if initial_state is None:
            raise ValueError('StateMachineClass.initial_state must not be None')
        return cls._state_to_str(initial_state)

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
            joined_choices = models.TextChoices('StatusChoices', joined)
            assert isinstance(joined_choices, type)
            return joined_choices
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
        raise NotImplementedError('ActorType must define .state_machine_name that points to a valid StateMachine')


class ModelWithStateMachine(BaseModelWithStateMachine):
    StatusChoices = DefaultStatusChoices

    status: models.CharField = BaseModelWithStateMachine.StatusField()
    retry_at: models.DateTimeField = BaseModelWithStateMachine.RetryAtField()

    state_machine_name: str | None         # e.g. 'core.models.ArchiveResultMachine'
    state_field_name: str                  = 'status'
    state_machine_attr: str                = 'sm'
    bind_events_as_methods: bool           = True

    active_state = StatusChoices.STARTED
    retry_at_field_name: str               = 'retry_at'

class BaseStateMachine(StateMachine):
    """
    Base class for all ArchiveBox state machines.

    Eliminates boilerplate __init__, __repr__, __str__ methods that were
    duplicated across all 4 state machines (Snapshot, ArchiveResult, Crawl, Binary).

    Subclasses must set model_attr_name to specify the attribute name
    (e.g., 'snapshot', 'archiveresult', 'crawl', 'binary').

    Example usage:
        class SnapshotMachine(BaseStateMachine):
            model_attr_name = 'snapshot'

            # States and transitions...
            queued = State(value=Snapshot.StatusChoices.QUEUED, initial=True)
            # ...

    The model instance is accessible via self.{model_attr_name}
    (e.g., self.snapshot, self.archiveresult, etc.)
    """

    model_attr_name: str = 'obj'  # Override in subclasses

    def __init__(self, obj, *args, **kwargs):
        setattr(self, self.model_attr_name, obj)
        super().__init__(obj, *args, **kwargs)

    def __repr__(self) -> str:
        obj = getattr(self, self.model_attr_name)
        return f'{self.__class__.__name__}[{obj.id}]'

    def __str__(self) -> str:
        return self.__repr__()
