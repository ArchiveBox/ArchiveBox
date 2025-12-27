"""Base models using UUIDv7 for all id fields."""

__package__ = 'archivebox.base_models'

import io
import csv
import json
from uuid import uuid7, UUID
from typing import Any, Iterable, ClassVar
from pathlib import Path

from django.contrib import admin
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.urls import reverse_lazy
from django.conf import settings

from django_stubs_ext.db.models import TypedModelMeta

from archivebox import DATA_DIR
from archivebox.misc.util import to_json
from archivebox.misc.hashing import get_dir_info


def get_or_create_system_user_pk(username='system'):
    User = get_user_model()
    # If there's exactly one superuser, use that for all system operations
    if User.objects.filter(is_superuser=True).count() == 1:
        return User.objects.filter(is_superuser=True).values_list('pk', flat=True)[0]
    # Otherwise get or create the system user
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={'is_staff': True, 'is_superuser': True, 'email': '', 'password': '!'}
    )
    return user.pk


class AutoDateTimeField(models.DateTimeField):
    """DateTimeField that automatically updates on save (legacy compatibility)."""
    def pre_save(self, model_instance, add):
        if add or not getattr(model_instance, self.attname):
            value = timezone.now()
            setattr(model_instance, self.attname, value)
            return value
        return super().pre_save(model_instance, add)


class ModelWithUUID(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False, db_index=True)

    class Meta(TypedModelMeta):
        abstract = True

    def __str__(self):
        return f'[{self.id}] {self.__class__.__name__}'

    @property
    def admin_change_url(self) -> str:
        return f"/admin/{self._meta.app_label}/{self._meta.model_name}/{self.pk}/change/"

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_any', args=[self.id])

    @property
    def api_docs_url(self) -> str:
        return f'/api/v1/docs#/{self._meta.app_label.title()}%20Models/api_v1_{self._meta.app_label}_get_{self._meta.db_table}'

    def as_json(self, keys: Iterable[str] = ()) -> dict:
        default_keys = ('id', 'created_at', 'modified_at', 'created_by_id')
        return {key: getattr(self, key) for key in (keys or default_keys) if hasattr(self, key)}


class ModelWithSerializers(ModelWithUUID):
    class Meta(TypedModelMeta):
        abstract = True

    def as_csv_row(self, keys: Iterable[str] = (), separator: str = ',') -> str:
        buffer = io.StringIO()
        csv.writer(buffer, delimiter=separator).writerow(str(getattr(self, key, '')) for key in (keys or self.as_json().keys()))
        return buffer.getvalue()

    def as_jsonl_row(self, keys: Iterable[str] = (), **json_kwargs) -> str:
        return json.dumps({key: getattr(self, key, '') for key in (keys or self.as_json().keys())}, sort_keys=True, indent=None, **json_kwargs)


class ModelWithNotes(models.Model):
    """Mixin for models with a notes field."""
    notes = models.TextField(blank=True, null=False, default='')

    class Meta:
        abstract = True


class ModelWithHealthStats(models.Model):
    """Mixin for models with health tracking fields."""
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True

    @property
    def health(self) -> int:
        total = max(self.num_uses_failed + self.num_uses_succeeded, 1)
        return round((self.num_uses_succeeded / total) * 100)


class ModelWithConfig(models.Model):
    """Mixin for models with a JSON config field."""
    config = models.JSONField(default=dict, null=False, blank=False, editable=True)

    class Meta:
        abstract = True


class ModelWithOutputDir(ModelWithSerializers):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.save_json_index()

    @property
    def output_dir_parent(self) -> str:
        return f'{self._meta.model_name}s'

    @property
    def output_dir_name(self) -> str:
        return str(self.id)

    @property
    def output_dir_str(self) -> str:
        return f'{self.output_dir_parent}/{self.output_dir_name}'

    @property
    def OUTPUT_DIR(self) -> Path:
        return DATA_DIR / self.output_dir_str

    def save_json_index(self):
        (self.OUTPUT_DIR / 'index.json').write_text(to_json(self.as_json()))
