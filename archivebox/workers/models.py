from typing import ClassVar, Type, Iterable
from datetime import datetime, timedelta

from statemachine.mixins import MachineMixin

from django.db import models
from django.utils import timezone
from django.utils.functional import classproperty

from statemachine import registry, StateMachine, State

from django.core import checks

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
