__package__ = 'archivebox.core'

from typing import Optional, Dict, Iterable, Any, List, TYPE_CHECKING
from archivebox.uuid_compat import uuid7
from datetime import datetime, timedelta
from django_stubs_ext.db.models import TypedModelMeta

import os
import json
from pathlib import Path

from statemachine import State, registry

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
    EXTRACTOR_INDEXING_PRECEDENCE,
    get_plugins, get_plugin_name, get_plugin_icon,
    DEFAULT_PLUGIN_ICONS,
)
from archivebox.base_models.models import (
    ModelWithUUID, ModelWithSerializers, ModelWithOutputDir,
    ModelWithConfig, ModelWithNotes, ModelWithHealthStats,
    get_or_create_system_user_pk,
)
from archivebox.workers.models import ModelWithStateMachine, BaseStateMachine
from archivebox.workers.tasks import bg_archive_snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import NetworkInterface, Binary



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
        app_label = 'core'
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

    @staticmethod
    def from_jsonl(record: Dict[str, Any], overrides: Dict[str, Any] = None):
        """
        Create/update Tag from JSONL record.

        Args:
            record: JSONL record with 'name' field
            overrides: Optional dict with 'snapshot' to auto-attach tag

        Returns:
            Tag instance or None
        """
        from archivebox.misc.jsonl import get_or_create_tag

        try:
            tag = get_or_create_tag(record)

            # Auto-attach to snapshot if in overrides
            if overrides and 'snapshot' in overrides and tag:
                overrides['snapshot'].tags.add(tag)

            return tag
        except ValueError:
            return None


class SnapshotTag(models.Model):
    id = models.AutoField(primary_key=True)
    snapshot = models.ForeignKey('Snapshot', db_column='snapshot_id', on_delete=models.CASCADE, to_field='id')
    tag = models.ForeignKey(Tag, db_column='tag_id', on_delete=models.CASCADE, to_field='id')

    class Meta:
        app_label = 'core'
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

    def remove(self, atomic: bool = False) -> tuple:
        """Remove snapshots from the database"""
        from django.db import transaction
        if atomic:
            with transaction.atomic():
                return self.delete()
        return self.delete()


