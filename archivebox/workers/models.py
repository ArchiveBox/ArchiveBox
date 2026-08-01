__package__ = "archivebox.workers"

import inspect
import logging

from typing import Any, ClassVar, Protocol, cast
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statemachine.callbacks import SPECS_ALL
from statemachine.dispatcher import Listener, Listeners
from statemachine.graph import iterate_states_and_transitions

from django.db import models
from django.core import checks
from django.utils import timezone
from django.utils.functional import classproperty
from django_stubs_ext.db.models import TypedModelMeta

from statemachine import registry, StateMachine, State


class DefaultStatusChoices(models.TextChoices):
    QUEUED = "queued", "Queued"
    STARTED = "started", "Started"
    PAUSED = "paused", "Paused"
    SEALED = "sealed", "Sealed"


default_status_field: models.CharField = models.CharField(
    choices=DefaultStatusChoices.choices,
    max_length=15,
    default=DefaultStatusChoices.QUEUED,
    null=False,
    blank=False,
    db_index=True,
)
default_retry_at_field: models.DateTimeField = models.DateTimeField(default=timezone.now, null=True, blank=True, db_index=True)
RETRY_AT_MAX = datetime(9999, 1, 1, tzinfo=UTC)
ACTIVE_STATE_LEASE_SECONDS = 60
logger = logging.getLogger(__name__)
MODULE_PATH = Path(__file__).resolve()
REPO_ROOT = MODULE_PATH.parents[2]
PACKAGE_ROOT = MODULE_PATH.parents[1]

ObjectState = State | str
ObjectStateList = Iterable[ObjectState]


class ModelStateMachine(Protocol):
    def tick(self) -> Any: ...

    def pause_requested(self) -> Any: ...

    def resume_requested(self) -> Any: ...


