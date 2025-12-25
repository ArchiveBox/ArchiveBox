__package__ = 'archivebox.core'

from typing import Optional, Dict, Iterable, Any, List, TYPE_CHECKING
from uuid import uuid7
from datetime import datetime, timedelta
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

from archivebox.config import CONSTANTS
from archivebox.misc.system import get_dir_size, atomic_write
from archivebox.misc.util import parse_date, base_url, domain as url_domain, to_json, ts_to_date_str, urlencode, htmlencode, urldecode
from archivebox.misc.hashing import get_dir_info
from archivebox.hooks import (
    ARCHIVE_METHODS_INDEXING_PRECEDENCE,
    get_extractors, get_extractor_name, get_extractor_icon,
    DEFAULT_EXTRACTOR_ICONS,
)
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
    # Keep AutoField for compatibility with main branch migrations
    # Don't use UUIDField here - requires complex FK transformation
    id = models.AutoField(primary_key=True, serialize=False, verbose_name='ID')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False, related_name='tag_set')
    created_at = models.DateTimeField(default=timezone.now, db_index=True, null=True)
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
        is_new = self._state.adding
        if is_new:
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

        if is_new:
            from archivebox.misc.logging_util import log_worker_event
            log_worker_event(
                worker_type='DB',
                event='Created Tag',
                indent_level=0,
                metadata={
                    'id': self.id,
                    'name': self.name,
                    'slug': self.slug,
                },
            )

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


class SnapshotQuerySet(models.QuerySet):
    """Custom QuerySet for Snapshot model with export methods that persist through .filter() etc."""

    # =========================================================================
    # Filtering Methods
    # =========================================================================

    FILTER_TYPES = {
        'exact': lambda pattern: models.Q(url=pattern),
        'substring': lambda pattern: models.Q(url__icontains=pattern),
        'regex': lambda pattern: models.Q(url__iregex=pattern),
        'domain': lambda pattern: models.Q(url__istartswith=f"http://{pattern}") | models.Q(url__istartswith=f"https://{pattern}") | models.Q(url__istartswith=f"ftp://{pattern}"),
        'tag': lambda pattern: models.Q(tags__name=pattern),
        'timestamp': lambda pattern: models.Q(timestamp=pattern),
    }

    def filter_by_patterns(self, patterns: List[str], filter_type: str = 'exact') -> 'SnapshotQuerySet':
        """Filter snapshots by URL patterns using specified filter type"""
        from archivebox.misc.logging import stderr

        q_filter = models.Q()
        for pattern in patterns:
            try:
                q_filter = q_filter | self.FILTER_TYPES[filter_type](pattern)
            except KeyError:
                stderr()
                stderr(f'[X] Got invalid pattern for --filter-type={filter_type}:', color='red')
                stderr(f'    {pattern}')
                raise SystemExit(2)
        return self.filter(q_filter)

    def search(self, patterns: List[str]) -> 'SnapshotQuerySet':
        """Search snapshots using the configured search backend"""
        from archivebox.config.common import SEARCH_BACKEND_CONFIG
        from archivebox.search import query_search_index
        from archivebox.misc.logging import stderr

        if not SEARCH_BACKEND_CONFIG.USE_SEARCHING_BACKEND:
            stderr()
            stderr('[X] The search backend is not enabled, set config.USE_SEARCHING_BACKEND = True', color='red')
            raise SystemExit(2)

        qsearch = self.none()
        for pattern in patterns:
            try:
                qsearch |= query_search_index(pattern)
            except:
                raise SystemExit(2)
        return self.all() & qsearch

    # =========================================================================
    # Export Methods
    # =========================================================================

    def to_json(self, with_headers: bool = False) -> str:
        """Generate JSON index from snapshots"""
        import sys
        from datetime import datetime, timezone as tz
        from archivebox.config import VERSION
        from archivebox.config.common import SERVER_CONFIG

        MAIN_INDEX_HEADER = {
            'info': 'This is an index of site data archived by ArchiveBox: The self-hosted web archive.',
            'schema': 'archivebox.index.json',
            'copyright_info': SERVER_CONFIG.FOOTER_INFO,
            'meta': {
                'project': 'ArchiveBox',
                'version': VERSION,
                'git_sha': VERSION,
                'website': 'https://ArchiveBox.io',
                'docs': 'https://github.com/ArchiveBox/ArchiveBox/wiki',
                'source': 'https://github.com/ArchiveBox/ArchiveBox',
                'issues': 'https://github.com/ArchiveBox/ArchiveBox/issues',
                'dependencies': {},
            },
        } if with_headers else {}

        snapshot_dicts = [s.to_dict(extended=True) for s in self.iterator(chunk_size=500)]

        if with_headers:
            output = {
                **MAIN_INDEX_HEADER,
                'num_links': len(snapshot_dicts),
                'updated': datetime.now(tz.utc),
                'last_run_cmd': sys.argv,
                'links': snapshot_dicts,
            }
        else:
            output = snapshot_dicts
        return to_json(output, indent=4, sort_keys=True)

    def to_csv(self, cols: Optional[List[str]] = None, header: bool = True, separator: str = ',', ljust: int = 0) -> str:
        """Generate CSV output from snapshots"""
        cols = cols or ['timestamp', 'is_archived', 'url']
        header_str = separator.join(col.ljust(ljust) for col in cols) if header else ''
        row_strs = (s.to_csv(cols=cols, ljust=ljust, separator=separator) for s in self.iterator(chunk_size=500))
        return '\n'.join((header_str, *row_strs))

    def to_html(self, with_headers: bool = True) -> str:
        """Generate main index HTML from snapshots"""
        from datetime import datetime, timezone as tz
        from django.template.loader import render_to_string
        from archivebox.config import VERSION
        from archivebox.config.common import SERVER_CONFIG
        from archivebox.config.version import get_COMMIT_HASH

        template = 'static_index.html' if with_headers else 'minimal_index.html'
        snapshot_list = list(self.iterator(chunk_size=500))

        return render_to_string(template, {
            'version': VERSION,
            'git_sha': get_COMMIT_HASH() or VERSION,
            'num_links': str(len(snapshot_list)),
            'date_updated': datetime.now(tz.utc).strftime('%Y-%m-%d'),
            'time_updated': datetime.now(tz.utc).strftime('%Y-%m-%d %H:%M'),
            'links': snapshot_list,
            'FOOTER_INFO': SERVER_CONFIG.FOOTER_INFO,
        })


