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
from archivebox.index.json import to_json
from archivebox.misc.hashing import get_dir_info


def get_or_create_system_user_pk(username='system'):
    User = get_user_model()
    if User.objects.filter(is_superuser=True).count() == 1:
        return User.objects.filter(is_superuser=True).values_list('pk', flat=True)[0]
    user, _ = User.objects.get_or_create(username=username, is_staff=True, is_superuser=True, defaults={'email': '', 'password': ''})
    return user.pk


class ModelWithUUID(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, db_index=True)

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
    notes = models.TextField(blank=True, null=False, default='')

    class Meta:
        abstract = True


class ModelWithHealthStats(models.Model):
    num_uses_failed = models.PositiveIntegerField(default=0)
    num_uses_succeeded = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True

    @property
    def health(self) -> int:
        total = max(self.num_uses_failed + self.num_uses_succeeded, 1)
        return round((self.num_uses_succeeded / total) * 100)


class ModelWithConfig(models.Model):
    config = models.JSONField(default=dict, null=False, blank=False, editable=True)

    class Meta:
        abstract = True


class ModelWithOutputDir(ModelWithSerializers):
    class Meta:
        abstract = True

    def save(self, *args, write_indexes=False, **kwargs):
        super().save(*args, **kwargs)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.save_json_index()
        if write_indexes:
            self.write_indexes()

    @property
    def output_dir_parent(self) -> str:
        return getattr(self, 'output_dir_parent', f'{self._meta.model_name}s')

    @property
    def output_dir_name(self) -> str:
        return str(self.id)

    @property
    def output_dir_str(self) -> str:
        return f'{self.output_dir_parent}/{self.output_dir_name}'

    @property
    def OUTPUT_DIR(self) -> Path:
        return DATA_DIR / self.output_dir_str

    def write_indexes(self):
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.save_merkle_index()
        self.save_html_index()

    def save_merkle_index(self):
        with open(self.OUTPUT_DIR / '.hashes.json', 'w') as f:
            json.dump(get_dir_info(self.OUTPUT_DIR, max_depth=6), f)

    def save_html_index(self):
        (self.OUTPUT_DIR / 'index.html').write_text(str(self))

    def save_json_index(self):
        (self.OUTPUT_DIR / 'index.json').write_text(to_json(self.as_json()))