class Snapshot(ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, ModelWithStateMachine):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    url = models.URLField(unique=False, db_index=True)  # URLs can appear in multiple crawls
    timestamp = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    bookmarked_at = models.DateTimeField(default=timezone.now, db_index=True)
    crawl: Crawl = models.ForeignKey(Crawl, on_delete=models.CASCADE, null=False, related_name='snapshot_set', db_index=True)  # type: ignore[assignment]
    parent_snapshot = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_snapshots', db_index=True, help_text='Parent snapshot that discovered this URL (for recursive crawling)')

    title = models.CharField(max_length=512, null=True, blank=True, db_index=True)
    downloaded_at = models.DateTimeField(default=None, null=True, editable=False, db_index=True, blank=True)
    depth = models.PositiveSmallIntegerField(default=0, db_index=True)  # 0 for root snapshot, 1+ for discovered URLs
    fs_version = models.CharField(max_length=10, default='0.9.0', help_text='Filesystem version of this snapshot (e.g., "0.7.0", "0.8.0", "0.9.0"). Used to trigger lazy migration on save().')
    current_step = models.PositiveSmallIntegerField(default=0, db_index=True, help_text='Current hook step being executed (0-9). Used for sequential hook execution.')

    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)
    status = ModelWithStateMachine.StatusField(choices=ModelWithStateMachine.StatusChoices, default=ModelWithStateMachine.StatusChoices.QUEUED)
    config = models.JSONField(default=dict, null=False, blank=False, editable=True)
    notes = models.TextField(blank=True, null=False, default='')
    output_dir = models.FilePathField(path=CONSTANTS.ARCHIVE_DIR, recursive=True, match='.*', default=None, null=True, blank=True, editable=True)

    tags = models.ManyToManyField(Tag, blank=True, through=SnapshotTag, related_name='snapshot_set', through_fields=('snapshot', 'tag'))

    state_machine_name = 'core.models.SnapshotMachine'
    state_field_name = 'status'
    retry_at_field_name = 'retry_at'
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED

    objects = SnapshotManager()
    archiveresult_set: models.Manager['ArchiveResult']

    class Meta(TypedModelMeta):
        app_label = 'core'
        verbose_name = "Snapshot"
        verbose_name_plural = "Snapshots"
        constraints = [
            # Allow same URL in different crawls, but not duplicates within same crawl
            models.UniqueConstraint(fields=['url', 'crawl'], name='unique_url_per_crawl'),
            # Global timestamp uniqueness for 1:1 symlink mapping
            models.UniqueConstraint(fields=['timestamp'], name='unique_timestamp'),
        ]

    def __str__(self):
        return f'[{self.id}] {self.url[:64]}'

    @property
    def created_by(self):
        """Convenience property to access the user who created this snapshot via its crawl."""
        return self.crawl.created_by

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if not self.bookmarked_at:
            self.bookmarked_at = self.created_at or timezone.now()
        if not self.timestamp:
            self.timestamp = str(self.bookmarked_at.timestamp())

        # Migrate filesystem if needed (happens automatically on save)
        if self.pk and self.fs_migration_needed:
            from django.db import transaction
            with transaction.atomic():
                # Walk through migration chain automatically
                current = self.fs_version
                target = self._fs_current_version()

                while current != target:
                    next_ver = self._fs_next_version(current)
                    method = f'_fs_migrate_from_{current.replace(".", "_")}_to_{next_ver.replace(".", "_")}'

                    # Only run if method exists (most are no-ops)
                    if hasattr(self, method):
                        getattr(self, method)()

                    current = next_ver

                # Update version (still in transaction)
                self.fs_version = target

        super().save(*args, **kwargs)
        if self.url not in self.crawl.urls:
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
                    'crawl_id': str(self.crawl_id),
                    'depth': self.depth,
                    'status': self.status,
                },
            )

    # =========================================================================
    # Filesystem Migration Methods
    # =========================================================================

    @staticmethod
    def _fs_current_version() -> str:
        """Get current ArchiveBox filesystem version (normalized to x.x.0 format)"""
        from archivebox.config import VERSION
        # Normalize version to x.x.0 format (e.g., "0.9.0rc1" -> "0.9.0")
        parts = VERSION.split('.')
        if len(parts) >= 2:
            major, minor = parts[0], parts[1]
            # Strip any non-numeric suffix from minor version
            minor = ''.join(c for c in minor if c.isdigit())
            return f'{major}.{minor}.0'
        return '0.9.0'  # Fallback if version parsing fails

    @property
    def fs_migration_needed(self) -> bool:
        """Check if snapshot needs filesystem migration"""
        return self.fs_version != self._fs_current_version()

    def _fs_next_version(self, version: str) -> str:
        """Get next version in migration chain (0.7/0.8 had same layout, only 0.8→0.9 migration needed)"""
        # Treat 0.7.0 and 0.8.0 as equivalent (both used archive/{timestamp})
        if version in ('0.7.0', '0.8.0'):
            return '0.9.0'
        return self._fs_current_version()

    def _fs_migrate_from_0_8_0_to_0_9_0(self):
        """
        Migrate from flat to nested structure.

        0.8.x: archive/{timestamp}/
        0.9.x: users/{user}/snapshots/YYYYMMDD/{domain}/{uuid}/

        Transaction handling:
        1. Copy files INSIDE transaction
        2. Create symlink INSIDE transaction
        3. Update fs_version INSIDE transaction (done by save())
        4. Exit transaction (DB commit)
        5. Delete old files OUTSIDE transaction (after commit)
        """
        import shutil
        from django.db import transaction

        old_dir = self.get_storage_path_for_version('0.8.0')
        new_dir = self.get_storage_path_for_version('0.9.0')

        if not old_dir.exists() or old_dir == new_dir or new_dir.exists():
            return

        new_dir.mkdir(parents=True, exist_ok=True)

        # Copy all files (idempotent)
        for old_file in old_dir.rglob('*'):
            if not old_file.is_file():
                continue

            rel_path = old_file.relative_to(old_dir)
            new_file = new_dir / rel_path

            # Skip if already copied
            if new_file.exists() and new_file.stat().st_size == old_file.stat().st_size:
                continue

            new_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_file, new_file)

        # Verify all copied
        old_files = {f.relative_to(old_dir): f.stat().st_size
                     for f in old_dir.rglob('*') if f.is_file()}
        new_files = {f.relative_to(new_dir): f.stat().st_size
                     for f in new_dir.rglob('*') if f.is_file()}

        if old_files.keys() != new_files.keys():
            missing = old_files.keys() - new_files.keys()
            raise Exception(f"Migration incomplete: missing {missing}")

        # Create backwards-compat symlink (INSIDE transaction)
        symlink_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
        if symlink_path.is_symlink():
            symlink_path.unlink()

        if not symlink_path.exists() or symlink_path == old_dir:
            symlink_path.symlink_to(new_dir, target_is_directory=True)

        # Schedule old directory deletion AFTER transaction commits
        transaction.on_commit(lambda: self._cleanup_old_migration_dir(old_dir))

    def _cleanup_old_migration_dir(self, old_dir: Path):
        """
        Delete old directory after successful migration.
        Called via transaction.on_commit() after DB commit succeeds.
        """
        import shutil
        import logging

        if old_dir.exists() and not old_dir.is_symlink():
            try:
                shutil.rmtree(old_dir)
            except Exception as e:
                # Log but don't raise - migration succeeded, this is just cleanup
                logging.getLogger('archivebox.migration').warning(
                    f"Could not remove old migration directory {old_dir}: {e}"
                )

    # =========================================================================
    # Path Calculation and Migration Helpers
    # =========================================================================

    @staticmethod
    def extract_domain_from_url(url: str) -> str:
        """
        Extract domain from URL for 0.9.x path structure.
        Uses full hostname with sanitized special chars.

        Examples:
            https://example.com:8080 → example.com_8080
            https://sub.example.com → sub.example.com
            file:///path → localhost
            data:text/html → data
        """
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)

            if parsed.scheme in ('http', 'https'):
                if parsed.port:
                    return f"{parsed.hostname}_{parsed.port}".replace(':', '_')
                return parsed.hostname or 'unknown'
            elif parsed.scheme == 'file':
                return 'localhost'
            elif parsed.scheme:
                return parsed.scheme
            else:
                return 'unknown'
        except Exception:
            return 'unknown'

    def get_storage_path_for_version(self, version: str) -> Path:
        """
        Calculate storage path for specific filesystem version.
        Centralizes path logic so it's reusable.

        0.7.x/0.8.x: archive/{timestamp}
        0.9.x: users/{username}/snapshots/YYYYMMDD/{domain}/{uuid}/
        """
        from datetime import datetime

        if version in ('0.7.0', '0.8.0'):
            return CONSTANTS.ARCHIVE_DIR / self.timestamp

        elif version in ('0.9.0', '1.0.0'):
            username = self.created_by.username

            # Use created_at for date grouping (fallback to timestamp)
            if self.created_at:
                date_str = self.created_at.strftime('%Y%m%d')
            else:
                date_str = datetime.fromtimestamp(float(self.timestamp)).strftime('%Y%m%d')

            domain = self.extract_domain_from_url(self.url)

            return (
                CONSTANTS.DATA_DIR / 'users' / username / 'snapshots' /
                date_str / domain / str(self.id)
            )
        else:
            # Unknown version - use current
            return self.get_storage_path_for_version(self._fs_current_version())

    # =========================================================================
    # Loading and Creation from Filesystem (Used by archivebox update ONLY)
    # =========================================================================

    @classmethod
    def load_from_directory(cls, snapshot_dir: Path) -> Optional['Snapshot']:
        """
        Load existing Snapshot from DB by reading index.json.

        Reads index.json, extracts url+timestamp, queries DB.
        Returns existing Snapshot or None if not found/invalid.
        Does NOT create new snapshots.

        ONLY used by: archivebox update (for orphan detection)
        """
        import json

        index_path = snapshot_dir / 'index.json'
        if not index_path.exists():
            return None

        try:
            with open(index_path) as f:
                data = json.load(f)
        except:
            return None

        url = data.get('url')
        if not url:
            return None

        # Get timestamp - prefer index.json, fallback to folder name
        timestamp = cls._select_best_timestamp(
            index_timestamp=data.get('timestamp'),
            folder_name=snapshot_dir.name
        )

        if not timestamp:
            return None

        # Look up existing
        try:
            return cls.objects.get(url=url, timestamp=timestamp)
        except cls.DoesNotExist:
            return None
        except cls.MultipleObjectsReturned:
            # Should not happen with unique constraint
            return cls.objects.filter(url=url, timestamp=timestamp).first()

    @classmethod
    def create_from_directory(cls, snapshot_dir: Path) -> Optional['Snapshot']:
        """
        Create new Snapshot from orphaned directory.

        Validates timestamp, ensures uniqueness.
        Returns new UNSAVED Snapshot or None if invalid.

        ONLY used by: archivebox update (for orphan import)
        """
        import json

        index_path = snapshot_dir / 'index.json'
        if not index_path.exists():
            return None

        try:
            with open(index_path) as f:
                data = json.load(f)
        except:
            return None

        url = data.get('url')
        if not url:
            return None

        # Get and validate timestamp
        timestamp = cls._select_best_timestamp(
            index_timestamp=data.get('timestamp'),
            folder_name=snapshot_dir.name
        )

        if not timestamp:
            return None

        # Ensure uniqueness (reuses existing logic from create_or_update_from_dict)
        timestamp = cls._ensure_unique_timestamp(url, timestamp)

        # Detect version
        fs_version = cls._detect_fs_version_from_index(data)

        return cls(
            url=url,
            timestamp=timestamp,
            title=data.get('title', ''),
            fs_version=fs_version,
            created_by_id=get_or_create_system_user_pk(),
        )

    @staticmethod
    def _select_best_timestamp(index_timestamp: str, folder_name: str) -> Optional[str]:
        """
        Select best timestamp from index.json vs folder name.

        Validates range (1995-2035).
        Prefers index.json if valid.
        """
        def is_valid_timestamp(ts):
            try:
                ts_int = int(float(ts))
                # 1995-01-01 to 2035-12-31
                return 788918400 <= ts_int <= 2082758400
            except:
                return False

        index_valid = is_valid_timestamp(index_timestamp) if index_timestamp else False
        folder_valid = is_valid_timestamp(folder_name)

        if index_valid:
            return str(int(float(index_timestamp)))
        elif folder_valid:
            return str(int(float(folder_name)))
        else:
            return None

    @classmethod
    def _ensure_unique_timestamp(cls, url: str, timestamp: str) -> str:
        """
        Ensure timestamp is globally unique.
        If collision with different URL, increment by 1 until unique.

        NOTE: Logic already exists in create_or_update_from_dict (line 266-267)
        This is just an extracted, reusable version.
        """
        while cls.objects.filter(timestamp=timestamp).exclude(url=url).exists():
            timestamp = str(int(float(timestamp)) + 1)
        return timestamp

    @staticmethod
    def _detect_fs_version_from_index(data: dict) -> str:
        """
        Detect fs_version from index.json structure.

        - Has fs_version field: use it
        - Has history dict: 0.7.0
        - Has archive_results list: 0.8.0
        - Default: 0.7.0
        """
        if 'fs_version' in data:
            return data['fs_version']
        if 'history' in data and 'archive_results' not in data:
            return '0.7.0'
        if 'archive_results' in data:
            return '0.8.0'
        return '0.7.0'

    # =========================================================================
    # Index.json Reconciliation
    # =========================================================================

    def reconcile_with_index_json(self):
        """
        Merge index.json with DB. DB is source of truth.

        - Title: longest non-URL
        - Tags: union
        - ArchiveResults: keep both (by plugin+start_ts)

        Writes back in 0.9.x format.

        Used by: archivebox update (to sync index.json with DB)
        """
        import json

        index_path = Path(self.output_dir) / 'index.json'

        index_data = {}
        if index_path.exists():
            try:
                with open(index_path) as f:
                    index_data = json.load(f)
            except:
                pass

        # Merge title
        self._merge_title_from_index(index_data)

        # Merge tags
        self._merge_tags_from_index(index_data)

        # Merge ArchiveResults
        self._merge_archive_results_from_index(index_data)

        # Write back
        self.write_index_json()

    def _merge_title_from_index(self, index_data: dict):
        """Merge title - prefer longest non-URL title."""
        index_title = index_data.get('title', '').strip()
        db_title = self.title or ''

        candidates = [t for t in [index_title, db_title] if t and t != self.url]
        if candidates:
            best_title = max(candidates, key=len)
            if self.title != best_title:
                self.title = best_title

    def _merge_tags_from_index(self, index_data: dict):
        """Merge tags - union of both sources."""
        from django.db import transaction

        index_tags = set(index_data.get('tags', '').split(',')) if index_data.get('tags') else set()
        index_tags = {t.strip() for t in index_tags if t.strip()}

        db_tags = set(self.tags.values_list('name', flat=True))

        new_tags = index_tags - db_tags
        if new_tags:
            with transaction.atomic():
                for tag_name in new_tags:
                    tag, _ = Tag.objects.get_or_create(name=tag_name)
                    self.tags.add(tag)

    def _merge_archive_results_from_index(self, index_data: dict):
        """Merge ArchiveResults - keep both (by plugin+start_ts)."""
        existing = {
            (ar.plugin, ar.start_ts): ar
            for ar in ArchiveResult.objects.filter(snapshot=self)
        }

        # Handle 0.8.x format (archive_results list)
        for result_data in index_data.get('archive_results', []):
            self._create_archive_result_if_missing(result_data, existing)

        # Handle 0.7.x format (history dict)
        if 'history' in index_data and isinstance(index_data['history'], dict):
            for plugin, result_list in index_data['history'].items():
                if isinstance(result_list, list):
                    for result_data in result_list:
                        # Support both old 'extractor' and new 'plugin' keys for backwards compat
                        result_data['plugin'] = result_data.get('plugin') or result_data.get('extractor') or plugin
                        self._create_archive_result_if_missing(result_data, existing)

    def _create_archive_result_if_missing(self, result_data: dict, existing: dict):
        """Create ArchiveResult if not already in DB."""
        from dateutil import parser

        # Support both old 'extractor' and new 'plugin' keys for backwards compat
        plugin = result_data.get('plugin') or result_data.get('extractor', '')
        if not plugin:
            return

        start_ts = None
        if result_data.get('start_ts'):
            try:
                start_ts = parser.parse(result_data['start_ts'])
            except:
                pass

        if (plugin, start_ts) in existing:
            return

        try:
            end_ts = None
            if result_data.get('end_ts'):
                try:
                    end_ts = parser.parse(result_data['end_ts'])
                except:
                    pass

            ArchiveResult.objects.create(
                snapshot=self,
                plugin=plugin,
                hook_name=result_data.get('hook_name', ''),
                status=result_data.get('status', 'failed'),
                output_str=result_data.get('output', ''),
                cmd=result_data.get('cmd', []),
                pwd=result_data.get('pwd', str(self.output_dir)),
                start_ts=start_ts,
                end_ts=end_ts,
            )
        except:
            pass

    def write_index_json(self):
        """Write index.json in 0.9.x format."""
        import json

        index_path = Path(self.output_dir) / 'index.json'

        data = {
            'url': self.url,
            'timestamp': self.timestamp,
            'title': self.title or '',
            'tags': ','.join(sorted(self.tags.values_list('name', flat=True))),
            'fs_version': self.fs_version,
            'bookmarked_at': self.bookmarked_at.isoformat() if self.bookmarked_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'archive_results': [
                {
                    'plugin': ar.plugin,
                    'status': ar.status,
                    'start_ts': ar.start_ts.isoformat() if ar.start_ts else None,
                    'end_ts': ar.end_ts.isoformat() if ar.end_ts else None,
                    'output': ar.output_str or '',
                    'cmd': ar.cmd if isinstance(ar.cmd, list) else [],
                    'pwd': ar.pwd,
                }
                for ar in ArchiveResult.objects.filter(snapshot=self).order_by('start_ts')
            ],
        }

        index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(index_path, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)

    # =========================================================================
    # Snapshot Utilities
    # =========================================================================

    @staticmethod
    def move_directory_to_invalid(snapshot_dir: Path):
        """
        Move invalid directory to data/invalid/YYYYMMDD/.

        Used by: archivebox update (when encountering invalid directories)
        """
        from datetime import datetime
        import shutil

        invalid_dir = CONSTANTS.DATA_DIR / 'invalid' / datetime.now().strftime('%Y%m%d')
        invalid_dir.mkdir(parents=True, exist_ok=True)

        dest = invalid_dir / snapshot_dir.name
        counter = 1
        while dest.exists():
            dest = invalid_dir / f"{snapshot_dir.name}_{counter}"
            counter += 1

        try:
            shutil.move(str(snapshot_dir), str(dest))
        except:
            pass

    @classmethod
    def find_and_merge_duplicates(cls) -> int:
        """
        Find and merge snapshots with same url:timestamp.
        Returns count of duplicate sets merged.

        Used by: archivebox update (Phase 3: deduplication)
        """
        from django.db.models import Count

        duplicates = (
            cls.objects
            .values('url', 'timestamp')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        merged = 0
        for dup in duplicates.iterator(chunk_size=500):
            snapshots = list(
                cls.objects
                .filter(url=dup['url'], timestamp=dup['timestamp'])
                .order_by('created_at')  # Keep oldest
            )

            if len(snapshots) > 1:
                try:
                    cls._merge_snapshots(snapshots)
                    merged += 1
                except:
                    pass

        return merged

    @classmethod
    def _merge_snapshots(cls, snapshots: list['Snapshot']):
        """
        Merge exact duplicates.
        Keep oldest, union files + ArchiveResults.
        """
        import shutil

        keeper = snapshots[0]
        duplicates = snapshots[1:]

        keeper_dir = Path(keeper.output_dir)

        for dup in duplicates:
            dup_dir = Path(dup.output_dir)

            # Merge files
            if dup_dir.exists() and dup_dir != keeper_dir:
                for dup_file in dup_dir.rglob('*'):
                    if not dup_file.is_file():
                        continue

                    rel = dup_file.relative_to(dup_dir)
                    keeper_file = keeper_dir / rel

                    if not keeper_file.exists():
                        keeper_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(dup_file, keeper_file)

                try:
                    shutil.rmtree(dup_dir)
                except:
                    pass

            # Merge tags
            for tag in dup.tags.all():
                keeper.tags.add(tag)

            # Move ArchiveResults
            ArchiveResult.objects.filter(snapshot=dup).update(snapshot=keeper)

            # Delete
            dup.delete()

    # =========================================================================
    # Output Directory Properties
    # =========================================================================

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
        """Generate HTML icons showing which extractor plugins have succeeded for this snapshot"""
        from django.utils.html import format_html, mark_safe

        cache_key = f'result_icons:{self.pk}:{(self.downloaded_at or self.modified_at or self.created_at or self.bookmarked_at).timestamp()}'

        def calc_icons():
            if hasattr(self, '_prefetched_objects_cache') and 'archiveresult_set' in self._prefetched_objects_cache:
                archive_results = {r.plugin: r for r in self.archiveresult_set.all() if r.status == "succeeded" and (r.output_files or r.output_str)}
            else:
                # Filter for results that have either output_files or output_str
                from django.db.models import Q
                archive_results = {r.plugin: r for r in self.archiveresult_set.filter(
                    Q(status="succeeded") & (Q(output_files__isnull=False) | ~Q(output_str=''))
                )}

            path = self.archive_path
            canon = self.canonical_outputs()
            output = ""
            output_template = '<a href="/{}/{}" class="exists-{}" title="{}">{}</a> &nbsp;'

            # Get all plugins from hooks system (sorted by numeric prefix)
            all_plugins = [get_plugin_name(e) for e in get_plugins()]

            for plugin in all_plugins:
                result = archive_results.get(plugin)
                existing = result and result.status == 'succeeded' and (result.output_files or result.output_str)
                icon = get_plugin_icon(plugin)

                # Skip plugins with empty icons that have no output
                # (e.g., staticfile only shows when there's actual output)
                if not icon.strip() and not existing:
                    continue

                output += format_html(
                    output_template,
                    path,
                    canon.get(plugin, plugin + '/'),
                    str(bool(existing)),
                    plugin,
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
        import os

        current_path = self.get_storage_path_for_version(self.fs_version)

        if current_path.exists():
            return str(current_path)

        # Check for backwards-compat symlink
        old_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
        if old_path.is_symlink():
            return str(Path(os.readlink(old_path)).resolve())
        elif old_path.exists():
            return str(old_path)

        return str(current_path)

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
        Execute snapshot by creating pending ArchiveResults for all enabled hooks.

        Called by: SnapshotMachine.enter_started()

        Hook Lifecycle:
            1. discover_hooks('Snapshot') → finds all plugin hooks
            2. For each hook:
               - Create ArchiveResult with status=QUEUED
               - Store hook_name (e.g., 'on_Snapshot__50_wget.py')
            3. ArchiveResults execute independently via ArchiveResultMachine
            4. Hook execution happens in ArchiveResult.run(), NOT here

        Returns:
            list[ArchiveResult]: Newly created pending results
        """
        return self.create_pending_archiveresults()

    def cleanup(self):
        """
        Clean up background ArchiveResult hooks.

        Called by the state machine when entering the 'sealed' state.
        Kills any background hooks and finalizes their ArchiveResults.
        """
        from archivebox.hooks import kill_process

        # Kill any background ArchiveResult hooks
        if not self.OUTPUT_DIR.exists():
            return

        # Find all .pid files in this snapshot's output directory
        for pid_file in self.OUTPUT_DIR.glob('**/*.pid'):
            kill_process(pid_file, validate=True)

        # Update all STARTED ArchiveResults from filesystem
        results = self.archiveresult_set.filter(status=ArchiveResult.StatusChoices.STARTED)
        for ar in results:
            ar.update_from_output()

    def has_running_background_hooks(self) -> bool:
        """
        Check if any ArchiveResult background hooks are still running.

        Used by state machine to determine if snapshot is finished.
        """
        from archivebox.hooks import process_is_alive

        if not self.OUTPUT_DIR.exists():
            return False

        for plugin_dir in self.OUTPUT_DIR.iterdir():
            if not plugin_dir.is_dir():
                continue
            pid_file = plugin_dir / 'hook.pid'
            if process_is_alive(pid_file):
                return True

        return False

    @staticmethod
    def from_jsonl(record: Dict[str, Any], overrides: Dict[str, Any] = None, queue_for_extraction: bool = True):
        """
        Create/update Snapshot from JSONL record or dict.

        Unified method that handles:
        - ID-based patching: {"id": "...", "title": "new title"}
        - URL-based create/update: {"url": "...", "title": "...", "tags": "..."}
        - Auto-creates Crawl if not provided
        - Optionally queues for extraction

        Args:
            record: Dict with 'url' (for create) or 'id' (for patch), plus other fields
            overrides: Dict with 'crawl', 'snapshot' (parent), 'created_by_id'
            queue_for_extraction: If True, sets status=QUEUED and retry_at (default: True)

        Returns:
            Snapshot instance or None
        """
        import re
        from django.utils import timezone
        from archivebox.misc.util import parse_date
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.config.common import GENERAL_CONFIG

        overrides = overrides or {}

        # If 'id' is provided, lookup and patch that specific snapshot
        snapshot_id = record.get('id')
        if snapshot_id:
            try:
                snapshot = Snapshot.objects.get(id=snapshot_id)

                # Generically update all fields present in record
                update_fields = []
                for field_name, value in record.items():
                    # Skip internal fields
                    if field_name in ('id', 'type'):
                        continue

                    # Skip if field doesn't exist on model
                    if not hasattr(snapshot, field_name):
                        continue

                    # Special parsing for date fields
                    if field_name in ('bookmarked_at', 'retry_at', 'created_at', 'modified_at'):
                        if value and isinstance(value, str):
                            value = parse_date(value)

                    # Update field if value is provided and different
                    if value is not None and getattr(snapshot, field_name) != value:
                        setattr(snapshot, field_name, value)
                        update_fields.append(field_name)

                if update_fields:
                    snapshot.save(update_fields=update_fields + ['modified_at'])

                return snapshot
            except Snapshot.DoesNotExist:
                # ID not found, fall through to create-by-URL logic
                pass

        url = record.get('url')
        if not url:
            return None

        # Determine or create crawl (every snapshot must have a crawl)
        crawl = overrides.get('crawl')
        parent_snapshot = overrides.get('snapshot')  # Parent snapshot
        created_by_id = overrides.get('created_by_id') or (parent_snapshot.created_by.pk if parent_snapshot else get_or_create_system_user_pk())

        # If no crawl provided, inherit from parent or auto-create one
        if not crawl:
            if parent_snapshot:
                # Inherit crawl from parent snapshot
                crawl = parent_snapshot.crawl
            else:
                # Auto-create a single-URL crawl
                from archivebox.crawls.models import Crawl
                from archivebox.config import CONSTANTS

                timestamp_str = timezone.now().strftime("%Y-%m-%d__%H-%M-%S")
                sources_file = CONSTANTS.SOURCES_DIR / f'{timestamp_str}__auto_crawl.txt'
                sources_file.parent.mkdir(parents=True, exist_ok=True)
                sources_file.write_text(url)

                crawl = Crawl.objects.create(
                    urls=url,
                    max_depth=0,
                    label=f'auto-created for {url[:50]}',
                    created_by_id=created_by_id,
                )

        # Parse tags
        tags_str = record.get('tags', '')
        tag_list = []
        if tags_str:
            tag_list = list(dict.fromkeys(
                tag.strip() for tag in re.split(GENERAL_CONFIG.TAG_SEPARATOR_PATTERN, tags_str)
                if tag.strip()
            ))

        # Get most recent snapshot with this URL (URLs can exist in multiple crawls)
        snapshot = Snapshot.objects.filter(url=url).order_by('-created_at').first()

        title = record.get('title')
        timestamp = record.get('timestamp')

        if snapshot:
            # Update existing snapshot
            if title and (not snapshot.title or len(title) > len(snapshot.title or '')):
                snapshot.title = title
                snapshot.save(update_fields=['title', 'modified_at'])
        else:
            # Create new snapshot
            if timestamp:
                while Snapshot.objects.filter(timestamp=timestamp).exists():
                    timestamp = str(float(timestamp) + 1.0)

            snapshot = Snapshot.objects.create(
                url=url,
                timestamp=timestamp,
                title=title,
                crawl=crawl,
            )

        # Update tags
        if tag_list:
            existing_tags = set(snapshot.tags.values_list('name', flat=True))
            new_tags = set(tag_list) | existing_tags
            snapshot.save_tags(new_tags)

        # Queue for extraction and update additional fields
        update_fields = []

        if queue_for_extraction:
            snapshot.status = Snapshot.StatusChoices.QUEUED
            snapshot.retry_at = timezone.now()
            update_fields.extend(['status', 'retry_at'])

        # Update additional fields if provided
        for field_name in ('depth', 'parent_snapshot_id', 'crawl_id', 'bookmarked_at'):
            value = record.get(field_name)
            if value is not None and getattr(snapshot, field_name) != value:
                setattr(snapshot, field_name, value)
                update_fields.append(field_name)

        if update_fields:
            snapshot.save(update_fields=update_fields + ['modified_at'])

        return snapshot

    def create_pending_archiveresults(self) -> list['ArchiveResult']:
        """
        Create ArchiveResult records for all enabled hooks.

        Uses the hooks system to discover available hooks from:
        - archivebox/plugins/*/on_Snapshot__*.{py,sh,js}
        - data/plugins/*/on_Snapshot__*.{py,sh,js}

        Creates one ArchiveResult per hook (not per plugin), with hook_name set.
        This enables step-based execution where all hooks in a step can run in parallel.
        """
        from archivebox.hooks import discover_hooks

        hooks = discover_hooks('Snapshot')
        archiveresults = []

        for hook_path in hooks:
            hook_name = hook_path.name  # e.g., 'on_Snapshot__50_wget.py'
            plugin = hook_path.parent.name  # e.g., 'wget'

            # Check if AR already exists for this specific hook
            if ArchiveResult.objects.filter(snapshot=self, hook_name=hook_name).exists():
                continue

            archiveresult, created = ArchiveResult.objects.get_or_create(
                snapshot=self,
                hook_name=hook_name,
                defaults={
                    'plugin': plugin,
                    'status': ArchiveResult.INITIAL_STATE,
                    'retry_at': timezone.now(),
                },
            )
            if archiveresult.status == ArchiveResult.INITIAL_STATE:
                archiveresults.append(archiveresult)

        return archiveresults

    def advance_step_if_ready(self) -> bool:
        """
        Advance current_step if all foreground hooks in current step are finished.

        Called by the state machine to check if step can advance.
        Background hooks (.bg) don't block step advancement.

        Step advancement rules:
        - All foreground ARs in current step must be finished (SUCCEEDED/FAILED/SKIPPED)
        - Background ARs (hook_name contains '.bg.') are ignored for advancement
        - When ready, increments current_step by 1 (up to 9)

        Returns:
            True if step was advanced, False if not ready or already at step 9.
        """
        from archivebox.hooks import extract_step, is_background_hook

        if self.current_step >= 9:
            return False  # Already at final step

        # Get all ARs for current step that are foreground
        current_step_ars = self.archiveresult_set.filter(
            hook_name__isnull=False
        ).exclude(hook_name='')

        # Check each AR in current step
        for ar in current_step_ars:
            ar_step = extract_step(ar.hook_name)
            if ar_step != self.current_step:
                continue  # Not in current step

            if is_background_hook(ar.hook_name):
                continue  # Background hooks don't block

            # Foreground hook in current step - check if finished
            if ar.status not in ArchiveResult.FINAL_OR_ACTIVE_STATES:
                # Still pending/queued - can't advance
                return False

            if ar.status == ArchiveResult.StatusChoices.STARTED:
                # Still running - can't advance
                return False

        # All foreground hooks in current step are finished - advance!
        self.current_step += 1
        self.save(update_fields=['current_step', 'modified_at'])
        return True

    def is_finished_processing(self) -> bool:
        """
        Check if this snapshot has finished processing.

        Used by SnapshotMachine.is_finished() to determine if snapshot is complete.

        Returns:
            True if all archiveresults are finished (or no work to do), False otherwise.
        """
        # if no archiveresults exist yet, it's not finished
        if not self.archiveresult_set.exists():
            return False

        # Try to advance step if ready (handles step-based hook execution)
        # This will increment current_step when all foreground hooks in current step are done
        while self.advance_step_if_ready():
            pass  # Keep advancing until we can't anymore

        # if archiveresults exist but are still pending, it's not finished
        if self.pending_archiveresults().exists():
            return False

        # Don't wait for background hooks - they'll be cleaned up on entering sealed state
        # Background hooks in STARTED state are excluded by pending_archiveresults()
        # (STARTED is in FINAL_OR_ACTIVE_STATES) so once all results are FINAL or ACTIVE,
        # we can transition to sealed and cleanup() will kill the background hooks

        # otherwise archiveresults exist and are all finished, so it's finished
        return True

    def retry_failed_archiveresults(self, retry_at: Optional['timezone.datetime'] = None) -> int:
        """
        Reset failed/skipped ArchiveResults to queued for retry.

        This enables seamless retry of the entire extraction pipeline:
        - Resets FAILED and SKIPPED results to QUEUED
        - Sets retry_at so workers pick them up
        - Plugins run in order (numeric prefix)
        - Each plugin checks its dependencies at runtime

        Dependency handling (e.g., chrome_session → screenshot):
        - Plugins check if required outputs exist before running
        - If dependency output missing → plugin returns 'skipped'
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

        # Also reset the snapshot and current_step so it gets re-checked from the beginning
        if count > 0:
            self.status = self.StatusChoices.STARTED
            self.retry_at = retry_at
            self.current_step = 0  # Reset to step 0 for retry
            self.save(update_fields=['status', 'retry_at', 'current_step', 'modified_at'])

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
        """
        Intelligently discover the best output file for each plugin.
        Uses actual ArchiveResult data and filesystem scanning with smart heuristics.
        """
        FAVICON_PROVIDER = 'https://www.google.com/s2/favicons?domain={}'

        # Mimetypes that can be embedded/previewed in an iframe
        IFRAME_EMBEDDABLE_EXTENSIONS = {
            'html', 'htm', 'pdf', 'txt', 'md', 'json', 'jsonl',
            'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico',
            'mp4', 'webm', 'mp3', 'opus', 'ogg', 'wav',
        }

        MIN_DISPLAY_SIZE = 15_000  # 15KB - filter out tiny files
        MAX_SCAN_FILES = 50  # Don't scan massive directories

        def find_best_output_in_dir(dir_path: Path, plugin_name: str) -> Optional[str]:
            """Find the best representative file in a plugin's output directory"""
            if not dir_path.exists() or not dir_path.is_dir():
                return None

            candidates = []
            file_count = 0

            # Special handling for media plugin - look for thumbnails
            is_media_dir = plugin_name == 'media'

            # Scan for suitable files
            for file_path in dir_path.rglob('*'):
                file_count += 1
                if file_count > MAX_SCAN_FILES:
                    break

                if file_path.is_dir() or file_path.name.startswith('.'):
                    continue

                ext = file_path.suffix.lstrip('.').lower()
                if ext not in IFRAME_EMBEDDABLE_EXTENSIONS:
                    continue

                try:
                    size = file_path.stat().st_size
                except OSError:
                    continue

                # For media dir, allow smaller image files (thumbnails are often < 15KB)
                min_size = 5_000 if (is_media_dir and ext in ('png', 'jpg', 'jpeg', 'webp', 'gif')) else MIN_DISPLAY_SIZE
                if size < min_size:
                    continue

                # Prefer main files: index.html, output.*, content.*, etc.
                priority = 0
                name_lower = file_path.name.lower()

                if is_media_dir:
                    # Special prioritization for media directories
                    if any(keyword in name_lower for keyword in ('thumb', 'thumbnail', 'cover', 'poster')):
                        priority = 200  # Highest priority for thumbnails
                    elif ext in ('png', 'jpg', 'jpeg', 'webp', 'gif'):
                        priority = 150  # High priority for any image
                    elif ext in ('mp4', 'webm', 'mp3', 'opus', 'ogg'):
                        priority = 100  # Lower priority for actual media files
                    else:
                        priority = 50
                elif 'index' in name_lower:
                    priority = 100
                elif name_lower.startswith(('output', 'content', plugin_name)):
                    priority = 50
                elif ext in ('html', 'htm', 'pdf'):
                    priority = 30
                elif ext in ('png', 'jpg', 'jpeg', 'webp'):
                    priority = 20
                else:
                    priority = 10

                candidates.append((priority, size, file_path))

            if not candidates:
                return None

            # Sort by priority (desc), then size (desc)
            candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
            best_file = candidates[0][2]
            return str(best_file.relative_to(Path(self.output_dir)))

        canonical = {
            'index_path': 'index.html',
            'google_favicon_path': FAVICON_PROVIDER.format(self.domain),
            'archive_org_path': f'https://web.archive.org/web/{self.base_url}',
        }

        # Scan each ArchiveResult's output directory for the best file
        snap_dir = Path(self.output_dir)
        for result in self.archiveresult_set.filter(status='succeeded'):
            if not result.output_files and not result.output_str:
                continue

            # Try to find the best output file for this plugin
            plugin_dir = snap_dir / result.plugin
            best_output = None

            # Check output_files first (new field)
            if result.output_files:
                first_file = next(iter(result.output_files.keys()), None)
                if first_file and (plugin_dir / first_file).exists():
                    best_output = f'{result.plugin}/{first_file}'

            # Fallback to output_str if it looks like a path
            if not best_output and result.output_str and (snap_dir / result.output_str).exists():
                best_output = result.output_str

            if not best_output and plugin_dir.exists():
                # Intelligently find the best file in the plugin's directory
                best_output = find_best_output_in_dir(plugin_dir, result.plugin)

            if best_output:
                canonical[f'{result.plugin}_path'] = best_output

        # Also scan top-level for legacy outputs (backwards compatibility)
        for file_path in snap_dir.glob('*'):
            if file_path.is_dir() or file_path.name in ('index.html', 'index.json'):
                continue

            ext = file_path.suffix.lstrip('.').lower()
            if ext not in IFRAME_EMBEDDABLE_EXTENSIONS:
                continue

            try:
                size = file_path.stat().st_size
                if size >= MIN_DISPLAY_SIZE:
                    # Add as generic output with stem as key
                    key = f'{file_path.stem}_path'
                    if key not in canonical:
                        canonical[key] = file_path.name
            except OSError:
                continue

        if self.is_static:
            static_path = f'warc/{self.timestamp}'
            canonical.update({
                'title': self.basename,
                'wget_path': static_path,
            })

        return canonical

    def latest_outputs(self, status: Optional[str] = None) -> Dict[str, Any]:
        """Get the latest output that each plugin produced"""
        from archivebox.hooks import get_plugins
        from django.db.models import Q

        latest: Dict[str, Any] = {}
        for plugin in get_plugins():
            results = self.archiveresult_set.filter(plugin=plugin)
            if status is not None:
                results = results.filter(status=status)
            # Filter for results with output_files or output_str
            results = results.filter(Q(output_files__isnull=False) | ~Q(output_str='')).order_by('-start_ts')
            result = results.first()
            # Return embed_path() for backwards compatibility
            latest[plugin] = result.embed_path() if result else None
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


# =============================================================================
# Snapshot State Machine
# =============================================================================

class SnapshotMachine(BaseStateMachine, strict_states=True):
    """
    State machine for managing Snapshot lifecycle.

    Hook Lifecycle:
    ┌─────────────────────────────────────────────────────────────┐
    │ QUEUED State                                                │
    │  • Waiting for snapshot to be ready                         │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() when can_start()
    ┌─────────────────────────────────────────────────────────────┐
    │ STARTED State → enter_started()                             │
    │  1. snapshot.run()                                          │
    │     • discover_hooks('Snapshot') → finds all plugin hooks   │
    │     • create_pending_archiveresults() → creates ONE         │
    │       ArchiveResult per hook (NO execution yet)             │
    │  2. ArchiveResults process independently with their own     │
    │     state machines (see ArchiveResultMachine)               │
    │  3. Advance through steps 0-9 as foreground hooks complete  │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() when is_finished()
    ┌─────────────────────────────────────────────────────────────┐
    │ SEALED State → enter_sealed()                               │
    │  • cleanup() → kills any background hooks still running     │
    │  • Set retry_at=None (no more processing)                   │
    └─────────────────────────────────────────────────────────────┘

    https://github.com/ArchiveBox/ArchiveBox/wiki/ArchiveBox-Architecture-Diagrams
    """

    model_attr_name = 'snapshot'

    # States
    queued = State(value=Snapshot.StatusChoices.QUEUED, initial=True)
    started = State(value=Snapshot.StatusChoices.STARTED)
    sealed = State(value=Snapshot.StatusChoices.SEALED, final=True)

    # Tick Event
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(sealed, cond='is_finished')
    )

    def can_start(self) -> bool:
        can_start = bool(self.snapshot.url)
        return can_start

    def is_finished(self) -> bool:
        """Check if snapshot processing is complete - delegates to model method."""
        return self.snapshot.is_finished_processing()

    @queued.enter
    def enter_queued(self):
        self.snapshot.update_and_requeue(
            retry_at=timezone.now(),
            status=Snapshot.StatusChoices.QUEUED,
        )

    @started.enter
    def enter_started(self):
        # lock the snapshot while we create the pending archiveresults
        self.snapshot.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=30),  # if failed, wait 30s before retrying
        )

        # Run the snapshot - creates pending archiveresults for all enabled plugins
        self.snapshot.run()

        # unlock the snapshot after we're done + set status = started
        self.snapshot.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=5),  # check again in 5s
            status=Snapshot.StatusChoices.STARTED,
        )

    @sealed.enter
    def enter_sealed(self):
        # Clean up background hooks
        self.snapshot.cleanup()

        self.snapshot.update_and_requeue(
            retry_at=None,
            status=Snapshot.StatusChoices.SEALED,
        )