class BaseModelWithStateMachine(models.Model):
    StatusChoices: ClassVar[type[DefaultStatusChoices]]

    # status: models.CharField
    # retry_at: models.DateTimeField

    state_machine_name: str | None = None
    state_field_name: str
    state_machine_attr: str = "sm"
    bind_events_as_methods: bool = False
    warn_on_save_outside_runner: ClassVar[bool] = True

    active_state: ObjectState
    retry_at_field_name: str

    class Meta(TypedModelMeta):
        app_label = "workers"
        abstract = True

    @property
    def sm(self) -> StateMachine:
        """Build the python-statemachine wrapper only at transition callsites.

        This model is loaded by high-volume paths that do not drive lifecycle
        transitions: admin lists, progress polling, index-only maintenance, and
        bulk recovery scans all instantiate thousands of rows just to read or
        update ordinary columns.  python-statemachine setup is correct but not
        free: it creates per-instance state wrappers, callback registries,
        queues, locks, and callback adapters.  Paying that cost from Django's
        model __init__ made plain ORM materialization scale with state-machine
        setup instead of row decoding.

        ArchiveBox drives lifecycle transitions explicitly through `.sm`
        (`snapshot.sm.tick()`, `crawl.sm.seal()`, etc.), so the machine can be
        cached on first use without changing the state model.  Code that only
        needs database fields never constructs one.
        """
        try:
            machine = vars(self)["_archivebox_state_machine"]
        except KeyError:
            machine = self.StateMachineClass(self, state_field=self.state_field_name)
            vars(self)["_archivebox_state_machine"] = machine
        return cast(StateMachine, machine)

    @classmethod
    def status_counts(cls, queryset: models.QuerySet | None = None, statuses: Iterable[str] | None = None) -> dict[str, int]:
        """Count requested statuses with separate indexed COUNT probes.

        For live/progress views this is often faster on large SQLite data dirs
        than a grouped aggregate, because each status can use the status index
        directly and the caller usually needs only a few states.
        """
        qs = queryset if queryset is not None else cls.objects.all()
        return {status: qs.filter(status=status).count() for status in (statuses or cls.StatusChoices.values)}

    @classmethod
    def check(cls, sender=None, **kwargs):
        import sys

        # Skip state machine checks during makemigrations to avoid premature registry access
        if "makemigrations" in sys.argv:
            return super().check(**kwargs)

        errors = super().check(**kwargs)

        found_id_field = False
        found_status_field = False
        found_retry_at_field = False

        for field in cls._meta.get_fields():
            if getattr(field, "_is_state_field", False):
                if cls.state_field_name == field.name:
                    found_status_field = True
                    if getattr(field, "choices", None) != cls.StatusChoices.choices:
                        errors.append(
                            checks.Error(
                                f"{cls.__name__}.{field.name} must have choices set to {cls.__name__}.StatusChoices.choices",
                                hint=f"{cls.__name__}.{field.name}.choices = {getattr(field, 'choices', None)!r}",
                                obj=cls,
                                id="workers.E011",
                            ),
                        )
            if getattr(field, "_is_retry_at_field", False):
                if cls.retry_at_field_name == field.name:
                    found_retry_at_field = True
            if field.name == "id" and getattr(field, "primary_key", False):
                found_id_field = True

        if not found_status_field:
            errors.append(
                checks.Error(
                    f"{cls.__name__}.state_field_name must be defined and point to a StatusField()",
                    hint=f"{cls.__name__}.state_field_name = {cls.state_field_name!r} but {cls.__name__}.{cls.state_field_name!r} was not found or does not refer to StatusField",
                    obj=cls,
                    id="workers.E012",
                ),
            )
        if not found_retry_at_field:
            errors.append(
                checks.Error(
                    f"{cls.__name__}.retry_at_field_name must be defined and point to a RetryAtField()",
                    hint=f"{cls.__name__}.retry_at_field_name = {cls.retry_at_field_name!r} but {cls.__name__}.{cls.retry_at_field_name!r} was not found or does not refer to RetryAtField",
                    obj=cls,
                    id="workers.E013",
                ),
            )

        if not found_id_field:
            errors.append(
                checks.Error(
                    f"{cls.__name__} must have an id field that is a primary key",
                    hint=f"{cls.__name__}.id field missing or not configured as primary key",
                    obj=cls,
                    id="workers.E014",
                ),
            )

        if not isinstance(cls.state_machine_name, str):
            errors.append(
                checks.Error(
                    f"{cls.__name__}.state_machine_name must be a dotted-import path to a StateMachine class",
                    hint=f"{cls.__name__}.state_machine_name = {cls.state_machine_name!r}",
                    obj=cls,
                    id="workers.E015",
                ),
            )

        try:
            cls.StateMachineClass
        except Exception as err:
            errors.append(
                checks.Error(
                    f"{cls.__name__}.state_machine_name must point to a valid StateMachine class, but got {type(err).__name__} {err} when trying to access {cls.__name__}.StateMachineClass",
                    hint=f"{cls.__name__}.state_machine_name = {cls.state_machine_name!r}",
                    obj=cls,
                    id="workers.E016",
                ),
            )

        if cls.INITIAL_STATE not in cls.StatusChoices.values:
            errors.append(
                checks.Error(
                    f"{cls.__name__}.StateMachineClass.initial_state must be present within {cls.__name__}.StatusChoices",
                    hint=f"{cls.__name__}.StateMachineClass.initial_state = {cls.StateMachineClass.initial_state!r}",
                    obj=cls,
                    id="workers.E017",
                ),
            )

        if cls.ACTIVE_STATE not in cls.StatusChoices.values:
            errors.append(
                checks.Error(
                    f"{cls.__name__}.active_state must be set to a valid State present within {cls.__name__}.StatusChoices",
                    hint=f"{cls.__name__}.active_state = {cls.active_state!r}",
                    obj=cls,
                    id="workers.E018",
                ),
            )

        for state in cls.FINAL_STATES:
            if state not in cls.StatusChoices.values:
                errors.append(
                    checks.Error(
                        f"{cls.__name__}.StateMachineClass.final_states must all be present within {cls.__name__}.StatusChoices",
                        hint=f"{cls.__name__}.StateMachineClass.final_states = {cls.StateMachineClass.final_states!r}",
                        obj=cls,
                        id="workers.E019",
                    ),
                )
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

    @property
    def is_paused(self) -> bool:
        paused_state = getattr(self.StatusChoices, "PAUSED", None)
        return paused_state is not None and self.STATE == paused_state

    def safe_update(self, update_fields: dict[str, Any], *, refresh: bool = True, extra_filter: dict[str, Any] | None = None) -> bool:
        """
        Atomic single-row UPDATE for scheduler writes that bypass save().

        The write is unconditional unless the caller passes extra_filter — the
        previous implicit modified_at CAS predicate spuriously collided with
        concurrent writers to unrelated fields (every save bumps modified_at),
        which silently dropped state-machine transitions. Callers that need a
        transition guard (only advance from state A to state B; only requeue a
        row still holding lease X) pass extra_filter explicitly.
        """
        values = dict(update_fields)
        values.setdefault("modified_at", timezone.now())
        queryset = type(self).objects.filter(pk=self.pk)
        if extra_filter:
            queryset = queryset.filter(**extra_filter)
        updated = queryset.update(**values)
        if updated != 1 and extra_filter:
            current = type(self).objects.filter(pk=self.pk).values(self.state_field_name).first()
            current_status = current.get(self.state_field_name) if current else "<deleted>"
            logger.info(
                "SafeUpdateGuardMiss: %s row %s extra_filter=%s did not match (current %s=%s, loaded %s=%s); update_fields=%s skipped",
                type(self).__name__,
                self.pk,
                extra_filter,
                self.state_field_name,
                current_status,
                self.state_field_name,
                self.STATE,
                sorted(values),
            )
        if refresh:
            try:
                self.refresh_from_db()
            except type(self).DoesNotExist:
                pass
        return updated == 1

    def save(self, *args, **kwargs):
        from archivebox.machine.models import Process

        process = Process.current()
        if self.warn_on_save_outside_runner and not self._state.adding and process.process_type != Process.TypeChoices.ORCHESTRATOR:
            root_type = getattr(process.root, "process_type", None)
            if root_type != Process.TypeChoices.ORCHESTRATOR:
                caller = "<unknown>"
                frame = inspect.currentframe()
                frame = frame.f_back if frame is not None else None
                try:
                    while frame is not None:
                        frame_path = Path(frame.f_code.co_filename).resolve()
                        if frame_path == MODULE_PATH:
                            frame = frame.f_back
                            continue
                        if frame_path.is_relative_to(PACKAGE_ROOT) and frame_path.name == "models.py" and frame.f_code.co_name == "save":
                            frame = frame.f_back
                            continue
                        if "site-packages" in frame_path.parts:
                            frame = frame.f_back
                            continue
                        try:
                            caller_path = frame_path.relative_to(REPO_ROOT)
                        except ValueError:
                            caller_path = frame_path
                        caller = f"{caller_path}:{frame.f_lineno}"
                        break
                finally:
                    del frame
                logger.warning(
                    "%s.save() outside runner process: id=%s status=%s retry_at=%s process=%s root=%s caller=%s; "
                    "queue/status writes outside the runner should usually use safe_update()",
                    type(self).__name__,
                    self.pk,
                    self.STATE,
                    self.RETRY_AT,
                    process.process_type,
                    root_type,
                    caller,
                )
        super().save(*args, **kwargs)

    def pause(self, *, save: bool = True) -> bool:
        try:
            paused_state = self.StatusChoices.PAUSED
        except AttributeError:
            return False
        if self.STATE in self.FINAL_STATES or self.is_paused:
            return False
        if save:
            cast(ModelStateMachine, self.sm).pause_requested()
            self.refresh_from_db()
            return self.is_paused
        self.STATE = paused_state
        self.RETRY_AT = RETRY_AT_MAX
        return True

    def resume(self, *, when: datetime | None = None, save: bool = True) -> bool:
        try:
            paused_state = self.StatusChoices.PAUSED
        except AttributeError:
            return False
        if not self.is_paused:
            return False
        if save:
            if when is None:
                cast(ModelStateMachine, self.sm).resume_requested()
                self.refresh_from_db()
                return self.STATE == self.StatusChoices.QUEUED
            self.STATE = self.StatusChoices.QUEUED
            self.RETRY_AT = when or timezone.now()
            updated = self.safe_update(
                {
                    self.state_field_name: self.StatusChoices.QUEUED,
                    self.retry_at_field_name: self.RETRY_AT,
                },
                extra_filter={self.state_field_name: paused_state},
            )
            return updated
        self.STATE = self.StatusChoices.QUEUED
        self.RETRY_AT = when or timezone.now()
        return True

    def update_and_requeue(self, *, refresh: bool = True, **kwargs) -> bool:
        """
        Scheduler-facing wrapper around safe_update().

        Call this when a state-machine row should become visible to the
        runner. It preserves the current retry_at lease as an additional guard
        while safe_update() owns the modified_at CAS write and refresh.
        """
        # retry_at is the scheduler lease, but it is not enough by itself:
        # sealed maintenance rows can legitimately keep the same retry_at while
        # other fields change. Include modified_at as a cheap compare-and-swap
        # guard so iterator/recovery scans never overwrite a row that the
        # runner touched after the object was read.
        current_retry_at = self.RETRY_AT
        return self.safe_update(
            dict(kwargs),
            refresh=refresh,
            extra_filter={self.retry_at_field_name: current_retry_at},
        )

    @classmethod
    def get_queue(cls):
        """
        Get the sorted and filtered QuerySet of objects that are ready for processing.
        retry_at is the only scheduler signal; callers branch on status after selection.
        """
        return cls.objects.filter(
            retry_at__lte=timezone.now(),
        ).order_by("retry_at")

    @classmethod
    def claim_for_worker(cls, obj: "BaseModelWithStateMachine", lock_seconds: int = 60) -> bool:
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
        now = timezone.now()
        lock_until = now + timedelta(seconds=lock_seconds)
        updated = cls.objects.filter(
            pk=obj.pk,
            retry_at=obj.RETRY_AT,
            retry_at__lte=now,
        ).update(
            retry_at=lock_until,
            modified_at=now,
        )
        if updated == 1:
            obj.RETRY_AT = lock_until
            cast(Any, obj).modified_at = now
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

        cast(ModelStateMachine, self.sm).tick()
        self.refresh_from_db()
        return True

    @classproperty
    def ACTIVE_STATE(cls) -> str:
        return cls._state_to_str(cls.active_state)

    @classproperty
    def INITIAL_STATE(cls) -> str:
        initial_state = cls.StateMachineClass.initial_state
        if initial_state is None:
            raise ValueError("StateMachineClass.initial_state must not be None")
        return cls._state_to_str(initial_state)

    @classproperty
    def FINAL_STATES(cls) -> list[str]:
        return [cls._state_to_str(state) for state in cls.StateMachineClass.final_states]

    @classproperty
    def FINAL_OR_ACTIVE_STATES(cls) -> list[str]:
        return [*cls.FINAL_STATES, cls.ACTIVE_STATE]

    @classmethod
    def extend_choices(cls, base_choices: type[models.TextChoices]):
        """
        Decorator to extend the base choices with extra choices, e.g.:

        class MyModel(ModelWithStateMachine):

            @ModelWithStateMachine.extend_choices(ModelWithStateMachine.StatusChoices)
            class StatusChoices(models.TextChoices):
                SUCCEEDED = 'succeeded'
                FAILED = 'failed'
                SKIPPED = 'skipped'
        """
        assert issubclass(base_choices, models.TextChoices), (
            f"@extend_choices(base_choices) must be a TextChoices class, not {base_choices.__name__}"
        )

        def wrapper(extra_choices: type[models.TextChoices]) -> type[models.TextChoices]:
            joined = {}
            for item in base_choices.choices:
                joined[item[0]] = item[1]
            for item in extra_choices.choices:
                joined[item[0]] = item[1]
            joined_choices = models.TextChoices("StatusChoices", joined)
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
        field._is_state_field = True  # type: ignore
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
        field._is_retry_at_field = True  # type: ignore
        return field

    @classproperty
    def StateMachineClass(cls) -> type[StateMachine]:
        """Get the StateMachine class for the given django Model."""

        model_state_machine_name = cls.state_machine_name
        if model_state_machine_name:
            StateMachineCls = registry.get_machine_cls(model_state_machine_name)
            assert issubclass(StateMachineCls, StateMachine)
            return StateMachineCls
        raise NotImplementedError("ActorType must define .state_machine_name that points to a valid StateMachine")


