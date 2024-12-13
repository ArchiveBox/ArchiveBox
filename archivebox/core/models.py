__package__ = 'archivebox.core'


from typing import Optional, Dict, Iterable, Any
from django_stubs_ext.db.models import TypedModelMeta

import os
import json

from pathlib import Path

from django.db import models
from django.db.models import QuerySet
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.utils import timezone
from django.core.cache import cache
from django.urls import reverse, reverse_lazy
from django.db.models import Case, When, IntegerField
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
    ABIDModel, ABIDField, AutoDateTimeField, get_or_create_system_user_pk,
    ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags  # ModelWithStateMachine
    ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats
)
from workers.models import ModelWithStateMachine
from workers.tasks import bg_archive_snapshot
from tags.models import KVTag
# from machine.models import Machine, NetworkInterface



class Tag(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ABIDModel):
    """
    Old tag model, loosely based on django-taggit model + ABID base.
    
    Being phazed out in favor of archivebox.tags.models.ATag
    """
    abid_prefix = 'tag_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.slug'
    abid_subtype_src = '"03"'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    read_only_fields = ('id', 'abid', 'created_at', 'created_by', 'slug')

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False, related_name='tag_set')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    name = models.CharField(unique=True, blank=False, max_length=100)
    slug = models.SlugField(unique=True, blank=False, max_length=100, editable=False)
    # slug is autoset on save from name, never set it manually

    snapshot_set: models.Manager['Snapshot']
    # crawl_set: models.Manager['Crawl']

    class Meta(TypedModelMeta):
        verbose_name = "Tag"
        verbose_name_plural = "Tags"

    def __str__(self):
        return self.name

    def slugify(self, tag, i=None):
        slug = slugify(tag)
        if i is not None:
            slug += "_%d" % i
        return slug
    
    def clean(self, *args, **kwargs):
        self.slug = self.slug or self.slugify(self.name)
        super().clean(*args, **kwargs)

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.slug = self.slugify(self.name)

            # if name is different but slug conficts with another tags slug, append a counter
            # with transaction.atomic():
            slugs = set(
                type(self)
                ._default_manager.filter(slug__startswith=self.slug)
                .values_list("slug", flat=True)
            )

            i = None
            while True:
                slug = self.slugify(self.name, i)
                if slug not in slugs:
                    self.slug = slug
                    return super().save(*args, **kwargs)
                i = 1 if i is None else i+1
        else:
            return super().save(*args, **kwargs)
        
    @property
    def api_url(self) -> str:
        # /api/v1/core/snapshot/{uulid}
        return reverse_lazy('api-1:get_tag', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_tag'



class SnapshotTag(models.Model):
    id = models.AutoField(primary_key=True)

    snapshot = models.ForeignKey('Snapshot', db_column='snapshot_id', on_delete=models.CASCADE, to_field='id')
    tag = models.ForeignKey(Tag, db_column='tag_id', on_delete=models.CASCADE, to_field='id')

    class Meta:
        db_table = 'core_snapshot_tags'
        unique_together = [('snapshot', 'tag')]


class Seed(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags, ABIDModel, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats):
    """
    A fountain that produces URLs (+metadata) each time it's queried e.g.
        - file:///data/sources/2024-01-02_11-57-51__cli_add.txt
        - file:///data/sources/2024-01-02_11-57-51__web_ui_add.txt
        - file:///Users/squash/Library/Application Support/Google/Chrome/Default/Bookmarks
        - https://getpocket.com/user/nikisweeting/feed
        - https://www.iana.org/assignments/uri-schemes/uri-schemes.xhtml
        - ...
    Each query of a Seed can produce the same list of URLs, or a different list each time.
    The list of URLs it returns is used to create a new Crawl and seed it with new pending Snapshots.
        
    When a crawl is created, a root_snapshot is initially created with a URI set to the Seed URI.
    The seed's preferred extractor is executed on that URI, which produces an ArchiveResult containing outlinks.
    The outlinks then get turned into new pending Snapshots under the same crawl,
    and the cycle repeats until Crawl.max_depth.

    Each consumption of a Seed by an Extractor can produce new urls, as Seeds can point to
    stateful remote services, files with contents that change, directories that have new files within, etc.
    """
    
    ### ModelWithReadOnlyFields:
    read_only_fields = ('id', 'abid', 'created_at', 'created_by', 'uri')
    
    ### Immutable fields
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)                  # unique source location where URLs will be loaded from
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    
    ### Mutable fields:
    extractor = models.CharField(default='auto', max_length=32, help_text='The parser / extractor to use to load URLs from this source (default: auto)')
    tags_str = models.CharField(max_length=255, null=False, blank=True, default='', help_text='An optional comma-separated list of tags to attach to any URLs that come from this source')
    label = models.CharField(max_length=255, null=False, blank=True, default='', help_text='A human-readable label for this seed')
    modified_at = models.DateTimeField(auto_now=True)

    ### ModelWithConfig:
    config = models.JSONField(default=dict, help_text='An optional JSON object containing extra config to put in scope when loading URLs from this source')

    ### ModelWithOutputDir:
    output_dir = models.CharField(max_length=255, null=False, blank=True, default='', help_text='The directory to store the output of this seed')

    ### ModelWithNotes:
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this seed should have')

    ### ModelWithKVTags:
    tag_set = GenericRelation(
        KVTag,
        related_query_name="seed",
        content_type_field="obj_type",
        object_id_field="obj_id",
        order_by=('name',),
    )
    
    ### ABIDModel:
    abid_prefix = 'src_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.uri'
    abid_subtype_src = 'self.extractor'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    ### Managers:
    crawl_set: models.Manager['Crawl']

    class Meta:
        verbose_name = 'Seed'
        verbose_name_plural = 'Seeds'
        
        unique_together = (('created_by', 'uri', 'extractor'),('created_by', 'label'))


    @classmethod
    def from_file(cls, source_file: Path, label: str='', parser: str='auto', tag: str='', created_by: int|None=None, config: dict|None=None):
        source_path = str(source_file.resolve()).replace(str(CONSTANTS.DATA_DIR), '/data')
        
        seed, _ = cls.objects.get_or_create(
            label=label or source_file.name,
            uri=f'file://{source_path}',
            created_by_id=getattr(created_by, 'pk', created_by) or get_or_create_system_user_pk(),
            extractor=parser,
            tags_str=tag,
            config=config or {},
        )
        seed.save()
        return seed

    @property
    def source_type(self):
        # e.g. http/https://
        #      file://
        #      pocketapi://
        #      s3://
        #      etc..
        return self.uri.split('://', 1)[0].lower()

    @property
    def api_url(self) -> str:
        # /api/v1/core/seed/{uulid}
        return reverse_lazy('api-1:get_seed', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_seed'

    @property
    def scheduled_crawl_set(self) -> QuerySet['CrawlSchedule']:
        from crawls.models import CrawlSchedule
        return CrawlSchedule.objects.filter(template__seed_id=self.pk)

    @property
    def snapshot_set(self) -> QuerySet['Snapshot']:
        from core.models import Snapshot
        
        crawl_ids = self.crawl_set.values_list('pk', flat=True)
        return Snapshot.objects.filter(crawl_id__in=crawl_ids)




class CrawlSchedule(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags, ABIDModel, ModelWithNotes, ModelWithHealthStats):
    """
    A record for a job that should run repeatedly on a given schedule.
    
    It pulls from a given Seed and creates a new Crawl for each scheduled run.
    The new Crawl will inherit all the properties of the crawl_template Crawl.
    """
    ### ModelWithReadOnlyFields:
    read_only_fields = ('id', 'abid', 'created_at', 'created_by', 'template_id')
    
    ### Immutable fields:
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    template: 'Crawl' = models.ForeignKey('Crawl', on_delete=models.CASCADE, null=False, blank=False, help_text='The base crawl that each new scheduled job should copy as a template')  # type: ignore
    
    ### Mutable fields
    schedule = models.CharField(max_length=64, blank=False, null=False, help_text='The schedule to run this crawl on in CRON syntax e.g. 0 0 * * * (see https://crontab.guru/)')
    is_enabled = models.BooleanField(default=True)
    label = models.CharField(max_length=64, blank=True, null=False, default='', help_text='A human-readable label for this scheduled crawl')
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this crawl should have')
    modified_at = models.DateTimeField(auto_now=True)
    
    ### ModelWithKVTags:
    tag_set = GenericRelation(
        KVTag,
        related_query_name="crawlschedule",
        content_type_field="obj_type",
        object_id_field="obj_id",
        order_by=('name',),
    )
    
    ### ABIDModel:
    abid_prefix = 'cws_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.template.seed.uri'
    abid_subtype_src = 'self.template.persona'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    ### Managers:
    crawl_set: models.Manager['Crawl']
    
    class Meta(TypedModelMeta):
        verbose_name = 'Scheduled Crawl'
        verbose_name_plural = 'Scheduled Crawls'
        
    def __str__(self) -> str:
        uri = (self.template and self.template.seed and self.template.seed.uri) or '<no url set>'
        crawl_label = self.label or (self.template and self.template.seed and self.template.seed.label) or 'Untitled Crawl'
        if self.id and self.template:
            return f'[{self.ABID}] {uri[:64]} @ {self.schedule} (Scheduled {crawl_label})'
        return f'[{self.abid_prefix}****not*saved*yet****] {uri[:64]} @ {self.schedule} (Scheduled {crawl_label})'
    
    @property
    def api_url(self) -> str:
        # /api/v1/core/crawlschedule/{uulid}
        return reverse_lazy('api-1:get_any', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_any'
    
    def save(self, *args, **kwargs):
        self.label = self.label or self.template.seed.label or self.template.seed.uri
        super().save(*args, **kwargs)
        
        # make sure the template crawl points to this schedule as its schedule
        self.template.schedule = self
        self.template.save()
        
    @property
    def snapshot_set(self) -> QuerySet['Snapshot']:
        from core.models import Snapshot
        
        crawl_ids = self.crawl_set.values_list('pk', flat=True)
        return Snapshot.objects.filter(crawl_id__in=crawl_ids)
    

class CrawlManager(models.Manager):
    pass

class CrawlQuerySet(models.QuerySet):
    """
    Enhanced QuerySet for Crawl that adds some useful methods.
    
    To get all the snapshots for a given set of Crawls:
        Crawl.objects.filter(seed__uri='https://example.com/some/rss.xml').snapshots() -> QuerySet[Snapshot]
    
    To get all the archiveresults for a given set of Crawls:
        Crawl.objects.filter(seed__uri='https://example.com/some/rss.xml').archiveresults() -> QuerySet[ArchiveResult]
    
    To export the list of Crawls as a CSV or JSON:
        Crawl.objects.filter(seed__uri='https://example.com/some/rss.xml').export_as_csv() -> str
        Crawl.objects.filter(seed__uri='https://example.com/some/rss.xml').export_as_json() -> str
    """
    def snapshots(self, **filter_kwargs) -> QuerySet['Snapshot']:
        return Snapshot.objects.filter(crawl_id__in=self.values_list('pk', flat=True), **filter_kwargs)
    
    def archiveresults(self) -> QuerySet['ArchiveResult']:
        return ArchiveResult.objects.filter(snapshot__crawl_id__in=self.values_list('pk', flat=True))
    
    def as_csv_str(self, keys: Iterable[str]=()) -> str:
        return '\n'.join(
            row.as_csv(keys=keys)
            for row in self.all()
        )
    
    def as_jsonl_str(self, keys: Iterable[str]=()) -> str:
        return '\n'.join([
            row.as_jsonl_row(keys=keys)
            for row in self.all()
        ])



class Crawl(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags, ABIDModel, ModelWithOutputDir, ModelWithConfig, ModelWithHealthStats, ModelWithStateMachine):
    """
    A single session of URLs to archive starting from a given Seed and expanding outwards. An "archiving session" so to speak.

    A new Crawl should be created for each loading from a Seed (because it can produce a different set of URLs every time its loaded).
    E.g. every scheduled import from an RSS feed should create a new Crawl, and more loadings from the same seed each create a new Crawl
    
    Every "Add" task triggered from the Web UI, CLI, or Scheduled Crawl should create a new Crawl with the seed set to a 
    file URI e.g. file:///sources/<date>_{ui,cli}_add.txt containing the user's input.
    """
    
    ### ModelWithReadOnlyFields:
    read_only_fields = ('id', 'abid', 'created_at', 'created_by', 'seed')
    
    ### Immutable fields:
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False)
    seed = models.ForeignKey(Seed, on_delete=models.PROTECT, related_name='crawl_set', null=False, blank=False)
    
    ### Mutable fields:
    urls = models.TextField(blank=True, null=False, default='', help_text='The log of URLs discovered in this crawl, one per line, should be 1:1 with snapshot_set')
    config = models.JSONField(default=dict)
    max_depth = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(4)])
    tags_str = models.CharField(max_length=1024, blank=True, null=False, default='')
    persona_id = models.UUIDField(null=True, blank=True)  # TODO: replace with self.persona = models.ForeignKey(Persona, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    label = models.CharField(max_length=64, blank=True, null=False, default='', help_text='A human-readable label for this crawl')
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this crawl should have')
    schedule = models.ForeignKey(CrawlSchedule, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    ### ModelWithKVTags:
    tag_set = GenericRelation(
        KVTag,
        related_query_name="crawl",
        content_type_field="obj_type",
        object_id_field="obj_id",
        order_by=('name',),
    )
    
    ### ModelWithStateMachine:
    state_machine_name = 'crawls.statemachines.CrawlMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED
    
    status = ModelWithStateMachine.StatusField(choices=StatusChoices, default=StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)

    ### ABIDModel:
    abid_prefix = 'cwl_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.seed.uri'
    abid_subtype_src = 'self.persona'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    ### Managers:    
    snapshot_set: models.Manager['Snapshot']
    
    # @property
    # def persona(self) -> Persona:
    #     # TODO: replace with self.persona = models.ForeignKey(Persona, on_delete=models.SET_NULL, null=True, blank=True, editable=True)
    #     return self.persona_id
    

    class Meta(TypedModelMeta):
        verbose_name = 'Crawl'
        verbose_name_plural = 'Crawls'
        
    def __str__(self):
        url = (self.seed and self.seed.uri) or '<no url set>'
        parser = (self.seed and self.seed.extractor) or 'auto'
        created_at = self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else '<no timestamp set>'
        if self.id and self.seed:
            return f'[{self.ABID}] {url[:64]} ({parser}) @ {created_at} ({self.label or "Untitled Crawl"})'
        return f'[{self.abid_prefix}****not*saved*yet****] {url[:64]} ({parser}) @ {created_at} ({self.label or "Untitled Crawl"})'
        
    @classmethod
    def from_seed(cls, seed: Seed, max_depth: int=0, persona: str='Default', tags_str: str='', config: dict|None=None, created_by: int|None=None):
        crawl, _ = cls.objects.get_or_create(
            seed=seed,
            max_depth=max_depth,
            tags_str=tags_str or seed.tags_str,
            persona=persona or seed.config.get('DEFAULT_PERSONA') or 'Default',
            config=seed.config or config or {},
            created_by_id=getattr(created_by, 'pk', created_by) or seed.created_by_id,
        )
        crawl.save()
        return crawl
        
    @property
    def template(self):
        """If this crawl was created under a ScheduledCrawl, returns the original template Crawl it was based off"""
        if not self.schedule:
            return None
        return self.schedule.template

    @property
    def api_url(self) -> str:
        # /api/v1/core/crawl/{uulid}
        # TODO: implement get_crawl
        return reverse_lazy('api-1:get_crawl', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_crawl'
    
    def pending_snapshots(self) -> QuerySet['Snapshot']:
        return self.snapshot_set.filter(retry_at__isnull=False)
    
    def pending_archiveresults(self) -> QuerySet['ArchiveResult']:
        from core.models import ArchiveResult
        
        snapshot_ids = self.snapshot_set.values_list('id', flat=True)
        pending_archiveresults = ArchiveResult.objects.filter(snapshot_id__in=snapshot_ids, retry_at__isnull=False)
        return pending_archiveresults
    
    def create_root_snapshot(self) -> 'Snapshot':
        print(f'Crawl[{self.ABID}].create_root_snapshot()')
        from core.models import Snapshot
        
        try:
            return Snapshot.objects.get(crawl=self, url=self.seed.uri)
        except Snapshot.DoesNotExist:
            pass

        root_snapshot, _ = Snapshot.objects.update_or_create(
            crawl=self,
            url=self.seed.uri,
            defaults={
                'status': Snapshot.INITIAL_STATE,
                'retry_at': timezone.now(),
                'timestamp': str(timezone.now().timestamp()),
                # 'config': self.seed.config,
            },
        )
        root_snapshot.save()
        return root_snapshot


class Outlink(ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags):
    """A record of a link found on a page, pointing to another page."""
    read_only_fields = ('id', 'src', 'dst', 'crawl', 'via')
    
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    
    src = models.URLField()   # parent page where the outlink/href was found       e.g. https://example.com/downloads
    dst = models.URLField()   # remote location the child outlink/href points to   e.g. https://example.com/downloads/some_file.pdf
    
    crawl = models.ForeignKey(Crawl, on_delete=models.CASCADE, null=False, blank=False, related_name='outlink_set')
    via = models.ForeignKey('core.ArchiveResult', on_delete=models.SET_NULL, null=True, blank=True, related_name='outlink_set')

    class Meta:
        unique_together = (('src', 'dst', 'via'),)




def validate_timestamp(value):
    assert isinstance(value, str) and value, f'timestamp must be a non-empty string, got: "{value}"'
    assert value.replace('.', '').isdigit(), f'timestamp must be a float str, got: "{value}"'

class SnapshotManager(models.Manager):
    def filter(self, *args, **kwargs):
        """add support for .filter(domain='example.com') to Snapshot queryset"""
        domain = kwargs.pop('domain', None)
        qs = super().filter(*args, **kwargs)
        if domain:
            qs = qs.filter(url__icontains=f'://{domain}')
        return qs
    
    def get_queryset(self):
        return (
            super().get_queryset()
                .prefetch_related('tags', 'archiveresult_set') 
                # .annotate(archiveresult_count=models.Count('archiveresult')).distinct()
        )


class Snapshot(
    ModelWithReadOnlyFields,
    ModelWithSerializers,
    ModelWithUUID,
    ModelWithKVTags,
    ABIDModel,
    ModelWithOutputDir,
    ModelWithConfig,
    ModelWithNotes,
    ModelWithHealthStats,
    ModelWithStateMachine,
):
    
    ### ModelWithSerializers
    # cls.from_dict() -> Self
    # self.as_json() -> dict[str, Any]
    # self.as_jsonl_row() -> str
    # self.as_csv_row() -> str
    # self.as_html_icon(), .as_html_embed(), .as_html_row(), ...
    
    ### ModelWithReadOnlyFields
    read_only_fields = ('id', 'abid', 'created_at', 'created_by_id', 'url', 'timestamp', 'bookmarked_at', 'crawl_id')
    
    ### Immutable fields:
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='snapshot_set', db_index=True)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)  # loaded from self._init_timestamp
    
    url = models.URLField(unique=True, db_index=True)
    timestamp = models.CharField(max_length=32, unique=True, db_index=True, editable=False, validators=[validate_timestamp])
    bookmarked_at = AutoDateTimeField(default=None, null=False, editable=True, db_index=True)
    crawl: Crawl = models.ForeignKey(Crawl, on_delete=models.CASCADE, default=None, null=True, blank=True, related_name='snapshot_set', db_index=True)  # type: ignore
    
    ### Mutable fields:
    title = models.CharField(max_length=512, null=True, blank=True, db_index=True)
    downloaded_at = models.DateTimeField(default=None, null=True, editable=False, db_index=True, blank=True)
    modified_at = models.DateTimeField(auto_now=True)
    
    ### ModelWithStateMachine
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)
    status = ModelWithStateMachine.StatusField(choices=StatusChoices, default=StatusChoices.QUEUED)
    
    ### ModelWithConfig
    config = models.JSONField(default=dict, null=False, blank=False, editable=True)
    
    ### ModelWithNotes
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this snapshot should have')

    ### ModelWithOutputDir
    output_dir = models.FilePathField(path=CONSTANTS.ARCHIVE_DIR, recursive=True, match='.*', default=None, null=True, blank=True, editable=True)
    # self.output_dir_parent -> str 'archive/snapshots/<YYYY-MM-DD>/<example.com>'
    # self.output_dir_name -> '<abid>'
    # self.output_dir_str -> 'archive/snapshots/<YYYY-MM-DD>/<example.com>/<abid>'
    # self.OUTPUT_DIR -> Path('/data/archive/snapshots/<YYYY-MM-DD>/<example.com>/<abid>')
    # self.save(): creates OUTPUT_DIR, writes index.json, writes indexes
    
    # old-style tags (dedicated ManyToMany Tag model above):
    tags = models.ManyToManyField(Tag, blank=True, through=SnapshotTag, related_name='snapshot_set', through_fields=('snapshot', 'tag'))
    
    # new-style tags (new key-value tags defined by tags.models.KVTag & ModelWithKVTags):
    kvtag_set = tag_set = GenericRelation(
        KVTag,
        related_query_name="snapshot",
        content_type_field="obj_type",
        object_id_field="obj_id",
        order_by=('created_at',),
    )
    
    ### ABIDModel
    abid_prefix = 'snp_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.url'
    abid_subtype_src = '"01"'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    # self.clean() -> sets self._timestamp
    # self.save() -> issues new ABID if creating new, otherwise uses existing ABID
    # self.ABID -> ABID
    # self.api_url -> '/api/v1/core/snapshot/{uulid}'
    # self.api_docs_url -> '/api/v1/docs#/Core%20Models/api_v1_core_get_snapshot'
    # self.admin_change_url -> '/admin/core/snapshot/{pk}/change/'
    # self.get_absolute_url() -> '/{self.archive_path}'
    # self.update_for_workers() -> bool
    
    ### ModelWithStateMachine
    state_machine_name = 'core.statemachines.SnapshotMachine'
    state_field_name = 'status'
    retry_at_field_name = 'retry_at'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED
    
    ### Relations & Managers
    objects = SnapshotManager()
    archiveresult_set: models.Manager['ArchiveResult']
    
    def save(self, *args, **kwargs):
        print(f'Snapshot[{self.ABID}].save()')
        if self.pk:
            existing_snapshot = self.__class__.objects.filter(pk=self.pk).first()
            if existing_snapshot and existing_snapshot.status == self.StatusChoices.SEALED:
                if self.as_json() != existing_snapshot.as_json():
                    raise Exception(f'Snapshot {self.pk} is already sealed, it cannot be modified any further. NEW: {self.as_json()} != Existing: {existing_snapshot.as_json()}')
        
        if not self.bookmarked_at:
            self.bookmarked_at = self.created_at or self._init_timestamp
            
        if not self.timestamp:
            self.timestamp = str(self.bookmarked_at.timestamp())

        super().save(*args, **kwargs)
        
        # make sure the crawl has this url in its urls log
        if self.crawl and self.url not in self.crawl.urls:
            self.crawl.urls += f'\n{self.url}'
            self.crawl.save()
            
            
    def output_dir_parent(self) -> str:
        return 'archive'
    
    def output_dir_name(self) -> str:
        return str(self.timestamp)

    def archive(self, overwrite=False, methods=None):
        result = bg_archive_snapshot(self, overwrite=overwrite, methods=methods)
        return result

    def __repr__(self) -> str:
        url = self.url or '<no url set>'
        created_at = self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else '<no timestamp set>'
        if self.id and self.url:
            return f'[{self.ABID}] {url[:64]} @ {created_at}'
        return f'[{self.abid_prefix}****not*saved*yet****] {url[:64]} @ {created_at}'

    def __str__(self) -> str:
        return repr(self)

    @classmethod
    def from_json(cls, fields: dict[str, Any]) -> Self:
        # print('LEGACY from_json()')
        return cls.from_dict(fields)

    def as_json(self, *args, **kwargs) -> dict:
        json_dict = super().as_json(*args, **kwargs)
        if 'tags' in json_dict:
            json_dict['tags'] = self.tags_str(nocache=False)
        return json_dict

    def as_link(self) -> Link:
        return Link.from_json(self.as_json())

    def as_link_with_details(self) -> Link:
        from ..index import load_link_details
        return load_link_details(self.as_link())

    @admin.display(description='Tags')
    def tags_str(self, nocache=True) -> str | None:
        calc_tags_str = lambda: ','.join(sorted(tag.name for tag in self.tags.all()))
        cache_key = f'{self.pk}-{(self.downloaded_at or self.bookmarked_at).timestamp()}-tags'
        
        if hasattr(self, '_prefetched_objects_cache') and 'tags' in self._prefetched_objects_cache:
            # tags are pre-fetched already, use them directly (best because db is always freshest)
            tags_str = calc_tags_str()
            return tags_str
        
        if nocache:
            tags_str = calc_tags_str()
            cache.set(cache_key, tags_str)
            return tags_str
        return cache.get_or_set(cache_key, calc_tags_str)

    def icons(self) -> str:
        return snapshot_icons(self)
    
    @property
    def api_url(self) -> str:
        # /api/v1/core/snapshot/{uulid}
        return reverse_lazy('api-1:get_snapshot', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'
    
    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_snapshot'
    
    def get_absolute_url(self):
        return f'/{self.archive_path}'
    
    @cached_property
    def title_stripped(self) -> str:
        return (self.title or '').replace("\n", " ").replace("\r", "")

    @cached_property
    def extension(self) -> str:
        from archivebox.misc.util import extension
        return extension(self.url)

    @cached_property
    def bookmarked(self):
        return parse_date(self.timestamp)

    @cached_property
    def bookmarked_date(self):
        # TODO: remove this
        return self.bookmarked
    
    @cached_property
    def domain(self) -> str:
        return url_domain(self.url)

    @cached_property
    def is_archived(self):
        return self.as_link().is_archived

    @cached_property
    def num_outputs(self) -> int:
        # DONT DO THIS: it will trigger a separate query for every snapshot
        # return self.archiveresult_set.filter(status='succeeded').count()
        # this is better:
        return sum((1 for result in self.archiveresult_set.all() if result.status == 'succeeded'))

    @cached_property
    def base_url(self):
        return base_url(self.url)

    @cached_property
    def link_dir(self):
        return str(CONSTANTS.ARCHIVE_DIR / self.timestamp)

    @cached_property
    def archive_path(self):
        return '{}/{}'.format(CONSTANTS.ARCHIVE_DIR_NAME, self.timestamp)

    @cached_property
    def archive_size(self):
        cache_key = f'{str(self.pk)[:12]}-{(self.downloaded_at or self.bookmarked_at).timestamp()}-size'

        def calc_dir_size():
            try:
                return get_dir_size(self.link_dir)[0]
            except Exception:
                return 0

        return cache.get_or_set(cache_key, calc_dir_size)

    @cached_property
    def thumbnail_url(self) -> Optional[str]:
        if hasattr(self, '_prefetched_objects_cache') and 'archiveresult_set' in self._prefetched_objects_cache:
            result = (sorted(
                (
                    result
                    for result in self.archiveresult_set.all()
                    if result.extractor == 'screenshot' and result.status =='succeeded' and result.output
                ),
                key=lambda result: result.created_at,
            ) or [None])[-1]
        else:
            result = self.archiveresult_set.filter(
                extractor='screenshot',
                status='succeeded'
            ).only('output').last()

        if result:
            return reverse('Snapshot', args=[f'{str(self.timestamp)}/{result.output}'])
        return None

    @cached_property
    def headers(self) -> Optional[Dict[str, str]]:
        try:
            return json.loads((Path(self.link_dir) / 'headers.json').read_text(encoding='utf-8').strip())
        except Exception:
            pass
        return None

    @cached_property
    def status_code(self) -> Optional[str]:
        return self.headers.get('Status-Code') if self.headers else None

    @cached_property
    def history(self) -> dict:
        # TODO: use ArchiveResult for this instead of json
        return self.as_link_with_details().history

    @cached_property
    def latest_title(self) -> Optional[str]:
        if self.title:
            return self.title   # whoopdedoo that was easy

        # check if ArchiveResult set has already been prefetched, if so use it instead of fetching it from db again
        if hasattr(self, '_prefetched_objects_cache') and 'archiveresult_set' in self._prefetched_objects_cache:
            try:
                return (sorted(
                    (
                        result.output.strip()
                        for result in self.archiveresult_set.all()
                        if result.extractor == 'title' and result.status =='succeeded' and result.output
                    ),
                    key=lambda title: len(title),
                ) or [None])[-1]
            except IndexError:
                pass


        try:
            # take longest successful title from ArchiveResult db history
            return sorted(
                self.archiveresult_set\
                    .filter(extractor='title', status='succeeded', output__isnull=False)\
                    .values_list('output', flat=True),
                key=lambda r: len(r),
            )[-1]
        except IndexError:
            pass

        try:
            # take longest successful title from Link json index file history
            return sorted(
                (
                    result.output.strip()
                    for result in self.history['title']
                    if result.status == 'succeeded' and result.output.strip()
                ),
                key=lambda r: len(r),
            )[-1]
        except (KeyError, IndexError):
            pass

        return None
    
    def save_tags(self, tags: Iterable[str]=()) -> None:
        tags_id = []
        for tag in tags:
            if tag.strip():
                tags_id.append(Tag.objects.get_or_create(name=tag)[0].pk)
        self.tags.clear()
        self.tags.add(*tags_id)
        
    def pending_archiveresults(self) -> QuerySet['ArchiveResult']:
        pending_archiveresults = self.archiveresult_set.exclude(status__in=ArchiveResult.FINAL_OR_ACTIVE_STATES)
        return pending_archiveresults
    
    def create_pending_archiveresults(self) -> list['ArchiveResult']:
        ALL_EXTRACTORS = ['favicon', 'title', 'screenshot', 'headers', 'singlefile', 'dom', 'git', 'archive_org', 'readability', 'mercury', 'pdf', 'wget']
        
        # config = get_scope_config(snapshot=self)
        config = {'EXTRACTORS': ','.join(ALL_EXTRACTORS)}
        
        if config.get('EXTRACTORS', 'auto') == 'auto':
            EXTRACTORS = ALL_EXTRACTORS
        else:
            EXTRACTORS = config.get('EXTRACTORS', '').split(',')
        
        archiveresults = []
        for extractor in EXTRACTORS:
            if not extractor:
                continue
            if ArchiveResult.objects.filter(snapshot=self, extractor=extractor).exists():
                continue
            archiveresult, created = ArchiveResult.objects.get_or_create(
                snapshot=self,
                extractor=extractor,
                defaults={
                    'status': ArchiveResult.INITIAL_STATE,
                    'retry_at': timezone.now(),
                },
            )
            if archiveresult.status == ArchiveResult.INITIAL_STATE:
                archiveresults.append(archiveresult)
        return archiveresults
    

    # def migrate_output_dir(self):
    #     """Move the output files to the new folder structure if needed"""
    #     print(f'{self}.migrate_output_dir()')
    #     self.migrate_from_0_7_2()
    #     self.migrate_from_0_8_6()
    #     # ... future migrations here
    
    # def migrate_from_0_7_2(self):
    #     """Migrate the folder structure from 0.7.2 to the current version"""
    #     # migrate any existing output_dir into data/archiveresults/<extractor>/YYYY-MM-DD/<domain>/<abid>
    #     # create self.output_dir if it doesn't exist
    #     # move loose files in snapshot_dir into self.output_dir
    #     # update self.pwd = self.output_dir
    #     print(f'{self}.migrate_from_0_7_2()')
    
    # def migrate_from_0_8_6(self):
    #     """Migrate the folder structure from 0.8.6 to the current version"""
    #     # ... future migration code here ...
    #     print(f'{self}.migrate_from_0_8_6()')
            
    # def save_json_index(self):
    #     """Save the json index file to ./.index.json"""
    #     print(f'{self}.save_json_index()')
    #     pass
    
    # def save_symlinks_index(self):
    #     """Update the symlink farm idnexes to point to the new location of self.output_dir"""
    #     # ln -s self.output_dir data/index/results_by_type/wget/YYYY-MM-DD/example.com/<abid>
    #     # ln -s self.output_dir data/index/results_by_day/YYYY-MM-DD/example.com/wget/<abid>
    #     # ln -s self.output_dir data/index/results_by_domain/example.com/YYYY-MM-DD/wget/<abid>
    #     # ln -s self.output_dir data/index/results_by_abid/<abid>
    #     # ln -s self.output_dir data/archive/<snapshot_timestamp>/<extractor>
    #     print(f'{self}.save_symlinks_index()')
    
    # def save_html_index(self):
    #     """Save the html index file to ./.index.html"""
    #     print(f'{self}.save_html_index()')
    #     pass

    # def save_merkle_index(self):
    #     """Calculate the recursive sha256 of all the files in the output path and save it to ./.checksum.json"""
    #     print(f'{self}.save_merkle_index()')
    #     pass

    # def save_search_index(self):
    #     """Pass any indexable text to the search backend indexer (e.g. sonic, SQLiteFTS5, etc.)"""
    #     print(f'{self}.save_search_index()')
    #     pass

    # def get_storage_dir(self, create=True, symlink=True) -> Path:
    #     date_str = self.bookmarked_at.strftime('%Y%m%d')
    #     domain_str = domain(self.url)
    #     abs_storage_dir = Path(CONSTANTS.ARCHIVE_DIR) / 'snapshots' / date_str / domain_str / str(self.ulid)

    #     if create and not abs_storage_dir.is_dir():
    #         abs_storage_dir.mkdir(parents=True, exist_ok=True)

    #     if symlink:
    #         LINK_PATHS = [
    #             Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'all_by_id' / str(self.ulid),
    #             # Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'snapshots_by_id' / str(self.ulid),
    #             Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'snapshots_by_date' / date_str / domain_str / str(self.ulid),
    #             Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'snapshots_by_domain' / domain_str / date_str / str(self.ulid),
    #         ]
    #         for link_path in LINK_PATHS:
    #             link_path.parent.mkdir(parents=True, exist_ok=True)
    #             try:
    #                 link_path.symlink_to(abs_storage_dir)
    #             except FileExistsError:
    #                 link_path.unlink()
    #                 link_path.symlink_to(abs_storage_dir)

    #     return abs_storage_dir


class ArchiveResultManager(models.Manager):
    def indexable(self, sorted: bool = True):
        """Return only ArchiveResults containing text suitable for full-text search (sorted in order of typical result quality)"""

        INDEXABLE_METHODS = [ r[0] for r in ARCHIVE_METHODS_INDEXING_PRECEDENCE ]
        qs = self.get_queryset().filter(extractor__in=INDEXABLE_METHODS, status='succeeded')

        if sorted:
            precedence = [
                When(extractor=method, then=Value(precedence))
                for method, precedence in ARCHIVE_METHODS_INDEXING_PRECEDENCE
            ]
            qs = qs.annotate(
                indexing_precedence=Case(
                    *precedence,
                    default=Value(1000),
                    output_field=IntegerField()
                )
            ).order_by('indexing_precedence')
        return qs


class ArchiveResult(
    ModelWithReadOnlyFields, ModelWithSerializers, ModelWithUUID, ModelWithKVTags, ABIDModel,
    ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, ModelWithStateMachine
):
    ### ABIDModel
    abid_prefix = 'res_'
    abid_ts_src = 'self.snapshot.created_at'
    abid_uri_src = 'self.snapshot.url'
    abid_subtype_src = 'self.extractor'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True
    
    ### ModelWithStateMachine
    class StatusChoices(models.TextChoices):
        QUEUED = 'queued', 'Queued'                     # pending, initial
        STARTED = 'started', 'Started'                  # active
        
        BACKOFF = 'backoff', 'Waiting to retry'         # pending
        SUCCEEDED = 'succeeded', 'Succeeded'            # final
        FAILED = 'failed', 'Failed'                     # final
        SKIPPED = 'skipped', 'Skipped'                  # final
        
    state_machine_name = 'core.statemachines.ArchiveResultMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    active_state = StatusChoices.STARTED
    
    EXTRACTOR_CHOICES = (
        ('htmltotext', 'htmltotext'),
        ('git', 'git'),
        ('singlefile', 'singlefile'),
        ('media', 'media'),
        ('archive_org', 'archive_org'),
        ('readability', 'readability'),
        ('mercury', 'mercury'),
        ('favicon', 'favicon'),
        ('pdf', 'pdf'),
        ('headers', 'headers'),
        ('screenshot', 'screenshot'),
        ('dom', 'dom'),
        ('title', 'title'),
        ('wget', 'wget'),
    )
    
    ### ModelWithReadOnlyFields
    read_only_fields = ('id', 'abid', 'created_at', 'created_by', 'snapshot', 'extractor', 'pwd')

    ### Immutable fields:
    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='archiveresult_set', db_index=True)
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    
    snapshot: Snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)   # type: ignore
    extractor = models.CharField(choices=EXTRACTOR_CHOICES, max_length=32, blank=False, null=False, db_index=True)
    pwd = models.CharField(max_length=256, default=None, null=True, blank=True)
    

    ### Mutable fields:
    cmd = models.JSONField(default=None, null=True, blank=True)
    modified_at = models.DateTimeField(auto_now=True)
    cmd_version = models.CharField(max_length=128, default=None, null=True, blank=True)
    output = models.CharField(max_length=1024, default=None, null=True, blank=True)
    start_ts = models.DateTimeField(default=None, null=True, blank=True)
    end_ts = models.DateTimeField(default=None, null=True, blank=True)
    
    ### ModelWithStateMachine
    status = ModelWithStateMachine.StatusField(choices=StatusChoices.choices, default=StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)

    ### ModelWithNotes
    notes = models.TextField(blank=True, null=False, default='', help_text='Any extra notes this ArchiveResult should have')

    ### ModelWithHealthStats
    # ...

    ### ModelWithKVTags
    # tag_set = GenericRelation(KVTag, related_query_name='archiveresult')

    ### ModelWithOutputDir
    output_dir = models.CharField(max_length=256, default=None, null=True, blank=True)

    # machine = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Machine Used')
    iface = models.ForeignKey(NetworkInterface, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Network Interface Used')

    objects = ArchiveResultManager()
    
    keys = ('snapshot_id', 'extractor', 'cmd', 'pwd', 'cmd_version', 'output', 'start_ts', 'end_ts', 'created_at', 'status', 'retry_at', 'abid', 'id')

    class Meta(TypedModelMeta):
        verbose_name = 'Archive Result'
        verbose_name_plural = 'Archive Results Log'

    def __repr__(self):
        snapshot_id = getattr(self, 'snapshot_id', None)
        url = self.snapshot.url if snapshot_id else '<no url set>'
        created_at = self.snapshot.created_at.strftime("%Y-%m-%d %H:%M") if snapshot_id else '<no timestamp set>'
        extractor = self.extractor or '<no extractor set>'
        if self.id and snapshot_id:
            return f'[{self.ABID}] {url[:64]} @ {created_at} -> {extractor}'
        return f'[{self.abid_prefix}****not*saved*yet****] {url} @ {created_at} -> {extractor}'

    def __str__(self):
        return repr(self)
    
    def save(self, *args, write_indexes: bool=False, **kwargs):
        print(f'ArchiveResult[{self.ABID}].save()')
        # if (self.pk and self.__class__.objects.filter(pk=self.pk).values_list('status', flat=True)[0] in [self.StatusChoices.FAILED, self.StatusChoices.SUCCEEDED, self.StatusChoices.SKIPPED]):
        #     raise Exception(f'ArchiveResult {self.pk} is in a final state, it cannot be modified any further.')
        if self.pk:
            existing_archiveresult = self.__class__.objects.filter(pk=self.pk).first()
            if existing_archiveresult and existing_archiveresult.status in [self.StatusChoices.FAILED, self.StatusChoices.SUCCEEDED, self.StatusChoices.SKIPPED]:
                if self.as_json() != existing_archiveresult.as_json():
                    raise Exception(f'ArchiveResult {self.pk} is in a final state, it cannot be modified any further. NEW: {self.as_json()} != Existing: {existing_archiveresult.as_json()}')
        super().save(*args, **kwargs)
        # DONT DO THIS:
        # self.snapshot.update_for_workers()   # this should be done manually wherever its needed, not in here as a side-effect on save()


    # TODO: finish connecting machine.models
    # @cached_property
    # def machine(self):
    #     return self.iface.machine if self.iface else None

    @cached_property
    def snapshot_dir(self):
        return Path(self.snapshot.link_dir)
    
    @cached_property
    def url(self):
        return self.snapshot.url

    @property
    def api_url(self) -> str:
        # /api/v1/core/archiveresult/{uulid}
        return reverse_lazy('api-1:get_archiveresult', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_archiveresult'

    def get_absolute_url(self):
        return f'/{self.snapshot.archive_path}/{self.extractor}'

    @property
    def extractor_module(self) -> Any | None:
        return abx.as_dict(abx.pm.hook.get_EXTRACTORS()).get(self.extractor, None)

    @property
    def EXTRACTOR(self) -> object:
        # return self.extractor_module
        return self.extractor_module(archiveresult=self)

    def embed_path(self) -> str | None:
        """
        return the actual runtime-calculated path to the file on-disk that
        should be used for user-facing iframe embeds of this result
        """

        try:
            return self.extractor_module.get_embed_path(self)
        except Exception as e:
            print(f'Error getting embed path for {self.extractor} extractor: {e}')
            return None

    def legacy_output_path(self):
        return self.canonical_outputs().get(f'{self.extractor}_path')

    def output_exists(self) -> bool:
        output_path = Path(self.snapshot_dir) / self.extractor
        return os.path.exists(output_path)
            
    def create_output_dir(self):
        output_dir = Path(self.snapshot_dir) / self.extractor
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir
        
    def canonical_outputs(self) -> Dict[str, Optional[str]]:
        """Predict the expected output paths that should be present after archiving"""
        # You'll need to implement the actual logic based on your requirements
        # TODO: banish this awful duplication from the codebase and import these
        # from their respective extractor files


        from abx_plugin_favicon.config import FAVICON_CONFIG
        canonical = {
            'index_path': 'index.html',
            'favicon_path': 'favicon.ico',
            'google_favicon_path': FAVICON_CONFIG.FAVICON_PROVIDER.format(self.domain),
            'wget_path': f'warc/{self.timestamp}',
            'warc_path': 'warc/',
            'singlefile_path': 'singlefile.html',
            'readability_path': 'readability/content.html',
            'mercury_path': 'mercury/content.html',
            'htmltotext_path': 'htmltotext.txt',
            'pdf_path': 'output.pdf',
            'screenshot_path': 'screenshot.png',
            'dom_path': 'output.html',
            'archive_org_path': f'https://web.archive.org/web/{self.base_url}',
            'git_path': 'git/',
            'media_path': 'media/',
            'headers_path': 'headers.json',
        }
        
        if self.is_static:
            static_path = f'warc/{self.timestamp}'
            canonical.update({
                'title': self.basename,
                'wget_path': static_path,
                'pdf_path': static_path,
                'screenshot_path': static_path,
                'dom_path': static_path,
                'singlefile_path': static_path,
                'readability_path': static_path,
                'mercury_path': static_path,
                'htmltotext_path': static_path,
            })
        return canonical
        
    @property
    def output_dir_name(self) -> str:
        return self.extractor
        
    @property
    def output_dir_parent(self) -> str:
        return str(self.snapshot.OUTPUT_DIR.relative_to(CONSTANTS.DATA_DIR))
        
    @cached_property
    def output_files(self) -> dict[str, dict]:
        dir_info = get_dir_info(self.OUTPUT_DIR, max_depth=6)
        with open(self.OUTPUT_DIR / '.hashes.json', 'w') as f:
            json.dump(dir_info, f)
        return dir_info
    
    def announce_event(self, output_type: str, event: dict):
        event = {
            **event,
            'type': output_type,
        }
        
        # if event references a file, make sure it exists on disk
        if 'path' in event:
            file_path = Path(self.OUTPUT_DIR) / event['path']
            assert file_path.exists(), f'ArchiveResult[{self.ABID}].announce_event(): File does not exist: {file_path} ({event})'
            
        with open(self.OUTPUT_DIR / '.events.jsonl', 'a') as f:
            f.write(json.dumps(event, sort_keys=True, default=str) + '\n')
            
    def events(self, filter_type: str | None=None) -> list[dict]:
        events = []
        try:
            with open(self.OUTPUT_DIR / '.events.jsonl', 'r') as f:
                for line in f:
                    event = json.loads(line)
                    if filter_type is None or event['type'] == filter_type:
                        events.append(event)
        except FileNotFoundError:
            pass
        return events
        
    def write_indexes(self):
        """Write the ArchiveResult json, html, and merkle indexes to output dir, and pass searchable text to the search backend"""
        super().write_indexes()
        self.save_search_index()
        # self.save_outlinks_to_crawl()
        
    # def save_outlinks_to_crawl(self):
    #     """Save the output of this ArchiveResult to the Crawl's urls field"""
    #     if self.output_urls:
    #     self.snapshot.crawl.urls += f'\n{self.url}'
    #     self.snapshot.crawl.save()

    # def migrate_output_dir(self):
    #     """Move the output files to the new folder structure if needed"""
    #     print(f'{self}.migrate_output_dir()')
    #     self.migrate_from_0_7_2()
    #     self.migrate_from_0_8_6()
    #     # ... future migrations here
    
    # def migrate_from_0_7_2(self):
    #     """Migrate the folder structure from 0.7.2 to the current version"""
    #     # migrate any existing output_dir into data/archiveresults/<extractor>/YYYY-MM-DD/<domain>/<abid>
    #     # create self.output_dir if it doesn't exist
    #     # move loose files in snapshot_dir into self.output_dir
    #     # update self.pwd = self.output_dir
    #     print(f'{self}.migrate_from_0_7_2()')
    
    # def migrate_from_0_8_6(self):
    #     """Migrate the folder structure from 0.8.6 to the current version"""
    #     # ... future migration code here ...
    #     print(f'{self}.migrate_from_0_8_6()')
            
    # def save_json_index(self):
    #     """Save the json index file to ./.index.json"""
    #     print(f'{self}.save_json_index()')
    #     pass
    
    # def save_symlinks_index(self):
    #     """Update the symlink farm idnexes to point to the new location of self.output_dir"""
    #     # ln -s self.output_dir data/index/results_by_type/wget/YYYY-MM-DD/example.com/<abid>
    #     # ln -s self.output_dir data/index/results_by_day/YYYY-MM-DD/example.com/wget/<abid>
    #     # ln -s self.output_dir data/index/results_by_domain/example.com/YYYY-MM-DD/wget/<abid>
    #     # ln -s self.output_dir data/index/results_by_abid/<abid>
    #     # ln -s self.output_dir data/archive/<snapshot_timestamp>/<extractor>
    #     print(f'{self}.save_symlinks_index()')
    
    # def save_html_index(self):
    #     """Save the html index file to ./.index.html"""
    #     print(f'{self}.save_html_index()')
    #     pass

    # def save_merkle_index(self):
    #     """Calculate the recursive sha256 of all the files in the output path and save it to ./.checksum.json"""
    #     print(f'{self}.save_merkle_index()')
    #     pass

    def save_search_index(self):
        """Pass any indexable text to the search backend indexer (e.g. sonic, SQLiteFTS5, etc.)"""
        print(f'{self}.save_search_index()')
        pass


    # def get_storage_dir(self, create=True, symlink=True):
    #     date_str = self.snapshot.bookmarked_at.strftime('%Y%m%d')
    #     domain_str = domain(self.snapshot.url)
    #     abs_storage_dir = Path(CONSTANTS.ARCHIVE_DIR) / 'results' / date_str / domain_str / self.extractor / str(self.ulid)

    #     if create and not abs_storage_dir.is_dir():
    #         abs_storage_dir.mkdir(parents=True, exist_ok=True)

    #     if symlink:
    #         LINK_PATHS = [
    #             Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'all_by_id' / str(self.ulid),
    #             # Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'results_by_id' / str(self.ulid),
    #             # Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'results_by_date' / date_str / domain_str / self.extractor / str(self.ulid),
    #             Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'results_by_domain' / domain_str / date_str / self.extractor / str(self.ulid),
    #             Path(CONSTANTS.ARCHIVE_DIR).parent / 'index' / 'results_by_type' / self.extractor / date_str / domain_str / str(self.ulid),
    #         ]
    #         for link_path in LINK_PATHS:
    #             link_path.parent.mkdir(parents=True, exist_ok=True)
    #             try:
    #                 link_path.symlink_to(abs_storage_dir)
    #             except FileExistsError:
    #                 link_path.unlink()
    #                 link_path.symlink_to(abs_storage_dir)

    #     return abs_storage_dir

    # def symlink_index(self, create=True):
    #     abs_result_dir = self.get_storage_dir(create=create)





        
# @abx.hookimpl.on_archiveresult_created
# def exec_archiveresult_extractor_effects(archiveresult):
#     config = get_scope_config(...)
    
#     # abx.archivebox.writes.update_archiveresult_started(archiveresult, start_ts=timezone.now())
#     # abx.archivebox.events.on_archiveresult_updated(archiveresult)
    
#     # check if it should be skipped
#     if not abx.archivebox.reads.get_archiveresult_should_run(archiveresult, config):
#         abx.archivebox.writes.update_archiveresult_skipped(archiveresult, status='skipped')
#         abx.archivebox.events.on_archiveresult_skipped(archiveresult, config)
#         return
    
#     # run the extractor method and save the output back to the archiveresult
#     try:
#         output = abx.archivebox.effects.exec_archiveresult_extractor(archiveresult, config)
#         abx.archivebox.writes.update_archiveresult_succeeded(archiveresult, output=output, error=None, end_ts=timezone.now())
#     except Exception as e:
#         abx.archivebox.writes.update_archiveresult_failed(archiveresult, error=e, end_ts=timezone.now())
    
#     # bump the modified time on the archiveresult and Snapshot
#     abx.archivebox.events.on_archiveresult_updated(archiveresult)
#     abx.archivebox.events.on_snapshot_updated(archiveresult.snapshot)
    

# @abx.hookimpl.reads.get_outlink_parents
# def get_outlink_parents(url, crawl_pk=None, config=None):
#     scope = Q(dst=url)
#     if crawl_pk:
#         scope = scope | Q(via__snapshot__crawl_id=crawl_pk)
    
#     parent = list(Outlink.objects.filter(scope))
#     if not parent:
#         # base case: we reached the top of the chain, no more parents left
#         return []
    
#     # recursive case: there is another parent above us, get its parents
#     yield parent[0]
#     yield from get_outlink_parents(parent[0].src, crawl_pk=crawl_pk, config=config)


