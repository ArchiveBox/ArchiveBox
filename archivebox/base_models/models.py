"""Base models using UUIDv7 for all id fields."""

__package__ = "archivebox.base_models"

import json
import shutil
from typing import Any

from archivebox.uuid_compat import CompactUUIDField, uuid7
from pathlib import Path

from django.db import models
from django.db.models import F
from django.db import transaction
from django.db.models.signals import pre_delete
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from django.conf import settings

from django_stubs_ext.db.models import TypedModelMeta

from archivebox.config import CONSTANTS


def normalize_config_json_values(config: Any) -> Any:
    if not isinstance(config, dict):
        return config

    normalized = dict(config)
    for key, value in list(normalized.items()):
        if not isinstance(value, str) or len(value) < 2:
            continue
        if value[:1] != '"' or value[-1:] != '"':
            continue
        try:
            decoded = json.loads(value)
        except ValueError:
            continue
        if isinstance(decoded, str):
            normalized[key] = decoded
    return normalized


def get_or_create_system_user_pk(username="system"):
    User = get_user_model()
    # If there's exactly one superuser, use that for all system operations
    if User.objects.filter(is_superuser=True).count() == 1:
        return User.objects.filter(is_superuser=True).values_list("pk", flat=True)[0]
    # Otherwise get or create the system user
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"is_staff": True, "is_superuser": True, "email": "", "password": "!"},
    )
    return user.pk


class AutoDateTimeField(models.DateTimeField):
    """DateTimeField that automatically updates on save (legacy compatibility)."""

    def pre_save(self, model_instance, add):
        if add or self.attname not in model_instance.__dict__ or not model_instance.__dict__[self.attname]:
            value = timezone.now()
            setattr(model_instance, self.attname, value)
            return value
        return super().pre_save(model_instance, add)


class ModelWithUUID(models.Model):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        default=get_or_create_system_user_pk,
        null=False,
        db_index=True,
    )

    class Meta(TypedModelMeta):
        abstract = True

    def __str__(self) -> str:
        return f"[{self.id}] {self.__class__.__name__}"

    @property
    def admin_change_url(self) -> str:
        return f"/admin/{self._meta.app_label}/{self._meta.model_name}/{self.pk}/change/"

    @property
    def api_url(self) -> str:
        return str(reverse_lazy("api-1:get_any", args=[self.id]))

    @property
    def api_docs_url(self) -> str:
        return f"/api/v1/docs#/{self._meta.app_label.title()}%20Models/api_v1_{self._meta.app_label}_get_{self._meta.db_table}"


class ModelWithNotes(models.Model):
    """Mixin for models with a notes field."""

    notes = models.TextField(blank=True, null=False, default="")

    class Meta(TypedModelMeta):
        abstract = True


class ModelWithHealthStats(models.Model):
    """Mixin for models with health tracking fields."""

    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    class Meta(TypedModelMeta):
        abstract = True

    @property
    def admin_change_url(self) -> str:
        return f"/admin/{self._meta.app_label}/{self._meta.model_name}/{self.pk}/change/"

    @property
    def health(self) -> int:
        total = max(self.num_uses_failed + self.num_uses_succeeded, 1)
        return round((self.num_uses_succeeded / total) * 100)

    def increment_health_stats(self, success: bool):
        """Atomically increment success or failure counter using F() expression."""
        field = "num_uses_succeeded" if success else "num_uses_failed"
        type(self).objects.filter(pk=self.pk).update(
            **{
                field: F(field) + 1,
                "modified_at": timezone.now(),
            },
        )


class ModelWithConfig(models.Model):
    """Mixin for models with a JSON config field."""

    config = models.JSONField(default=dict, null=True, blank=True, editable=True)

    class Meta(TypedModelMeta):
        abstract = True

    def save(self, *args, **kwargs):
        normalized_config = normalize_config_json_values(self.config)
        if normalized_config != self.config:
            self.config = normalized_config
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = tuple(dict.fromkeys([*update_fields, "config"]))
        super().save(*args, **kwargs)