class ModelWithStateMachine(BaseModelWithStateMachine):
    StatusChoices = DefaultStatusChoices

    status: models.CharField = BaseModelWithStateMachine.StatusField()
    retry_at: models.DateTimeField = BaseModelWithStateMachine.RetryAtField()

    state_machine_name: str | None  # e.g. 'core.models.ArchiveResultMachine'
    state_field_name: str = "status"
    state_machine_attr: str = "sm"
    bind_events_as_methods: bool = False

    active_state = StatusChoices.STARTED
    retry_at_field_name: str = "retry_at"

    class Meta(BaseModelWithStateMachine.Meta):
        abstract = True


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

    model_attr_name: str = "obj"  # Override in subclasses

    def __init__(self, obj, *args, **kwargs):
        setattr(self, self.model_attr_name, obj)
        super().__init__(obj, *args, **kwargs)

    def _register_callbacks(self, listeners: list[object]):
        """Register transition callbacks without scanning the Django model.

        python-statemachine normally treats the wrapped model as a callback
        listener.  That is useful when transition specs point at methods on the
        domain object, but ArchiveBox keeps all transition guards/actions on the
        machine classes themselves (`SnapshotMachine.can_start`,
        `CrawlMachine.enter_sealed`, etc.).  Scanning the Django model therefore
        only adds work: `dir(model)` is large, callback resolution walks that
        attribute set for every state/transition, and the cost lands on every
        `.sm` construction.

        Keep support for explicit external listeners, but do not register
        `self.model` as an implicit listener.  If a future machine wants model
        methods as callbacks, pass that model explicitly as a listener at the
        callsite so the cost is local and visible.
        """
        self._listeners.update({id(listener): listener for listener in listeners})
        callbacks = Listeners.from_listeners(
            (
                Listener.from_obj(self, skip_attrs=self._protected_attrs),
                *(Listener.from_obj(listener) for listener in listeners),
            ),
        )
        registry = self._callbacks
        callbacks.resolve(self._specs, registry=registry, allowed_references=SPECS_ALL)

        check_callbacks = self._callbacks.check
        for visited in iterate_states_and_transitions(self.states):
            callbacks.resolve(visited._specs, registry=registry, allowed_references=SPECS_ALL)
            check_callbacks(visited._specs)

        self._callbacks.async_or_sync()

    def __repr__(self) -> str:
        obj = getattr(self, self.model_attr_name)
        return f"{self.__class__.__name__}[{obj.id}]"

    def __str__(self) -> str:
        return self.__repr__()