class ArchiveResultManager(models.Manager):
    def indexable(self, sorted: bool = True):
        INDEXABLE_METHODS = [r[0] for r in EXTRACTOR_INDEXING_PRECEDENCE]
        qs = self.get_queryset().filter(plugin__in=INDEXABLE_METHODS, status='succeeded')
        if sorted:
            precedence = [When(plugin=method, then=Value(p)) for method, p in EXTRACTOR_INDEXING_PRECEDENCE]
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
    def get_plugin_choices(cls):
        """Get plugin choices from discovered hooks (for forms/admin)."""
        plugins = [get_plugin_name(e) for e in get_plugins()]
        return tuple((e, e) for e in plugins)

    # Keep AutoField for backward compatibility with 0.7.x databases
    # UUID field is added separately by migration for new records
    id = models.AutoField(primary_key=True, editable=False)
    # Note: unique constraint is added by migration 0027 - don't set unique=True here
    # or SQLite table recreation in earlier migrations will fail
    uuid = models.UUIDField(default=uuid7, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    snapshot: Snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)  # type: ignore
    # No choices= constraint - plugin names come from plugin system and can be any string
    plugin = models.CharField(max_length=32, blank=False, null=False, db_index=True)
    hook_name = models.CharField(max_length=255, blank=True, default='', db_index=True, help_text='Full filename of the hook that executed (e.g., on_Snapshot__50_wget.py)')
    pwd = models.CharField(max_length=256, default=None, null=True, blank=True)
    cmd = models.JSONField(default=None, null=True, blank=True)
    cmd_version = models.CharField(max_length=128, default=None, null=True, blank=True)

    # New output fields (replacing old 'output' field)
    output_str = models.TextField(blank=True, default='', help_text='Human-readable output summary')
    output_json = models.JSONField(null=True, blank=True, default=None, help_text='Structured metadata (headers, redirects, etc.)')
    output_files = models.JSONField(default=dict, help_text='Dict of {relative_path: {metadata}}')
    output_size = models.BigIntegerField(default=0, help_text='Total bytes of all output files')
    output_mimetypes = models.CharField(max_length=512, blank=True, default='', help_text='CSV of mimetypes sorted by size')

    # Binary FK (optional - set when hook reports cmd)
    binary = models.ForeignKey(
        Binary,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='archiveresults',
        help_text='Primary binary used by this hook'
    )

    start_ts = models.DateTimeField(default=None, null=True, blank=True)
    end_ts = models.DateTimeField(default=None, null=True, blank=True)

    status = ModelWithStateMachine.StatusField(choices=StatusChoices.choices, default=StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)
    notes = models.TextField(blank=True, null=False, default='')
    output_dir = models.CharField(max_length=256, default=None, null=True, blank=True)
    iface = models.ForeignKey(NetworkInterface, on_delete=models.SET_NULL, null=True, blank=True)

    state_machine_name = 'core.models.ArchiveResultMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    active_state = StatusChoices.STARTED

    objects = ArchiveResultManager()

    class Meta(TypedModelMeta):
        app_label = 'core'
        verbose_name = 'Archive Result'
        verbose_name_plural = 'Archive Results Log'

    def __str__(self):
        return f'[{self.id}] {self.snapshot.url[:64]} -> {self.plugin}'

    @property
    def created_by(self):
        """Convenience property to access the user who created this archive result via its snapshot's crawl."""
        return self.snapshot.crawl.created_by

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
                plugin=self.plugin,
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
        return f'/{self.snapshot.archive_path}/{self.plugin}'

    @property
    def plugin_module(self) -> Any | None:
        # Hook scripts are now used instead of Python plugin modules
        # The plugin name maps to hooks in archivebox/plugins/{plugin}/
        return None

    def output_exists(self) -> bool:
        return os.path.exists(Path(self.snapshot_dir) / self.plugin)

    def embed_path(self) -> Optional[str]:
        """
        Get the relative path to the embeddable output file for this result.

        Returns the first file from output_files if set, otherwise tries to
        find a reasonable default based on the plugin type.
        """
        # Check output_files dict for primary output
        if self.output_files:
            # Return first file from output_files (dict preserves insertion order)
            first_file = next(iter(self.output_files.keys()), None)
            if first_file:
                return f'{self.plugin}/{first_file}'

        # Fallback: check output_str if it looks like a file path
        if self.output_str and ('/' in self.output_str or '.' in self.output_str):
            return self.output_str

        # Try to find output file based on plugin's canonical output path
        canonical = self.snapshot.canonical_outputs()
        plugin_key = f'{self.plugin}_path'
        if plugin_key in canonical:
            return canonical[plugin_key]

        # Fallback to plugin directory
        return f'{self.plugin}/'

    def create_output_dir(self):
        output_dir = Path(self.snapshot_dir) / self.plugin
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    @property
    def output_dir_name(self) -> str:
        return self.plugin

    @property
    def output_dir_parent(self) -> str:
        return str(self.snapshot.OUTPUT_DIR.relative_to(CONSTANTS.DATA_DIR))

    def save_search_index(self):
        pass

    def cascade_health_update(self, success: bool):
        """Update health stats for self, parent Snapshot, and grandparent Crawl."""
        self.increment_health_stats(success)
        self.snapshot.increment_health_stats(success)
        self.snapshot.crawl.increment_health_stats(success)

    def run(self):
        """
        Execute this ArchiveResult's hook and update status.

        If self.hook_name is set, runs only that specific hook.
        If self.hook_name is empty, discovers and runs all hooks for self.plugin (backwards compat).

        Updates status/output fields, queues discovered URLs, and triggers indexing.
        """
        from django.utils import timezone
        from archivebox.hooks import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR, run_hook, is_background_hook
        from archivebox.config.configset import get_config

        # Get merged config with proper context
        config = get_config(
            crawl=self.snapshot.crawl,
            snapshot=self.snapshot,
        )

        # Determine which hook(s) to run
        hooks = []

        if self.hook_name:
            # SPECIFIC HOOK MODE: Find the specific hook by name
            for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
                if not base_dir.exists():
                    continue
                plugin_dir = base_dir / self.plugin
                if plugin_dir.exists():
                    hook_path = plugin_dir / self.hook_name
                    if hook_path.exists():
                        hooks.append(hook_path)
                        break
        else:
            # LEGACY MODE: Discover all hooks for this plugin (backwards compatibility)
            for base_dir in (BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR):
                if not base_dir.exists():
                    continue
                plugin_dir = base_dir / self.plugin
                if plugin_dir.exists():
                    matches = list(plugin_dir.glob('on_Snapshot__*.*'))
                    if matches:
                        hooks.extend(sorted(matches))

        if not hooks:
            self.status = self.StatusChoices.FAILED
            if self.hook_name:
                self.output_str = f'Hook not found: {self.plugin}/{self.hook_name}'
            else:
                self.output_str = f'No hooks found for plugin: {self.plugin}'
            self.retry_at = None
            self.save()
            return

        # Output directory is plugin_dir for the hook output
        plugin_dir = Path(self.snapshot.output_dir) / self.plugin

        start_ts = timezone.now()
        is_bg_hook = False

        for hook in hooks:
            # Check if this is a background hook
            is_bg_hook = is_background_hook(hook.name)

            result = run_hook(
                hook,
                output_dir=plugin_dir,
                config=config,
                url=self.snapshot.url,
                snapshot_id=str(self.snapshot.id),
                crawl_id=str(self.snapshot.crawl.id),
                depth=self.snapshot.depth,
            )

            # Background hooks return None
            if result is None:
                is_bg_hook = True

        # Update status based on hook execution
        if is_bg_hook:
            # BACKGROUND HOOK - still running, return immediately
            # Status stays STARTED, will be finalized by Snapshot.cleanup()
            self.status = self.StatusChoices.STARTED
            self.start_ts = start_ts
            self.pwd = str(plugin_dir)
            self.save()
            return

        # FOREGROUND HOOK - completed, update from filesystem
        self.start_ts = start_ts
        self.pwd = str(plugin_dir)
        self.update_from_output()

        # Clean up empty output directory if no files were created
        if plugin_dir.exists() and not self.output_files:
            try:
                if not any(plugin_dir.iterdir()):
                    plugin_dir.rmdir()
            except (OSError, RuntimeError):
                pass

    def update_from_output(self):
        """
        Update this ArchiveResult from filesystem logs and output files.

        Used for:
        - Foreground hooks that completed (called from ArchiveResult.run())
        - Background hooks that completed (called from Snapshot.cleanup())

        Updates:
        - status, output_str, output_json from ArchiveResult JSONL record
        - output_files, output_size, output_mimetypes by walking filesystem
        - end_ts, retry_at, cmd, cmd_version, binary FK
        - Processes side-effect records (Snapshot, Tag, etc.) via process_hook_records()
        """
        import json
        import mimetypes
        from collections import defaultdict
        from pathlib import Path
        from django.utils import timezone
        from archivebox.hooks import process_hook_records

        plugin_dir = Path(self.pwd) if self.pwd else None
        if not plugin_dir or not plugin_dir.exists():
            self.status = self.StatusChoices.FAILED
            self.output_str = 'Output directory not found'
            self.end_ts = timezone.now()
            self.retry_at = None
            self.save()
            return

        # Read and parse JSONL output from stdout.log
        stdout_file = plugin_dir / 'stdout.log'
        stdout = stdout_file.read_text() if stdout_file.exists() else ''

        records = []
        for line in stdout.splitlines():
            if line.strip() and line.strip().startswith('{'):
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        # Find ArchiveResult record and update status/output from it
        ar_records = [r for r in records if r.get('type') == 'ArchiveResult']
        if ar_records:
            hook_data = ar_records[0]

            # Update status
            status_map = {
                'succeeded': self.StatusChoices.SUCCEEDED,
                'failed': self.StatusChoices.FAILED,
                'skipped': self.StatusChoices.SKIPPED,
            }
            self.status = status_map.get(hook_data.get('status', 'failed'), self.StatusChoices.FAILED)

            # Update output fields
            self.output_str = hook_data.get('output_str') or hook_data.get('output') or ''
            self.output_json = hook_data.get('output_json')

            # Update cmd fields
            if hook_data.get('cmd'):
                self.cmd = hook_data['cmd']
                self._set_binary_from_cmd(hook_data['cmd'])
            if hook_data.get('cmd_version'):
                self.cmd_version = hook_data['cmd_version'][:128]
        else:
            # No ArchiveResult record = failed
            self.status = self.StatusChoices.FAILED
            self.output_str = 'Hook did not output ArchiveResult record'

        # Walk filesystem and populate output_files, output_size, output_mimetypes
        exclude_names = {'stdout.log', 'stderr.log', 'hook.pid', 'listener.pid'}
        mime_sizes = defaultdict(int)
        total_size = 0
        output_files = {}

        for file_path in plugin_dir.rglob('*'):
            if not file_path.is_file():
                continue
            if file_path.name in exclude_names:
                continue

            try:
                stat = file_path.stat()
                mime_type, _ = mimetypes.guess_type(str(file_path))
                mime_type = mime_type or 'application/octet-stream'

                relative_path = str(file_path.relative_to(plugin_dir))
                output_files[relative_path] = {}
                mime_sizes[mime_type] += stat.st_size
                total_size += stat.st_size
            except (OSError, IOError):
                continue

        self.output_files = output_files
        self.output_size = total_size
        sorted_mimes = sorted(mime_sizes.items(), key=lambda x: x[1], reverse=True)
        self.output_mimetypes = ','.join(mime for mime, _ in sorted_mimes)

        # Update timestamps
        self.end_ts = timezone.now()
        self.retry_at = None

        self.save()

        # Process side-effect records (filter Snapshots for depth/URL)
        filtered_records = []
        for record in records:
            record_type = record.get('type')

            # Skip ArchiveResult records (already processed above)
            if record_type == 'ArchiveResult':
                continue

            # Filter Snapshot records for depth/URL constraints
            if record_type == 'Snapshot':
                url = record.get('url')
                if not url:
                    continue

                depth = record.get('depth', self.snapshot.depth + 1)
                if depth > self.snapshot.crawl.max_depth:
                    continue

                if not self._url_passes_filters(url):
                    continue

            filtered_records.append(record)

        # Process filtered records with unified dispatcher
        overrides = {
            'snapshot': self.snapshot,
            'crawl': self.snapshot.crawl,
            'created_by_id': self.created_by.pk,
        }
        process_hook_records(filtered_records, overrides=overrides)

        # Cleanup PID files and empty logs
        pid_file = plugin_dir / 'hook.pid'
        pid_file.unlink(missing_ok=True)
        stderr_file = plugin_dir / 'stderr.log'
        if stdout_file.exists() and stdout_file.stat().st_size == 0:
            stdout_file.unlink()
        if stderr_file.exists() and stderr_file.stat().st_size == 0:
            stderr_file.unlink()

    def _set_binary_from_cmd(self, cmd: list) -> None:
        """
        Find Binary for command and set binary FK.

        Tries matching by absolute path first, then by binary name.
        Only matches binaries on the current machine.
        """
        if not cmd:
            return

        from archivebox.machine.models import Machine

        bin_path_or_name = cmd[0] if isinstance(cmd, list) else cmd
        machine = Machine.current()

        # Try matching by absolute path first
        binary = Binary.objects.filter(
            abspath=bin_path_or_name,
            machine=machine
        ).first()

        if binary:
            self.binary = binary
            return

        # Fallback: match by binary name
        bin_name = Path(bin_path_or_name).name
        binary = Binary.objects.filter(
            name=bin_name,
            machine=machine
        ).first()

        if binary:
            self.binary = binary

    def _url_passes_filters(self, url: str) -> bool:
        """Check if URL passes URL_ALLOWLIST and URL_DENYLIST config filters.

        Uses proper config hierarchy: defaults -> file -> env -> machine -> user -> crawl -> snapshot
        """
        import re
        from archivebox.config.configset import get_config

        # Get merged config with proper hierarchy
        config = get_config(
            user=self.created_by,
            crawl=self.snapshot.crawl,
            snapshot=self.snapshot,
        )

        # Get allowlist/denylist (can be string or list)
        allowlist_raw = config.get('URL_ALLOWLIST', '')
        denylist_raw = config.get('URL_DENYLIST', '')

        # Normalize to list of patterns
        def to_pattern_list(value):
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [p.strip() for p in value.split(',') if p.strip()]
            return []

        allowlist = to_pattern_list(allowlist_raw)
        denylist = to_pattern_list(denylist_raw)

        # Denylist takes precedence
        if denylist:
            for pattern in denylist:
                try:
                    if re.search(pattern, url):
                        return False
                except re.error:
                    continue  # Skip invalid regex patterns

        # If allowlist exists, URL must match at least one pattern
        if allowlist:
            for pattern in allowlist:
                try:
                    if re.search(pattern, url):
                        return True
                except re.error:
                    continue  # Skip invalid regex patterns
            return False  # No allowlist patterns matched

        return True  # No filters or passed filters

    @property
    def output_dir(self) -> Path:
        """Get the output directory for this plugin's results."""
        return Path(self.snapshot.output_dir) / self.plugin

    def is_background_hook(self) -> bool:
        """Check if this ArchiveResult is for a background hook."""
        plugin_dir = Path(self.pwd) if self.pwd else None
        if not plugin_dir:
            return False
        pid_file = plugin_dir / 'hook.pid'
        return pid_file.exists()


