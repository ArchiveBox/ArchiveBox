__package__ = 'archivebox.core'

from typing import Optional, Dict, Iterable, Any
from uuid import uuid7
from django_stubs_ext.db.models import TypedModelMeta

import os
import json
from pathlib import Path

from django.db import models
from django.db.models import QuerySet, Value, Case, When, IntegerField
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.utils import timezone
from django.core.cache import cache
from django.urls import reverse, reverse_lazy
from django.contrib import admin
from django.conf import settings

import abx

from archivebox.config import CONSTANTS
from archivebox.misc.system import get_dir_size
from archivebox.misc.util import parse_date, base_url, domain as url_domain
from archivebox.misc.hashing import get_dir_info
from archivebox.index.schema import Link
from archivebox.index.html import snapshot_icons
from archivebox.extractors import ARCHIVE_METHODS_INDEXING_PRECEDENCE
from archivebox.base_models.models import (
    ModelWithUUID, ModelWithSerializers, ModelWithOutputDir,
    ModelWithConfig, ModelWithNotes, ModelWithHealthStats,
    get_or_create_system_user_pk,
)
from workers.models import ModelWithStateMachine
from workers.tasks import bg_archive_snapshot
from crawls.models import Crawl
from machine.models import NetworkInterface


class Tag(ModelWithSerializers):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False, related_name='tag_set')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)
    name = models.CharField(unique=True, blank=False, max_length=100)
    slug = models.SlugField(unique=True, blank=False, max_length=100, editable=False)

    snapshot_set: models.Manager['Snapshot']

    class Meta(TypedModelMeta):
        verbose_name = "Tag"
        verbose_name_plural = "Tags"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.slug = slugify(self.name)
            existing = set(Tag.objects.filter(slug__startswith=self.slug).values_list("slug", flat=True))
            i = None
            while True:
                slug = f"{slugify(self.name)}_{i}" if i else slugify(self.name)
                if slug not in existing:
                    self.slug = slug
                    break
                i = (i or 0) + 1
        super().save(*args, **kwargs)

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_tag', args=[self.id])


class SnapshotTag(models.Model):
    id = models.AutoField(primary_key=True)
    snapshot = models.ForeignKey('Snapshot', db_column='snapshot_id', on_delete=models.CASCADE, to_field='id')
    tag = models.ForeignKey(Tag, db_column='tag_id', on_delete=models.CASCADE, to_field='id')

    class Meta:
        db_table = 'core_snapshot_tags'
        unique_together = [('snapshot', 'tag')]


class SnapshotManager(models.Manager):
    def filter(self, *args, **kwargs):
        domain = kwargs.pop('domain', None)
        qs = super().filter(*args, **kwargs)
        if domain:
            qs = qs.filter(url__icontains=f'://{domain}')
        return qs

    def get_queryset(self):
        return super().get_queryset().prefetch_related('tags', 'archiveresult_set')


class Snapshot(ModelWithSerializers, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, ModelWithStateMachine):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='snapshot_set', db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    url = models.URLField(unique=True, db_index=True)
    timestamp = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    bookmarked_at = models.DateTimeField(default=timezone.now, db_index=True)
    crawl: Crawl = models.ForeignKey(Crawl, on_delete=models.CASCADE, default=None, null=True, blank=True, related_name='snapshot_set', db_index=True)  # type: ignore

    title = models.CharField(max_length=512, null=True, blank=True, db_index=True)
    downloaded_at = models.DateTimeField(default=None, null=True, editable=False, db_index=True, blank=True)

    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)
    status = ModelWithStateMachine.StatusField(choices=ModelWithStateMachine.StatusChoices, default=ModelWithStateMachine.StatusChoices.QUEUED)
    config = models.JSONField(default=dict, null=False, blank=False, editable=True)
    notes = models.TextField(blank=True, null=False, default='')
    output_dir = models.FilePathField(path=CONSTANTS.ARCHIVE_DIR, recursive=True, match='.*', default=None, null=True, blank=True, editable=True)

    tags = models.ManyToManyField(Tag, blank=True, through=SnapshotTag, related_name='snapshot_set', through_fields=('snapshot', 'tag'))

    state_machine_name = 'core.statemachines.SnapshotMachine'
    state_field_name = 'status'
    retry_at_field_name = 'retry_at'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED

    objects = SnapshotManager()
    archiveresult_set: models.Manager['ArchiveResult']

    class Meta(TypedModelMeta):
        verbose_name = "Snapshot"
        verbose_name_plural = "Snapshots"

    def __str__(self):
        return f'[{self.id}] {self.url[:64]}'

    def save(self, *args, **kwargs):
        if not self.bookmarked_at:
            self.bookmarked_at = self.created_at or timezone.now()
        if not self.timestamp:
            self.timestamp = str(self.bookmarked_at.timestamp())
        super().save(*args, **kwargs)
        if self.crawl and self.url not in self.crawl.urls:
            self.crawl.urls += f'\n{self.url}'
            self.crawl.save()

    def output_dir_parent(self) -> str:
        return 'archive'

    def output_dir_name(self) -> str:
        return str(self.timestamp)

    def archive(self, overwrite=False, methods=None):
        return bg_archive_snapshot(self, overwrite=overwrite, methods=methods)

    def as_link(self) -> Link:
        return Link.from_json(self.as_json())

    @admin.display(description='Tags')
    def tags_str(self, nocache=True) -> str | None:
        calc_tags_str = lambda: ','.join(sorted(tag.name for tag in self.tags.all()))
        if hasattr(self, '_prefetched_objects_cache') and 'tags' in self._prefetched_objects_cache:
            return calc_tags_str()
        cache_key = f'{self.pk}-tags'
        return cache.get_or_set(cache_key, calc_tags_str) if not nocache else calc_tags_str()

    def icons(self) -> str:
        return snapshot_icons(self)

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_snapshot', args=[self.id])

    def get_absolute_url(self):
        return f'/{self.archive_path}'

    @cached_property
    def domain(self) -> str:
        return url_domain(self.url)

    @cached_property
    def link_dir(self):
        return str(CONSTANTS.ARCHIVE_DIR / self.timestamp)

    @cached_property
    def archive_path(self):
        return f'{CONSTANTS.ARCHIVE_DIR_NAME}/{self.timestamp}'

    @cached_property
    def archive_size(self):
        try:
            return get_dir_size(self.link_dir)[0]
        except Exception:
            return 0

    def save_tags(self, tags: Iterable[str] = ()) -> None:
        tags_id = [Tag.objects.get_or_create(name=tag)[0].pk for tag in tags if tag.strip()]
        self.tags.clear()
        self.tags.add(*tags_id)

    def pending_archiveresults(self) -> QuerySet['ArchiveResult']:
        return self.archiveresult_set.exclude(status__in=ArchiveResult.FINAL_OR_ACTIVE_STATES)

    def create_pending_archiveresults(self) -> list['ArchiveResult']:
        ALL_EXTRACTORS = ['favicon', 'title', 'screenshot', 'headers', 'singlefile', 'dom', 'git', 'archive_org', 'readability', 'mercury', 'pdf', 'wget']
        archiveresults = []
        for extractor in ALL_EXTRACTORS:
            if ArchiveResult.objects.filter(snapshot=self, extractor=extractor).exists():
                continue
            archiveresult, _ = ArchiveResult.objects.get_or_create(
                snapshot=self, extractor=extractor,
                defaults={'status': ArchiveResult.INITIAL_STATE, 'retry_at': timezone.now()},
            )
            if archiveresult.status == ArchiveResult.INITIAL_STATE:
                archiveresults.append(archiveresult)
        return archiveresults


