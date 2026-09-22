__package__ = "archivebox.workers"

import inspect
import logging

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, cast

from django.db import models
from django.utils import timezone
from django_stubs_ext.db.models import TypedModelMeta


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


class ModelWithQueue(models.Model):
    """Durable queue fields and atomic lease operations shared by work rows.

    Concrete models own lifecycle transitions. This mixin only owns the common
    database queue protocol: status, retry_at, pause/resume, and claims.
    """

    StatusChoices: ClassVar[type[models.TextChoices]] = DefaultStatusChoices
    INITIAL_STATE: ClassVar[str] = DefaultStatusChoices.QUEUED
    ACTIVE_STATE: ClassVar[str] = DefaultStatusChoices.STARTED
    FINAL_STATES: ClassVar[tuple[str, ...]] = (DefaultStatusChoices.SEALED,)
    warn_on_save_outside_runner: ClassVar[bool] = True

    status: models.CharField = models.CharField(**default_status_field.deconstruct()[3])
    retry_at: models.DateTimeField = models.DateTimeField(**default_retry_at_field.deconstruct()[3])

    class Meta(TypedModelMeta):
        app_label = "workers"
        abstract = True

    FINAL_OR_ACTIVE_STATES: ClassVar[tuple[str, ...]] = (*FINAL_STATES, ACTIVE_STATE)

    @classmethod
    def status_counts(cls, queryset: models.QuerySet | None = None, statuses: Iterable[str] | None = None) -> dict[str, int]:
        qs = queryset if queryset is not None else cls.objects.all()
        return {status: qs.filter(status=status).count() for status in (statuses or cls.StatusChoices.values)}

    @property
    def RETRY_AT(self) -> datetime | None:
        return self.retry_at

    @RETRY_AT.setter
    def RETRY_AT(self, value: datetime | None) -> None:
        self.retry_at = value

    @property
    def STATE(self) -> str:
        return self.status

    @STATE.setter
    def STATE(self, value: str) -> None:
        self.status = value

    def bump_retry_at(self, seconds: int = 10) -> None:
        self.retry_at = timezone.now() + timedelta(seconds=seconds)

    @property
    def is_paused(self) -> bool:
        paused_state = getattr(self.StatusChoices, "PAUSED", None)
        return paused_state is not None and self.status == paused_state

    def safe_update(self, update_fields: dict[str, Any], *, refresh: bool = True, extra_filter: dict[str, Any] | None = None) -> bool:
        values = dict(update_fields)
        values.setdefault("modified_at", timezone.now())
        queryset = type(self).objects.filter(pk=self.pk)
        if extra_filter:
            queryset = queryset.filter(**extra_filter)
        updated = queryset.update(**values)
        if updated != 1 and extra_filter:
            current = type(self).objects.filter(pk=self.pk).values("status").first()
            logger.info(
                "SafeUpdateGuardMiss: %s row %s extra_filter=%s current_status=%s loaded_status=%s update_fields=%s skipped",
                type(self).__name__,
                self.pk,
                extra_filter,
                current.get("status") if current else "<deleted>",
                self.status,
                sorted(values),
            )
        if refresh:
            try:
                self.refresh_from_db()
            except type(self).DoesNotExist:
                pass
        return updated == 1

    def save(self, *args: Any, **kwargs: Any) -> None:
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
                    "%s.save() outside runner process: id=%s status=%s retry_at=%s process=%s root=%s caller=%s",
                    type(self).__name__,
                    self.pk,
                    self.status,
                    self.retry_at,
                    process.process_type,
                    root_type,
                    caller,
                )
        super().save(*args, **kwargs)

    def pause(self, *, save: bool = True) -> bool:
        paused_state = getattr(self.StatusChoices, "PAUSED", None)
        if paused_state is None or self.status in self.FINAL_STATES or self.is_paused:
            return False
        previous_status = self.status
        self.status = paused_state
        self.retry_at = RETRY_AT_MAX
        if save:
            return self.safe_update(
                {"status": paused_state, "retry_at": RETRY_AT_MAX},
                extra_filter={"status": previous_status},
            )
        return True

    def resume(self, *, when: datetime | None = None, save: bool = True) -> bool:
        paused_state = getattr(self.StatusChoices, "PAUSED", None)
        if paused_state is None or not self.is_paused:
            return False
        resume_at = when or timezone.now()
        self.status = self.StatusChoices.QUEUED
        self.retry_at = resume_at
        if save:
            return self.safe_update(
                {"status": self.StatusChoices.QUEUED, "retry_at": resume_at},
                extra_filter={"status": paused_state},
            )
        return True

    def update_and_requeue(self, *, refresh: bool = True, **kwargs: Any) -> bool:
        return self.safe_update(dict(kwargs), refresh=refresh, extra_filter={"retry_at": self.retry_at})

    @classmethod
    def get_queue(cls):
        return cls.objects.filter(retry_at__lte=timezone.now()).order_by("retry_at")

    @classmethod
    def claim_for_worker(cls, obj: "ModelWithQueue", lock_seconds: int = 60) -> bool:
        now = timezone.now()
        lock_until = now + timedelta(seconds=lock_seconds)
        updated = cls.objects.filter(pk=obj.pk, retry_at=obj.retry_at, retry_at__lte=now).update(
            retry_at=lock_until,
            modified_at=now,
        )
        if updated == 1:
            obj.retry_at = lock_until
            cast(Any, obj).modified_at = now
        return updated == 1

    def claim_processing_lock(self, lock_seconds: int = 60) -> bool:
        if self.status in self.FINAL_STATES or self.retry_at is None:
            return False
        return type(self).claim_for_worker(self, lock_seconds=lock_seconds)

    @classmethod
    def extend_choices(cls, base_choices: type[models.TextChoices]):
        assert issubclass(base_choices, models.TextChoices)

        def wrapper(extra_choices: type[models.TextChoices]) -> type[models.TextChoices]:
            joined = {value: label for value, label in (*base_choices.choices, *extra_choices.choices)}
            choices = models.TextChoices("StatusChoices", joined)
            assert isinstance(choices, type)
            return choices

        return wrapper

    @classmethod
    def StatusField(cls, **kwargs: Any) -> models.CharField:
        return models.CharField(**{**default_status_field.deconstruct()[3], **kwargs})

    @classmethod
    def RetryAtField(cls, **kwargs: Any) -> models.DateTimeField:
        return models.DateTimeField(**{**default_retry_at_field.deconstruct()[3], **kwargs})