# =============================================================================
# ArchiveResult State Machine
# =============================================================================

class ArchiveResultMachine(BaseStateMachine, strict_states=True):
    """
    State machine for managing ArchiveResult (single plugin execution) lifecycle.

    Hook Lifecycle:
    ┌─────────────────────────────────────────────────────────────┐
    │ QUEUED State                                                │
    │  • Waiting for its turn to run                              │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() when can_start()
    ┌─────────────────────────────────────────────────────────────┐
    │ STARTED State → enter_started()                             │
    │  1. archiveresult.run()                                     │
    │     • Find specific hook by hook_name                       │
    │     • run_hook(script, output_dir, ...) → subprocess        │
    │                                                              │
    │  2a. FOREGROUND hook (returns HookResult):                  │
    │      • update_from_output() immediately                     │
    │        - Read stdout.log                                    │
    │        - Parse JSONL records                                │
    │        - Extract 'ArchiveResult' record → update status     │
    │        - Walk output_dir → populate output_files            │
    │        - Call process_hook_records() for side effects       │
    │                                                              │
    │  2b. BACKGROUND hook (returns None):                        │
    │      • Status stays STARTED                                 │
    │      • Continues running in background                      │
    │      • Killed by Snapshot.cleanup() when sealed             │
    └─────────────────────────────────────────────────────────────┘
                            ↓ tick() checks status
    ┌─────────────────────────────────────────────────────────────┐
    │ SUCCEEDED / FAILED / SKIPPED / BACKOFF                      │
    │  • Set by hook's JSONL output during update_from_output()   │
    │  • Health stats incremented (num_uses_succeeded/failed)     │
    │  • Parent Snapshot health stats also updated                │
    └─────────────────────────────────────────────────────────────┘

    https://github.com/ArchiveBox/ArchiveBox/wiki/ArchiveBox-Architecture-Diagrams
    """

    model_attr_name = 'archiveresult'

    # States
    queued = State(value=ArchiveResult.StatusChoices.QUEUED, initial=True)
    started = State(value=ArchiveResult.StatusChoices.STARTED)
    backoff = State(value=ArchiveResult.StatusChoices.BACKOFF)
    succeeded = State(value=ArchiveResult.StatusChoices.SUCCEEDED, final=True)
    failed = State(value=ArchiveResult.StatusChoices.FAILED, final=True)
    skipped = State(value=ArchiveResult.StatusChoices.SKIPPED, final=True)

    # Tick Event - transitions based on conditions
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to.itself(unless='is_finished') |
        started.to(succeeded, cond='is_succeeded') |
        started.to(failed, cond='is_failed') |
        started.to(skipped, cond='is_skipped') |
        started.to(backoff, cond='is_backoff') |
        backoff.to.itself(unless='can_start') |
        backoff.to(started, cond='can_start') |
        backoff.to(succeeded, cond='is_succeeded') |
        backoff.to(failed, cond='is_failed') |
        backoff.to(skipped, cond='is_skipped')
    )

    def can_start(self) -> bool:
        can_start = bool(self.archiveresult.snapshot.url)
        return can_start

    def is_succeeded(self) -> bool:
        """Check if extractor plugin succeeded (status was set by run())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.SUCCEEDED

    def is_failed(self) -> bool:
        """Check if extractor plugin failed (status was set by run())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.FAILED

    def is_skipped(self) -> bool:
        """Check if extractor plugin was skipped (status was set by run())."""
        return self.archiveresult.status == ArchiveResult.StatusChoices.SKIPPED

    def is_backoff(self) -> bool:
        """Check if we should backoff and retry later."""
        # Backoff if status is still started (plugin didn't complete) and output_str is empty
        return (
            self.archiveresult.status == ArchiveResult.StatusChoices.STARTED and
            not self.archiveresult.output_str
        )

    def is_finished(self) -> bool:
        """Check if extraction has completed (success, failure, or skipped)."""
        return self.archiveresult.status in (
            ArchiveResult.StatusChoices.SUCCEEDED,
            ArchiveResult.StatusChoices.FAILED,
            ArchiveResult.StatusChoices.SKIPPED,
        )

    @queued.enter
    def enter_queued(self):
        self.archiveresult.update_and_requeue(
            retry_at=timezone.now(),
            status=ArchiveResult.StatusChoices.QUEUED,
            start_ts=None,
        )  # bump the snapshot's retry_at so they pickup any new changes

    @started.enter
    def enter_started(self):
        from archivebox.machine.models import NetworkInterface

        # Lock the object and mark start time
        self.archiveresult.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=120),  # 2 min timeout for plugin
            status=ArchiveResult.StatusChoices.STARTED,
            start_ts=timezone.now(),
            iface=NetworkInterface.current(),
        )

        # Run the plugin - this updates status, output, timestamps, etc.
        self.archiveresult.run()

        # Save the updated result
        self.archiveresult.save()


    @backoff.enter
    def enter_backoff(self):
        self.archiveresult.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=60),
            status=ArchiveResult.StatusChoices.BACKOFF,
            end_ts=None,
        )

    @succeeded.enter
    def enter_succeeded(self):
        self.archiveresult.update_and_requeue(
            retry_at=None,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            end_ts=timezone.now(),
        )

        # Update health stats for ArchiveResult, Snapshot, and Crawl cascade
        self.archiveresult.cascade_health_update(success=True)

    @failed.enter
    def enter_failed(self):
        self.archiveresult.update_and_requeue(
            retry_at=None,
            status=ArchiveResult.StatusChoices.FAILED,
            end_ts=timezone.now(),
        )

        # Update health stats for ArchiveResult, Snapshot, and Crawl cascade
        self.archiveresult.cascade_health_update(success=False)

    @skipped.enter
    def enter_skipped(self):
        self.archiveresult.update_and_requeue(
            retry_at=None,
            status=ArchiveResult.StatusChoices.SKIPPED,
            end_ts=timezone.now(),
        )

    def after_transition(self, event: str, source: State, target: State):
        self.archiveresult.snapshot.update_and_requeue()  # bump snapshot retry time so it picks up all the new changes


# =============================================================================
# State Machine Registration
# =============================================================================

# Manually register state machines with python-statemachine registry
# (normally auto-discovered from statemachines.py, but we define them here for clarity)
registry.register(SnapshotMachine)
registry.register(ArchiveResultMachine)