class ArchiveResultManager(models.Manager):
    def indexable(self, sorted: bool = True):
        INDEXABLE_METHODS = [r[0] for r in ARCHIVE_METHODS_INDEXING_PRECEDENCE]
        qs = self.get_queryset().filter(extractor__in=INDEXABLE_METHODS, status='succeeded')
        if sorted:
            precedence = [When(extractor=method, then=Value(p)) for method, p in ARCHIVE_METHODS_INDEXING_PRECEDENCE]
            qs = qs.annotate(indexing_precedence=Case(*precedence, default=Value(1000), output_field=IntegerField())).order_by('indexing_precedence')
        return qs


class ArchiveResult(ModelWithSerializers, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, ModelWithStateMachine):
    class StatusChoices(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        STARTED = 'started', 'Started'
        BACKOFF = 'backoff', 'Waiting to retry'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'

    EXTRACTOR_CHOICES = (
        ('htmltotext', 'htmltotext'), ('git', 'git'), ('singlefile', 'singlefile'), ('media', 'media'),
        ('archive_org', 'archive_org'), ('readability', 'readability'), ('mercury', 'mercury'),
        ('favicon', 'favicon'), ('pdf', 'pdf'), ('headers', 'headers'), ('screenshot', 'screenshot'),
        ('dom', 'dom'), ('title', 'title'), ('wget', 'wget'),
    )

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='archiveresult_set', db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    snapshot: Snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)  # type: ignore
    extractor = models.CharField(choices=EXTRACTOR_CHOICES, max_length=32, blank=False, null=False, db_index=True)
    pwd = models.CharField(max_length=256, default=None, null=True, blank=True)
    cmd = models.JSONField(default=None, null=True, blank=True)
    cmd_version = models.CharField(max_length=128, default=None, null=True, blank=True)
    output = models.CharField(max_length=1024, default=None, null=True, blank=True)
    start_ts = models.DateTimeField(default=None, null=True, blank=True)
    end_ts = models.DateTimeField(default=None, null=True, blank=True)

    status = ModelWithStateMachine.StatusField(choices=StatusChoices.choices, default=StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)
    notes = models.TextField(blank=True, null=False, default='')
    output_dir = models.CharField(max_length=256, default=None, null=True, blank=True)
    iface = models.ForeignKey(NetworkInterface, on_delete=models.SET_NULL, null=True, blank=True)

    state_machine_name = 'core.statemachines.ArchiveResultMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    active_state = StatusChoices.STARTED

    objects = ArchiveResultManager()

    class Meta(TypedModelMeta):
        verbose_name = 'Archive Result'
        verbose_name_plural = 'Archive Results Log'

    def __str__(self):
        return f'[{self.id}] {self.snapshot.url[:64]} -> {self.extractor}'

    @cached_property
    def snapshot_dir(self):
        return Path(self.snapshot.link_dir)

    @cached_property
    def url(self):
        return self.snapshot.url

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_archiveresult', args=[self.id])

    def get_absolute_url(self):
        return f'/{self.snapshot.archive_path}/{self.extractor}'

    @property
    def extractor_module(self) -> Any | None:
        return abx.as_dict(abx.pm.hook.get_EXTRACTORS()).get(self.extractor, None)

    def output_exists(self) -> bool:
        return os.path.exists(Path(self.snapshot_dir) / self.extractor)

    def create_output_dir(self):
        output_dir = Path(self.snapshot_dir) / self.extractor
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    @property
    def output_dir_name(self) -> str:
        return self.extractor

    @property
    def output_dir_parent(self) -> str:
        return str(self.snapshot.OUTPUT_DIR.relative_to(CONSTANTS.DATA_DIR))

    def write_indexes(self):
        super().write_indexes()

    def save_search_index(self):
        pass