class SnapshotManager(models.Manager.from_queryset(SnapshotQuerySet)):
    """Manager for Snapshot model - uses SnapshotQuerySet for chainable methods"""

    def filter(self, *args, **kwargs):
        domain = kwargs.pop('domain', None)
        qs = super().filter(*args, **kwargs)
        if domain:
            qs = qs.filter(url__icontains=f'://{domain}')
        return qs

    def get_queryset(self):
        return super().get_queryset().prefetch_related('tags', 'archiveresult_set')

    # =========================================================================
    # Import Methods
    # =========================================================================

    def create_or_update_from_dict(self, link_dict: Dict[str, Any], created_by_id: Optional[int] = None) -> 'Snapshot':
        """Create or update a Snapshot from a SnapshotDict (parser output)"""
        import re
        from archivebox.config.common import GENERAL_CONFIG

        url = link_dict['url']
        timestamp = link_dict.get('timestamp')
        title = link_dict.get('title')
        tags_str = link_dict.get('tags')

        tag_list = []
        if tags_str:
            tag_list = list(dict.fromkeys(
                tag.strip() for tag in re.split(GENERAL_CONFIG.TAG_SEPARATOR_PATTERN, tags_str)
                if tag.strip()
            ))

        # Get most recent snapshot with this URL (URLs can exist in multiple crawls)
        snapshot = self.filter(url=url).order_by('-created_at').first()
        if snapshot:
            if title and (not snapshot.title or len(title) > len(snapshot.title or '')):
                snapshot.title = title
                snapshot.save(update_fields=['title', 'modified_at'])
        else:
            if timestamp:
                while self.filter(timestamp=timestamp).exists():
                    timestamp = str(float(timestamp) + 1.0)

            snapshot = self.create(
                url=url,
                timestamp=timestamp,
                title=title,
                created_by_id=created_by_id or get_or_create_system_user_pk(),
            )

        if tag_list:
            existing_tags = set(snapshot.tags.values_list('name', flat=True))
            new_tags = set(tag_list) | existing_tags
            snapshot.save_tags(new_tags)

        return snapshot

    def create_from_dicts(self, link_dicts: List[Dict[str, Any]], created_by_id: Optional[int] = None) -> List['Snapshot']:
        """Create or update multiple Snapshots from a list of SnapshotDicts"""
        return [self.create_or_update_from_dict(d, created_by_id=created_by_id) for d in link_dicts]

    def remove(self, atomic: bool = False) -> tuple:
        """Remove snapshots from the database"""
        from django.db import transaction
        if atomic:
            with transaction.atomic():
                return self.delete()
        return self.delete()