class ModelWithDeleteAfter(models.Model):
    delete_after_final_statuses: tuple[str, ...] = ()
    delete_at = models.DateTimeField(default=None, null=True, blank=True, db_index=True)

    class Meta(TypedModelMeta):
        abstract = True

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.delete_at is None:
            self.set_delete_at_from_config()
            if self.delete_at is not None and update_fields is not None:
                kwargs["update_fields"] = tuple(dict.fromkeys([*update_fields, "delete_at"]))
        super().save(*args, **kwargs)

    def get_delete_after_config_value(self):
        from archivebox.config.common import get_config

        return get_config(include_machine=False, resolve_plugins=False).DELETE_AFTER

    def set_delete_at_from_config(self, config_value=None) -> bool:
        if self.delete_at is not None:
            return False

        from archivebox.config.common import parse_delete_after

        duration = parse_delete_after(self.get_delete_after_config_value() if config_value is None else config_value)
        if duration is None:
            return False

        self.delete_at = (self.created_at or timezone.now()) + duration
        return True

    @classmethod
    def missing_delete_at_candidates(cls):
        return cls.objects.none()

    @classmethod
    def delete_expired(cls, *, batch_size: int = 100, backfill_missing: bool = True) -> int:
        if backfill_missing:
            missing_delete_at = list(cls.missing_delete_at_candidates().order_by("created_at", "pk")[:batch_size])
            for obj in missing_delete_at:
                if obj.set_delete_at_from_config():
                    cls.objects.filter(pk=obj.pk, delete_at__isnull=True).update(
                        delete_at=obj.delete_at,
                        modified_at=timezone.now(),
                    )

        # Keep the expiration sweep anchored on delete_at. Some large tables
        # have millions of final-status rows but almost no retained rows; adding
        # the status filter before SQLite has narrowed by delete_at can make the
        # runner scan the hot status index before it claims new work.
        due_pks = list(
            cls.objects.filter(delete_at__isnull=False, delete_at__lte=timezone.now())
            .order_by("delete_at", "pk")
            .values_list("pk", flat=True)[:batch_size],
        )
        if not due_pks:
            return 0

        queryset = cls.objects.filter(pk__in=due_pks)
        if cls.delete_after_final_statuses:
            queryset = queryset.filter(status__in=cls.delete_after_final_statuses)

        count = 0
        expired = list(queryset.order_by("delete_at", "pk"))
        for obj in expired:
            obj.delete()
            count += 1
        return count


class ModelWithOutputDir(ModelWithUUID):
    class Meta(ModelWithUUID.Meta):
        abstract = True

    _delete_signal_registered = False

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        output_dir = Path(self.output_dir)
        # Avoid holding SQLite write transactions open across slow filesystem work.
        transaction.on_commit(lambda: output_dir.mkdir(parents=True, exist_ok=True))
        # Note: index.json is deprecated, models should use write_index_jsonl() for full data

    @property
    def output_dir_parent(self) -> str:
        return f"{self._meta.model_name}s"

    @property
    def output_dir_name(self) -> str:
        return str(self.id)

    @property
    def output_dir_str(self) -> str:
        return f"{self.output_dir_parent}/{self.output_dir_name}"

    @property
    def output_dir(self) -> Path:
        raise NotImplementedError(f"{self.__class__.__name__} must implement output_dir property")

    def output_paths_for_delete(self) -> tuple[Path, ...]:
        return (Path(self.output_dir),)

    @classmethod
    def validate_output_paths_for_delete(cls, paths) -> tuple[Path, ...]:
        data_dir = CONSTANTS.DATA_DIR.resolve()
        safe_paths = []
        for raw_path in paths:
            path = Path(raw_path)
            is_safe = False
            for candidate in (path.absolute(), path.resolve()):
                try:
                    candidate.relative_to(data_dir)
                    is_safe = True
                    break
                except ValueError:
                    continue
            if not is_safe:
                raise ValueError(f"Refusing to delete output path outside DATA_DIR: {path}")
            safe_paths.append(path)
        return tuple(safe_paths)

    @classmethod
    def delete_output_paths(cls, paths) -> None:
        for path in cls.validate_output_paths_for_delete(paths):
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    def schedule_delete_cleanup(self, *, using: str | None = None) -> None:
        """Capture output paths before DB deletion and remove them after commit."""
        paths = self.validate_output_paths_for_delete(self.output_paths_for_delete())
        transaction.on_commit(lambda: self.delete_output_paths(paths), using=using)

    @classmethod
    def register_delete_signal(cls) -> None:
        if cls._delete_signal_registered:
            return

        def schedule_output_dir_cleanup(sender, instance, using, **kwargs):
            if not isinstance(instance, ModelWithOutputDir):
                return
            instance.schedule_delete_cleanup(using=using)

        pre_delete.connect(
            schedule_output_dir_cleanup,
            dispatch_uid="archivebox.output_dir_cleanup_on_delete",
            weak=False,
        )
        cls._delete_signal_registered = True
