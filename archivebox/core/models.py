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
    get_plugins, get_plugin_name, get_plugin_icon,
)
from archivebox.base_models.models import (
    ModelWithUUID, ModelWithOutputDir,
    ModelWithConfig, ModelWithNotes, ModelWithHealthStats,
    get_or_create_system_user_pk,
)
from archivebox.workers.models import ModelWithStateMachine, BaseStateMachine
from archivebox.workers.tasks import bg_archive_snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import NetworkInterface, Binary



class Tag(ModelWithUUID):
    # Keep AutoField for compatibility with main branch migrations
    # Don't use UUIDField here - requires complex FK transformation
    id = models.AutoField(primary_key=True, serialize=False, verbose_name='ID')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, default=get_or_create_system_user_pk, null=True, related_name='tag_set')
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

    def to_json(self) -> dict:
        """
        Convert Tag model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION
        return {
            'type': 'Tag',
            'schema_version': VERSION,
            'id': str(self.id),
            'name': self.name,
            'slug': self.slug,
        }

    @staticmethod
    def from_json(record: Dict[str, Any], overrides: Dict[str, Any] = None):
        """
        Create/update Tag from JSON dict.

        Args:
            record: JSON dict with 'name' field
            overrides: Optional dict with 'snapshot' to auto-attach tag

        Returns:
            Tag instance or None
        """
        name = record.get('name')
        if not name:
            return None

        tag, _ = Tag.objects.get_or_create(name=name)

        # Auto-attach to snapshot if in overrides
        if overrides and 'snapshot' in overrides and tag:
            overrides['snapshot'].tags.add(tag)

        return tag


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
        # Don't prefetch by default - it causes "too many open files" during bulk operations
        # Views/templates can add .prefetch_related('tags', 'archiveresult_set') where needed
        return super().get_queryset()

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
    # output_dir is computed via @cached_property from fs_version and get_storage_path_for_version()

    tags = models.ManyToManyField(Tag, blank=True, through=SnapshotTag, related_name='snapshot_set', through_fields=('snapshot', 'tag'))

    state_machine_name = 'archivebox.core.models.SnapshotMachine'
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

    @property
    def process_set(self):
        """Get all Process objects related to this snapshot's ArchiveResults."""
        import json
        import json
        from archivebox.machine.models import Process
        return Process.objects.filter(archiveresult__snapshot_id=self.id)

    @property
    def binary_set(self):
        """Get all Binary objects used by processes related to this snapshot."""
        from archivebox.machine.models import Binary
        return Binary.objects.filter(process_set__archiveresult__snapshot_id=self.id).distinct()

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if not self.bookmarked_at:
            self.bookmarked_at = self.created_at or timezone.now()
        if not self.timestamp:
            self.timestamp = str(self.bookmarked_at.timestamp())

        # Migrate filesystem if needed (happens automatically on save)
        if self.pk and self.fs_migration_needed:
            print(f"[DEBUG save()] Triggering filesystem migration for {str(self.id)[:8]}: {self.fs_version} → {self._fs_current_version()}")
            # Walk through migration chain automatically
            current = self.fs_version
            target = self._fs_current_version()

            while current != target:
                next_ver = self._fs_next_version(current)
                method = f'_fs_migrate_from_{current.replace(".", "_")}_to_{next_ver.replace(".", "_")}'

                # Only run if method exists (most are no-ops)
                if hasattr(self, method):
                    print(f"[DEBUG save()] Running {method}()")
                    getattr(self, method)()

                current = next_ver

            # Update version
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
        2. Convert index.json to index.jsonl INSIDE transaction
        3. Create symlink INSIDE transaction
        4. Update fs_version INSIDE transaction (done by save())
        5. Exit transaction (DB commit)
        6. Delete old files OUTSIDE transaction (after commit)
        """
        import shutil
        from django.db import transaction

        old_dir = self.get_storage_path_for_version('0.8.0')
        new_dir = self.get_storage_path_for_version('0.9.0')

        print(f"[DEBUG _fs_migrate] {self.timestamp}: old_exists={old_dir.exists()}, same={old_dir == new_dir}, new_exists={new_dir.exists()}")

        if not old_dir.exists() or old_dir == new_dir:
            # No migration needed
            print(f"[DEBUG _fs_migrate] Returning None (early return)")
            return None

        if new_dir.exists():
            # New directory already exists (files already copied), but we still need cleanup
            # Return cleanup info so old directory can be cleaned up
            print(f"[DEBUG _fs_migrate] Returning cleanup info (new_dir exists)")
            return (old_dir, new_dir)

        new_dir.mkdir(parents=True, exist_ok=True)

        # Copy all files (idempotent), skipping index.json (will be converted to jsonl)
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

        # Convert index.json to index.jsonl in the new directory
        self.convert_index_json_to_jsonl()

        # Schedule cleanup AFTER transaction commits successfully
        # This ensures DB changes are committed before we delete old files
        from django.db import transaction
        transaction.on_commit(lambda: self._cleanup_old_migration_dir(old_dir, new_dir))

        # Return cleanup info for manual cleanup if needed (when called directly)
        return (old_dir, new_dir)

    def _cleanup_old_migration_dir(self, old_dir: Path, new_dir: Path):
        """
        Delete old directory and create symlink after successful migration.
        """
        import shutil
        import logging

        # Delete old directory
        if old_dir.exists() and not old_dir.is_symlink():
            try:
                shutil.rmtree(old_dir)
            except Exception as e:
                logging.getLogger('archivebox.migration').warning(
                    f"Could not remove old migration directory {old_dir}: {e}"
                )
                return  # Don't create symlink if cleanup failed

        # Create backwards-compat symlink (after old dir is deleted)
        symlink_path = old_dir  # Same path as old_dir
        if symlink_path.is_symlink():
            symlink_path.unlink()

        if not symlink_path.exists():
            try:
                symlink_path.symlink_to(new_dir, target_is_directory=True)
            except Exception as e:
                logging.getLogger('archivebox.migration').warning(
                    f"Could not create symlink from {symlink_path} to {new_dir}: {e}"
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
        Load existing Snapshot from DB by reading index.jsonl or index.json.

        Reads index file, extracts url+timestamp, queries DB.
        Returns existing Snapshot or None if not found/invalid.
        Does NOT create new snapshots.

        ONLY used by: archivebox update (for orphan detection)
        """
        from archivebox.machine.models import Process

        # Try index.jsonl first (new format), then index.json (legacy)
        jsonl_path = snapshot_dir / CONSTANTS.JSONL_INDEX_FILENAME
        json_path = snapshot_dir / CONSTANTS.JSON_INDEX_FILENAME

        data = None
        if jsonl_path.exists():
            try:
                records = Process.parse_records_from_text(jsonl_path.read_text())
                for record in records:
                    if record.get('type') == 'Snapshot':
                        data = record
                        break
            except OSError:
                pass
        elif json_path.exists():
            try:
                with open(json_path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        if not data:
            return None

        url = data.get('url')
        if not url:
            return None

        # Get timestamp - prefer index file, fallback to folder name
        timestamp = cls._select_best_timestamp(
            index_timestamp=data.get('timestamp'),
            folder_name=snapshot_dir.name
        )

        if not timestamp:
            return None

        # Look up existing (try exact match first, then fuzzy match for truncated timestamps)
        try:
            snapshot = cls.objects.get(url=url, timestamp=timestamp)
            print(f"[DEBUG load_from_directory] Found existing snapshot for {url} @ {timestamp}: {str(snapshot.id)[:8]}")
            return snapshot
        except cls.DoesNotExist:
            print(f"[DEBUG load_from_directory] NOT FOUND (exact): {url} @ {timestamp}")
            # Try fuzzy match - index.json may have truncated timestamp
            # e.g., index has "1767000340" but DB has "1767000340.624737"
            candidates = cls.objects.filter(url=url, timestamp__startswith=timestamp)
            if candidates.count() == 1:
                snapshot = candidates.first()
                print(f"[DEBUG load_from_directory] Found via fuzzy match: {snapshot.timestamp}")
                return snapshot
            elif candidates.count() > 1:
                print(f"[DEBUG load_from_directory] Multiple fuzzy matches, using first")
                return candidates.first()
            print(f"[DEBUG load_from_directory] NOT FOUND (fuzzy): {url} @ {timestamp}")
            return None
        except cls.MultipleObjectsReturned:
            # Should not happen with unique constraint
            print(f"[DEBUG load_from_directory] Multiple snapshots found for {url} @ {timestamp}")
            return cls.objects.filter(url=url, timestamp=timestamp).first()

    @classmethod
    def create_from_directory(cls, snapshot_dir: Path) -> Optional['Snapshot']:
        """
        Create new Snapshot from orphaned directory.

        Validates timestamp, ensures uniqueness.
        Returns new UNSAVED Snapshot or None if invalid.

        ONLY used by: archivebox update (for orphan import)
        """
        from archivebox.machine.models import Process

        # Try index.jsonl first (new format), then index.json (legacy)
        jsonl_path = snapshot_dir / CONSTANTS.JSONL_INDEX_FILENAME
        json_path = snapshot_dir / CONSTANTS.JSON_INDEX_FILENAME

        data = None
        if jsonl_path.exists():
            try:
                records = Process.parse_records_from_text(jsonl_path.read_text())
                for record in records:
                    if record.get('type') == 'Snapshot':
                        data = record
                        break
            except OSError:
                pass
        elif json_path.exists():
            try:
                with open(json_path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        if not data:
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

        # Get or create catchall crawl for orphaned snapshots
        from archivebox.crawls.models import Crawl
        system_user_id = get_or_create_system_user_pk()
        catchall_crawl, _ = Crawl.objects.get_or_create(
            label='[migration] orphaned snapshots',
            defaults={
                'urls': f'# Orphaned snapshot: {url}',
                'max_depth': 0,
                'created_by_id': system_user_id,
            }
        )

        return cls(
            url=url,
            timestamp=timestamp,
            title=data.get('title', ''),
            fs_version=fs_version,
            crawl=catchall_crawl,
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

    def reconcile_with_index(self):
        """
        Merge index.json/index.jsonl with DB. DB is source of truth.

        - Title: longest non-URL
        - Tags: union
        - ArchiveResults: keep both (by plugin+start_ts)

        Converts index.json to index.jsonl if needed, then writes back in JSONL format.

        Used by: archivebox update (to sync index with DB)
        """
        import json

        # Try to convert index.json to index.jsonl first
        self.convert_index_json_to_jsonl()

        # Check for index.jsonl (preferred) or index.json (legacy)
        jsonl_path = Path(self.output_dir) / CONSTANTS.JSONL_INDEX_FILENAME
        json_path = Path(self.output_dir) / CONSTANTS.JSON_INDEX_FILENAME

        index_data = {}

        if jsonl_path.exists():
            # Read from JSONL format
            jsonl_data = self.read_index_jsonl()
            if jsonl_data['snapshot']:
                index_data = jsonl_data['snapshot']
                # Convert archive_results list to expected format
                index_data['archive_results'] = jsonl_data['archive_results']
        elif json_path.exists():
            # Fallback to legacy JSON format
            try:
                with open(json_path) as f:
                    index_data = json.load(f)
            except:
                pass

        # Merge title
        self._merge_title_from_index(index_data)

        # Merge tags
        self._merge_tags_from_index(index_data)

        # Merge ArchiveResults
        self._merge_archive_results_from_index(index_data)

        # Write back in JSONL format
        self.write_index_jsonl()

    def reconcile_with_index_json(self):
        """Deprecated: use reconcile_with_index() instead."""
        return self.reconcile_with_index()

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

            # Support both 'output' (legacy) and 'output_str' (new JSONL) field names
            output_str = result_data.get('output_str') or result_data.get('output', '')

            ArchiveResult.objects.create(
                snapshot=self,
                plugin=plugin,
                hook_name=result_data.get('hook_name', ''),
                status=result_data.get('status', 'failed'),
                output_str=output_str,
                cmd=result_data.get('cmd', []),
                pwd=result_data.get('pwd', str(self.output_dir)),
                start_ts=start_ts,
                end_ts=end_ts,
            )
        except:
            pass

    def write_index_json(self):
        """Write index.json in 0.9.x format (deprecated, use write_index_jsonl)."""
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

    def write_index_jsonl(self):
        """
        Write index.jsonl in flat JSONL format.

        Each line is a JSON record with a 'type' field:
        - Snapshot: snapshot metadata (crawl_id, url, tags, etc.)
        - ArchiveResult: extractor results (plugin, status, output, etc.)
        - Binary: binary info used for the extraction
        - Process: process execution details (cmd, exit_code, timing, etc.)
        """
        import json

        index_path = Path(self.output_dir) / CONSTANTS.JSONL_INDEX_FILENAME
        index_path.parent.mkdir(parents=True, exist_ok=True)

        # Track unique binaries and processes to avoid duplicates
        binaries_seen = set()
        processes_seen = set()

        with open(index_path, 'w') as f:
            # Write Snapshot record first (to_json includes crawl_id, fs_version)
            f.write(json.dumps(self.to_json()) + '\n')

            # Write ArchiveResult records with their associated Binary and Process
            # Use select_related to optimize queries
            for ar in self.archiveresult_set.select_related('process__binary').order_by('start_ts'):
                # Write Binary record if not already written
                if ar.process and ar.process.binary and ar.process.binary_id not in binaries_seen:
                    binaries_seen.add(ar.process.binary_id)
                    f.write(json.dumps(ar.process.binary.to_json()) + '\n')

                # Write Process record if not already written
                if ar.process and ar.process_id not in processes_seen:
                    processes_seen.add(ar.process_id)
                    f.write(json.dumps(ar.process.to_json()) + '\n')

                # Write ArchiveResult record
                f.write(json.dumps(ar.to_json()) + '\n')

    def read_index_jsonl(self) -> dict:
        """
        Read index.jsonl and return parsed records grouped by type.

        Returns dict with keys: 'snapshot', 'archive_results', 'binaries', 'processes'
        """
        from archivebox.machine.models import Process
        from archivebox.misc.jsonl import (
            TYPE_SNAPSHOT, TYPE_ARCHIVERESULT, TYPE_BINARY, TYPE_PROCESS,
        )

        index_path = Path(self.output_dir) / CONSTANTS.JSONL_INDEX_FILENAME
        result = {
            'snapshot': None,
            'archive_results': [],
            'binaries': [],
            'processes': [],
        }

        if not index_path.exists():
            return result

        records = Process.parse_records_from_text(index_path.read_text())
        for record in records:
            record_type = record.get('type')
            if record_type == TYPE_SNAPSHOT:
                result['snapshot'] = record
            elif record_type == TYPE_ARCHIVERESULT:
                result['archive_results'].append(record)
            elif record_type == TYPE_BINARY:
                result['binaries'].append(record)
            elif record_type == TYPE_PROCESS:
                result['processes'].append(record)

        return result

    def convert_index_json_to_jsonl(self) -> bool:
        """
        Convert index.json to index.jsonl format.

        Reads existing index.json, creates index.jsonl, and removes index.json.
        Returns True if conversion was performed, False if no conversion needed.
        """
        import json

        json_path = Path(self.output_dir) / CONSTANTS.JSON_INDEX_FILENAME
        jsonl_path = Path(self.output_dir) / CONSTANTS.JSONL_INDEX_FILENAME

        # Skip if already converted or no json file exists
        if jsonl_path.exists() or not json_path.exists():
            return False

        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False

        # Detect format version and extract records
        fs_version = data.get('fs_version', '0.7.0')

        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with open(jsonl_path, 'w') as f:
            # Write Snapshot record
            snapshot_record = {
                'type': 'Snapshot',
                'id': str(self.id),
                'crawl_id': str(self.crawl_id) if self.crawl_id else None,
                'url': data.get('url', self.url),
                'timestamp': data.get('timestamp', self.timestamp),
                'title': data.get('title', self.title or ''),
                'tags': data.get('tags', ''),
                'fs_version': fs_version,
                'bookmarked_at': data.get('bookmarked_at'),
                'created_at': data.get('created_at'),
            }
            f.write(json.dumps(snapshot_record) + '\n')

            # Handle 0.8.x/0.9.x format (archive_results list)
            for result_data in data.get('archive_results', []):
                ar_record = {
                    'type': 'ArchiveResult',
                    'snapshot_id': str(self.id),
                    'plugin': result_data.get('plugin', ''),
                    'status': result_data.get('status', ''),
                    'output_str': result_data.get('output', ''),
                    'start_ts': result_data.get('start_ts'),
                    'end_ts': result_data.get('end_ts'),
                }
                if result_data.get('cmd'):
                    ar_record['cmd'] = result_data['cmd']
                f.write(json.dumps(ar_record) + '\n')

            # Handle 0.7.x format (history dict)
            if 'history' in data and isinstance(data['history'], dict):
                for plugin, result_list in data['history'].items():
                    if not isinstance(result_list, list):
                        continue
                    for result_data in result_list:
                        ar_record = {
                            'type': 'ArchiveResult',
                            'snapshot_id': str(self.id),
                            'plugin': result_data.get('plugin') or result_data.get('extractor') or plugin,
                            'status': result_data.get('status', ''),
                            'output_str': result_data.get('output', ''),
                            'start_ts': result_data.get('start_ts'),
                            'end_ts': result_data.get('end_ts'),
                        }
                        if result_data.get('cmd'):
                            ar_record['cmd'] = result_data['cmd']
                        f.write(json.dumps(ar_record) + '\n')

        # Remove old index.json after successful conversion
        try:
            json_path.unlink()
        except OSError:
            pass

        return True

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
            output = ""
            output_template = '<a href="/{}/{}" class="exists-{}" title="{}">{}</a> &nbsp;'

            # Get all plugins from hooks system (sorted by numeric prefix)
            all_plugins = [get_plugin_name(e) for e in get_plugins()]

            for plugin in all_plugins:
                result = archive_results.get(plugin)
                existing = result and result.status == 'succeeded' and (result.output_files or result.output_str)
                icon = mark_safe(get_plugin_icon(plugin))

                # Skip plugins with empty icons that have no output
                # (e.g., staticfile only shows when there's actual output)
                if not icon.strip() and not existing:
                    continue

                embed_path = result.embed_path() if result else f'{plugin}/'
                output += format_html(
                    output_template,
                    path,
                    embed_path,
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

    @property
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

    def ensure_crawl_symlink(self) -> None:
        """Ensure snapshot is symlinked under its crawl output directory."""
        import os
        from pathlib import Path
        from django.utils import timezone
        from archivebox import DATA_DIR
        from archivebox.crawls.models import Crawl

        if not self.crawl_id:
            return
        crawl = Crawl.objects.filter(id=self.crawl_id).select_related('created_by').first()
        if not crawl:
            return

        date_base = crawl.created_at or self.created_at or timezone.now()
        date_str = date_base.strftime('%Y%m%d')
        domain = self.extract_domain_from_url(self.url)
        username = crawl.created_by.username if crawl.created_by_id else 'system'

        crawl_dir = DATA_DIR / 'users' / username / 'crawls' / date_str / domain / str(crawl.id)
        link_path = crawl_dir / 'snapshots' / domain / str(self.id)
        link_parent = link_path.parent
        link_parent.mkdir(parents=True, exist_ok=True)

        target = Path(self.output_dir)
        if link_path.exists() or link_path.is_symlink():
            if link_path.is_symlink():
                if link_path.resolve() == target.resolve():
                    return
                link_path.unlink(missing_ok=True)
            else:
                return

        rel_target = os.path.relpath(target, link_parent)
        try:
            link_path.symlink_to(rel_target, target_is_directory=True)
        except OSError:
            return

    @cached_property
    def legacy_archive_path(self) -> str:
        return f'{CONSTANTS.ARCHIVE_DIR_NAME}/{self.timestamp}'

    @cached_property
    def url_path(self) -> str:
        """URL path matching the current snapshot output_dir layout."""
        try:
            rel_path = Path(self.output_dir).resolve().relative_to(CONSTANTS.DATA_DIR)
        except Exception:
            return self.legacy_archive_path

        parts = rel_path.parts
        # New layout: users/<username>/snapshots/<YYYYMMDD>/<domain>/<uuid>/
        if len(parts) >= 6 and parts[0] == 'users' and parts[2] == 'snapshots':
            username = parts[1]
            if username == 'system':
                username = 'web'
            date_str = parts[3]
            domain = parts[4]
            snapshot_id = parts[5]
            return f'{username}/{date_str}/{domain}/{snapshot_id}'

        # Legacy layout: archive/<timestamp>/
        if len(parts) >= 2 and parts[0] == CONSTANTS.ARCHIVE_DIR_NAME:
            return f'{parts[0]}/{parts[1]}'

        return '/'.join(parts)

    @cached_property
    def archive_path(self):
        return self.url_path

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
        Clean up background ArchiveResult hooks and empty results.

        Called by the state machine when entering the 'sealed' state.
        Uses Process records to kill background hooks, then deletes empty ArchiveResults.
        """
        from archivebox.machine.models import Process

        # Kill any background ArchiveResult hooks using Process records
        # Find all running hook Processes linked to this snapshot's ArchiveResults
        running_hooks = Process.objects.filter(
            archiveresult__snapshot=self,
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
        ).distinct()

        for process in running_hooks:
            # Use Process.kill_tree() to gracefully kill parent + children
            killed_count = process.kill_tree(graceful_timeout=2.0)
            if killed_count > 0:
                print(f'[yellow]🔪 Killed {killed_count} process(es) for hook {process.pid}[/yellow]')

        # Clean up .pid files from output directory
        if Path(self.output_dir).exists():
            for pid_file in Path(self.output_dir).glob('**/*.pid'):
                pid_file.unlink(missing_ok=True)

        # Update all background ArchiveResults from filesystem (in case output arrived late)
        results = self.archiveresult_set.filter(hook_name__contains='.bg.')
        for ar in results:
            ar.update_from_output()

        # Delete ArchiveResults that produced no output files
        empty_ars = self.archiveresult_set.filter(
            output_files={}  # No output files
        ).filter(
            status__in=ArchiveResult.FINAL_STATES  # Only delete finished ones
        )

        deleted_count = empty_ars.count()
        if deleted_count > 0:
            empty_ars.delete()
            print(f'[yellow]🗑️  Deleted {deleted_count} empty ArchiveResults for {self.url}[/yellow]')

    def to_json(self) -> dict:
        """
        Convert Snapshot model instance to a JSON-serializable dict.
        Includes all fields needed to fully reconstruct/identify this snapshot.
        """
        from archivebox.config import VERSION
        return {
            'type': 'Snapshot',
            'schema_version': VERSION,
            'id': str(self.id),
            'crawl_id': str(self.crawl_id),
            'url': self.url,
            'title': self.title,
            'tags': self.tags_str(),
            'bookmarked_at': self.bookmarked_at.isoformat() if self.bookmarked_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'timestamp': self.timestamp,
            'depth': self.depth,
            'status': self.status,
            'fs_version': self.fs_version,
        }

    @staticmethod
    def from_json(record: Dict[str, Any], overrides: Dict[str, Any] = None, queue_for_extraction: bool = True):
        """
        Create/update Snapshot from JSON dict.

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

        # DEBUG: Check if crawl_id in record matches overrides crawl
        import sys
        record_crawl_id = record.get('crawl_id')
        if record_crawl_id and crawl and str(crawl.id) != str(record_crawl_id):
            print(f"[yellow]⚠️  Snapshot.from_json crawl mismatch: record has crawl_id={record_crawl_id}, overrides has crawl={crawl.id}[/yellow]", file=sys.stderr)

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
                print(f"[red]⚠️  Snapshot.from_json auto-created new crawl {crawl.id} for url={url}[/red]", file=sys.stderr)

        # Parse tags
        tags_str = record.get('tags', '')
        tag_list = []
        if tags_str:
            tag_list = list(dict.fromkeys(
                tag.strip() for tag in re.split(GENERAL_CONFIG.TAG_SEPARATOR_PATTERN, tags_str)
                if tag.strip()
            ))

        # Check for existing snapshot with same URL in same crawl
        # (URLs can exist in multiple crawls, but should be unique within a crawl)
        snapshot = Snapshot.objects.filter(url=url, crawl=crawl).order_by('-created_at').first()

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

        snapshot.ensure_crawl_symlink()

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
        from archivebox.config.configset import get_config

        # Get merged config with crawl-specific PLUGINS filter
        config = get_config(crawl=self.crawl, snapshot=self)
        hooks = discover_hooks('Snapshot', config=config)
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


    def is_finished_processing(self) -> bool:
        """
        Check if all ArchiveResults are finished.

        Note: This is only called for observability/progress tracking.
        SnapshotWorker owns the execution and doesn't poll this.
        """
        # Check if any ARs are still pending/started
        pending = self.archiveresult_set.exclude(
            status__in=ArchiveResult.FINAL_STATES
        ).exists()

        return not pending

    def get_progress_stats(self) -> dict:
        """
        Get progress statistics for this snapshot's archiving process.

        Returns dict with:
            - total: Total number of archive results
            - succeeded: Number of succeeded results
            - failed: Number of failed results
            - running: Number of currently running results
            - pending: Number of pending/queued results
            - percent: Completion percentage (0-100)
            - output_size: Total output size in bytes
            - is_sealed: Whether the snapshot is in a final state
        """
        from django.db.models import Sum

        results = self.archiveresult_set.all()

        # Count by status
        succeeded = results.filter(status='succeeded').count()
        failed = results.filter(status='failed').count()
        running = results.filter(status='started').count()
        skipped = results.filter(status='skipped').count()
        total = results.count()
        pending = total - succeeded - failed - running - skipped

        # Calculate percentage (succeeded + failed + skipped as completed)
        completed = succeeded + failed + skipped
        percent = int((completed / total * 100) if total > 0 else 0)

        # Sum output sizes
        output_size = results.filter(status='succeeded').aggregate(
            total_size=Sum('output_size')
        )['total_size'] or 0

        # Check if sealed
        is_sealed = self.status in (self.StatusChoices.SEALED, self.StatusChoices.FAILED, self.StatusChoices.BACKOFF)

        return {
            'total': total,
            'succeeded': succeeded,
            'failed': failed,
            'running': running,
            'pending': pending,
            'skipped': skipped,
            'percent': percent,
            'output_size': output_size,
            'is_sealed': is_sealed,
        }

    def retry_failed_archiveresults(self, retry_at: Optional['timezone.datetime'] = None) -> int:
        """
        Reset failed/skipped ArchiveResults to queued for retry.

        This enables seamless retry of the entire extraction pipeline:
        - Resets FAILED and SKIPPED results to QUEUED
        - Sets retry_at so workers pick them up
        - Plugins run in order (numeric prefix)
        - Each plugin checks its dependencies at runtime

        Dependency handling (e.g., chrome → screenshot):
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

    def discover_outputs(self) -> list[dict]:
        """Discover output files from ArchiveResults and filesystem."""
        from archivebox.misc.util import ts_to_date_str

        ArchiveResult = self.archiveresult_set.model
        snap_dir = Path(self.output_dir)
        outputs: list[dict] = []
        seen: set[str] = set()

        text_exts = ('.json', '.jsonl', '.txt', '.csv', '.tsv', '.xml', '.yml', '.yaml', '.md', '.log')

        def is_metadata_path(path: str | None) -> bool:
            lower = (path or '').lower()
            return lower.endswith(text_exts)

        def is_compact_path(path: str | None) -> bool:
            lower = (path or '').lower()
            return lower.endswith(text_exts)

        for result in self.archiveresult_set.all().order_by('start_ts'):
            embed_path = result.embed_path()
            if not embed_path or embed_path.strip() in ('.', '/', './'):
                continue
            abs_path = snap_dir / embed_path
            if not abs_path.exists():
                continue
            if abs_path.is_dir():
                if not any(p.is_file() for p in abs_path.rglob('*')):
                    continue
                size = sum(p.stat().st_size for p in abs_path.rglob('*') if p.is_file())
            else:
                size = abs_path.stat().st_size
            outputs.append({
                'name': result.plugin,
                'path': embed_path,
                'ts': ts_to_date_str(result.end_ts),
                'size': size or 0,
                'is_metadata': is_metadata_path(embed_path),
                'is_compact': is_compact_path(embed_path),
                'result': result,
            })
            seen.add(result.plugin)

        embeddable_exts = {
            'html', 'htm', 'pdf', 'txt', 'md', 'json', 'jsonl', 'csv', 'tsv',
            'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico',
            'mp4', 'webm', 'mp3', 'opus', 'ogg', 'wav',
        }

        for entry in snap_dir.iterdir():
            if entry.name in ('index.html', 'index.json', 'favicon.ico', 'warc'):
                continue
            if entry.is_dir():
                plugin = entry.name
                if plugin in seen:
                    continue
                best_file = ArchiveResult._find_best_output_file(entry, plugin)
                if not best_file:
                    continue
                rel_path = str(best_file.relative_to(snap_dir))
                outputs.append({
                    'name': plugin,
                    'path': rel_path,
                    'ts': ts_to_date_str(best_file.stat().st_mtime or 0),
                    'size': best_file.stat().st_size or 0,
                    'is_metadata': is_metadata_path(rel_path),
                    'is_compact': is_compact_path(rel_path),
                    'result': None,
                })
                seen.add(plugin)
            elif entry.is_file():
                ext = entry.suffix.lstrip('.').lower()
                if ext not in embeddable_exts:
                    continue
                plugin = entry.stem
                if plugin in seen:
                    continue
                outputs.append({
                    'name': plugin,
                    'path': entry.name,
                    'ts': ts_to_date_str(entry.stat().st_mtime or 0),
                    'size': entry.stat().st_size or 0,
                    'is_metadata': is_metadata_path(entry.name),
                    'is_compact': is_compact_path(entry.name),
                    'result': None,
                })
                seen.add(plugin)

        return outputs

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
        return result

    def to_json_str(self, indent: int = 4) -> str:
        """Convert to JSON string (legacy method, use to_json() for dict)"""
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

        preview_priority = [
            'singlefile',
            'screenshot',
            'wget',
            'dom',
            'pdf',
            'readability',
        ]

        outputs = self.discover_outputs()
        outputs_by_plugin = {out['name']: out for out in outputs}

        best_preview_path = 'about:blank'
        for plugin in preview_priority:
            out = outputs_by_plugin.get(plugin)
            if out and out.get('path'):
                best_preview_path = out['path']
                break

        if best_preview_path == 'about:blank' and outputs:
            best_preview_path = outputs[0].get('path') or 'about:blank'
        context = {
            **self.to_dict(extended=True),
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
            'best_preview_path': best_preview_path,
            'archiveresults': outputs,
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

    # Tick Event (polled by workers)
    tick = (
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to(sealed, cond='is_finished')
    )

    # Manual event (can also be triggered by last ArchiveResult finishing)
    seal = started.to(sealed)

    def can_start(self) -> bool:
        can_start = bool(self.snapshot.url)
        return can_start

    def is_finished(self) -> bool:
        """Check if all ArchiveResults for this snapshot are finished."""
        return self.snapshot.is_finished_processing()

    @queued.enter
    def enter_queued(self):
        self.snapshot.update_and_requeue(
            retry_at=timezone.now(),
            status=Snapshot.StatusChoices.QUEUED,
        )

    @started.enter
    def enter_started(self):
        """Just mark as started - SnapshotWorker will create ARs and run hooks."""
        self.snapshot.status = Snapshot.StatusChoices.STARTED
        self.snapshot.retry_at = None  # No more polling
        self.snapshot.save(update_fields=['status', 'retry_at', 'modified_at'])

    @sealed.enter
    def enter_sealed(self):
        import sys

        # Clean up background hooks
        self.snapshot.cleanup()

        self.snapshot.update_and_requeue(
            retry_at=None,
            status=Snapshot.StatusChoices.SEALED,
        )

        print(f'[cyan]  ✅ SnapshotMachine.enter_sealed() - sealed {self.snapshot.url}[/cyan]', file=sys.stderr)

        # Check if this is the last snapshot for the parent crawl - if so, seal the crawl
        if self.snapshot.crawl:
            crawl = self.snapshot.crawl
            remaining_active = Snapshot.objects.filter(
                crawl=crawl,
                status__in=[Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED]
            ).count()

            if remaining_active == 0:
                print(f'[cyan]🔒 All snapshots sealed for crawl {crawl.id}, sealing crawl[/cyan]', file=sys.stderr)
                # Seal the parent crawl
                crawl.sm.seal()


class ArchiveResult(ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithStateMachine):
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

    # UUID primary key (migrated from integer in 0029)
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    snapshot: Snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)  # type: ignore
    # No choices= constraint - plugin names come from plugin system and can be any string
    plugin = models.CharField(max_length=32, blank=False, null=False, db_index=True, default='')
    hook_name = models.CharField(max_length=255, blank=True, default='', db_index=True, help_text='Full filename of the hook that executed (e.g., on_Snapshot__50_wget.py)')

    # Process FK - tracks execution details (cmd, pwd, stdout, stderr, etc.)
    # Added POST-v0.9.0, will be added in a separate migration
    process = models.OneToOneField(
        'machine.Process',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='archiveresult',
        help_text='Process execution details for this archive result'
    )

    # New output fields (replacing old 'output' field)
    output_str = models.TextField(blank=True, default='', help_text='Human-readable output summary')
    output_json = models.JSONField(null=True, blank=True, default=None, help_text='Structured metadata (headers, redirects, etc.)')
    output_files = models.JSONField(default=dict, help_text='Dict of {relative_path: {metadata}}')
    output_size = models.BigIntegerField(default=0, help_text='Total bytes of all output files')
    output_mimetypes = models.CharField(max_length=512, blank=True, default='', help_text='CSV of mimetypes sorted by size')

    start_ts = models.DateTimeField(default=None, null=True, blank=True)
    end_ts = models.DateTimeField(default=None, null=True, blank=True)

    status = ModelWithStateMachine.StatusField(choices=StatusChoices.choices, default=StatusChoices.QUEUED)
    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)
    notes = models.TextField(blank=True, null=False, default='')
    # output_dir is computed via @property from snapshot.output_dir / plugin

    state_machine_name = 'archivebox.core.models.ArchiveResultMachine'
    retry_at_field_name = 'retry_at'
    state_field_name = 'status'
    active_state = StatusChoices.STARTED

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

    def to_json(self) -> dict:
        """
        Convert ArchiveResult model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION
        record = {
            'type': 'ArchiveResult',
            'schema_version': VERSION,
            'id': str(self.id),
            'snapshot_id': str(self.snapshot_id),
            'plugin': self.plugin,
            'hook_name': self.hook_name,
            'status': self.status,
            'output_str': self.output_str,
            'start_ts': self.start_ts.isoformat() if self.start_ts else None,
            'end_ts': self.end_ts.isoformat() if self.end_ts else None,
        }
        # Include optional fields if set
        if self.output_json:
            record['output_json'] = self.output_json
        if self.output_files:
            record['output_files'] = self.output_files
        if self.output_size:
            record['output_size'] = self.output_size
        if self.output_mimetypes:
            record['output_mimetypes'] = self.output_mimetypes
        if self.cmd:
            record['cmd'] = self.cmd
        if self.cmd_version:
            record['cmd_version'] = self.cmd_version
        if self.process_id:
            record['process_id'] = str(self.process_id)
        return record

    @staticmethod
    def from_json(record: Dict[str, Any], overrides: Dict[str, Any] = None):
        """
        Create/update ArchiveResult from JSON dict.

        Args:
            record: JSON dict with 'snapshot_id', 'plugin', etc.
            overrides: Optional dict of field overrides

        Returns:
            ArchiveResult instance or None
        """
        snapshot_id = record.get('snapshot_id')
        plugin = record.get('plugin')

        if not snapshot_id or not plugin:
            return None

        # Try to get existing by ID first
        result_id = record.get('id')
        if result_id:
            try:
                return ArchiveResult.objects.get(id=result_id)
            except ArchiveResult.DoesNotExist:
                pass

        # Get or create by snapshot_id + plugin
        try:
            from archivebox.core.models import Snapshot
            snapshot = Snapshot.objects.get(id=snapshot_id)

            result, _ = ArchiveResult.objects.get_or_create(
                snapshot=snapshot,
                plugin=plugin,
                defaults={
                    'hook_name': record.get('hook_name', ''),
                    'status': record.get('status', 'queued'),
                    'output_str': record.get('output_str', ''),
                }
            )
            return result
        except Snapshot.DoesNotExist:
            return None

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        # Create Process record if this is a new ArchiveResult and no process exists yet
        if is_new and not self.process_id:
            from archivebox.machine.models import Process, Machine

            process = Process.objects.create(
                machine=Machine.current(),
                pwd=str(Path(self.snapshot.output_dir) / self.plugin),
                cmd=[],  # Will be set by run()
                status='queued',
                timeout=120,
                env={},
            )
            self.process = process

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

    @staticmethod
    def _find_best_output_file(dir_path: Path, plugin_name: str | None = None) -> Optional[Path]:
        if not dir_path.exists() or not dir_path.is_dir():
            return None

        embeddable_exts = {
            'html', 'htm', 'pdf', 'txt', 'md', 'json', 'jsonl', 'csv', 'tsv',
            'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'ico',
            'mp4', 'webm', 'mp3', 'opus', 'ogg', 'wav',
        }

        for name in ('index.html', 'index.htm'):
            candidate = dir_path / name
            if candidate.exists() and candidate.is_file():
                return candidate

        candidates = []
        file_count = 0
        max_scan = 200
        plugin_lower = (plugin_name or '').lower()
        for file_path in dir_path.rglob('*'):
            file_count += 1
            if file_count > max_scan:
                break
            if file_path.is_dir() or file_path.name.startswith('.'):
                continue
            ext = file_path.suffix.lstrip('.').lower()
            if ext not in embeddable_exts:
                continue
            try:
                size = file_path.stat().st_size
            except OSError:
                continue
            name_lower = file_path.name.lower()
            priority = 0
            if name_lower.startswith('index'):
                priority = 100
            elif plugin_lower and name_lower.startswith(('output', 'content', plugin_lower)):
                priority = 60
            elif ext in ('html', 'htm', 'pdf'):
                priority = 40
            elif ext in ('png', 'jpg', 'jpeg', 'webp', 'svg', 'gif', 'ico'):
                priority = 30
            elif ext in ('json', 'jsonl', 'txt', 'md', 'csv', 'tsv'):
                priority = 20
            else:
                priority = 10
            candidates.append((priority, size, file_path))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return candidates[0][2]

    def embed_path(self) -> Optional[str]:
        """
        Get the relative path to the embeddable output file for this result.

        Returns the first file from output_files if set, otherwise tries to
        find a reasonable default based on the plugin type.
        """
        snapshot_dir = Path(self.snapshot_dir)
        plugin_dir = snapshot_dir / self.plugin

        # Fallback: treat output_str as a file path only if it exists on disk
        if self.output_str:
            try:
                output_path = Path(self.output_str)

                if output_path.is_absolute():
                    # If absolute and within snapshot dir, normalize to relative
                    if snapshot_dir in output_path.parents and output_path.exists():
                        return str(output_path.relative_to(snapshot_dir))
                else:
                    # If relative, prefer plugin-prefixed path, then direct path
                    if (plugin_dir / output_path).exists():
                        return f'{self.plugin}/{output_path}'
                    if output_path.name in ('index.html', 'index.json') and output_path.parent == Path('.'):
                        return None
                    if (snapshot_dir / output_path).exists():
                        return str(output_path)
            except Exception:
                pass

        # Check output_files dict for primary output (ignore non-output files)
        if self.output_files:
            ignored = {'stdout.log', 'stderr.log', 'hook.pid', 'listener.pid', 'cmd.sh'}
            output_candidates = [
                f for f in self.output_files.keys()
                if Path(f).name not in ignored
            ]
            first_file = output_candidates[0] if output_candidates else None
            if first_file and (plugin_dir / first_file).exists():
                return f'{self.plugin}/{first_file}'

        best_file = self._find_best_output_file(plugin_dir, self.plugin)
        if best_file:
            return str(best_file.relative_to(snapshot_dir))

        return None

    def create_output_dir(self):
        output_dir = Path(self.snapshot_dir) / self.plugin
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    @property
    def output_dir_name(self) -> str:
        return self.plugin

    @property
    def output_dir_parent(self) -> str:
        return str(Path(self.snapshot.output_dir).relative_to(CONSTANTS.DATA_DIR))

    # Properties that delegate to Process model (for backwards compatibility)
    # These properties will replace the direct fields after migration is complete
    # They allow existing code to continue using archiveresult.pwd, .cmd, etc.

    # Note: After migration 3 creates Process records and migration 5 removes the old fields,
    # these properties provide seamless access to Process data through ArchiveResult

    # Uncommented after migration 3 completed - properties now active
    @property
    def pwd(self) -> str:
        """Working directory (from Process)."""
        return self.process.pwd if self.process_id else ''

    @property
    def cmd(self) -> list:
        """Command array (from Process)."""
        return self.process.cmd if self.process_id else []

    @property
    def cmd_version(self) -> str:
        """Command version (from Process.binary)."""
        return self.process.cmd_version if self.process_id else ''

    @property
    def binary(self):
        """Binary FK (from Process)."""
        return self.process.binary if self.process_id else None

    @property
    def iface(self):
        """Network interface FK (from Process)."""
        return self.process.iface if self.process_id else None

    @property
    def machine(self):
        """Machine FK (from Process)."""
        return self.process.machine if self.process_id else None

    @property
    def timeout(self) -> int:
        """Timeout in seconds (from Process)."""
        return self.process.timeout if self.process_id else 120

    def save_search_index(self):
        pass

    def cascade_health_update(self, success: bool):
        """Update health stats for parent Snapshot, Crawl, and execution infrastructure (Binary, Machine, NetworkInterface)."""
        # Update archival hierarchy
        self.snapshot.increment_health_stats(success)
        self.snapshot.crawl.increment_health_stats(success)

        # Update execution infrastructure
        if self.binary:
            self.binary.increment_health_stats(success)
            if self.binary.machine:
                self.binary.machine.increment_health_stats(success)

        if self.iface:
            self.iface.increment_health_stats(success)

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
        process = None

        for hook in hooks:
            # Run hook using Process.launch() - returns Process model
            process = run_hook(
                hook,
                output_dir=plugin_dir,
                config=config,
                url=self.snapshot.url,
                snapshot_id=str(self.snapshot.id),
                crawl_id=str(self.snapshot.crawl.id),
                depth=self.snapshot.depth,
            )

            # Link ArchiveResult to Process
            self.process = process
            self.start_ts = start_ts
            self.save(update_fields=['process_id', 'start_ts', 'modified_at'])

        if not process:
            # No hooks ran
            self.status = self.StatusChoices.FAILED
            self.output_str = 'No hooks executed'
            self.save()
            return

        # Update status based on hook execution
        if process.status == process.StatusChoices.RUNNING:
            # BACKGROUND HOOK - still running, return immediately
            # Status is already STARTED from enter_started(), will be finalized by Snapshot.cleanup()
            return

        # FOREGROUND HOOK - completed, update from filesystem
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
        import mimetypes
        from collections import defaultdict
        from pathlib import Path
        from django.utils import timezone
        from archivebox.hooks import process_hook_records, extract_records_from_process
        from archivebox.machine.models import Process

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
        records = []
        if self.process_id and self.process:
            records = extract_records_from_process(self.process)

        if not records:
            stdout = stdout_file.read_text() if stdout_file.exists() else ''
            records = Process.parse_records_from_text(stdout)

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
                if self.process_id:
                    self.process.cmd = hook_data['cmd']
                    self.process.save()
                self._set_binary_from_cmd(hook_data['cmd'])
            # Note: cmd_version is derived from binary.version, not stored on Process
        else:
            # No ArchiveResult record: treat background hooks or clean exits as skipped
            is_background = False
            try:
                from archivebox.hooks import is_background_hook
                is_background = bool(self.hook_name and is_background_hook(self.hook_name))
            except Exception:
                pass

            if is_background or (self.process_id and self.process and self.process.exit_code == 0):
                self.status = self.StatusChoices.SKIPPED
                self.output_str = 'Hook did not output ArchiveResult record'
            else:
                self.status = self.StatusChoices.FAILED
                self.output_str = 'Hook did not output ArchiveResult record'

        # Walk filesystem and populate output_files, output_size, output_mimetypes
        exclude_names = {'stdout.log', 'stderr.log', 'hook.pid', 'listener.pid', 'cmd.sh'}
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

        # Cleanup PID files (keep logs even if empty so they can be tailed)
        pid_file = plugin_dir / 'hook.pid'
        pid_file.unlink(missing_ok=True)

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
            if self.process_id:
                self.process.binary = binary
                self.process.save()
            return

        # Fallback: match by binary name
        bin_name = Path(bin_path_or_name).name
        binary = Binary.objects.filter(
            name=bin_name,
            machine=machine
        ).first()

        if binary:
            if self.process_id:
                self.process.binary = binary
                self.process.save()

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
    # Flow: queued → started → (succeeded|failed|skipped)
    #       queued → skipped (if exceeded max attempts)
    #       started → backoff → started (retry)
    tick = (
        queued.to(skipped, cond='is_exceeded_max_attempts') |  # Check skip first
        queued.to.itself(unless='can_start') |
        queued.to(started, cond='can_start') |
        started.to(succeeded, cond='is_succeeded') |
        started.to(failed, cond='is_failed') |
        started.to(skipped, cond='is_skipped') |
        started.to(backoff, cond='is_backoff') |
        backoff.to(skipped, cond='is_exceeded_max_attempts') |  # Check skip from backoff too
        backoff.to.itself(unless='can_start') |
        backoff.to(started, cond='can_start')
        # Removed redundant transitions: backoff.to(succeeded/failed/skipped)
        # Reason: backoff should always retry→started, then started→final states
    )

    def can_start(self) -> bool:
        """Pure function - check if AR can start (has valid URL)."""
        return bool(self.archiveresult.snapshot.url)

    def is_exceeded_max_attempts(self) -> bool:
        """Check if snapshot has exceeded MAX_URL_ATTEMPTS failed results."""
        from archivebox.config.configset import get_config

        config = get_config(
            crawl=self.archiveresult.snapshot.crawl,
            snapshot=self.archiveresult.snapshot,
        )
        max_attempts = config.get('MAX_URL_ATTEMPTS', 50)

        # Count failed ArchiveResults for this snapshot (any plugin type)
        failed_count = self.archiveresult.snapshot.archiveresult_set.filter(
            status=ArchiveResult.StatusChoices.FAILED
        ).count()

        return failed_count >= max_attempts

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
        """
        Check if extraction has completed (success, failure, or skipped).

        For background hooks in STARTED state, checks if their Process has finished and reaps them.
        """
        # If already in final state, return True
        if self.archiveresult.status in (
            ArchiveResult.StatusChoices.SUCCEEDED,
            ArchiveResult.StatusChoices.FAILED,
            ArchiveResult.StatusChoices.SKIPPED,
        ):
            return True

        # If in STARTED state with a Process, check if Process has finished running
        if self.archiveresult.status == ArchiveResult.StatusChoices.STARTED:
            if self.archiveresult.process_id:
                process = self.archiveresult.process

                # If process is NOT running anymore, reap the background hook
                if not process.is_running():
                    self.archiveresult.update_from_output()
                    # Check if now in final state after reaping
                    return self.archiveresult.status in (
                        ArchiveResult.StatusChoices.SUCCEEDED,
                        ArchiveResult.StatusChoices.FAILED,
                        ArchiveResult.StatusChoices.SKIPPED,
                    )

        return False

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

        # Update Process with network interface
        if self.archiveresult.process_id:
            self.archiveresult.process.iface = NetworkInterface.current()
            self.archiveresult.process.save()

        # Lock the object and mark start time
        self.archiveresult.update_and_requeue(
            retry_at=timezone.now() + timedelta(seconds=120),  # 2 min timeout for plugin
            status=ArchiveResult.StatusChoices.STARTED,
            start_ts=timezone.now(),
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

    def _check_and_seal_parent_snapshot(self):
        """
        Check if this is the last ArchiveResult to finish - if so, seal the parent Snapshot.

        Note: In the new architecture, SnapshotWorker handles step advancement and sealing.
        This method is kept for backwards compatibility with manual CLI commands.
        """
        import sys

        snapshot = self.archiveresult.snapshot

        # Check if all archiveresults are finished (in final states)
        remaining_active = snapshot.archiveresult_set.exclude(
            status__in=[
                ArchiveResult.StatusChoices.SUCCEEDED,
                ArchiveResult.StatusChoices.FAILED,
                ArchiveResult.StatusChoices.SKIPPED,
            ]
        ).count()

        if remaining_active == 0:
            print(f'[cyan]    🔒 All archiveresults finished for snapshot {snapshot.url}, sealing snapshot[/cyan]', file=sys.stderr)
            # Seal the parent snapshot
            snapshot.sm.seal()

    @succeeded.enter
    def enter_succeeded(self):
        import sys

        self.archiveresult.update_and_requeue(
            retry_at=None,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            end_ts=timezone.now(),
        )

        # Update health stats for ArchiveResult, Snapshot, and Crawl cascade
        self.archiveresult.cascade_health_update(success=True)

        print(f'[cyan]    ✅ ArchiveResult succeeded: {self.archiveresult.plugin} for {self.archiveresult.snapshot.url}[/cyan]', file=sys.stderr)

        # Check if this is the last AR to finish - seal parent snapshot if so
        self._check_and_seal_parent_snapshot()

    @failed.enter
    def enter_failed(self):
        import sys

        print(f'[red]    ❌ ArchiveResult.enter_failed() called for {self.archiveresult.plugin}[/red]', file=sys.stderr)

        self.archiveresult.update_and_requeue(
            retry_at=None,
            status=ArchiveResult.StatusChoices.FAILED,
            end_ts=timezone.now(),
        )

        # Update health stats for ArchiveResult, Snapshot, and Crawl cascade
        self.archiveresult.cascade_health_update(success=False)

        print(f'[red]    ❌ ArchiveResult failed: {self.archiveresult.plugin} for {self.archiveresult.snapshot.url}[/red]', file=sys.stderr)

        # Check if this is the last AR to finish - seal parent snapshot if so
        self._check_and_seal_parent_snapshot()

    @skipped.enter
    def enter_skipped(self):
        import sys

        # Set output_str if not already set (e.g., when skipped due to max attempts)
        if not self.archiveresult.output_str and self.is_exceeded_max_attempts():
            from archivebox.config.configset import get_config
            config = get_config(
                crawl=self.archiveresult.snapshot.crawl,
                snapshot=self.archiveresult.snapshot,
            )
            max_attempts = config.get('MAX_URL_ATTEMPTS', 50)
            self.archiveresult.output_str = f'Skipped: snapshot exceeded MAX_URL_ATTEMPTS ({max_attempts} failures)'

        self.archiveresult.update_and_requeue(
            retry_at=None,
            status=ArchiveResult.StatusChoices.SKIPPED,
            end_ts=timezone.now(),
        )

        print(f'[dim]    ⏭️  ArchiveResult skipped: {self.archiveresult.plugin} for {self.archiveresult.snapshot.url}[/dim]', file=sys.stderr)

        # Check if this is the last AR to finish - seal parent snapshot if so
        self._check_and_seal_parent_snapshot()


# =============================================================================
# State Machine Registration
# =============================================================================

# Manually register state machines with python-statemachine registry
# (normally auto-discovered from statemachines.py, but we define them here for clarity)
registry.register(SnapshotMachine)
registry.register(ArchiveResultMachine)
