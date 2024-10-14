__package__ = 'archivebox.core'


from typing import Optional, Dict, Iterable
from django_stubs_ext.db.models import TypedModelMeta

import os
import json

from pathlib import Path

from django.db import models
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.core.cache import cache
from django.urls import reverse, reverse_lazy
from django.db.models import Case, When, Value, IntegerField
from django.core.validators import MaxValueValidator, MinValueValidator 
from django.contrib import admin
from django.conf import settings

from archivebox.config import CONSTANTS

from abid_utils.models import ABIDModel, ABIDField, AutoDateTimeField
from queues.tasks import bg_archive_snapshot
# from machine.models import Machine, NetworkInterface

from archivebox.misc.system import get_dir_size
from archivebox.misc.util import parse_date, base_url
from ..index.schema import Link
from ..index.html import snapshot_icons
from ..extractors import ARCHIVE_METHODS_INDEXING_PRECEDENCE, EXTRACTORS
from ..parsers import PARSERS


# class BaseModel(models.Model):
#     # TODO: migrate all models to a shared base class with all our standard fields and helpers:
#     #       ulid/created_at/modified_at/created_by/is_deleted/as_json/from_json/etc.
#     #
#     # id = models.AutoField(primary_key=True, serialize=False, verbose_name='ID')
#     # ulid = models.CharField(max_length=26, null=True, blank=True, db_index=True, unique=True)

#     class Meta(TypedModelMeta):
#         abstract = True



class Tag(ABIDModel):
    """
    Based on django-taggit model + ABID base.
    """
    abid_prefix = 'tag_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.slug'
    abid_subtype_src = '"03"'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='tag_set')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    name = models.CharField(unique=True, blank=False, max_length=100)
    slug = models.SlugField(unique=True, blank=False, max_length=100, editable=False)
    # slug is autoset on save from name, never set it manually

    snapshot_set: models.Manager['Snapshot']
    crawl_set: models.Manager['Crawl']

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

    def save(self, *args, **kwargs):
        if self._state.adding and not self.slug:
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


# class CrawlTag(models.Model):
#     id = models.AutoField(primary_key=True)

#     crawl = models.ForeignKey('Crawl', db_column='crawl_id', on_delete=models.CASCADE, to_field='id')
#     tag = models.ForeignKey(Tag, db_column='tag_id', on_delete=models.CASCADE, to_field='id')

#     class Meta:
#         db_table = 'core_crawl_tags'
#         unique_together = [('crawl', 'tag')]


class Crawl(ABIDModel):
    abid_prefix = 'crl_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.urls'
    abid_subtype_src = 'self.crawler'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True

    # CRAWLER_CHOICES = (
    #     ('breadth_first', 'Breadth-First'),
    #     ('depth_first', 'Depth-First'),
    # )
    PARSER_CHOICES = (
        ('auto', 'auto'),
        *((parser_key, value[0]) for parser_key, value in PARSERS.items()),
    )

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='crawl_set')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    urls = models.TextField(blank=False, null=False)
    depth = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(0), MaxValueValidator(2)])
    parser = models.CharField(choices=PARSER_CHOICES, default='auto', max_length=32)
    
    # crawler = models.CharField(choices=CRAWLER_CHOICES, default='breadth_first', max_length=32)
    # tags = models.ManyToManyField(Tag, blank=True, related_name='crawl_set', through='CrawlTag')
    # schedule = models.JSONField()
    # config = models.JSONField()
    

    class Meta(TypedModelMeta):
        verbose_name = 'Crawl'
        verbose_name_plural = 'Crawls'

    def __str__(self):
        return self.parser

    @cached_property
    def crawl_dir(self):
        return Path()

    @property
    def api_url(self) -> str:
        # /api/v1/core/crawl/{uulid}
        return reverse_lazy('api-1:get_crawl', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_crawl'

    # def get_absolute_url(self):
    #     return f'/crawls/{self.abid}'
    
    def crawl(self):
        # write self.urls to sources/crawl__<user>__YYYYMMDDHHMMSS.txt
        # run parse_links(sources/crawl__<user>__YYYYMMDDHHMMSS.txt, parser=self.parser) and for each resulting link:
        #   create a Snapshot
        #   enqueue task bg_archive_snapshot(snapshot)
        pass




class SnapshotManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().prefetch_related('tags', 'archiveresult_set')  # .annotate(archiveresult_count=models.Count('archiveresult')).distinct()


class Snapshot(ABIDModel):
    abid_prefix = 'snp_'
    abid_ts_src = 'self.created_at'
    abid_uri_src = 'self.url'
    abid_subtype_src = '"01"'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='snapshot_set')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)  # loaded from self._init_timestamp
    modified_at = models.DateTimeField(auto_now=True)

    # legacy ts fields
    bookmarked_at = AutoDateTimeField(default=None, null=False, editable=True, db_index=True)
    downloaded_at = models.DateTimeField(default=None, null=True, editable=False, db_index=True, blank=True)

    url = models.URLField(unique=True, db_index=True)
    timestamp = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    tags = models.ManyToManyField(Tag, blank=True, through=SnapshotTag, related_name='snapshot_set', through_fields=('snapshot', 'tag'))
    title = models.CharField(max_length=512, null=True, blank=True, db_index=True)    

    keys = ('url', 'timestamp', 'title', 'tags', 'downloaded_at')

    archiveresult_set: models.Manager['ArchiveResult']

    objects = SnapshotManager()

    def save(self, *args, **kwargs):
        if not self.bookmarked_at:
            self.bookmarked_at = self.created_at or self._init_timestamp
        
        super().save(*args, **kwargs)

    def archive(self, overwrite=False, methods=None):
        result = bg_archive_snapshot(self, overwrite=overwrite, methods=methods)
        return result

    def __repr__(self) -> str:
        title = (self.title_stripped or '-')[:64]
        return f'[{self.timestamp}] {self.url[:64]} ({title})'

    def __str__(self) -> str:
        title = (self.title_stripped or '-')[:64]
        return f'[{self.timestamp}] {self.url[:64]} ({title})'

    @classmethod
    def from_json(cls, info: dict):
        info = {k: v for k, v in info.items() if k in cls.keys}
        return cls(**info)

    def as_json(self, *args) -> dict:
        args = args or self.keys
        return {
            key: getattr(self, key) if key != 'tags' else self.tags_str(nocache=False)
            for key in args
        }

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