class Snapshot(ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, ModelWithStateMachine):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False, related_name='snapshot_set', db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    url = models.URLField(unique=False, db_index=True)  # URLs can appear in multiple crawls
    timestamp = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    bookmarked_at = models.DateTimeField(default=timezone.now, db_index=True)
    crawl: Crawl = models.ForeignKey(Crawl, on_delete=models.CASCADE, default=None, null=True, blank=True, related_name='snapshot_set', db_index=True)  # type: ignore

    title = models.CharField(max_length=512, null=True, blank=True, db_index=True)
    downloaded_at = models.DateTimeField(default=None, null=True, editable=False, db_index=True, blank=True)
    depth = models.PositiveSmallIntegerField(default=0, db_index=True)  # 0 for root snapshot, 1+ for discovered URLs

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
        constraints = [
            # Allow same URL in different crawls, but not duplicates within same crawl
            models.UniqueConstraint(fields=['url', 'crawl'], name='unique_url_per_crawl'),
        ]

    def __str__(self):
        return f'[{self.id}] {self.url[:64]}'

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if not self.bookmarked_at:
            self.bookmarked_at = self.created_at or timezone.now()
        if not self.timestamp:
            self.timestamp = str(self.bookmarked_at.timestamp())
        super().save(*args, **kwargs)
        if self.crawl and self.url not in self.crawl.urls:
            self.crawl.urls += f'\n{self.url}'
            self.crawl.save()

        if is_new:
            from archivebox.misc.logging_util import log_worker_event
            log_worker_event(
                worker_type='DB',
                event='Created Snapshot',
                indent_level=2,
                url=self.url,
                metadata={
                    'id': str(self.id),
                    'crawl_id': str(self.crawl_id) if self.crawl_id else None,
                    'depth': self.depth,
                    'status': self.status,
                },
            )

    @property
    def output_dir_parent(self) -> str:
        return 'archive'

    @property
    def output_dir_name(self) -> str:
        return str(self.timestamp)

    def archive(self, overwrite=False, methods=None):
        return bg_archive_snapshot(self, overwrite=overwrite, methods=methods)

    @admin.display(description='Tags')
    def tags_str(self, nocache=True) -> str | None:
        calc_tags_str = lambda: ','.join(sorted(tag.name for tag in self.tags.all()))
        if hasattr(self, '_prefetched_objects_cache') and 'tags' in self._prefetched_objects_cache:
            return calc_tags_str()
        cache_key = f'{self.pk}-tags'
        return cache.get_or_set(cache_key, calc_tags_str) if not nocache else calc_tags_str()

    def icons(self) -> str:
        """Generate HTML icons showing which extractors have succeeded for this snapshot"""
        from django.utils.html import format_html, mark_safe

        cache_key = f'result_icons:{self.pk}:{(self.downloaded_at or self.modified_at or self.created_at or self.bookmarked_at).timestamp()}'

        def calc_icons():
            if hasattr(self, '_prefetched_objects_cache') and 'archiveresult_set' in self._prefetched_objects_cache:
                archive_results = {r.extractor: r for r in self.archiveresult_set.all() if r.status == "succeeded" and r.output}
            else:
                archive_results = {r.extractor: r for r in self.archiveresult_set.filter(status="succeeded", output__isnull=False)}

            path = self.archive_path
            canon = self.canonical_outputs()
            output = ""
            output_template = '<a href="/{}/{}" class="exists-{}" title="{}">{}</a> &nbsp;'

            # Get all extractors from hooks system (sorted by numeric prefix)
            all_extractors = [get_extractor_name(e) for e in get_extractors()]

            for extractor in all_extractors:
                result = archive_results.get(extractor)
                existing = result and result.status == 'succeeded' and result.output
                icon = get_extractor_icon(extractor)
                output += format_html(
                    output_template,
                    path,
                    canon.get(extractor, extractor + '/'),
                    str(bool(existing)),
                    extractor,
                    icon
                )

            return format_html('<span class="files-icons" style="font-size: 1.1em; opacity: 0.8; min-width: 240px; display: inline-block">{}</span>', mark_safe(output))

        cache_result = cache.get(cache_key)
        if cache_result:
            return cache_result

        fresh_result = calc_icons()
        cache.set(cache_key, fresh_result, timeout=60 * 60 * 24)
        return fresh_result

    @property
    def api_url(self) -> str:
        return reverse_lazy('api-1:get_snapshot', args=[self.id])

    def get_absolute_url(self):
        return f'/{self.archive_path}'

    @cached_property
    def domain(self) -> str:
        return url_domain(self.url)

    @cached_property
    def output_dir(self):
        """The filesystem path to the snapshot's output directory."""
        return str(CONSTANTS.ARCHIVE_DIR / self.timestamp)

    @cached_property
    def archive_path(self):
        return f'{CONSTANTS.ARCHIVE_DIR_NAME}/{self.timestamp}'

    @cached_property
    def archive_size(self):
        try:
            return get_dir_size(self.output_dir)[0]
        except Exception:
            return 0

    def save_tags(self, tags: Iterable[str] = ()) -> None:
        tags_id = [Tag.objects.get_or_create(name=tag)[0].pk for tag in tags if tag.strip()]
        self.tags.clear()
        self.tags.add(*tags_id)

    def pending_archiveresults(self) -> QuerySet['ArchiveResult']:
        return self.archiveresult_set.exclude(status__in=ArchiveResult.FINAL_OR_ACTIVE_STATES)

    def run(self) -> list['ArchiveResult']:
        """
        Execute this Snapshot by creating ArchiveResults for all enabled extractors.

        Called by the state machine when entering the 'started' state.
        """
        return self.create_pending_archiveresults()

    def create_pending_archiveresults(self) -> list['ArchiveResult']:
        """
        Create ArchiveResult records for all enabled extractors.
        
        Uses the hooks system to discover available extractors from:
        - archivebox/plugins/*/on_Snapshot__*.{py,sh,js}
        - data/plugins/*/on_Snapshot__*.{py,sh,js}
        """
        from archivebox.hooks import get_enabled_extractors
        
        extractors = get_enabled_extractors()
        archiveresults = []
        
        for extractor in extractors:
            if ArchiveResult.objects.filter(snapshot=self, extractor=extractor).exists():
                continue
            archiveresult, _ = ArchiveResult.objects.get_or_create(
                snapshot=self, extractor=extractor,
                defaults={
                    'status': ArchiveResult.INITIAL_STATE,
                    'retry_at': timezone.now(),
                    'created_by_id': self.created_by_id,
                },
            )
            if archiveresult.status == ArchiveResult.INITIAL_STATE:
                archiveresults.append(archiveresult)
        return archiveresults

    def retry_failed_archiveresults(self, retry_at: Optional['timezone.datetime'] = None) -> int:
        """
        Reset failed/skipped ArchiveResults to queued for retry.

        This enables seamless retry of the entire extraction pipeline:
        - Resets FAILED and SKIPPED results to QUEUED
        - Sets retry_at so workers pick them up
        - Extractors run in order (numeric prefix)
        - Each extractor checks its dependencies at runtime

        Dependency handling (e.g., chrome_session → screenshot):
        - Extractors check if required outputs exist before running
        - If dependency output missing → extractor returns 'skipped'
        - On retry, if dependency now succeeds → dependent can run

        Returns count of ArchiveResults reset.
        """
        retry_at = retry_at or timezone.now()

        count = self.archiveresult_set.filter(
            status__in=[
                ArchiveResult.StatusChoices.FAILED,
                ArchiveResult.StatusChoices.SKIPPED,
            ]
        ).update(
            status=ArchiveResult.StatusChoices.QUEUED,
            retry_at=retry_at,
            output=None,
            start_ts=None,
            end_ts=None,
        )

        # Also reset the snapshot so it gets re-checked
        if count > 0:
            self.status = self.StatusChoices.STARTED
            self.retry_at = retry_at
            self.save(update_fields=['status', 'retry_at', 'modified_at'])

        return count

    # =========================================================================
    # URL Helper Properties (migrated from Link schema)
    # =========================================================================

    @cached_property
    def url_hash(self) -> str:
        from hashlib import sha256
        return sha256(self.url.encode()).hexdigest()[:8]

    @cached_property
    def scheme(self) -> str:
        return self.url.split('://')[0]

    @cached_property
    def path(self) -> str:
        parts = self.url.split('://', 1)
        return '/' + parts[1].split('/', 1)[1] if len(parts) > 1 and '/' in parts[1] else '/'

    @cached_property
    def basename(self) -> str:
        return self.path.split('/')[-1]

    @cached_property
    def extension(self) -> str:
        basename = self.basename
        return basename.split('.')[-1] if '.' in basename else ''

    @cached_property
    def base_url(self) -> str:
        return f'{self.scheme}://{self.domain}'

    @cached_property
    def is_static(self) -> bool:
        static_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.mp4', '.mp3', '.wav', '.webm'}
        return any(self.url.lower().endswith(ext) for ext in static_extensions)

    @cached_property
    def is_archived(self) -> bool:
        output_paths = (
            self.domain,
            'output.html',
            'output.pdf',
            'screenshot.png',
            'singlefile.html',
            'readability/content.html',
            'mercury/content.html',
            'htmltotext.txt',
            'media',
            'git',
        )
        return any((Path(self.output_dir) / path).exists() for path in output_paths)

    # =========================================================================
    # Date/Time Properties (migrated from Link schema)
    # =========================================================================

    @cached_property
    def bookmarked_date(self) -> Optional[str]:
        max_ts = (timezone.now() + timedelta(days=30)).timestamp()
        if self.timestamp and self.timestamp.replace('.', '').isdigit():
            if 0 < float(self.timestamp) < max_ts:
                return self._ts_to_date_str(datetime.fromtimestamp(float(self.timestamp)))
            return str(self.timestamp)
        return None

    @cached_property
    def downloaded_datestr(self) -> Optional[str]:
        return self._ts_to_date_str(self.downloaded_at) if self.downloaded_at else None

    @cached_property
    def archive_dates(self) -> List[datetime]:
        return [
            result.start_ts
            for result in self.archiveresult_set.all()
            if result.start_ts
        ]

    @cached_property
    def oldest_archive_date(self) -> Optional[datetime]:
        dates = self.archive_dates
        return min(dates) if dates else None

    @cached_property
    def newest_archive_date(self) -> Optional[datetime]:
        dates = self.archive_dates
        return max(dates) if dates else None

    @cached_property
    def num_outputs(self) -> int:
        return self.archiveresult_set.filter(status='succeeded').count()

    @cached_property
    def num_failures(self) -> int:
        return self.archiveresult_set.filter(status='failed').count()

    # =========================================================================
    # Output Path Methods (migrated from Link schema)
    # =========================================================================

    def canonical_outputs(self) -> Dict[str, Optional[str]]:
        """Predict the expected output paths that should be present after archiving"""
        FAVICON_PROVIDER = 'https://www.google.com/s2/favicons?domain={}'
        canonical = {
            'index_path': 'index.html',
            'favicon_path': 'favicon.ico',
            'google_favicon_path': FAVICON_PROVIDER.format(self.domain),
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

    def latest_outputs(self, status: Optional[str] = None) -> Dict[str, Any]:
        """Get the latest output that each archive method produced"""
        from archivebox.hooks import get_extractors

        latest: Dict[str, Any] = {}
        for archive_method in get_extractors():
            results = self.archiveresult_set.filter(extractor=archive_method)
            if status is not None:
                results = results.filter(status=status)
            results = results.filter(output__isnull=False).order_by('-start_ts')
            latest[archive_method] = results.first().output if results.exists() else None
        return latest

    # =========================================================================
    # Serialization Methods
    # =========================================================================

    def to_dict(self, extended: bool = False) -> Dict[str, Any]:
        """Convert Snapshot to a dictionary (replacement for Link._asdict())"""
        from archivebox.misc.util import ts_to_date_str

        result = {
            'TYPE': 'core.models.Snapshot',
            'id': str(self.id),
            'url': self.url,
            'timestamp': self.timestamp,
            'title': self.title,
            'tags': self.tags_str(),
            'downloaded_at': self.downloaded_at.isoformat() if self.downloaded_at else None,
            'bookmarked_at': self.bookmarked_at.isoformat() if self.bookmarked_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            # Computed properties
            'domain': self.domain,
            'scheme': self.scheme,
            'base_url': self.base_url,
            'path': self.path,
            'basename': self.basename,
            'extension': self.extension,
            'is_static': self.is_static,
            'is_archived': self.is_archived,
            'archive_path': self.archive_path,
            'output_dir': self.output_dir,
            'link_dir': self.output_dir,  # backwards compatibility alias
            'archive_size': self.archive_size,
            'bookmarked_date': self.bookmarked_date,
            'downloaded_datestr': self.downloaded_datestr,
            'num_outputs': self.num_outputs,
            'num_failures': self.num_failures,
        }
        if extended:
            result['canonical'] = self.canonical_outputs()
        return result

    def to_json(self, indent: int = 4) -> str:
        """Convert to JSON string"""
        return to_json(self.to_dict(extended=True), indent=indent)

    def to_csv(self, cols: Optional[List[str]] = None, separator: str = ',', ljust: int = 0) -> str:
        """Convert to CSV string"""
        data = self.to_dict()
        cols = cols or ['timestamp', 'is_archived', 'url']
        return separator.join(to_json(data.get(col, ''), indent=None).ljust(ljust) for col in cols)

    def write_json_details(self, out_dir: Optional[str] = None) -> None:
        """Write JSON index file for this snapshot to its output directory"""
        out_dir = out_dir or self.output_dir
        path = Path(out_dir) / CONSTANTS.JSON_INDEX_FILENAME
        atomic_write(str(path), self.to_dict(extended=True))

    def write_html_details(self, out_dir: Optional[str] = None) -> None:
        """Write HTML detail page for this snapshot to its output directory"""
        from django.template.loader import render_to_string
        from archivebox.config.common import SERVER_CONFIG
        from archivebox.config.configset import get_config
        from archivebox.misc.logging_util import printable_filesize

        out_dir = out_dir or self.output_dir
        config = get_config()
        SAVE_ARCHIVE_DOT_ORG = config.get('SAVE_ARCHIVE_DOT_ORG', True)
        TITLE_LOADING_MSG = 'Not yet archived...'

        canonical = self.canonical_outputs()
        context = {
            **self.to_dict(extended=True),
            **{f'{k}_path': v for k, v in canonical.items()},
            'canonical': {f'{k}_path': v for k, v in canonical.items()},
            'title': htmlencode(self.title or (self.base_url if self.is_archived else TITLE_LOADING_MSG)),
            'url_str': htmlencode(urldecode(self.base_url)),
            'archive_url': urlencode(f'warc/{self.timestamp}' or (self.domain if self.is_archived else '')) or 'about:blank',
            'extension': self.extension or 'html',
            'tags': self.tags_str() or 'untagged',
            'size': printable_filesize(self.archive_size) if self.archive_size else 'pending',
            'status': 'archived' if self.is_archived else 'not yet archived',
            'status_color': 'success' if self.is_archived else 'danger',
            'oldest_archive_date': ts_to_date_str(self.oldest_archive_date),
            'SAVE_ARCHIVE_DOT_ORG': SAVE_ARCHIVE_DOT_ORG,
            'PREVIEW_ORIGINALS': SERVER_CONFIG.PREVIEW_ORIGINALS,
        }
        rendered_html = render_to_string('snapshot.html', context)
        atomic_write(str(Path(out_dir) / CONSTANTS.HTML_INDEX_FILENAME), rendered_html)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    @staticmethod
    def _ts_to_date_str(dt: Optional[datetime]) -> Optional[str]:
        return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else None


class ArchiveResultManager(models.Manager):
    def indexable(self, sorted: bool = True):
        INDEXABLE_METHODS = [r[0] for r in ARCHIVE_METHODS_INDEXING_PRECEDENCE]
        qs = self.get_queryset().filter(extractor__in=INDEXABLE_METHODS, status='succeeded')
        if sorted:
            precedence = [When(extractor=method, then=Value(p)) for method, p in ARCHIVE_METHODS_INDEXING_PRECEDENCE]
            qs = qs.annotate(indexing_precedence=Case(*precedence, default=Value(1000), output_field=IntegerField())).order_by('indexing_precedence')
        return qs


class ArchiveResult(ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, ModelWithStateMachine):
    class StatusChoices(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        STARTED = 'started', 'Started'
        BACKOFF = 'backoff', 'Waiting to retry'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'

    @classmethod
    def get_extractor_choices(cls):
        """Get extractor choices from discovered hooks (for forms/admin)."""
        extractors = [get_extractor_name(e) for e in get_extractors()]
        return tuple((e, e) for e in extractors)

    # Keep AutoField for backward compatibility with 0.7.x databases
    # UUID field is added separately by migration for new records
    id = models.AutoField(primary_key=True, editable=False)
    uuid = models.UUIDField(default=uuid7, null=True, blank=True, db_index=True, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=False, related_name='archiveresult_set', db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    snapshot: Snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)  # type: ignore
    # No choices= constraint - extractor names come from plugin system and can be any string
    extractor = models.CharField(max_length=32, blank=False, null=False, db_index=True)
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

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        # Skip ModelWithOutputDir.save() to avoid creating index.json in plugin directories
        # Call the Django Model.save() directly instead
        models.Model.save(self, *args, **kwargs)

        if is_new:
            from archivebox.misc.logging_util import log_worker_event
            log_worker_event(
                worker_type='DB',
                event='Created ArchiveResult',
                indent_level=3,
                extractor=self.extractor,
                metadata={
                    'id': str(self.id),
                    'snapshot_id': str(self.snapshot_id),
                    'snapshot_url': str(self.snapshot.url)[:64],
                    'status': self.status,
                },
            )

    @cached_property
    def snapshot_dir(self):
        return Path(self.snapshot.output_dir)

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
        # Hook scripts are now used instead of Python extractor modules
        # The extractor name maps to hooks in archivebox/plugins/{extractor}/
        return None

    def output_exists(self) -> bool:
        return os.path.exists(Path(self.snapshot_dir) / self.extractor)

    def embed_path(self) -> Optional[str]:
        """
        Get the relative path to the embeddable output file for this result.

        Returns the output field if set and file exists, otherwise tries to
        find a reasonable default based on the extractor type.
        """
        if self.output:
            return self.output

        # Try to find output file based on extractor's canonical output path
        canonical = self.snapshot.canonical_outputs()
        extractor_key = f'{self.extractor}_path'
        if extractor_key in canonical:
            return canonical[extractor_key]

        # Fallback to extractor directory
        return f'{self.extractor}/'

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

    def save_search_index(self):
        pass

    def run(self):
        """
        Execute this ArchiveResult's extractor and update status.

        Discovers and runs the hook script for self.extractor,
        updates status/output fields, queues discovered URLs, and triggers indexing.
        """
        from django.utils import timezone
        from archivebox.hooks import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR, run_hook

        config_objects = [self.snapshot.crawl, self.snapshot] if self.snapshot.crawl else [self.snapshot]

        # Find hook for this extractor
        hook = None
        for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
            if not base_dir.exists():
                continue
            matches = list(base_dir.glob(f'*/on_Snapshot__{self.extractor}.*'))
            if matches:
                hook = matches[0]
                break

        if not hook:
            self.status = self.StatusChoices.FAILED
            self.output = f'No hook found for: {self.extractor}'
            self.retry_at = None
            self.save()
            return

        # Use plugin directory name instead of extractor name (removes numeric prefix)
        plugin_name = hook.parent.name
        extractor_dir = Path(self.snapshot.output_dir) / plugin_name

        # Run the hook
        start_ts = timezone.now()
        result = run_hook(
            hook,
            output_dir=extractor_dir,
            config_objects=config_objects,
            url=self.snapshot.url,
            snapshot_id=str(self.snapshot.id),
        )
        end_ts = timezone.now()

        # Clean up empty output directory if no files were created
        output_files = result.get('output_files', [])
        if not output_files and extractor_dir.exists():
            try:
                # Only remove if directory is completely empty
                if not any(extractor_dir.iterdir()):
                    extractor_dir.rmdir()
            except (OSError, RuntimeError):
                pass  # Directory not empty or can't be removed, that's fine

        # Determine status from return code and JSON output
        output_json = result.get('output_json') or {}
        json_status = output_json.get('status')

        if json_status == 'skipped':
            status = 'skipped'
        elif json_status == 'failed':
            status = 'failed'
        elif result['returncode'] == 0:
            status = 'succeeded'
        else:
            status = 'failed'

        # Update self from result
        status_map = {
            'succeeded': self.StatusChoices.SUCCEEDED,
            'failed': self.StatusChoices.FAILED,
            'skipped': self.StatusChoices.SKIPPED,
        }
        self.status = status_map.get(status, self.StatusChoices.FAILED)
        self.output = output_json.get('output') or result['stdout'][:1024] or result['stderr'][:1024] or None
        self.start_ts = start_ts
        self.end_ts = end_ts
        self.retry_at = None
        self.pwd = str(extractor_dir)

        # Save cmd and cmd_version from extractor output
        if output_json.get('cmd_version'):
            self.cmd_version = output_json['cmd_version'][:128]  # Max length from model
        if output_json.get('cmd'):
            self.cmd = output_json['cmd']

        self.save()

        # Queue any discovered URLs for crawling (parser extractors write urls.jsonl)
        self._queue_urls_for_crawl(extractor_dir)

        # Update snapshot title if this is the title extractor
        # Check both old numeric name and new plugin name for compatibility
        extractor_name = get_extractor_name(self.extractor)
        if self.status == self.StatusChoices.SUCCEEDED and extractor_name == 'title':
            self._update_snapshot_title(extractor_dir)

        # Trigger search indexing if succeeded
        if self.status == self.StatusChoices.SUCCEEDED:
            self.trigger_search_indexing()

    def _update_snapshot_title(self, extractor_dir: Path):
        """
        Update snapshot title from title extractor output.

        The title extractor writes title.txt with the extracted page title.
        This updates the Snapshot.title field if the file exists and has content.
        """
        title_file = extractor_dir / 'title.txt'
        if title_file.exists():
            try:
                title = title_file.read_text(encoding='utf-8').strip()
                if title and (not self.snapshot.title or len(title) > len(self.snapshot.title)):
                    self.snapshot.title = title[:512]  # Max length from model
                    self.snapshot.save(update_fields=['title', 'modified_at'])
            except Exception:
                pass  # Failed to read title, that's okay

    def _queue_urls_for_crawl(self, extractor_dir: Path):
        """
        Read urls.jsonl and queue discovered URLs for crawling.

        Parser extractors output urls.jsonl with discovered URLs and Tags.
        - Tag records: {"type": "Tag", "name": "..."}
        - Snapshot records: {"type": "Snapshot", "url": "...", ...}

        Tags are created in the database.
        URLs get added to the parent Crawl's queue with metadata
        (depth, via_snapshot, via_extractor) for recursive crawling.

        Used at all depths:
        - depth=0: Initial source file (e.g., bookmarks.html) parsed for URLs
        - depth>0: Crawled pages parsed for outbound links
        """
        import json

        if not self.snapshot.crawl:
            return

        urls_file = extractor_dir / 'urls.jsonl'
        if not urls_file.exists():
            return

        urls_added = 0
        tags_created = 0
        with open(urls_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    record_type = entry.get('type', 'Snapshot')

                    # Handle Tag records
                    if record_type == 'Tag':
                        tag_name = entry.get('name')
                        if tag_name:
                            Tag.objects.get_or_create(name=tag_name)
                            tags_created += 1
                        continue

                    # Handle Snapshot records (or records without type)
                    if not entry.get('url'):
                        continue

                    # Add crawl metadata
                    entry['depth'] = self.snapshot.depth + 1
                    entry['via_snapshot'] = str(self.snapshot.id)
                    entry['via_extractor'] = self.extractor

                    if self.snapshot.crawl.add_url(entry):
                        urls_added += 1
                except json.JSONDecodeError:
                    continue

        if urls_added > 0:
            self.snapshot.crawl.create_snapshots_from_urls()
    
    def trigger_search_indexing(self):
        """Run any ArchiveResult__index hooks to update search indexes."""
        from archivebox.hooks import discover_hooks, run_hook

        # Pass config objects in priority order (later overrides earlier)
        config_objects = [self.snapshot.crawl, self.snapshot] if self.snapshot.crawl else [self.snapshot]

        for hook in discover_hooks('ArchiveResult__index'):
            run_hook(
                hook,
                output_dir=self.output_dir,
                config_objects=config_objects,
                url=self.snapshot.url,
                snapshot_id=str(self.snapshot.id),
                extractor=self.extractor,
            )
    
    @property
    def output_dir(self) -> Path:
        """Get the output directory for this extractor's results."""
        return Path(self.snapshot.output_dir) / self.extractor