class ArchiveResult(ABIDModel):
    abid_prefix = 'res_'
    abid_ts_src = 'self.snapshot.created_at'
    abid_uri_src = 'self.snapshot.url'
    abid_subtype_src = 'self.extractor'
    abid_rand_src = 'self.id'
    abid_drift_allowed = True

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
    STATUS_CHOICES = [
        ("succeeded", "succeeded"),
        ("failed", "failed"),
        ("skipped", "skipped")
    ]

    id = models.UUIDField(primary_key=True, default=None, null=False, editable=False, unique=True, verbose_name='ID')
    abid = ABIDField(prefix=abid_prefix)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=None, null=False, related_name='archiveresult_set')
    created_at = AutoDateTimeField(default=None, null=False, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE, to_field='id', db_column='snapshot_id')

    extractor = models.CharField(choices=EXTRACTOR_CHOICES, max_length=32)
    cmd = models.JSONField()
    pwd = models.CharField(max_length=256)
    cmd_version = models.CharField(max_length=128, default=None, null=True, blank=True)
    output = models.CharField(max_length=1024)
    start_ts = models.DateTimeField(db_index=True)
    end_ts = models.DateTimeField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)

    # the network interface that was used to download this result
    # uplink = models.ForeignKey(NetworkInterface, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Network Interface Used')

    objects = ArchiveResultManager()

    class Meta(TypedModelMeta):
        verbose_name = 'Archive Result'
        verbose_name_plural = 'Archive Results Log'


    def __str__(self):
        # return f'[{self.abid}] 📅 {self.start_ts.strftime("%Y-%m-%d %H:%M")} 📄 {self.extractor} {self.snapshot.url}'
        return self.extractor

    @cached_property
    def machine(self):
        return self.iface.machine if self.iface else None

    @cached_property
    def snapshot_dir(self):
        return Path(self.snapshot.link_dir)

    @property
    def api_url(self) -> str:
        # /api/v1/core/archiveresult/{uulid}
        return reverse_lazy('api-1:get_archiveresult', args=[self.abid])  # + f'?api_key={get_or_create_api_token(request.user)}'

    @property
    def api_docs_url(self) -> str:
        return '/api/v1/docs#/Core%20Models/api_v1_core_get_archiveresult'

    def get_absolute_url(self):
        return f'/{self.snapshot.archive_path}/{self.output_path()}'

    @property
    def extractor_module(self):
        return EXTRACTORS[self.extractor]

    def output_path(self) -> str:
        """return the canonical output filename or directory name within the snapshot dir"""
        return self.extractor_module.get_output_path()

    def embed_path(self) -> str:
        """
        return the actual runtime-calculated path to the file on-disk that
        should be used for user-facing iframe embeds of this result
        """

        if get_embed_path_func := getattr(self.extractor_module, 'get_embed_path', None):
            return get_embed_path_func(self)

        return self.extractor_module.get_output_path()

    def legacy_output_path(self):
        link = self.snapshot.as_link()
        return link.canonical_outputs().get(f'{self.extractor}_path')

    def output_exists(self) -> bool:
        return os.access(self.output_path(), os.R_OK)


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
