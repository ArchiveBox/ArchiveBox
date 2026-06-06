__package__ = "archivebox.core"

from typing import TYPE_CHECKING, Optional, Any
from collections.abc import Iterable, Sequence
import uuid
from archivebox.uuid_compat import CompactUUIDField, uuid7
from datetime import datetime, timedelta

import os
import json
from pathlib import Path
from urllib.parse import urlparse

from statemachine import State, registry

from django.db import models, transaction
from django.db.models import Case, F, Q, QuerySet, Sum, Value, When
from django.db.models.functions import Coalesce, Concat
from django.db.models.fields.json import KT
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.utils import timezone
from django.core.cache import cache
from django.urls import reverse_lazy
from django.contrib import admin
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils.safestring import mark_safe

from archivebox.config import CONSTANTS
from archivebox.config.common import get_config, rprint
from archivebox.misc.system import atomic_write
from archivebox.misc.util import (
    MAX_URL_LENGTH,
    parse_date,
    domain as url_domain,
    to_json,
    ts_to_date_str,
    urlencode,
    htmlencode,
    urldecode,
    validate_url_length,
)
from archivebox.plugins.discovery import (
    get_plugins,
    get_plugin_name,
    get_plugin_icon,
)
from archivebox.base_models.models import (
    ModelWithUUID,
    ModelWithDeleteAfter,
    ModelWithOutputDir,
    ModelWithConfig,
    ModelWithNotes,
    ModelWithHealthStats,
    get_or_create_system_user_pk,
)
from archivebox.workers.models import ACTIVE_STATE_LEASE_SECONDS, RETRY_AT_MAX, ModelWithStateMachine, BaseStateMachine
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Binary

if TYPE_CHECKING:
    from archivebox.config.common import ArchiveBoxBaseConfig


class UngroupedSubquery(models.Subquery):
    """Scalar subquery that should not be copied into the outer GROUP BY."""

    def get_group_by_cols(self):
        return []


class Tag(ModelWithUUID):
    # Keep AutoField for compatibility with main branch migrations
    # Don't use UUIDField here - requires complex FK transformation
    id = models.AutoField(primary_key=True, serialize=False, verbose_name="ID")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        default=get_or_create_system_user_pk,
        null=True,
        related_name="tag_set",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True, null=True)
    modified_at = models.DateTimeField(auto_now=True)
    name = models.CharField(unique=True, blank=False, max_length=100)

    snapshot_set: models.Manager["Snapshot"]

    class Meta(ModelWithUUID.Meta):
        app_label = "core"
        verbose_name = "Tag"
        verbose_name_plural = "Tags"

    def __str__(self):
        return self.name

    @property
    def slug(self) -> str:
        """ASCII-safe slugified form of the tag name (derived, not stored)."""
        return slugify(self.name or "") or "tag"

    @property
    def api_url(self) -> str:
        return str(reverse_lazy("api-1:get_tag", args=[self.id]))

    def to_json(self) -> dict:
        """
        Convert Tag model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION

        return {
            "type": "Tag",
            "schema_version": VERSION,
            "id": str(self.id),
            "name": self.name,
        }

    @staticmethod
    def from_json(record: dict[str, Any], overrides: dict[str, Any] | None = None):
        """
        Create/update Tag from JSON dict.

        Args:
            record: JSON dict with 'name' field
            overrides: Optional dict with 'snapshot' to auto-attach tag

        Returns:
            Tag instance or None
        """
        name = record.get("name")
        if not name:
            return None

        tag, _ = Tag.objects.get_or_create(name=name)

        # Auto-attach to snapshot if in overrides
        if overrides and "snapshot" in overrides and tag:
            overrides["snapshot"].tags.add(tag)

        return tag


class SnapshotTag(models.Model):
    id = models.AutoField(primary_key=True)
    snapshot = models.ForeignKey("Snapshot", db_column="snapshot_id", on_delete=models.CASCADE, to_field="id")
    tag = models.ForeignKey(Tag, db_column="tag_id", on_delete=models.CASCADE, to_field="id")

    class Meta:
        app_label = "core"
        db_table = "core_snapshot_tags"
        unique_together = [("snapshot", "tag")]


class SnapshotQuerySet(models.QuerySet):
    """Custom QuerySet for Snapshot model with export methods that persist through .filter() etc."""

    def paged_iterator(self, chunk_size: int = 500):
        """
        Iterate snapshots using bounded keyset pages instead of one streaming cursor.

        Django's iterator(chunk_size=...) still keeps a single SQLite SELECT
        cursor open until the full queryset is exhausted. That is fine for
        read-only exports, but update/migration code does filesystem work and
        writes while iterating; a long-lived read cursor there can stretch lock
        waits across thousands of rows. This respects the queryset's existing
        filters, order_by(), select_related(), and prefetch_related() state; if
        no ordering is defined, it falls back to primary-key order.
        """
        pk_field = self.model._meta.pk.name
        raw_ordering = tuple(self.query.order_by or self.model._meta.ordering or (pk_field,))

        if any(not isinstance(term, str) or term == "?" for term in raw_ordering):
            offset = 0
            while True:
                batch = list(self[offset : offset + chunk_size])
                if not batch:
                    break
                yield from batch
                offset += chunk_size
            return

        ordering = []
        for term in raw_ordering:
            descending = term.startswith("-")
            field_name = term[1:] if descending else term
            if field_name == "pk":
                field_name = pk_field
            ordering.append(f"-{field_name}" if descending else field_name)

        ordered_field_names = [term[1:] if term.startswith("-") else term for term in ordering]
        try:
            if any(self.model._meta.get_field(field_name).null for field_name in ordered_field_names):
                offset = 0
                while True:
                    batch = list(self[offset : offset + chunk_size])
                    if not batch:
                        break
                    yield from batch
                    offset += chunk_size
                return
        except Exception:
            offset = 0
            while True:
                batch = list(self[offset : offset + chunk_size])
                if not batch:
                    break
                yield from batch
                offset += chunk_size
            return

        unique_field_names = {pk_field, *(field.name for field in self.model._meta.fields if field.unique)}
        if not any(field_name in unique_field_names for field_name in ordered_field_names):
            offset = 0
            while True:
                batch = list(self[offset : offset + chunk_size])
                if not batch:
                    break
                yield from batch
                offset += chunk_size
            return

        last_values = None
        value_field_names = tuple(dict.fromkeys([*ordered_field_names, pk_field]))
        while True:
            batch_qs = self.order_by(*ordering)
            if last_values is not None:
                page_filter = models.Q()
                for idx, term in enumerate(ordering):
                    descending = term.startswith("-")
                    field_name = term[1:] if descending else term
                    prefix = {ordered_field_names[i]: last_values[i] for i in range(idx)}
                    comparison = "lt" if descending else "gt"
                    page_filter |= models.Q(**prefix, **{f"{field_name}__{comparison}": last_values[idx]})
                batch_qs = batch_qs.filter(page_filter)

            batch_rows = list(batch_qs.values_list(*value_field_names)[:chunk_size])
            if not batch_rows:
                break

            pk_idx = value_field_names.index(pk_field)
            snapshot_ids = [row[pk_idx] for row in batch_rows]
            snapshots_by_id = {snapshot.pk: snapshot for snapshot in self.filter(pk__in=snapshot_ids).order_by()}

            for row in batch_rows:
                snapshot_id = row[pk_idx]
                snapshot = snapshots_by_id.get(snapshot_id)
                if snapshot is not None:
                    yield snapshot

            last_values = batch_rows[-1][: len(ordered_field_names)]

    # =========================================================================
    # Filtering Methods
    # =========================================================================

    FILTER_TYPES = {
        "exact": lambda pattern: models.Q(url=pattern),
        "substring": lambda pattern: models.Q(url__icontains=pattern),
        "regex": lambda pattern: models.Q(url__iregex=pattern),
        "domain": lambda pattern: (
            models.Q(url__istartswith=f"http://{pattern}")
            | models.Q(url__istartswith=f"https://{pattern}")
            | models.Q(url__istartswith=f"ftp://{pattern}")
        ),
        "tag": lambda pattern: models.Q(tags__name=pattern),
        "timestamp": lambda pattern: models.Q(timestamp=pattern),
    }
    FILTER_TYPE_CHOICES = tuple(FILTER_TYPES)
    FILTER_ARG_KEYS = (
        "after",
        "before",
        "filter_type",
        "filter_patterns",
        "status",
        "url__icontains",
        "url__istartswith",
        "tag",
        "crawl_id",
        "limit",
        "sort",
        "search",
    )
    SPECIAL_FILTER_ARG_KEYS = frozenset({"filter_patterns", "filter_type", "query", "search", "tag", "before", "after", "limit", "sort"})

    def filter_by_patterns(self, patterns: list[str], filter_type: str = "exact") -> "SnapshotQuerySet":
        """Filter snapshots by URL patterns using specified filter type"""
        from archivebox.misc.logging import stderr

        q_filter = models.Q()
        for pattern in patterns:
            try:
                q_filter = q_filter | self.FILTER_TYPES[filter_type](pattern)
            except KeyError:
                stderr()
                stderr(f"[X] Got invalid pattern for --filter-type={filter_type}:", color="red")
                stderr(f"    {pattern}")
                raise SystemExit(2)
        return self.filter(q_filter)

    def search(self, **kwargs) -> "SnapshotQuerySet":
        from datetime import timezone as dt_timezone

        from archivebox.core.snapshot_status import filter_snapshots_by_status
        from archivebox.search.query import apply_snapshot_search

        queryset = self
        filter_patterns = tuple(str(pattern) for pattern in kwargs.get("filter_patterns") or ())
        filter_type = kwargs.get("filter_type") or "substring"
        query = kwargs.get("query")
        if isinstance(query, (list, tuple)):
            query = " ".join(str(part) for part in query)
        query = (query or (" ".join(filter_patterns) if kwargs.get("search") else "")).strip()

        field_names = {field.name for field in self.model._meta.get_fields()}
        field_names.update(field.attname for field in self.model._meta.fields)
        field_filters = {
            key: value
            for key, value in kwargs.items()
            if value is not None and key not in self.SPECIAL_FILTER_ARG_KEYS and key.split("__", 1)[0] in field_names
        }
        status = field_filters.pop("status", None)
        queryset = filter_snapshots_by_status(queryset, status)
        if field_filters:
            queryset = queryset.filter(**field_filters)
        if kwargs.get("tag"):
            queryset = queryset.filter(tags__name__iexact=kwargs["tag"])
        if kwargs.get("before") is not None:
            queryset = queryset.filter(bookmarked_at__lt=datetime.fromtimestamp(float(kwargs["before"]), tz=dt_timezone.utc))
        if kwargs.get("after") is not None:
            queryset = queryset.filter(bookmarked_at__gt=datetime.fromtimestamp(float(kwargs["after"]), tz=dt_timezone.utc))

        if query:
            queryset = apply_snapshot_search(
                queryset,
                query,
                search_mode=kwargs.get("search"),
                ordering=("-created_at",) if not kwargs.get("sort") else None,
                max_results=kwargs.get("limit"),
                skip_backend_when_metadata_satisfies_limit=True,
                include_metadata_for_forced_backend=True,
            )
        elif filter_patterns:
            queryset = queryset.filter_by_patterns(list(filter_patterns), filter_type)

        if kwargs.get("sort"):
            queryset = queryset.order_by(kwargs["sort"])
        elif not queryset.query.order_by:
            queryset = queryset.order_by("-created_at")

        limit = kwargs.get("limit")
        if limit is not None and limit > 0:
            queryset = queryset[:limit]

        return queryset

    # =========================================================================
    # Export Methods
    # =========================================================================

    def to_json(self, with_headers: bool = False) -> str:
        """Generate JSON index from snapshots"""
        import sys
        from datetime import datetime, timezone as tz
        from archivebox.config import VERSION

        config = get_config()

        MAIN_INDEX_HEADER = (
            {
                "info": "This is an index of site data archived by ArchiveBox: The self-hosted web archive.",
                "schema": "archivebox.index.json",
                "copyright_info": config.FOOTER_INFO,
                "meta": {
                    "project": "ArchiveBox",
                    "version": VERSION,
                    "git_sha": VERSION,
                    "website": "https://ArchiveBox.io",
                    "docs": "https://github.com/ArchiveBox/ArchiveBox/wiki",
                    "source": "https://github.com/ArchiveBox/ArchiveBox",
                    "issues": "https://github.com/ArchiveBox/ArchiveBox/issues",
                    "dependencies": {},
                },
            }
            if with_headers
            else {}
        )

        snapshot_dicts = [s.to_dict(extended=True) for s in self.iterator(chunk_size=500)]

        if with_headers:
            output = {
                **MAIN_INDEX_HEADER,
                "num_links": len(snapshot_dicts),
                "updated": datetime.now(tz.utc),
                "last_run_cmd": sys.argv,
                "links": snapshot_dicts,
            }
        else:
            output = snapshot_dicts
        return to_json(output, indent=4, sort_keys=True)

    def to_csv(self, cols: list[str] | None = None, header: bool = True, separator: str = ",", ljust: int = 0) -> str:
        """Generate CSV output from snapshots"""
        cols = cols or ["timestamp", "is_archived", "url"]
        header_str = separator.join(col.ljust(ljust) for col in cols) if header else ""
        row_strs = (s.to_csv(cols=cols, ljust=ljust, separator=separator) for s in self.iterator(chunk_size=500))
        return "\n".join((header_str, *row_strs))

    def to_html(self, with_headers: bool = True) -> str:
        """Generate main index HTML from snapshots"""
        from datetime import datetime, timezone as tz
        from django.template.loader import render_to_string
        from archivebox.config import VERSION
        from archivebox.config.version import get_COMMIT_HASH

        config = get_config()

        template = "static_index.html" if with_headers else "minimal_index.html"
        snapshot_list = list(self.iterator(chunk_size=500))

        return render_to_string(
            template,
            {
                "version": VERSION,
                "git_sha": get_COMMIT_HASH() or VERSION,
                "num_links": str(len(snapshot_list)),
                "date_updated": datetime.now(tz.utc).strftime("%Y-%m-%d"),
                "time_updated": datetime.now(tz.utc).strftime("%Y-%m-%d %H:%M"),
                "links": snapshot_list,
                "FOOTER_INFO": config.FOOTER_INFO,
            },
        )


class SnapshotManager(models.Manager.from_queryset(SnapshotQuerySet)):  # ty: ignore[unsupported-base]
    """Manager for Snapshot model - uses SnapshotQuerySet for chainable methods"""

    def filter(self, *args, **kwargs):
        domain = kwargs.pop("domain", None)
        qs = super().filter(*args, **kwargs)
        if domain:
            qs = qs.filter(url__icontains=f"://{domain}")
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
                return self.get_queryset().delete()
        return self.get_queryset().delete()


class Snapshot(ModelWithDeleteAfter, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, ModelWithStateMachine):
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    url = models.CharField(max_length=MAX_URL_LENGTH, unique=False, db_index=True)  # URLs can appear in multiple crawls
    timestamp = models.CharField(max_length=32, unique=True, db_index=True, editable=False)
    bookmarked_at = models.DateTimeField(default=timezone.now, db_index=True)
    crawl: Crawl = models.ForeignKey(Crawl, on_delete=models.CASCADE, null=False, related_name="snapshot_set", db_index=True)  # type: ignore[assignment]
    parent_snapshot = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_snapshots",
        db_index=True,
        help_text="Parent snapshot that discovered this URL (for recursive crawling)",
    )

    title = models.CharField(max_length=512, null=True, blank=True, db_index=True)
    downloaded_at = models.DateTimeField(default=None, null=True, editable=False, db_index=True, blank=True)
    depth = models.PositiveSmallIntegerField(default=0, db_index=True)  # 0 for root snapshot, 1+ for discovered URLs
    fs_version = models.CharField(
        max_length=10,
        default="0.9.0",
        help_text='Filesystem version of this snapshot (e.g., "0.7.0", "0.8.0", "0.9.0"). Used to trigger lazy migration on save().',
    )
    current_step = models.PositiveSmallIntegerField(
        default=0,
        db_index=True,
        help_text="Current hook step being executed (0-9). Used for sequential hook execution.",
    )

    retry_at = ModelWithStateMachine.RetryAtField(default=timezone.now)
    status = ModelWithStateMachine.StatusField(
        choices=ModelWithStateMachine.StatusChoices,
        default=ModelWithStateMachine.StatusChoices.QUEUED,
    )
    config = models.JSONField(default=dict, null=False, blank=False, editable=True)
    permissions = models.GeneratedField(
        expression=KT("config__PERMISSIONS"),
        output_field=models.CharField(max_length=16, null=True),
        db_persist=True,
        db_index=True,
        editable=False,
    )
    output_size = models.BigIntegerField(
        default=0,
        db_index=True,
        editable=False,
        help_text="Total bytes of all ArchiveResult output files",
    )
    notes = models.TextField(blank=True, null=False, default="")
    # output_dir is computed via @cached_property from fs_version and get_storage_path_for_version()

    tags = models.ManyToManyField(Tag, blank=True, through=SnapshotTag, related_name="snapshot_set", through_fields=("snapshot", "tag"))

    state_machine_name = "archivebox.core.models.SnapshotMachine"
    state_field_name = "status"
    retry_at_field_name = "retry_at"
    StatusChoices = ModelWithStateMachine.StatusChoices
    active_state = StatusChoices.STARTED
    delete_after_final_statuses = (StatusChoices.SEALED,)
    RUNNABLE_STATES = (StatusChoices.QUEUED, StatusChoices.STARTED)
    OPEN_STATES = (*RUNNABLE_STATES, StatusChoices.PAUSED)

    crawl_id: uuid.UUID
    parent_snapshot_id: uuid.UUID | None
    _prefetched_objects_cache: dict[str, Any]

    objects = SnapshotManager()
    archiveresult_set: models.Manager["ArchiveResult"]

    if TYPE_CHECKING:

        @property
        def sm(self) -> "SnapshotMachine": ...

    class Meta(
        ModelWithDeleteAfter.Meta,
        ModelWithOutputDir.Meta,
        ModelWithConfig.Meta,
        ModelWithNotes.Meta,
        ModelWithHealthStats.Meta,
        ModelWithStateMachine.Meta,
    ):
        app_label = "core"
        verbose_name = "Snapshot"
        verbose_name_plural = "Snapshots"
        indexes = [
            models.Index(fields=["-bookmarked_at", "-created_at"], name="snapshot_public_order_idx"),
            models.Index(fields=["crawl", "status", "modified_at"], name="snapshot_progress_idx"),
        ]
        constraints = [
            # Allow same URL in different crawls, but not duplicates within same crawl
            models.UniqueConstraint(fields=["url", "crawl"], name="unique_url_per_crawl"),
            # Global timestamp uniqueness for 1:1 symlink mapping
            models.UniqueConstraint(fields=["timestamp"], name="unique_timestamp"),
        ]

    def __str__(self):
        return f"[{self.id}] {self.url[:64]}"

    @classmethod
    def crawl_count_subquery(cls, *, status: str | None = None, outer_ref: str = "pk") -> QuerySet:
        """Return a scalar subquery counting Snapshots for one outer Crawl."""
        qs = cls.objects.filter(crawl_id=models.OuterRef(outer_ref))
        if status is not None:
            qs = qs.filter(status=status)
        return qs.order_by().values("crawl_id").annotate(count=models.Count("pk")).values("count")

    @classmethod
    def crawl_count_expr(cls, *, status: str | None = None, outer_ref: str = "pk"):
        # Use scalar subqueries for sortable Crawl admin counters: SQLite can
        # probe the (crawl_id, status, modified_at) index per Crawl row instead
        # of joining/grouping all visible Snapshot rows.
        return Coalesce(
            models.Subquery(cls.crawl_count_subquery(status=status, outer_ref=outer_ref), output_field=models.IntegerField()),
            models.Value(0),
        )

    @classmethod
    def crawl_total_and_status_counts(cls, crawl_ids: Iterable[Any], *, status: str) -> dict[str, dict[str, int]]:
        """Return total and status-filtered Snapshot counts keyed by Crawl ID."""
        crawl_ids = list(crawl_ids)
        if not crawl_ids:
            return {}
        return {
            str(row["crawl_id"]): {
                "total": row["total"],
                "status": row["status_count"],
            }
            for row in cls.objects.filter(crawl_id__in=crawl_ids)
            .values("crawl_id")
            .annotate(
                total=models.Count("pk"),
                status_count=models.Count("pk", filter=Q(status=status)),
            )
        }

    def update_and_requeue(self, **kwargs) -> bool:
        """
        Update this Snapshot through the shared retry_at ownership path.

        Any non-final Snapshot work means the parent Crawl must also be visible
        to the runner. Keep that invariant here so CLI/admin callers do not
        hand-edit the parent Crawl state every time they retry a hook.
        """
        updated = super().update_and_requeue(**kwargs)
        if not updated:
            return False

        next_status = kwargs.get("status", self.status)
        if next_status not in (self.StatusChoices.QUEUED, self.StatusChoices.STARTED) or not self.crawl_id:
            return True

        crawl = self.crawl
        crawl_status = crawl.StatusChoices.STARTED if crawl.status == crawl.StatusChoices.STARTED else crawl.StatusChoices.QUEUED
        crawl.update_and_requeue(
            status=crawl_status,
            retry_at=kwargs.get("retry_at") or timezone.now(),
        )
        return True

    def queue_for_extraction(self, *, when=None) -> bool:
        """Queue this Snapshot for the runner using the normal state path."""
        return self.update_and_requeue(
            status=self.StatusChoices.QUEUED,
            retry_at=when or timezone.now(),
            current_step=0,
        )

    def pause(self, *, save: bool = True) -> bool:
        paused = super().pause(save=save)
        if paused and self.pk:
            ArchiveResult.pause_queryset(self.archiveresult_set.all())
        return paused

    def resume(self, *, when: datetime | None = None, save: bool = True) -> bool:
        resumed = super().resume(when=when, save=save)
        if resumed and self.pk:
            ArchiveResult.resume_queryset(self.archiveresult_set.all(), when=when)
        return resumed

    def restore_paused_scheduler_marker(self) -> None:
        """
        Keep explicit maintenance from accidentally resuming paused snapshots.

        Targeted jobs such as `archivebox update --index-only` may bump
        retry_at so the orchestrator can run only queued search ArchiveResult
        rows. After that maintenance pass, the lifecycle must remain PAUSED and
        retry_at must go back to MAX until a real resume transition happens.
        """
        type(self).objects.filter(
            pk=self.pk,
            status=self.StatusChoices.PAUSED,
        ).update(
            retry_at=RETRY_AT_MAX,
            modified_at=timezone.now(),
        )
        self.status = self.StatusChoices.PAUSED
        self.retry_at = RETRY_AT_MAX

    def reconcile_parent_lifecycle(self, *, lock_seconds: int = 60) -> bool | None:
        """
        Follow parent Crawl pause/seal state before any Snapshot work runs.

        Crawl.pause()/cancel() only wake child rows. The runner claims each due
        Snapshot and lets this method perform the actual child transition, so
        cancellation stays fast and Snapshot cleanup still runs from the normal
        state-machine owner.
        """
        parent_status = Crawl.objects.filter(id=self.crawl_id).values_list("status", flat=True).first()
        if parent_status == Crawl.StatusChoices.SEALED and self.status != self.StatusChoices.SEALED:
            if not self.claim_processing_lock(lock_seconds=lock_seconds):
                return False
            self.refresh_from_db()
            parent_status = Crawl.objects.filter(id=self.crawl_id).values_list("status", flat=True).first()
            if parent_status == Crawl.StatusChoices.SEALED and self.status != self.StatusChoices.SEALED:
                self.sm.seal()
            return True

        if parent_status == Crawl.StatusChoices.PAUSED and self.status not in (self.StatusChoices.PAUSED, self.StatusChoices.SEALED):
            if not self.claim_processing_lock(lock_seconds=lock_seconds):
                return False
            self.refresh_from_db()
            parent_status = Crawl.objects.filter(id=self.crawl_id).values_list("status", flat=True).first()
            if parent_status == Crawl.StatusChoices.PAUSED and self.status not in (
                self.StatusChoices.PAUSED,
                self.StatusChoices.SEALED,
            ):
                self.pause()
            return True

        return None

    def finalize_completed_upload_results(self) -> int:
        now = timezone.now()
        result_ids = []
        upload_results = (
            self.archiveresult_set.filter(
                status=ArchiveResult.StatusChoices.QUEUED,
                hook_name="on_Snapshot__archivebox_browser_extension_upload",
                output_size__gt=0,
            )
            .exclude(output_files={})
            .only("id", "output_files")
        )
        for result in upload_results:
            if ArchiveResult.output_files_upload_complete(result.output_files or {}):
                result_ids.append(result.id)
        if not result_ids:
            return 0
        # Browser-extension uploads are already-finished external writes. If the
        # PATCH request saved files but omitted status, finalize only this
        # Snapshot's complete uploads without scanning ArchiveResult globally.
        return ArchiveResult.objects.filter(id__in=result_ids, status=ArchiveResult.StatusChoices.QUEUED).update(
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            modified_at=now,
        )

    def reset_abandoned_results(self) -> tuple[int, int]:
        reset_count = 0
        running_count = 0
        for result in self.archiveresult_set.filter(
            status__in=[ArchiveResult.StatusChoices.STARTED, ArchiveResult.StatusChoices.BACKOFF],
        ).select_related("process"):
            process = result.process
            if process is not None and process.is_running:
                running_count += 1
                continue
            result.reset_for_retry()
            reset_count += 1
        return reset_count, running_count

    def cancel(self) -> None:
        if self.status != self.StatusChoices.SEALED:
            self.sm.seal()

    def get_delete_after_config_value(self):
        from archivebox.config.common import resolve_delete_after_config_value

        return resolve_delete_after_config_value(self.config, self.crawl.config)

    @classmethod
    def missing_delete_at_candidates(cls):
        return cls.objects.filter(delete_at__isnull=True).filter(
            Q(config__has_key="DELETE_AFTER") | Q(crawl__config__has_key="DELETE_AFTER"),
        )

    @classmethod
    def is_archivebox_internal_url(cls, url: str) -> bool:
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False

        from archivebox.core.routes_util import (
            get_admin_host,
            get_api_host,
            get_base_host,
            get_listen_host,
            get_public_host,
            get_web_host,
            split_host_port,
        )

        config = get_config()
        host = parsed.hostname.lower().strip(".")
        port = str(parsed.port) if parsed.port else None
        protected_subdomains = {"admin", "web", "api", "public"}
        protected_hosts: set[tuple[str, str | None]] = set()
        protected_roots: set[tuple[str, str | None]] = set()
        for host_value in (
            get_listen_host(config=config),
            get_base_host(config=config),
            get_admin_host(config=config),
            get_web_host(config=config),
            get_api_host(config=config),
            get_public_host(config=config),
        ):
            if not host_value:
                continue
            protected_host, protected_port = split_host_port(host_value)
            protected_host = protected_host.strip(".")
            if not protected_host:
                continue
            protected_hosts.add((protected_host, protected_port))
            if protected_host in {"", "0.0.0.0", "::", "127.0.0.1", "::1", "localhost"}:
                for local_alias in ("127.0.0.1", "localhost"):
                    protected_hosts.add((local_alias, protected_port))
            parts = protected_host.split(".", 1)
            if len(parts) == 2 and (parts[0] in protected_subdomains or parts[0].startswith("snap-")):
                protected_roots.add((parts[1], protected_port))
            else:
                protected_roots.add((protected_host, protected_port))

        for protected_host, protected_port in protected_hosts:
            if host == protected_host and (protected_port is None or port == protected_port):
                return True

        if config.USES_SUBDOMAIN_ROUTING:
            for protected_root, protected_port in protected_roots:
                if protected_port is not None and port != protected_port:
                    continue
                if not protected_root or not host.endswith(f".{protected_root}"):
                    continue
                subdomain = host[: -(len(protected_root) + 1)]
                if subdomain in protected_subdomains or subdomain.startswith("snap-"):
                    return True

        return False

    @property
    def created_by(self):
        """Convenience property to access the user who created this snapshot via its crawl."""
        return self.crawl.created_by

    @property
    def process_set(self):
        """Get all Process objects related to this snapshot's ArchiveResults."""
        from archivebox.machine.models import Process

        return Process.objects.filter(archiveresult__snapshot_id=self.id)

    @property
    def binary_set(self):
        """Get all Binary objects used by processes related to this snapshot."""
        from archivebox.machine.models import Binary

        return Binary.objects.filter(process_set__archiveresult__snapshot_id=self.id).distinct()

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        validate_url_field = self._state.adding or update_fields is None or "url" in update_fields
        if validate_url_field:
            try:
                validate_url_length(self.url or "")
            except ValueError as err:
                raise ValidationError({"url": str(err)}) from err

            if self.is_archivebox_internal_url(self.url):
                raise ValidationError({"url": "ArchiveBox cannot archive its own admin, web, api, or snapshot URLs."})

        if not self.bookmarked_at:
            self.bookmarked_at = self.created_at or timezone.now()
        if not self.timestamp:
            self.timestamp = str(self.bookmarked_at.timestamp())

        if self._state.adding or update_fields is None or "title" in update_fields:
            self.title = self._normalize_title_candidate(self.title, snapshot_url=self.url or "") or None

        # Migrate filesystem if needed (happens automatically on save)
        if self.pk and self.fs_migration_needed:
            self.migrate_filesystem_to_current_version()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = tuple(dict.fromkeys([*update_fields, "fs_version", "modified_at"]))
        elif self.pk:
            current_dir = self.get_storage_path_for_version(self._fs_current_version())
            source_dir = Path(self.output_dir)
            if source_dir.exists() and source_dir != current_dir and not source_dir.is_symlink():
                self.migrate_filesystem_to_current_version(source_dir=source_dir)

        super().save(*args, **kwargs)

        from django.db import transaction

        def finish_snapshot_save():
            self.ensure_legacy_archive_symlink()
            self.ensure_crawl_symlink()
            crawl = self.crawl
            if not crawl.url_passes_filters(self.url, snapshot=self):
                return
            # Best-effort skip if our URL is already recorded on the crawl;
            # the atomic UPDATE below is what actually prevents clobbering.
            crawl.refresh_from_db(fields=["urls"])
            if self.url in {url for _raw_line, url in crawl._iter_url_lines() if url}:
                return
            now = timezone.now()
            # Atomic append: SQLite reads `urls` inside the UPDATE statement,
            # so concurrent appends never clobber each other (no read-then-write
            # window, no CAS retry needed). A rare duplicate URL on a race is
            # harmless — downstream consumers dedupe via Snapshot uniqueness.
            text = models.TextField()
            type(crawl).objects.filter(pk=crawl.pk).update(
                urls=Case(
                    When(Q(urls="") | Q(urls__isnull=True), then=Value(self.url, output_field=text)),
                    default=Concat(
                        "urls",
                        Value("\n", output_field=text),
                        Value(self.url, output_field=text),
                        output_field=text,
                    ),
                    output_field=text,
                ),
                modified_at=now,
            )
            crawl.modified_at = now

        # get_or_create/update_or_create wrap save() in atomic(); defer filesystem
        # work and crawl maintenance so SQLite commits before touching the disk.
        transaction.on_commit(finish_snapshot_save)

        migration_cleanup = self.__dict__.get("_pending_fs_migration_cleanup")
        if migration_cleanup:
            old_dir, new_dir = migration_cleanup
            transaction.on_commit(lambda: self._cleanup_old_migration_dir(old_dir, new_dir))
            delattr(self, "_pending_fs_migration_cleanup")

        # if is_new:
        #     from archivebox.misc.logging_util import log_worker_event
        #     log_worker_event(
        #         worker_type='DB',
        #         event='Created Snapshot',
        #         indent_level=2,
        #         url=self.url,
        #         metadata={
        #             'id': str(self.id),
        #             'crawl_id': str(self.crawl_id),
        #             'depth': self.depth,
        #             'status': self.status,
        #         },
        #     )

    # =========================================================================
    # Filesystem Migration Methods
    # =========================================================================

    @staticmethod
    def _fs_current_version() -> str:
        """Get current ArchiveBox filesystem layout version."""
        return "0.9.4"

    @property
    def fs_migration_needed(self) -> bool:
        """Check if snapshot needs filesystem migration"""
        return self.fs_version != self._fs_current_version()

    def _fs_next_version(self, version: str) -> str:
        """Get next version in migration chain (0.7/0.8 had same layout, only 0.8→0.9 migration needed)"""
        # Treat 0.7.0 and 0.8.0 as equivalent (both used archive/{timestamp})
        if version in ("0.7.0", "0.8.0"):
            return "0.9.0"
        if version in ("0.9.0", "0.9.1", "0.9.2", "0.9.3"):
            return "0.9.4"
        return self._fs_current_version()

    @staticmethod
    def is_legacy_archive_dir(path: Path) -> bool:
        """Return True for old-style archive/{timestamp} snapshot directories."""
        if path.name in CONSTANTS.RESERVED_ARCHIVE_DIR_NAMES or path.name.startswith("."):
            return False
        try:
            ts_int = int(float(path.name))
        except (TypeError, ValueError, OverflowError):
            return False
        return 788918400 <= ts_int <= 2082758400

    def migrate_filesystem_to_current_version(self, source_dir: Path | None = None, config: "ArchiveBoxBaseConfig | None" = None) -> None:
        """
        Copy legacy snapshot output into the current layout and defer old-dir cleanup.

        The ordering is intentionally crash-safe:
        1. Copy from the legacy directory into the new directory idempotently.
        2. Verify the new directory has every old file.
        3. Convert metadata in the new directory.
        4. Update fs_version in memory for the caller to save.
        5. Cleanup is scheduled only after the DB commit succeeds.
        """
        current = self.fs_version
        target = self._fs_current_version()
        cleanup: tuple[Path, Path] | None = None
        runtime_config = config or get_config()

        if source_dir and current == target:
            current_dir = self.get_storage_path_for_version(target)
            cleanup = self._fs_migrate_legacy_to_0_9_0(source_dir=source_dir, target_dir=current_dir)
            crawl_dir = self.crawl.output_dir
            old_crawl_dir = crawl_dir.with_name(str(uuid.UUID(hex=self.crawl.id.hex)))
            if old_crawl_dir.exists() and not crawl_dir.exists() and not old_crawl_dir.is_symlink():
                crawl_dir.parent.mkdir(parents=True, exist_ok=True)
                old_crawl_dir.rename(crawl_dir)
            if cleanup:
                self._pending_fs_migration_cleanup = cleanup
            return

        while current != target:
            next_ver = self._fs_next_version(current)
            migrations = {
                ("0.7.0", "0.9.0"): self._fs_migrate_from_0_7_0_to_0_9_0,
                ("0.8.0", "0.9.0"): self._fs_migrate_from_0_8_0_to_0_9_0,
                ("0.9.0", "0.9.4"): self._fs_migrate_from_0_9_0_to_0_9_4,
                ("0.9.1", "0.9.4"): self._fs_migrate_from_0_9_0_to_0_9_4,
                ("0.9.2", "0.9.4"): self._fs_migrate_from_0_9_0_to_0_9_4,
                ("0.9.3", "0.9.4"): self._fs_migrate_from_0_9_0_to_0_9_4,
            }

            migration = migrations.get((current, next_ver))
            if migration is None:
                raise ValueError(f"No filesystem migration path from {current} to {next_ver}")
            cleanup = migration(source_dir=source_dir, config=runtime_config)

            current = next_ver
            source_dir = None

        self.fs_version = target
        if cleanup:
            self._pending_fs_migration_cleanup = cleanup

    def _fs_migrate_from_0_7_0_to_0_9_0(self, source_dir: Path | None = None, config: "ArchiveBoxBaseConfig | None" = None):
        return self._fs_migrate_legacy_to_0_9_0(source_dir=source_dir, config=config)

    def _fs_migrate_from_0_8_0_to_0_9_0(self, source_dir: Path | None = None, config: "ArchiveBoxBaseConfig | None" = None):
        return self._fs_migrate_legacy_to_0_9_0(source_dir=source_dir, config=config)

    def _fs_migrate_from_0_9_0_to_0_9_4(self, source_dir: Path | None = None, config: "ArchiveBoxBaseConfig | None" = None):
        runtime_config = config or get_config()
        target_dir = self.get_storage_path_for_version("0.9.4")
        cleanup = self._fs_migrate_legacy_to_0_9_0(source_dir=source_dir or self.output_dir, target_dir=target_dir, config=runtime_config)
        crawl_dir = self.crawl.output_dir
        old_crawl_dir = crawl_dir.with_name(str(uuid.UUID(hex=self.crawl.id.hex)))
        if old_crawl_dir.exists() and not crawl_dir.exists() and not old_crawl_dir.is_symlink():
            crawl_dir.parent.mkdir(parents=True, exist_ok=True)
            old_crawl_dir.rename(crawl_dir)
        return cleanup

    def _fs_migrate_legacy_to_0_9_0(
        self,
        source_dir: Path | None = None,
        target_dir: Path | None = None,
        config: "ArchiveBoxBaseConfig | None" = None,
    ):
        """
        Migrate from flat to nested structure.

        0.8.x: archive/{timestamp}/
        0.9.x: archive/users/{user}/snapshots/YYYYMMDD/{domain}/{uuid}/
        """
        import filecmp
        import shutil

        old_dir = Path(source_dir) if source_dir else self.get_storage_path_for_version("0.8.0")
        new_dir = Path(target_dir) if target_dir else self.get_storage_path_for_version("0.9.0")

        if old_dir == new_dir:
            return None

        if old_dir.is_symlink():
            return None

        if not old_dir.exists():
            if new_dir.exists():
                self.convert_index_json_to_jsonl(output_dir=new_dir)
                return None
            return None

        if not new_dir.exists():
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                old_dir.rename(new_dir)
                self.convert_index_json_to_jsonl(output_dir=new_dir)
                return (old_dir, new_dir)
            except OSError:
                pass

        new_dir.mkdir(parents=True, exist_ok=True)

        # Copy all files idempotently. If a previous attempt already converted
        # index.json to index.jsonl, recopying index.json is harmless; conversion
        # below removes it again after ensuring index.jsonl exists.
        for old_file in old_dir.rglob("*"):
            if not old_file.is_file():
                continue

            rel_path = old_file.relative_to(old_dir)
            new_file = new_dir / rel_path

            # Skip if already copied
            if new_file.exists():
                if new_file.stat().st_size == old_file.stat().st_size and filecmp.cmp(old_file, new_file, shallow=False):
                    continue

            new_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_file, new_file)

        # Verify all copied
        old_files = {f.relative_to(old_dir): f.stat().st_size for f in old_dir.rglob("*") if f.is_file()}
        new_files = {f.relative_to(new_dir): f.stat().st_size for f in new_dir.rglob("*") if f.is_file()}

        if old_files.keys() != new_files.keys():
            missing = old_files.keys() - new_files.keys()
            missing.discard(Path(CONSTANTS.JSON_INDEX_FILENAME))
            if missing:
                raise Exception(f"Migration incomplete: missing {missing}")

        for rel_path, old_size in old_files.items():
            if rel_path == Path(CONSTANTS.JSON_INDEX_FILENAME):
                continue
            if new_files.get(rel_path) != old_size:
                raise Exception(f"Migration incomplete: size mismatch for {rel_path}")
            if not filecmp.cmp(old_dir / rel_path, new_dir / rel_path, shallow=False):
                raise Exception(f"Migration incomplete: content mismatch for {rel_path}")

        # Convert index.json to index.jsonl in the new directory.
        self.convert_index_json_to_jsonl(output_dir=new_dir)

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
                logging.getLogger("archivebox.migration").warning(
                    f"Could not remove old migration directory {old_dir}: {e}",
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
                logging.getLogger("archivebox.migration").warning(
                    f"Could not create symlink from {symlink_path} to {new_dir}: {e}",
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

            if parsed.scheme in ("http", "https"):
                if parsed.port:
                    return f"{parsed.hostname}_{parsed.port}".replace(":", "_")
                return parsed.hostname or "unknown"
            elif parsed.scheme == "file":
                return "localhost"
            elif parsed.scheme:
                return parsed.scheme
            else:
                return "unknown"
        except Exception:
            return "unknown"

    def get_storage_path_for_version(self, version: str) -> Path:
        """
        Calculate storage path for specific filesystem version.
        Centralizes path logic so it's reusable.

        0.7.x/0.8.x: archive/{timestamp}
        0.9.x: archive/users/{username}/snapshots/YYYYMMDD/{domain}/{uuid}/
        """
        if version in ("0.7.0", "0.8.0"):
            return CONSTANTS.ARCHIVE_DIR / self.timestamp

        elif version in ("0.9.0", "0.9.1", "0.9.2", "0.9.3", "0.9.4", "1.0.0"):
            username = self.created_by.username

            date_base = self.bookmarked_at or self.created_at
            date_str = date_base.strftime("%Y%m%d") if date_base else "unknown"

            domain = self.extract_domain_from_url(self.url)

            return CONSTANTS.USERS_DIR / username / CONSTANTS.SNAPSHOTS_DIR_NAME / date_str / domain / str(self.id)
        else:
            # Unknown version - use current
            return self.get_storage_path_for_version(self._fs_current_version())

    # =========================================================================
    # Loading and Creation from Filesystem (Used by archivebox update ONLY)
    # =========================================================================

    @classmethod
    def load_from_directory(cls, snapshot_dir: Path) -> Optional["Snapshot"]:
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
                    if record.get("type") == "Snapshot":
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
            timestamp = cls._select_best_timestamp(
                index_timestamp=None,
                folder_name=snapshot_dir.name,
            )
            if not timestamp:
                return None
            try:
                return cls.objects.select_related("crawl__created_by").get(timestamp=timestamp)
            except cls.DoesNotExist:
                return None
            except cls.MultipleObjectsReturned:
                return cls.objects.select_related("crawl__created_by").filter(timestamp=timestamp).first()

        url = data.get("url")
        if not url:
            timestamp = cls._select_best_timestamp(
                index_timestamp=data.get("timestamp"),
                folder_name=snapshot_dir.name,
            )
            if not timestamp:
                return None
            try:
                return cls.objects.select_related("crawl__created_by").get(timestamp=timestamp)
            except cls.DoesNotExist:
                return None
            except cls.MultipleObjectsReturned:
                return cls.objects.select_related("crawl__created_by").filter(timestamp=timestamp).first()

        # Get timestamp - prefer index file, fallback to folder name
        timestamp = cls._select_best_timestamp(
            index_timestamp=data.get("timestamp"),
            folder_name=snapshot_dir.name,
        )
        folder_timestamp = cls._select_best_timestamp(
            index_timestamp=None,
            folder_name=snapshot_dir.name,
        )

        if not timestamp:
            return None

        # Look up existing (try exact match first, then fuzzy match for truncated timestamps)
        try:
            snapshot = cls.objects.select_related("crawl__created_by").get(url=url, timestamp=timestamp)
            return snapshot
        except cls.DoesNotExist:
            # Try fuzzy match - index.json may have truncated timestamp
            # e.g., index has "1767000340" but DB has "1767000340.624737"
            # Do not fuzzy-match when the legacy folder name itself is a valid
            # timestamp; distinct dirs like 1508259732 and 1508259732.0 must
            # remain distinct snapshots.
            if not folder_timestamp or timestamp != folder_timestamp:
                candidates = cls.objects.select_related("crawl__created_by").filter(url=url, timestamp__startswith=timestamp)
                if candidates.count() == 1:
                    snapshot = candidates.first()
                    if snapshot is None:
                        return None
                    return snapshot
                elif candidates.count() > 1:
                    return candidates.first()
            return None
        except cls.MultipleObjectsReturned:
            # Should not happen with unique constraint
            return cls.objects.select_related("crawl__created_by").filter(url=url, timestamp=timestamp).first()

    @classmethod
    def create_from_directory(cls, snapshot_dir: Path) -> Optional["Snapshot"]:
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
                    if record.get("type") == "Snapshot":
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

        if not data or not data.get("url"):
            archive_org_path = snapshot_dir / "archive.org.txt"
            try:
                archived_url = archive_org_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[0].strip()
            except (IndexError, OSError):
                archived_url = ""

            if archived_url.startswith(("http://", "https://")):
                if "://web.archive.org/web/" in archived_url and "/web/" in archived_url:
                    archive_target = archived_url.split("/web/", 1)[1].split("/", 1)
                    if len(archive_target) == 2:
                        candidate = archive_target[1]
                        if not candidate.startswith(("http://", "https://")) and "/" in candidate:
                            candidate = candidate.split("/", 1)[1]
                        if candidate.startswith(("http://", "https://")):
                            archived_url = candidate

                data = {
                    "url": archived_url,
                    "timestamp": snapshot_dir.name,
                    "title": "",
                }

        if not data:
            return None

        url = data.get("url")
        if not url:
            return None

        # Get and validate timestamp
        timestamp = cls._select_best_timestamp(
            index_timestamp=data.get("timestamp"),
            folder_name=snapshot_dir.name,
        )

        if not timestamp:
            return None

        # Ensure uniqueness (reuses existing logic from create_or_update_from_dict)
        timestamp = cls._ensure_unique_timestamp(url, timestamp)

        # Detect version
        fs_version = cls._detect_fs_version_from_index(data)

        system_user_id = get_or_create_system_user_pk()
        catchall_crawl, _ = Crawl.objects.get_or_create(
            label="[migration] orphaned snapshots",
            defaults={
                "urls": f"# Orphaned snapshot: {url}",
                "max_depth": 0,
                "created_by_id": system_user_id,
            },
        )
        if cls.objects.filter(crawl=catchall_crawl, url=url).exists():
            catchall_crawl = Crawl.objects.create(
                label=f"[migration] orphaned snapshot {timestamp}",
                urls=url,
                max_depth=0,
                created_by_id=system_user_id,
            )

        snapshot_kwargs = {
            "url": url,
            "timestamp": timestamp,
            "title": data.get("title", ""),
            "fs_version": fs_version,
            "crawl": catchall_crawl,
        }
        try:
            bookmarked_at = parse_date(data.get("bookmarked_at") or timestamp)
        except (TypeError, ValueError, OSError):
            bookmarked_at = None
        try:
            created_at = parse_date(data.get("created_at"))
        except (TypeError, ValueError, OSError):
            created_at = None
        if bookmarked_at:
            snapshot_kwargs["bookmarked_at"] = bookmarked_at
        if created_at:
            snapshot_kwargs["created_at"] = created_at

        return cls(
            **snapshot_kwargs,
        )

    @staticmethod
    def _select_best_timestamp(index_timestamp: object | None, folder_name: str) -> str | None:
        """
        Select best timestamp from index.json vs folder name.

        Validates range (1995-2035). When a valid legacy folder name is
        available it is the stable filesystem identity, so preserve it over
        normalized variants like "1508259732.0" found in old index files.
        """

        def is_valid_timestamp(ts: object | None) -> bool:
            if not isinstance(ts, (str, int, float)):
                return False
            try:
                ts_int = int(float(ts))
                # 1995-01-01 to 2035-12-31
                return 788918400 <= ts_int <= 2082758400
            except (TypeError, ValueError, OverflowError):
                return False

        index_valid = is_valid_timestamp(index_timestamp) if index_timestamp else False
        folder_valid = is_valid_timestamp(folder_name)

        if folder_valid:
            return str(folder_name).strip()
        if index_valid and index_timestamp is not None:
            return str(index_timestamp).strip()
        return None

    @classmethod
    def _ensure_unique_timestamp(cls, url: str, timestamp: str) -> str:
        """
        Ensure timestamp is globally unique.
        If there is a collision, add a tiny fractional suffix until unique.
        """
        candidate = str(timestamp)
        base = float(timestamp)
        suffix = 0
        while cls.objects.filter(timestamp=candidate).exists():
            suffix += 1
            candidate = f"{base + (suffix / 1_000_000):.6f}".rstrip("0").rstrip(".")
        return candidate

    @staticmethod
    def _detect_fs_version_from_index(data: dict) -> str:
        """
        Detect fs_version from index.json structure.

        - Has fs_version field: use it
        - Has history dict: 0.7.0
        - Has archive_results list: 0.8.0
        - Default: 0.7.0
        """
        if "fs_version" in data:
            return data["fs_version"]
        if "history" in data and "archive_results" not in data:
            return "0.7.0"
        if "archive_results" in data:
            return "0.8.0"
        return "0.7.0"

    # =========================================================================
    # Index.json Reconciliation
    # =========================================================================

    def reconcile_with_index(self, output_dir: Path | None = None, update_existing_archive_results: bool = True):
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
        output_dir = Path(output_dir) if output_dir is not None else Path(self.output_dir)
        self.convert_index_json_to_jsonl(output_dir=output_dir)

        # Check for index.jsonl (preferred) or index.json (legacy)
        jsonl_path = output_dir / CONSTANTS.JSONL_INDEX_FILENAME
        json_path = output_dir / CONSTANTS.JSON_INDEX_FILENAME

        index_data = {}

        if jsonl_path.exists():
            # Read from JSONL format
            jsonl_data = self.read_index_jsonl(output_dir=output_dir)
            if jsonl_data["snapshot"]:
                index_data = jsonl_data["snapshot"]
                # Convert archive_results list to expected format
                index_data["archive_results"] = jsonl_data["archive_results"]
        elif json_path.exists():
            # Fallback to legacy JSON format
            try:
                with open(json_path) as f:
                    index_data = json.load(f)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                pass

        # Merge title
        self._merge_title_from_index(index_data)

        # Merge tags
        self._merge_tags_from_index(index_data)

        # Merge ArchiveResults
        self._merge_archive_results_from_index(index_data, update_existing=update_existing_archive_results)
        if not self._normalize_title_candidate(self.title, snapshot_url=self.url):
            title_results = (
                self.archiveresult_set.filter(
                    plugin="title",
                    status=ArchiveResult.StatusChoices.SUCCEEDED,
                )
                .exclude(output_str="")
                .order_by("-start_ts", "-end_ts", "-created_at")
            )
            for title_result in title_results.only("output_str"):
                result_title = self._normalize_title_candidate(title_result.output_str, snapshot_url=self.url)
                if result_title:
                    self.title = result_title
                    break

        # Write back in JSONL format
        self.write_index_jsonl(output_dir=output_dir)

    def reconcile_with_index_json(self, output_dir: Path | None = None, update_existing_archive_results: bool = True):
        """Deprecated: use reconcile_with_index() instead."""
        return self.reconcile_with_index(output_dir=output_dir, update_existing_archive_results=update_existing_archive_results)

    def _merge_title_from_index(self, index_data: dict):
        """Merge title - prefer longest non-URL title."""
        index_title = self._normalize_title_candidate(index_data.get("title"), snapshot_url=self.url)
        db_title = self._normalize_title_candidate(self.title, snapshot_url=self.url)

        candidates = [t for t in [index_title, db_title] if t]
        if candidates:
            best_title = max(candidates, key=len)
            if self.title != best_title:
                self.title = best_title
        elif self.title:
            self.title = None

    def _merge_tags_from_index(self, index_data: dict):
        """Merge tags - union of both sources."""
        from django.db import transaction

        index_tags = set(index_data.get("tags", "").split(",")) if index_data.get("tags") else set()
        index_tags = {t.strip() for t in index_tags if t.strip()}

        db_tags = set(self.tags.values_list("name", flat=True))

        new_tags = index_tags - db_tags
        if new_tags:
            with transaction.atomic():
                for tag_name in new_tags:
                    tag, _ = Tag.objects.get_or_create(name=tag_name)
                    self.tags.add(tag)

    def _merge_archive_results_from_index(self, index_data: dict, update_existing: bool = True):
        """Merge ArchiveResults one row per hook; retries update the existing row."""
        existing = {(ar.plugin, ar.hook_name): ar for ar in ArchiveResult.objects.filter(snapshot=self)}
        if update_existing:
            for archiveresult in existing.values():
                normalized_status = ArchiveResult.normalize_status(archiveresult.status)
                if archiveresult.status != normalized_status:
                    archiveresult.status = normalized_status
                    archiveresult.save(update_fields=["status", "modified_at"])

        # Handle 0.8.x format (archive_results list)
        for result_data in index_data.get("archive_results", []):
            self._create_archive_result_if_missing(result_data, existing, update_existing=update_existing)

        # Handle 0.7.x format (history dict)
        if "history" in index_data and isinstance(index_data["history"], dict):
            for plugin, result_list in index_data["history"].items():
                if isinstance(result_list, list):
                    for result_data in result_list:
                        # Support both old 'extractor' and new 'plugin' keys for backwards compat
                        result_data["plugin"] = result_data.get("plugin") or result_data.get("extractor") or plugin
                        self._create_archive_result_if_missing(result_data, existing, update_existing=update_existing)

    def _create_archive_result_if_missing(self, result_data: dict, existing: dict, update_existing: bool = True):
        """Create ArchiveResult if not already in DB."""
        from dateutil import parser
        from django.db import transaction
        from archivebox.machine.models import Machine, Process

        # Support both old 'extractor' and new 'plugin' keys for backwards compat
        plugin = (result_data.get("plugin") or result_data.get("extractor", ""))[:32]
        if not plugin:
            return

        start_ts = None
        if result_data.get("start_ts"):
            try:
                start_ts = parser.parse(result_data["start_ts"])
                if start_ts and timezone.is_naive(start_ts):
                    start_ts = timezone.make_aware(start_ts, timezone.get_current_timezone())
            except (TypeError, ValueError, OverflowError):
                pass

        end_ts = None
        if result_data.get("end_ts"):
            try:
                end_ts = parser.parse(result_data["end_ts"])
                if end_ts and timezone.is_naive(end_ts):
                    end_ts = timezone.make_aware(end_ts, timezone.get_current_timezone())
            except (TypeError, ValueError, OverflowError):
                pass

        # Support both 'output' (legacy) and 'output_str' (new JSONL) field names
        output_str = result_data.get("output_str") or result_data.get("output", "")
        status = ArchiveResult.normalize_status(result_data.get("status") or ArchiveResult.StatusChoices.FAILED)
        process = None
        cmd = result_data.get("cmd") or []
        pwd = result_data.get("pwd") or ""
        output_files = ArchiveResult._normalize_output_files(result_data.get("output_files"))
        output_size = ArchiveResult._coerce_output_file_size(result_data.get("output_size"))
        output_json = result_data.get("output_json")
        output_mimetypes = result_data.get("output_mimetypes", "")

        hook_name = result_data.get("hook_name", "")
        existing_result = existing.get((plugin, hook_name))
        if existing_result:
            if not update_existing:
                return

            update_fields = []
            if existing_result.status != status:
                existing_result.status = status
                update_fields.append("status")
            if output_str and existing_result.output_str != output_str:
                existing_result.output_str = output_str
                update_fields.append("output_str")
            if output_json and existing_result.output_json != output_json:
                existing_result.output_json = output_json
                update_fields.append("output_json")
            if output_files and existing_result.output_files != output_files:
                existing_result.output_files = output_files
                update_fields.append("output_files")
            if "output_size" in result_data and existing_result.output_size != output_size:
                existing_result.output_size = output_size
                update_fields.append("output_size")
            if output_mimetypes and existing_result.output_mimetypes != output_mimetypes:
                existing_result.output_mimetypes = output_mimetypes
                update_fields.append("output_mimetypes")
            if start_ts and existing_result.start_ts != start_ts:
                existing_result.start_ts = start_ts
                update_fields.append("start_ts")
            if end_ts and existing_result.end_ts != end_ts:
                existing_result.end_ts = end_ts
                update_fields.append("end_ts")
            if update_fields:
                existing_result.save(update_fields=[*update_fields, "modified_at"])
            return

        # Machine.current() can probe the host and sanitize config. Do that before
        # atomic() so the transaction below only covers the two related row writes.
        machine = Machine.current() if cmd or pwd else None
        with transaction.atomic():
            if machine is not None:
                process = Process.objects.create(
                    machine=machine,
                    process_type=Process.TypeChoices.HOOK,
                    worker_type="archiveresult",
                    cmd=cmd,
                    pwd=pwd,
                    status=Process.StatusChoices.EXITED,
                    exit_code=0 if status in ("succeeded", "skipped", "noresults") else 1,
                    started_at=start_ts,
                    ended_at=end_ts,
                )

            archiveresult = ArchiveResult.objects.create(
                snapshot=self,
                plugin=plugin,
                hook_name=hook_name,
                status=status,
                output_str=output_str,
                output_json=output_json,
                output_files=output_files,
                output_size=output_size,
                output_mimetypes=output_mimetypes,
                start_ts=start_ts,
                end_ts=end_ts,
                process=process,
            )
        existing[(plugin, hook_name)] = archiveresult

    def write_index_json(self):
        """Write index.json in 0.9.x format (deprecated, use write_index_jsonl)."""
        import json

        index_path = Path(self.output_dir) / "index.json"

        data = {
            "url": self.url,
            "timestamp": self.timestamp,
            "title": self.title or "",
            "tags": ",".join(sorted(self.tags.values_list("name", flat=True))),
            "fs_version": self.fs_version,
            "bookmarked_at": self.bookmarked_at.isoformat() if self.bookmarked_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "archive_results": [
                {
                    "plugin": ar.plugin,
                    "status": ar.status,
                    "start_ts": ar.start_ts.isoformat() if ar.start_ts else None,
                    "end_ts": ar.end_ts.isoformat() if ar.end_ts else None,
                    "output": ar.output_str or "",
                    "cmd": ar.cmd if isinstance(ar.cmd, list) else [],
                    "pwd": ar.pwd,
                }
                for ar in ArchiveResult.objects.filter(snapshot=self).order_by("start_ts")
            ],
        }

        index_path.parent.mkdir(parents=True, exist_ok=True)
        with open(index_path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)

    def write_index_jsonl(self, output_dir: Path | None = None):
        """
        Write index.jsonl in flat JSONL format.

        Each line is a JSON record with a 'type' field:
        - Snapshot: snapshot metadata (crawl_id, url, tags, etc.)
        - ArchiveResult: extractor results (plugin, status, output, etc.)
        - Binary: binary info used for the extraction
        - Process: process execution details (cmd, exit_code, timing, etc.)
        """
        import json

        output_dir = Path(output_dir) if output_dir is not None else Path(self.output_dir)
        index_path = output_dir / CONSTANTS.JSONL_INDEX_FILENAME
        index_path.parent.mkdir(parents=True, exist_ok=True)

        # Track unique binaries and processes to avoid duplicates
        binaries_seen = set()
        processes_seen = set()

        tmp_index_path = index_path.with_name(f".{index_path.name}.tmp")
        with open(tmp_index_path, "w") as f:
            # Write Snapshot record first (to_json includes crawl_id, fs_version)
            f.write(json.dumps(self.to_json()) + "\n")

            # Write ArchiveResult records with their associated Binary and Process
            # Use select_related to optimize queries
            for ar in self.archiveresult_set.select_related("process__binary").order_by("start_ts"):
                process = ar.process_record
                # Write Binary record if not already written
                if process and process.binary and process.binary_id not in binaries_seen:
                    binaries_seen.add(process.binary_id)
                    f.write(json.dumps(process.binary.to_json()) + "\n")

                # Write Process record if not already written
                if process and process.id not in processes_seen:
                    processes_seen.add(process.id)
                    f.write(json.dumps(process.to_json()) + "\n")

                # Write ArchiveResult record
                f.write(json.dumps(ar.to_json(snapshot_output_dir=output_dir)) + "\n")
        os.replace(tmp_index_path, index_path)

    def read_index_jsonl(self, output_dir: Path | None = None) -> dict:
        """
        Read index.jsonl and return parsed records grouped by type.

        Returns dict with keys: 'snapshot', 'archive_results', 'binaries', 'processes'
        """
        from archivebox.machine.models import Process
        from archivebox.misc.jsonl import (
            TYPE_SNAPSHOT,
            TYPE_ARCHIVERESULT,
            TYPE_BINARYREQUEST,
            TYPE_BINARY,
            TYPE_PROCESS,
        )

        output_dir = Path(output_dir) if output_dir is not None else Path(self.output_dir)
        index_path = output_dir / CONSTANTS.JSONL_INDEX_FILENAME
        result: dict[str, Any] = {
            "snapshot": None,
            "archive_results": [],
            "binaries": [],
            "processes": [],
        }

        if not index_path.exists():
            return result

        records = Process.parse_records_from_text(index_path.read_text())
        for record in records:
            record_type = record.get("type")
            if record_type == TYPE_SNAPSHOT:
                result["snapshot"] = record
            elif record_type == TYPE_ARCHIVERESULT:
                result["archive_results"].append(record)
            elif record_type in {TYPE_BINARYREQUEST, TYPE_BINARY}:
                result["binaries"].append(record)
            elif record_type == TYPE_PROCESS:
                result["processes"].append(record)

        return result

    def convert_index_json_to_jsonl(self, output_dir: Path | None = None) -> bool:
        """
        Convert index.json to index.jsonl format.

        Reads existing index.json, creates index.jsonl, and removes index.json.
        Returns True if conversion was performed, False if no conversion needed.
        """
        import json

        output_dir = Path(output_dir) if output_dir is not None else Path(self.output_dir)
        json_path = output_dir / CONSTANTS.JSON_INDEX_FILENAME
        jsonl_path = output_dir / CONSTANTS.JSONL_INDEX_FILENAME

        # Skip if already converted or no json file exists
        if jsonl_path.exists():
            json_path.unlink(missing_ok=True)
            return False
        if not json_path.exists():
            return False

        try:
            with open(json_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return False

        # Detect format version and extract records
        fs_version = data.get("fs_version", "0.7.0")

        records = []
        snapshot_record = {
            "type": "Snapshot",
            "id": str(self.id),
            "crawl_id": str(self.crawl_id) if self.crawl_id else None,
            "url": data.get("url", self.url),
            "timestamp": data.get("timestamp", self.timestamp),
            "title": data.get("title", self.title or ""),
            "tags": data.get("tags", ""),
            "fs_version": fs_version,
            "bookmarked_at": data.get("bookmarked_at"),
            "created_at": data.get("created_at"),
        }
        records.append(snapshot_record)

        # Handle 0.8.x/0.9.x format (archive_results list)
        for result_data in data.get("archive_results", []):
            ar_record = {
                "type": "ArchiveResult",
                "snapshot_id": str(self.id),
                "plugin": result_data.get("plugin", ""),
                "hook_name": result_data.get("hook_name", ""),
                "status": result_data.get("status") or ArchiveResult.StatusChoices.FAILED,
                "output_str": result_data.get("output_str") or result_data.get("output", ""),
                "output_json": result_data.get("output_json"),
                "output_files": result_data.get("output_files"),
                "output_size": result_data.get("output_size"),
                "output_mimetypes": result_data.get("output_mimetypes", ""),
                "start_ts": result_data.get("start_ts"),
                "end_ts": result_data.get("end_ts"),
            }
            if result_data.get("cmd"):
                ar_record["cmd"] = result_data["cmd"]
            if result_data.get("pwd"):
                ar_record["pwd"] = result_data["pwd"]
            records.append(ar_record)

        # Handle 0.7.x format (history dict)
        if "history" in data and isinstance(data["history"], dict):
            for plugin, result_list in data["history"].items():
                if not isinstance(result_list, list):
                    continue
                for result_data in result_list:
                    ar_record = {
                        "type": "ArchiveResult",
                        "snapshot_id": str(self.id),
                        "plugin": result_data.get("plugin") or result_data.get("extractor") or plugin,
                        "hook_name": result_data.get("hook_name", ""),
                        "status": result_data.get("status") or ArchiveResult.StatusChoices.FAILED,
                        "output_str": result_data.get("output_str") or result_data.get("output", ""),
                        "output_json": result_data.get("output_json"),
                        "output_files": result_data.get("output_files"),
                        "output_size": result_data.get("output_size"),
                        "output_mimetypes": result_data.get("output_mimetypes", ""),
                        "start_ts": result_data.get("start_ts"),
                        "end_ts": result_data.get("end_ts"),
                    }
                    if result_data.get("cmd"):
                        ar_record["cmd"] = result_data["cmd"]
                    if result_data.get("pwd"):
                        ar_record["pwd"] = result_data["pwd"]
                    records.append(ar_record)

        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_jsonl_path = jsonl_path.with_name(f".{jsonl_path.name}.tmp")
        with open(tmp_jsonl_path, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(record) + "\n" for record in records))
        os.replace(tmp_jsonl_path, jsonl_path)

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

        invalid_dir = CONSTANTS.DATA_DIR / "invalid" / datetime.now().strftime("%Y%m%d")
        invalid_dir.mkdir(parents=True, exist_ok=True)

        dest = invalid_dir / snapshot_dir.name
        counter = 1
        while dest.exists():
            dest = invalid_dir / f"{snapshot_dir.name}_{counter}"
            counter += 1

        try:
            shutil.move(str(snapshot_dir), str(dest))
        except Exception:
            pass

    @classmethod
    def find_and_merge_duplicates(cls) -> int:
        """
        Find and merge snapshots with same url:timestamp.
        Returns count of duplicate sets merged.

        Used by: archivebox update (Phase 3: deduplication)
        """
        from django.db.models import Count

        duplicates = cls.objects.values("url", "timestamp").annotate(count=Count("id")).filter(count__gt=1)

        merged = 0
        for dup in duplicates.iterator(chunk_size=500):
            snapshots = list(
                cls.objects.filter(url=dup["url"], timestamp=dup["timestamp"]).order_by("created_at"),  # Keep oldest
            )

            if len(snapshots) > 1:
                try:
                    cls._merge_snapshots(snapshots)
                    merged += 1
                except Exception:
                    pass

        return merged

    @classmethod
    def _merge_snapshots(cls, snapshots: Sequence["Snapshot"]):
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
                for dup_file in dup_dir.rglob("*"):
                    if not dup_file.is_file():
                        continue

                    rel = dup_file.relative_to(dup_dir)
                    keeper_file = keeper_dir / rel

                    if not keeper_file.exists():
                        keeper_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(dup_file, keeper_file)

                try:
                    shutil.rmtree(dup_dir)
                except Exception:
                    pass

            # Merge tags
            for tag in dup.tags.all():
                keeper.tags.add(tag)

            # Move ArchiveResults
            ArchiveResult.objects.filter(snapshot=dup).update(
                snapshot=keeper,
                modified_at=timezone.now(),
            )

            # Delete
            dup.delete()

    # =========================================================================
    # Output Directory Properties
    # =========================================================================

    @property
    def output_dir_parent(self) -> str:
        return "archive"

    @property
    def output_dir_name(self) -> str:
        return str(self.timestamp)

    def archive(self, overwrite=False, methods=None):
        updates = {
            "status": self.StatusChoices.QUEUED,
            "retry_at": timezone.now(),
        }
        if overwrite:
            updates["downloaded_at"] = None
        return int(self.update_and_requeue(**updates))

    @admin.display(description="Tags")
    def tags_str(self, nocache=True) -> str | None:
        calc_tags_str = lambda: ",".join(sorted(tag.name for tag in self.tags.all()))
        prefetched_cache = self.__dict__.get("_prefetched_objects_cache", {})
        if "tags" in prefetched_cache:
            return calc_tags_str()
        cache_key = f"{self.pk}-tags"
        return cache.get_or_set(cache_key, calc_tags_str) if not nocache else calc_tags_str()

    def icons(self, path: str | None = None) -> str:
        """Generate HTML icons showing which extractor plugins have succeeded for this snapshot"""
        from django.utils.html import format_html

        compact_icons = self.__dict__.get("_icons_compact", False)
        cache_key = f"result_icons:{self.pk}:{'compact' if compact_icons else 'full'}:{(self.downloaded_at or self.modified_at or self.created_at or self.bookmarked_at).timestamp()}"

        def calc_icons():
            if compact_icons and self.status == self.StatusChoices.STARTED:
                progress_stats = self.__dict__.get("_icons_progress_stats") or self.get_progress_stats()
                total = int(progress_stats.get("total") or 0)
                succeeded = int(progress_stats.get("succeeded") or 0)
                failed = int(progress_stats.get("failed") or 0)
                skipped = int(progress_stats.get("skipped") or 0)
                noresults = int(progress_stats.get("noresults") or 0)
                running = int(progress_stats.get("running") or 0)
                completed = succeeded + failed + skipped + noresults
                percent = int((completed / total * 100) if total > 0 else 0)
                return format_html(
                    '<div class="snapshot-files-progress" title="{} of {} hooks complete" style="min-width: 96px;">'
                    '<div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">'
                    '<span class="snapshot-progress-spinner" style="display: inline-block; width: 12px; height: 12px; border: 2px solid #e2e8f0; border-top-color: #3b82f6; border-radius: 50%; animation: snapshot-spin 0.8s linear infinite;"></span>'
                    '<span style="font-size: 11px; color: #64748b;">{}/{} hooks</span>'
                    "</div>"
                    '<div style="background: #e2e8f0; border-radius: 4px; height: 6px; overflow: hidden;">'
                    '<div style="background: #3b82f6; width: {}%; height: 100%; transition: width 0.3s;"></div>'
                    "</div>"
                    '<div style="font-size: 10px; color: #94a3b8; margin-top: 2px;">'
                    "✓{} ✗{} ⏳{}"
                    "</div>"
                    "</div>",
                    completed,
                    total,
                    completed,
                    total,
                    percent,
                    succeeded,
                    failed,
                    running,
                )

            precomputed_archive_results = self.__dict__.get("_icons_archive_results")
            prefetched_cache = self.__dict__.get("_prefetched_objects_cache", {})
            if precomputed_archive_results is not None and compact_icons:
                archive_results = {plugin: True for plugin in precomputed_archive_results}
            elif "archiveresult_set" in prefetched_cache:
                archive_results = {
                    r.plugin: r
                    for r in self.archiveresult_set.all()
                    if r.status == "succeeded" and (compact_icons or r.output_files or r.output_str)
                }
            else:
                # Filter for results that have either output_files or output_str
                from django.db.models import Q

                archive_results_qs = self.archiveresult_set.filter(status="succeeded")
                if not compact_icons:
                    archive_results_qs = archive_results_qs.filter(Q(output_files__isnull=False) | ~Q(output_str=""))
                archive_results = {r.plugin: r for r in archive_results_qs}

            archive_path = path or self.archive_path
            output = ""
            output_template = '<a href="/{}/{}" class="exists-{}" title="{}">{}</a>'

            # Get all plugins from hooks system (sorted by numeric prefix)
            all_plugins = self.__dict__.get("_icons_plugin_names")
            if all_plugins is None and not compact_icons:
                all_plugins = [get_plugin_name(e) for e in get_plugins()]
            elif all_plugins is None:
                all_plugins = []
            ordered_plugins = [plugin for plugin in all_plugins if plugin in archive_results]
            ordered_plugins.extend(sorted(set(archive_results) - set(ordered_plugins)))

            for plugin in ordered_plugins:
                result = archive_results.get(plugin)
                existing = result is True or bool(
                    result and result.status == "succeeded" and (compact_icons or result.output_files or result.output_str),
                )
                if not existing:
                    continue
                icon = mark_safe(get_plugin_icon(plugin))

                # Skip plugins with empty icons that have no output
                # (e.g., staticfile only shows when there's actual output)
                if not icon.strip():
                    continue

                embed_path = f"{plugin}/" if compact_icons else result.embed_path()
                output += format_html(
                    output_template,
                    archive_path,
                    embed_path,
                    str(bool(existing)),
                    plugin,
                    icon,
                )

            return format_html(
                '<span class="files-icons" style="font-size: 1em; opacity: 0.8; display: inline-grid; grid-auto-flow: column; grid-auto-columns: auto; grid-template-rows: repeat(4, auto); gap: 0 0; justify-content: start; align-content: start;">{}</span>',
                mark_safe(output),
            )

        if compact_icons and self.status == self.StatusChoices.STARTED:
            return calc_icons()

        cache_result = cache.get(cache_key)
        if cache_result:
            return cache_result

        fresh_result = calc_icons()
        cache.set(cache_key, fresh_result, timeout=60 * 60 * 24)
        return fresh_result

    @property
    def api_url(self) -> str:
        return str(reverse_lazy("api-1:get_snapshot", args=[self.id]))

    def get_absolute_url(self):
        return f"/{self.archive_path}"

    @cached_property
    def domain(self) -> str:
        return url_domain(self.url)

    @property
    def title_stripped(self) -> str:
        return (self.title or "").strip()

    @staticmethod
    def _normalize_title_candidate(candidate: str | None, *, snapshot_url: str) -> str:
        title = " ".join(line.strip() for line in str(candidate or "").splitlines() if line.strip()).strip()
        if not title:
            return ""
        if title.lower() in {"pending...", "no title found", "unable to detect page title"}:
            return ""
        if title == snapshot_url:
            return ""
        if title.startswith(("http://", "https://")):
            return ""
        if "/" in title and title.lower().endswith(".txt"):
            return ""
        return title

    @property
    def resolved_title(self) -> str:
        stored_title = self._normalize_title_candidate(self.title, snapshot_url=self.url)
        if stored_title:
            return stored_title

        title_results = (
            self.archiveresult_set.filter(
                plugin="title",
                status=ArchiveResult.StatusChoices.SUCCEEDED,
            )
            .exclude(output_str="")
            .order_by("-start_ts", "-end_ts", "-created_at")
        )
        for title_result in title_results.only("output_str"):
            result_title = self._normalize_title_candidate(title_result.output_str, snapshot_url=self.url)
            if result_title:
                return result_title

        title_file = self.output_dir / "title" / "title.txt"
        if title_file.exists():
            try:
                file_title = self._normalize_title_candidate(title_file.read_text(encoding="utf-8"), snapshot_url=self.url)
            except OSError:
                file_title = ""
            if file_title:
                return file_title

        return ""

    @cached_property
    def hashes_index(self) -> dict[str, dict[str, Any]]:
        hashes_path = self.output_dir / "hashes" / "hashes.json"
        if not hashes_path.exists():
            return {}

        try:
            data = json.loads(hashes_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        index: dict[str, dict[str, Any]] = {}
        if isinstance(data, dict) and isinstance(data.get("files"), list):
            for entry in data["files"]:
                if not isinstance(entry, dict):
                    continue
                path = str(entry.get("path") or "").strip().rstrip("/")
                if not path:
                    continue
                index[path] = {
                    "size": entry.get("size") or entry.get("num_bytes") or entry.get("bytes") or 0,
                    "is_dir": bool(entry.get("is_dir")) or str(entry.get("path") or "").endswith("/"),
                    "hash": entry.get("hash") or entry.get("hash_sha256"),
                }
        elif isinstance(data, dict):
            for path, entry in data.items():
                if not isinstance(entry, dict) or path == ".":
                    continue
                clean_path = str(path).rstrip("/")
                if not clean_path:
                    continue
                index[clean_path] = {
                    "size": entry.get("size") or entry.get("num_bytes") or 0,
                    "is_dir": bool(entry.get("mime_type") == "inode/directory" or str(path).endswith("/")),
                    "hash": entry.get("hash") or entry.get("hash_sha256"),
                }
        return index

    @property
    def output_dir(self) -> Path:
        """The filesystem path to the snapshot's output directory."""
        import os

        current_path = self.get_storage_path_for_version(self.fs_version)

        if current_path.exists():
            return current_path

        if self.fs_version in ("0.9.0", "0.9.1", "0.9.2", "0.9.3", "0.9.4", "1.0.0"):
            hyphen_path = current_path.with_name(str(uuid.UUID(hex=self.id.hex)))
            if hyphen_path.exists():
                return hyphen_path

        # Check for backwards-compat symlink
        old_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
        if old_path.is_symlink():
            link_target = Path(os.readlink(old_path))
            return (old_path.parent / link_target).resolve() if not link_target.is_absolute() else link_target.resolve()
        elif old_path.exists():
            return old_path

        return current_path

    def ensure_legacy_archive_symlink(self) -> None:
        """Ensure the legacy archive/<timestamp> path resolves to this snapshot."""
        import os

        legacy_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
        target = Path(self.get_storage_path_for_version(self._fs_current_version()))

        if target == legacy_path:
            return

        legacy_path.parent.mkdir(parents=True, exist_ok=True)

        if legacy_path.exists() or legacy_path.is_symlink():
            if legacy_path.is_symlink():
                try:
                    if legacy_path.resolve() == target.resolve():
                        return
                except OSError:
                    pass
                legacy_path.unlink(missing_ok=True)
            else:
                return

        rel_target = os.path.relpath(target, legacy_path.parent)
        try:
            legacy_path.symlink_to(rel_target, target_is_directory=True)
        except OSError:
            return

    def ensure_crawl_symlink(self, *, crawl_dir: Path | None = None, snapshot_dir: Path | None = None) -> None:
        """Ensure snapshot is symlinked under its crawl output directory."""
        import os
        from pathlib import Path

        if crawl_dir is None:
            if not self.crawl_id:
                return
            try:
                crawl = self.crawl
            except ObjectDoesNotExist:
                crawl = None
            if crawl is None:
                crawl = Crawl.objects.filter(id=self.crawl_id).select_related("created_by").first()
            if not crawl:
                return
            crawl_dir = Path(crawl.output_dir)

        domain = self.extract_domain_from_url(self.url)

        link_path = Path(crawl_dir) / CONSTANTS.SNAPSHOTS_DIR_NAME / domain / str(self.id)
        link_parent = link_path.parent
        link_parent.mkdir(parents=True, exist_ok=True)

        target = Path(snapshot_dir) if snapshot_dir is not None else Path(self.output_dir)
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
        return f"{CONSTANTS.ARCHIVE_DIR_NAME}/{self.timestamp}"

    @cached_property
    def archive_path_from_db(self) -> str:
        """Best-effort public URL path derived from DB fields only."""
        if self.fs_version in ("0.7.0", "0.8.0"):
            return self.legacy_archive_path

        if self.fs_version in ("0.9.0", "0.9.1", "0.9.2", "0.9.3", "0.9.4", "1.0.0"):
            username = "web"
            crawl = self.crawl if self.crawl_id else None
            if crawl and crawl.created_by_id:
                username = crawl.created_by.username
            if username == "system":
                username = "web"

            date_base = self.bookmarked_at or self.created_at
            if date_base:
                date_str = date_base.strftime("%Y%m%d")
            else:
                return self.legacy_archive_path

            domain = self.extract_domain_from_url(self.url)
            return f"{username}/{date_str}/{domain}/{self.id}"

        return self.legacy_archive_path

    @cached_property
    def url_path(self) -> str:
        """URL path matching the current snapshot output_dir layout."""
        if self.fs_version in ("0.9.0", "0.9.1", "0.9.2", "0.9.3", "0.9.4", "1.0.0"):
            return self.archive_path_from_db

        output_dir = Path(self.output_dir).resolve()
        try:
            rel_users_path = output_dir.relative_to(CONSTANTS.USERS_DIR)
        except Exception:
            rel_users_path = None

        if rel_users_path:
            parts = rel_users_path.parts
            # Configured users root: <username>/snapshots/<YYYYMMDD>/<domain>/<uuid>/
            if len(parts) >= 5 and parts[1] == CONSTANTS.SNAPSHOTS_DIR_NAME:
                username = parts[0]
                if username == "system":
                    username = "web"
                date_str = parts[2]
                domain = parts[3]
                snapshot_id = parts[4].replace("-", "")
                return f"{username}/{date_str}/{domain}/{snapshot_id}"

        try:
            rel_path = output_dir.relative_to(CONSTANTS.DATA_DIR)
        except Exception:
            return self.legacy_archive_path

        parts = rel_path.parts
        # New layout: archive/users/<username>/snapshots/<YYYYMMDD>/<domain>/<uuid>/
        if (
            len(parts) >= 7
            and parts[0] == CONSTANTS.ARCHIVE_DIR_NAME
            and parts[1] == CONSTANTS.USERS_DIR_NAME
            and parts[3] == CONSTANTS.SNAPSHOTS_DIR_NAME
        ):
            username = parts[2]
            if username == "system":
                username = "web"
            date_str = parts[4]
            domain = parts[5]
            snapshot_id = parts[6].replace("-", "")
            return f"{username}/{date_str}/{domain}/{snapshot_id}"

        # Previous dev layout: users/<username>/snapshots/<YYYYMMDD>/<domain>/<uuid>/
        if len(parts) >= 6 and parts[0] == "users" and parts[2] == "snapshots":
            username = parts[1]
            if username == "system":
                username = "web"
            date_str = parts[3]
            domain = parts[4]
            snapshot_id = parts[5].replace("-", "")
            return f"{username}/{date_str}/{domain}/{snapshot_id}"

        # Legacy layout: archive/<timestamp>/
        if len(parts) >= 2 and parts[0] == CONSTANTS.ARCHIVE_DIR_NAME:
            return f"{parts[0]}/{parts[1]}"

        return "/".join(parts)

    @cached_property
    def archive_path(self):
        return self.url_path

    @cached_property
    def archive_size(self):
        return int(self.output_size or 0)

    def save_tags(self, tags: Iterable[str] = ()) -> None:
        tags_id = [Tag.objects.get_or_create(name=tag)[0].pk for tag in tags if tag.strip()]
        self.tags.clear()
        self.tags.add(*tags_id)

    def pending_archiveresults(self) -> QuerySet["ArchiveResult"]:
        return self.archiveresult_set.exclude(status__in=ArchiveResult.FINAL_OR_ACTIVE_STATES)

    def run(self) -> list["ArchiveResult"]:
        """
        Execute snapshot by creating pending ArchiveResults for all enabled hooks.

        Returns:
            list[ArchiveResult]: Newly created pending results
        """
        return self.create_pending_archiveresults()

    def cleanup(self):
        """
        Clean up background ArchiveResult hooks and empty results.

        Called by the state machine when entering the 'sealed' state.
        Deletes empty ArchiveResults after the abx-dl cleanup phase has finished.
        """
        # Clean up .pid files from output directory.
        output_dir = Path(self.output_dir)
        output_dir_exists = output_dir.exists()
        if output_dir_exists:
            for pid_file in output_dir.glob("**/*.pid"):
                pid_file.unlink(missing_ok=True)

            # Update all background ArchiveResults from filesystem in case
            # output arrived late. If there is no snapshot directory, there is
            # no filesystem output to reconcile and no reason to hit this query.
            for ar in self.archiveresult_set.filter(hook_name__contains=".bg."):
                ar.update_from_output()
        else:
            return

        # Delete ArchiveResults that produced no output files
        empty_ars = self.archiveresult_set.filter(
            output_files={},  # No output files
        ).filter(
            status__in=ArchiveResult.FINAL_STATES,  # Only delete finished ones
        )

        if empty_ars.exists():
            deleted_count, _ = empty_ars.delete()
            rprint(f"[yellow]🗑️  Deleted {deleted_count} empty ArchiveResults for {self.url}[/yellow]")

    def to_json(self) -> dict:
        """
        Convert Snapshot model instance to a JSON-serializable dict.
        Includes all fields needed to fully reconstruct/identify this snapshot.
        """
        from archivebox.config import VERSION

        archive_size = self.archive_size

        return {
            "type": "Snapshot",
            "schema_version": VERSION,
            "id": str(self.id),
            "crawl_id": str(self.crawl_id),
            "url": self.url,
            "title": self.title,
            "tags": self.tags_str(),
            "bookmarked_at": self.bookmarked_at.isoformat() if self.bookmarked_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "timestamp": self.timestamp,
            "depth": self.depth,
            "status": self.status,
            "fs_version": self.fs_version,
            "archive_size": archive_size,
            "output_size": archive_size,
        }

    @staticmethod
    def from_json(record: dict[str, Any], overrides: dict[str, Any] | None = None, queue_for_extraction: bool = True):
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
        from archivebox.base_models.models import get_or_create_system_user_pk

        config = get_config()

        overrides = overrides or {}

        # If 'id' is provided, lookup and patch that specific snapshot
        snapshot_id = record.get("id")
        if snapshot_id:
            try:
                snapshot = Snapshot.objects.get(id=snapshot_id)

                # Generically update all fields present in record
                update_fields = []
                for field_name, value in record.items():
                    # Skip internal fields
                    if field_name in ("id", "type"):
                        continue

                    # Skip if field doesn't exist on model
                    if not hasattr(snapshot, field_name):
                        continue

                    # Special parsing for date fields
                    if field_name in ("bookmarked_at", "retry_at", "created_at", "modified_at"):
                        if value and isinstance(value, str):
                            value = parse_date(value)

                    # Update field if value is provided and different
                    if value is not None and getattr(snapshot, field_name) != value:
                        setattr(snapshot, field_name, value)
                        update_fields.append(field_name)

                if update_fields:
                    snapshot.save(update_fields=update_fields + ["modified_at"])

                return snapshot
            except Snapshot.DoesNotExist:
                # ID not found, fall through to create-by-URL logic
                pass

        from archivebox.misc.util import fix_url_from_markdown, sanitize_extracted_url

        url = sanitize_extracted_url(fix_url_from_markdown(str(record.get("url") or "").strip()))
        if not url:
            return None

        # Determine or create crawl (every snapshot must have a crawl)
        crawl = overrides.get("crawl")
        parent_snapshot = overrides.get("snapshot")  # Parent snapshot
        created_by_id = overrides.get("created_by_id") or (
            parent_snapshot.created_by.pk if parent_snapshot else get_or_create_system_user_pk()
        )

        import sys

        record_crawl_id = record.get("crawl_id")
        if record_crawl_id and crawl and str(crawl.id) != str(record_crawl_id):
            rprint(
                f"[yellow]⚠️  Snapshot.from_json crawl mismatch: record has crawl_id={record_crawl_id}, overrides has crawl={crawl.id}[/yellow]",
                file=sys.stderr,
            )

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
                sources_file = CONSTANTS.SOURCES_DIR / f"{timestamp_str}__auto_crawl.txt"
                sources_file.parent.mkdir(parents=True, exist_ok=True)
                sources_file.write_text(url)

                crawl = Crawl.objects.create(
                    urls=url,
                    max_depth=0,
                    label=f"auto-created for {url[:50]}",
                    created_by_id=created_by_id,
                )
                rprint(f"[red]⚠️  Snapshot.from_json auto-created new crawl {crawl.id} for url={url}[/red]", file=sys.stderr)

        # Parse tags (accept either a list ["tag1", "tag2"] or a comma-separated string "tag1,tag2")
        tags_raw = record.get("tags", "")
        tag_list = []
        if isinstance(tags_raw, list):
            tag_list = list(dict.fromkeys(tag.strip() for tag in tags_raw if tag.strip()))
        elif tags_raw:
            tag_list = list(
                dict.fromkeys(tag.strip() for tag in re.split(config.TAG_SEPARATOR_PATTERN, tags_raw) if tag.strip()),
            )

        # Check for existing snapshot with same URL in same crawl
        # (URLs can exist in multiple crawls, but should be unique within a crawl)
        snapshot = Snapshot.objects.filter(url=url, crawl=crawl).order_by("-created_at").first()

        title = record.get("title")
        timestamp = record.get("timestamp")
        timestamp_for_bookmark = Snapshot._select_best_timestamp(index_timestamp=timestamp, folder_name="")
        try:
            bookmarked_at = parse_date(record.get("bookmarked_at") or timestamp_for_bookmark)
        except (TypeError, ValueError, OSError):
            bookmarked_at = None
        try:
            created_at = parse_date(record.get("created_at"))
        except (TypeError, ValueError, OSError):
            created_at = None

        if snapshot:
            # Update existing snapshot
            if title and (not snapshot.title or len(title) > len(snapshot.title or "")):
                snapshot.title = title
                snapshot.save(update_fields=["title", "modified_at"])
        else:
            # Create new snapshot
            if timestamp:
                while Snapshot.objects.filter(timestamp=timestamp).exists():
                    timestamp = str(float(timestamp) + 1.0)

            create_kwargs = {
                "url": url,
                "timestamp": timestamp,
                "title": title,
                "crawl": crawl,
            }
            if bookmarked_at:
                create_kwargs["bookmarked_at"] = bookmarked_at
            if created_at:
                create_kwargs["created_at"] = created_at
            snapshot = Snapshot.objects.create(**create_kwargs)

        # Update tags
        if tag_list:
            existing_tags = set(snapshot.tags.values_list("name", flat=True))
            new_tags = set(tag_list) | existing_tags
            snapshot.save_tags(new_tags)

        # Queue for extraction and update additional fields
        update_fields = []

        if queue_for_extraction:
            if snapshot.status != Snapshot.StatusChoices.PAUSED:
                snapshot.status = Snapshot.StatusChoices.QUEUED
                update_fields.append("status")
            snapshot.retry_at = timezone.now()
            update_fields.append("retry_at")

        # Update additional fields if provided
        for field_name in ("depth", "parent_snapshot_id", "crawl_id", "bookmarked_at", "created_at", "downloaded_at"):
            value = record.get(field_name)
            if field_name in ("bookmarked_at", "created_at", "downloaded_at") and value and isinstance(value, str):
                value = parse_date(value)
            if value is not None and getattr(snapshot, field_name) != value:
                setattr(snapshot, field_name, value)
                update_fields.append(field_name)

        if update_fields:
            snapshot.save(update_fields=update_fields + ["modified_at"])

        snapshot.ensure_crawl_symlink()

        return snapshot

    def create_pending_archiveresults(self, hooks: Iterable[tuple[str, str]] | None = None) -> list["ArchiveResult"]:
        """
        Create ArchiveResult records for all enabled hooks.

        Uses the hooks system to discover available hooks from:
        - abx_plugins/plugins/*/on_Snapshot__*.{py,sh,js}
        - data/custom_plugins/*/on_Snapshot__*.{py,sh,js}

        Creates one ArchiveResult per hook (not per plugin), with hook_name set.
        This enables step-based execution where all hooks in a step can run in parallel.
        """
        if hooks is None:
            from archivebox.plugins.hooks import discover_hooks
            from archivebox.config.common import get_config

            # Compatibility path for direct model callers. The runner passes its
            # abx-dl hook inventory explicitly so queued rows match execution.
            config = get_config(crawl=self.crawl, snapshot=self)
            hooks = ((hook_path.parent.name, hook_path.stem) for hook_path in discover_hooks("Snapshot", config=config))
        archiveresults = []

        for plugin, hook_name in hooks:
            # ArchiveResult output is one filesystem directory per plugin hook, so
            # retries must update this row in place instead of creating siblings.
            archiveresult, _created = ArchiveResult.objects.get_or_create(
                snapshot=self,
                plugin=plugin,
                hook_name=hook_name,
                defaults={
                    "status": ArchiveResult.INITIAL_STATE,
                },
            )
            if archiveresult.status == ArchiveResult.INITIAL_STATE:
                archiveresults.append(archiveresult)

        return archiveresults

    def is_finished_processing(self) -> bool:
        """
        Check if all ArchiveResults are finished.

        Note: This is only called for observability/progress tracking.
        The shared runner owns execution and does not poll this.
        """
        # Check if any ARs are still pending/started
        pending = self.archiveresult_set.exclude(
            status__in=ArchiveResult.FINAL_STATES,
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

        counts = ArchiveResult.status_counts(
            results,
            (
                ArchiveResult.StatusChoices.SUCCEEDED,
                ArchiveResult.StatusChoices.FAILED,
                ArchiveResult.StatusChoices.STARTED,
                ArchiveResult.StatusChoices.SKIPPED,
                ArchiveResult.StatusChoices.NORESULTS,
            ),
        )
        succeeded = counts.get(ArchiveResult.StatusChoices.SUCCEEDED, 0)
        failed = counts.get(ArchiveResult.StatusChoices.FAILED, 0)
        running = counts.get(ArchiveResult.StatusChoices.STARTED, 0)
        skipped = counts.get(ArchiveResult.StatusChoices.SKIPPED, 0)
        noresults = counts.get(ArchiveResult.StatusChoices.NORESULTS, 0)
        total = results.count()
        pending = total - succeeded - failed - running - skipped - noresults

        # Calculate percentage (succeeded + failed + skipped + noresults as completed)
        completed = succeeded + failed + skipped + noresults
        percent = int((completed / total * 100) if total > 0 else 0)

        # Sum output sizes
        output_size = results.aggregate(total_size=Sum("output_size"))["total_size"] or 0

        # Check if sealed
        is_sealed = self.status not in (self.StatusChoices.QUEUED, self.StatusChoices.STARTED)

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "running": running,
            "pending": pending,
            "skipped": skipped,
            "noresults": noresults,
            "percent": percent,
            "output_size": output_size,
            "is_sealed": is_sealed,
        }

    def retry_failed_archiveresults(self) -> int:
        """
        Reset failed/skipped ArchiveResults to queued for retry.

        Returns count of ArchiveResults reset.
        """
        retryable_results = ArchiveResult.objects.filter(
            snapshot=self,
            status__in=[
                ArchiveResult.StatusChoices.FAILED,
                ArchiveResult.StatusChoices.SKIPPED,
                ArchiveResult.StatusChoices.NORESULTS,
            ],
        )
        legacy_result_count = retryable_results.filter(hook_name="").count()
        now = timezone.now()
        count = retryable_results.exclude(hook_name="").update(
            status=ArchiveResult.StatusChoices.QUEUED,
            output_str="",
            output_json=None,
            output_files={},
            output_size=0,
            output_mimetypes="",
            start_ts=None,
            end_ts=None,
            modified_at=now,
        )

        if count + legacy_result_count > 0:
            self.refresh_from_db(fields=["modified_at", "retry_at", "status"])
            self.queue_for_extraction(when=now)

        return count + legacy_result_count

    # =========================================================================
    # URL Helper Properties (migrated from Link schema)
    # =========================================================================

    @cached_property
    def url_hash(self) -> str:
        from hashlib import sha256

        return sha256(self.url.encode()).hexdigest()[:8]

    @cached_property
    def scheme(self) -> str:
        return self.url.split("://")[0]

    @cached_property
    def path(self) -> str:
        parts = self.url.split("://", 1)
        return "/" + parts[1].split("/", 1)[1] if len(parts) > 1 and "/" in parts[1] else "/"

    @cached_property
    def basename(self) -> str:
        return self.path.split("/")[-1]

    @cached_property
    def extension(self) -> str:
        basename = self.basename
        return basename.split(".")[-1] if "." in basename else ""

    @cached_property
    def base_url(self) -> str:
        return f"{self.scheme}://{self.domain}"

    @cached_property
    def is_static(self) -> bool:
        static_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".mp4", ".mp3", ".wav", ".webm"}
        return any(self.url.lower().endswith(ext) for ext in static_extensions)

    @cached_property
    def is_archived(self) -> bool:
        cached_is_archived = self.__dict__.get("_is_archived_cached")
        if cached_is_archived is not None:
            return bool(cached_is_archived)

        if self.downloaded_at or self.status == self.StatusChoices.SEALED:
            return True

        output_paths = (
            self.domain,
            "output.html",
            "output.pdf",
            "screenshot.png",
            "singlefile.html",
            "readability/content.html",
            "mercury/content.html",
            "htmltotext.txt",
            "media",
            "git",
        )
        output_dir = Path(self.output_dir)
        return any((output_dir / path).exists() for path in output_paths)

    # =========================================================================
    # Date/Time Properties (migrated from Link schema)
    # =========================================================================

    @cached_property
    def bookmarked_date(self) -> str | None:
        if self.bookmarked_at:
            return self._ts_to_date_str(self.bookmarked_at)
        if self.timestamp:
            return str(self.timestamp)
        return None

    @cached_property
    def downloaded_datestr(self) -> str | None:
        return self._ts_to_date_str(self.downloaded_at) if self.downloaded_at else None

    @cached_property
    def archive_dates(self) -> list[datetime]:
        return [result.start_ts for result in self.archiveresult_set.all() if result.start_ts]

    @cached_property
    def oldest_archive_date(self) -> datetime | None:
        dates = self.archive_dates
        return min(dates) if dates else None

    @cached_property
    def newest_archive_date(self) -> datetime | None:
        dates = self.archive_dates
        return max(dates) if dates else None

    @cached_property
    def num_outputs(self) -> int:
        if "num_outputs_cached" in self.__dict__:
            return int(self.__dict__["num_outputs_cached"] or 0)

        prefetched_cache = self.__dict__.get("_prefetched_objects_cache", {})
        if "archiveresult_set" in prefetched_cache:
            return sum(1 for result in self.archiveresult_set.all() if result.status == "succeeded")

        return self.archiveresult_set.filter(status="succeeded").count()

    @cached_property
    def num_failures(self) -> int:
        if "num_failures_cached" in self.__dict__:
            return int(self.__dict__["num_failures_cached"] or 0)

        prefetched_cache = self.__dict__.get("_prefetched_objects_cache", {})
        if "archiveresult_set" in prefetched_cache:
            return sum(1 for result in self.archiveresult_set.all() if result.status == "failed")

        return self.archiveresult_set.filter(status="failed").count()

    # =========================================================================
    # Output Path Methods (migrated from Link schema)
    # =========================================================================

    def latest_outputs(self, status: str | None = None) -> dict[str, Any]:
        """Get the latest output that each plugin produced"""
        from archivebox.plugins.discovery import get_plugins
        from django.db.models import Q

        latest: dict[str, Any] = {}
        for plugin in get_plugins():
            results = self.archiveresult_set.filter(plugin=plugin)
            if status is not None:
                results = results.filter(status=status)
            # Filter for results with output_files or output_str
            results = results.filter(Q(output_files__isnull=False) | ~Q(output_str="")).order_by("-start_ts")
            result = results.first()
            # Return embed_path() for backwards compatibility
            latest[plugin] = result.embed_path() if result else None
        return latest

    def discover_outputs(self, include_filesystem_fallback: bool = True) -> list[dict]:
        """Discover output files from ArchiveResults and filesystem."""
        from archivebox.misc.util import ts_to_date_str

        ArchiveResult = self.archiveresult_set.model
        snap_dir = Path(self.output_dir)
        outputs: list[dict] = []
        seen: set[str] = set()

        text_exts = (".json", ".jsonl", ".txt", ".csv", ".tsv", ".xml", ".yml", ".yaml", ".md", ".log")

        def is_metadata_path(path: str | None) -> bool:
            lower = (path or "").lower()
            return lower.endswith(text_exts)

        def is_compact_path(path: str | None) -> bool:
            lower = (path or "").lower()
            return lower.endswith(text_exts)

        hashes_index = self.hashes_index if include_filesystem_fallback else {}
        for result in self.archiveresult_set.all().order_by("start_ts"):
            output_file_map = result.output_file_map()
            embed_path = result.embed_path_db(output_file_map=output_file_map)
            if not embed_path and include_filesystem_fallback:
                embed_path = result.embed_path()
            if not embed_path or embed_path.strip() in (".", "/", "./"):
                continue
            size = (
                result.output_size
                or sum(result._coerce_output_file_size(metadata.get("size")) for metadata in output_file_map.values())
                or hashes_index.get(embed_path, {}).get("size")
                or 0
            )
            if not size and include_filesystem_fallback and not hashes_index:
                abs_path = snap_dir / embed_path
                if not abs_path.exists():
                    continue
                if abs_path.is_dir():
                    if not any(p.is_file() for p in abs_path.rglob("*")):
                        continue
                    size = sum(p.stat().st_size for p in abs_path.rglob("*") if p.is_file())
                else:
                    size = abs_path.stat().st_size
                    plugin_lower = (result.plugin or "").lower()
                    if plugin_lower in ("ytdlp", "yt-dlp", "youtube-dl"):
                        plugin_dir = snap_dir / result.plugin
                        if plugin_dir.exists():
                            try:
                                size = sum(p.stat().st_size for p in plugin_dir.rglob("*") if p.is_file())
                            except OSError:
                                pass
            outputs.append(
                {
                    "name": result.plugin,
                    "path": embed_path,
                    "ts": ts_to_date_str(result.end_ts),
                    "size": size or 0,
                    "is_metadata": is_metadata_path(embed_path),
                    "is_compact": is_compact_path(embed_path),
                    "result": result,
                },
            )
            seen.add(result.plugin)

        if hashes_index:
            grouped_hash_outputs: dict[str, dict[str, dict[str, Any]]] = {}
            ignored_roots = {"index.html", "index.json", "index.jsonl", "favicon.ico", "warc", "hashes"}
            for rel_path, meta in hashes_index.items():
                parts = Path(rel_path).parts
                if len(parts) < 2:
                    continue
                root = parts[0]
                if root.startswith(".") or root in seen or root in ignored_roots:
                    continue
                child_path = str(Path(*parts[1:]))
                grouped_hash_outputs.setdefault(root, {})[child_path] = meta

            fallback_ts = ts_to_date_str(self.downloaded_at or self.created_at)
            for root, root_entries in grouped_hash_outputs.items():
                fallback_path = ArchiveResult._fallback_output_file_path(list(root_entries.keys()), root, root_entries)
                if not fallback_path:
                    continue
                fallback_meta = root_entries.get(fallback_path, {})
                outputs.append(
                    {
                        "name": root,
                        "path": f"{root}/{fallback_path}",
                        "ts": fallback_ts,
                        "size": int(fallback_meta.get("size") or 0),
                        "is_metadata": is_metadata_path(fallback_path),
                        "is_compact": is_compact_path(fallback_path),
                        "result": None,
                    },
                )
                seen.add(root)

        if not include_filesystem_fallback or hashes_index:
            return outputs
        if not snap_dir.is_dir():
            return outputs

        embeddable_exts = {
            "html",
            "htm",
            "mhtml",
            "mht",
            "pdf",
            "txt",
            "md",
            "json",
            "jsonl",
            "csv",
            "tsv",
            "png",
            "jpg",
            "jpeg",
            "gif",
            "webp",
            "svg",
            "ico",
            "mp4",
            "webm",
            "mp3",
            "opus",
            "ogg",
            "wav",
        }

        for entry in snap_dir.iterdir():
            if entry.name in ("index.html", "index.json", "favicon.ico", "warc"):
                continue
            if entry.is_dir():
                plugin = entry.name
                if plugin in seen:
                    continue
                best_file = ArchiveResult._find_best_output_file(entry, plugin)
                if not best_file:
                    continue
                best_file_stat = best_file.stat()
                rel_path = str(best_file.relative_to(snap_dir))
                outputs.append(
                    {
                        "name": plugin,
                        "path": rel_path,
                        "ts": ts_to_date_str(best_file_stat.st_mtime or 0),
                        "size": best_file_stat.st_size or 0,
                        "is_metadata": is_metadata_path(rel_path),
                        "is_compact": is_compact_path(rel_path),
                        "result": None,
                    },
                )
                seen.add(plugin)
            elif entry.is_file():
                ext = entry.suffix.lstrip(".").lower()
                if ext not in embeddable_exts:
                    continue
                plugin = entry.stem
                if plugin in seen:
                    continue
                entry_stat = entry.stat()
                outputs.append(
                    {
                        "name": plugin,
                        "path": entry.name,
                        "ts": ts_to_date_str(entry_stat.st_mtime or 0),
                        "size": entry_stat.st_size or 0,
                        "is_metadata": is_metadata_path(entry.name),
                        "is_compact": is_compact_path(entry.name),
                        "result": None,
                    },
                )
                seen.add(plugin)

        return outputs

    # =========================================================================
    # Serialization Methods
    # =========================================================================

    def to_dict(self, extended: bool = False) -> dict[str, Any]:
        """Convert Snapshot to a dictionary (replacement for Link._asdict())"""
        from archivebox.core.routes_util import build_snapshot_url

        archive_size = self.archive_size

        result = {
            "TYPE": "core.models.Snapshot",
            "id": str(self.id),
            "crawl_id": str(self.crawl_id),
            "url": self.url,
            "timestamp": self.timestamp,
            "title": self.title,
            "tags": sorted(tag.name for tag in self.tags.all()),
            "downloaded_at": self.downloaded_at.isoformat() if self.downloaded_at else None,
            "bookmarked_at": self.bookmarked_at.isoformat() if self.bookmarked_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            "retry_at": self.retry_at.isoformat() if self.retry_at else None,
            "depth": self.depth,
            "status": self.status,
            "fs_version": self.fs_version,
            # Computed properties
            "domain": self.domain,
            "scheme": self.scheme,
            "base_url": self.base_url,
            "path": self.path,
            "basename": self.basename,
            "extension": self.extension,
            "is_static": self.is_static,
            "is_archived": self.is_archived,
            "archive_path": self.archive_path,
            "archive_url": build_snapshot_url(str(self.id), "index.html"),
            "output_dir": self.output_dir,
            "link_dir": self.output_dir,  # backwards compatibility alias
            "archive_size": archive_size,
            "output_size": archive_size,
            "bookmarked_date": self.bookmarked_date,
            "downloaded_datestr": self.downloaded_datestr,
            "num_outputs": self.num_outputs,
            "num_failures": self.num_failures,
        }
        return result

    def to_json_str(self, indent: int = 4) -> str:
        """Convert to JSON string (legacy method, use to_json() for dict)"""
        return to_json(self.to_dict(extended=True), indent=indent)

    def to_csv(self, cols: list[str] | None = None, separator: str = ",", ljust: int = 0) -> str:
        """Convert to CSV string"""
        data = self.to_dict()
        cols = cols or ["timestamp", "is_archived", "url"]
        invalid_cols = [col for col in dict.fromkeys(cols) if col not in data]
        if invalid_cols:
            supported_cols = ", ".join(sorted(data))
            raise ValueError(f"Invalid CSV field(s): {', '.join(invalid_cols)}\nSupported CSV fields: {supported_cols}")
        return separator.join(to_json(data[col], indent=None).ljust(ljust) for col in cols)

    def write_json_details(self, out_dir: Path | str | None = None) -> None:
        """Write JSON index file for this snapshot to its output directory"""
        output_dir = Path(out_dir) if out_dir is not None else self.output_dir
        path = output_dir / CONSTANTS.JSON_INDEX_FILENAME
        atomic_write(str(path), self.to_dict(extended=True))

    def write_html_details(self, out_dir: Path | str | None = None) -> None:
        """Write HTML detail page for this snapshot to its output directory"""
        from django.template.loader import render_to_string
        from archivebox.core.widgets import TagEditorWidget
        from archivebox.misc.logging_util import printable_filesize

        output_dir = Path(out_dir) if out_dir is not None else self.output_dir
        TITLE_LOADING_MSG = "Not yet archived..."

        preview_priority = [
            "singlefile",
            "screenshot",
            "wget",
            "dom",
            "pdf",
            "readability",
        ]

        outputs = self.discover_outputs(include_filesystem_fallback=True)
        loose_items, failed_items = self.get_detail_page_auxiliary_items(outputs)
        outputs_by_plugin = {out["name"]: out for out in outputs}
        output_size = sum(int(out.get("size") or 0) for out in outputs)
        is_archived = bool(outputs or self.downloaded_at or self.status == self.StatusChoices.SEALED)

        best_preview_path = "about:blank"
        best_result = {"path": "about:blank", "result": None}
        for plugin in preview_priority:
            out = outputs_by_plugin.get(plugin)
            if out and out.get("path"):
                best_preview_path = str(out["path"])
                best_result = out
                break

        if best_preview_path == "about:blank" and outputs:
            best_preview_path = str(outputs[0].get("path") or "about:blank")
            best_result = outputs[0]
        tag_widget = TagEditorWidget()
        context = {
            **self.to_dict(extended=True),
            "snapshot": self,
            "title": htmlencode(self.resolved_title or (self.base_url if is_archived else TITLE_LOADING_MSG)),
            "url_str": htmlencode(urldecode(self.base_url)),
            "archive_url": urlencode(f"warc/{self.timestamp}" or (self.domain if is_archived else "")) or "about:blank",
            "extension": self.extension or "html",
            "tags": self.tags_str() or "untagged",
            "size": printable_filesize(output_size) if output_size else "pending",
            "status": "archived" if is_archived else "not yet archived",
            "status_color": "success" if is_archived else "danger",
            "oldest_archive_date": ts_to_date_str(self.oldest_archive_date),
            "best_preview_path": best_preview_path,
            "best_result": best_result,
            "archiveresults": outputs,
            "loose_items": loose_items,
            "failed_items": failed_items,
            "related_snapshots": [],
            "related_years": [],
            "title_tags": [{"name": tag.name, "style": tag_widget._tag_style(tag.name)} for tag in self.tags.all().order_by("name")],
        }
        rendered_html = render_to_string("core/snapshot.html", context)
        atomic_write(str(output_dir / CONSTANTS.HTML_INDEX_FILENAME), rendered_html)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def get_detail_page_auxiliary_items(
        self,
        outputs: list[dict] | None = None,
        hidden_card_plugins: set[str] | None = None,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        if outputs is None:
            outputs = self.discover_outputs(include_filesystem_fallback=True)
        hidden_card_plugins = hidden_card_plugins or set()
        accounted_entries: set[str] = set()
        for output in outputs:
            output_name = str(output.get("name") or "")
            if output_name:
                accounted_entries.add(output_name)
            output_path = str(output.get("path") or "")
            if not output_path:
                continue
            parts = Path(output_path).parts
            if parts:
                accounted_entries.add(parts[0])

        ignore_names = {".DS_Store", "index.html", "index.json", "index.jsonl", "favicon.ico"}
        loose_items: list[dict[str, object]] = []
        if self.hashes_index:
            grouped: dict[str, dict[str, object]] = {}
            for rel_path, meta in self.hashes_index.items():
                parts = Path(rel_path).parts
                if not parts:
                    continue
                root = parts[0]
                if root.startswith(".") or root in ignore_names or root in accounted_entries:
                    continue
                entry = grouped.setdefault(
                    root,
                    {
                        "name": root,
                        "path": root,
                        "is_dir": len(parts) > 1 or bool(meta.get("is_dir")),
                        "size": 0,
                    },
                )
                entry["is_dir"] = bool(entry.get("is_dir")) or len(parts) > 1 or bool(meta.get("is_dir"))
                entry["size"] = int(entry.get("size") or 0) + int(meta.get("size") or 0)
            loose_items = sorted(grouped.values(), key=lambda item: str(item["name"]).lower())

        ArchiveResult = self.archiveresult_set.model
        failed_items: list[dict[str, object]] = []
        seen_failed: set[str] = set()
        for result in self.archiveresult_set.all().order_by("start_ts"):
            if result.status != ArchiveResult.StatusChoices.FAILED:
                continue
            root = str(result.plugin or "").strip()
            if not root or root in seen_failed:
                continue
            seen_failed.add(root)
            failed_items.append(
                {
                    "name": f"{get_plugin_name(root)} ({result.status})",
                    "path": root,
                    "is_dir": True,
                    "size": int(result.output_size or 0),
                },
            )

        return loose_items, failed_items

    @staticmethod
    def _ts_to_date_str(dt: datetime | None) -> str | None:
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


# =============================================================================
# Snapshot State Machine
# =============================================================================


class SnapshotMachine(BaseStateMachine):
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
    │  2. The shared abx-dl runner executes hooks and the         │
    │     projector updates ArchiveResult rows from events        │
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

    model_attr_name = "snapshot"

    # States
    queued = State(value=Snapshot.StatusChoices.QUEUED, initial=True)
    started = State(value=Snapshot.StatusChoices.STARTED)
    paused = State(value=Snapshot.StatusChoices.PAUSED)
    sealed = State(value=Snapshot.StatusChoices.SEALED, final=True)

    # Tick Event (polled by workers)
    tick = (
        queued.to(sealed, cond="has_finished_archive_results")
        | queued.to.itself(unless="can_start")
        | queued.to(started, cond="can_start")
        | started.to(sealed, cond="is_finished")
        | paused.to.itself()
    )

    # Manual event (can also be triggered by last ArchiveResult finishing)
    seal = queued.to(sealed) | started.to(sealed) | paused.to(sealed)
    pause_requested = queued.to(paused) | started.to(paused)
    resume_requested = paused.to(queued)

    snapshot: Snapshot

    def can_start(self) -> bool:
        can_start = bool(self.snapshot.url)
        return can_start

    def is_finished(self) -> bool:
        """Check if all ArchiveResults for this snapshot are finished."""
        return self.snapshot.is_finished_processing()

    def has_finished_archive_results(self) -> bool:
        """A queued snapshot with only final projected rows was interrupted after hook completion."""
        results = self.snapshot.archiveresult_set.all()
        return results.exists() and not results.exclude(status__in=ArchiveResult.FINAL_STATES).exists()

    @queued.enter
    def enter_queued(self):
        self.snapshot.update_and_requeue(
            retry_at=timezone.now(),
            status=Snapshot.StatusChoices.QUEUED,
        )

    @paused.enter
    def enter_paused(self):
        self.snapshot.update_and_requeue(
            retry_at=RETRY_AT_MAX,
            status=Snapshot.StatusChoices.PAUSED,
        )

    @started.enter
    def enter_started(self):
        """Just mark as started. The shared runner creates ArchiveResults and runs hooks."""
        owned_retry_at = self.snapshot.retry_at
        now = timezone.now()
        lease_until = now + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS)
        # The runner owns queued Snapshot startup through retry_at. Creating
        # pending ArchiveResult rows immediately before tick() can touch
        # Snapshot.modified_at, so using modified_at CAS here would reject the
        # legitimate owner. Keep the write to the scheduler columns only.
        updated = Snapshot.objects.filter(
            pk=self.snapshot.pk,
            retry_at=owned_retry_at,
            status=Snapshot.StatusChoices.QUEUED,
        ).update(
            status=Snapshot.StatusChoices.STARTED,
            retry_at=lease_until,
            modified_at=now,
        )
        if updated != 1:
            self.snapshot.refresh_from_db()
            return
        self.snapshot.status = Snapshot.StatusChoices.STARTED
        self.snapshot.retry_at = lease_until
        self.snapshot.modified_at = now

    @sealed.enter
    def enter_sealed(self):
        now = timezone.now()
        owned_retry_at = self.snapshot.retry_at
        # The runner owns this row via retry_at. Commit the final lifecycle
        # state before cleanup so late projectors can update metadata without
        # tripping a modified_at CAS while the row still looks QUEUED/STARTED.
        updated = (
            type(self.snapshot)
            .objects.filter(
                pk=self.snapshot.pk,
                retry_at=owned_retry_at,
                status__in=[
                    Snapshot.StatusChoices.QUEUED,
                    Snapshot.StatusChoices.STARTED,
                    Snapshot.StatusChoices.PAUSED,
                ],
            )
            .update(
                status=Snapshot.StatusChoices.SEALED,
                retry_at=None,
                modified_at=now,
            )
        )
        if updated != 1:
            self.snapshot.refresh_from_db()
            return

        self.snapshot.status = Snapshot.StatusChoices.SEALED
        self.snapshot.retry_at = None
        self.snapshot.modified_at = now

        # Clean up background hooks after the final state is visible in DB.
        self.snapshot.cleanup()

        # Crawl finalization is handled by the runner/CrawlService cleanup
        # phase. Sealing the parent crawl here races recursive discovery:
        # Snapshot hooks can write urls.jsonl just before this state transition,
        # and the runner still needs to enqueue those child snapshots.


class ArchiveResult(ModelWithDeleteAfter, ModelWithOutputDir, ModelWithNotes):
    class StatusChoices(models.TextChoices):
        QUEUED = "queued", "Queued"
        STARTED = "started", "Started"
        PAUSED = "paused", "Paused"
        BACKOFF = "backoff", "Waiting to retry"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"
        NORESULTS = "noresults", "No Results"

    INITIAL_STATE = StatusChoices.QUEUED
    ACTIVE_STATE = StatusChoices.STARTED
    FINAL_STATES = (
        StatusChoices.SUCCEEDED,
        StatusChoices.FAILED,
        StatusChoices.SKIPPED,
        StatusChoices.NORESULTS,
    )
    FINAL_OR_ACTIVE_STATES = (*FINAL_STATES, ACTIVE_STATE)
    delete_after_final_statuses = FINAL_STATES

    @classmethod
    def normalize_status(cls, status: str | None) -> str:
        return {
            "success": cls.StatusChoices.SUCCEEDED,
            "succeded": cls.StatusChoices.SUCCEEDED,
            "succeeded": cls.StatusChoices.SUCCEEDED,
            "failed": cls.StatusChoices.FAILED,
            "skipped": cls.StatusChoices.SKIPPED,
            "noresults": cls.StatusChoices.NORESULTS,
            "queued": cls.StatusChoices.QUEUED,
            "started": cls.StatusChoices.STARTED,
            "paused": cls.StatusChoices.PAUSED,
            "backoff": cls.StatusChoices.BACKOFF,
        }.get(str(status or "").strip().lower(), cls.StatusChoices.FAILED)

    @staticmethod
    def output_files_upload_complete(output_files: dict[str, dict[str, Any]]) -> bool:
        if not output_files:
            return False
        for metadata in output_files.values():
            upload = metadata.get("upload") if isinstance(metadata, dict) else None
            if isinstance(upload, dict) and upload.get("chunked") and not upload.get("complete"):
                return False
        return True

    @classmethod
    def get_plugin_choices(cls):
        """Get plugin choices from discovered hooks (for forms/admin)."""
        plugins = [get_plugin_name(e) for e in get_plugins()]
        return tuple((e, e) for e in plugins)

    @classmethod
    def snapshot_count_subquery(cls, *, status: str | None = None, outer_ref: str = "pk") -> QuerySet:
        """Return a scalar subquery counting ArchiveResults for one outer Snapshot.

        Use this instead of filtered join aggregates for per-row Snapshot counts:
        the scalar form lets SQLite probe the covering ``(snapshot_id, status)``
        or ``(status, snapshot_id)`` indexes once per visible Snapshot row,
        instead of joining and grouping the whole candidate Snapshot queryset.
        """
        qs = cls.objects.filter(snapshot_id=models.OuterRef(outer_ref))
        if status is not None:
            qs = qs.filter(status=status)
        return qs.order_by().values("snapshot_id").annotate(count=models.Count("*")).values("count")

    @classmethod
    def snapshot_half_count_subquery(cls, *, outer_ref: str = "snapshot_id") -> QuerySet:
        return (
            cls.objects.filter(snapshot_id=models.OuterRef(outer_ref))
            .order_by()
            .values("snapshot_id")
            .annotate(half=models.Count("*") / models.Value(2))
            .values("half")
        )

    @classmethod
    def snapshot_count_expr(cls, *, status: str | None = None, outer_ref: str = "pk"):
        return Coalesce(
            models.Subquery(cls.snapshot_count_subquery(status=status, outer_ref=outer_ref), output_field=models.IntegerField()),
            models.Value(0),
        )

    @classmethod
    def status_counts(cls, queryset: QuerySet | None = None, statuses: Iterable[str] | None = None) -> dict[str, int]:
        """Count requested statuses with separate indexed COUNT probes."""
        qs = queryset if queryset is not None else cls.objects.all()
        return {status: qs.filter(status=status).count() for status in (statuses or cls.StatusChoices.values)}

    @classmethod
    def snapshot_ids_with_majority_status(cls, status: str | Iterable[str]) -> QuerySet:
        """Return Snapshot IDs where more than half of ArchiveResults have ``status``.

        Start from ArchiveResult.status for every majority-status filter. The
        ``(status, snapshot_id)`` index keeps the plan predictable even when a
        user's collection has an unusual status distribution.
        """
        statuses = tuple(status) if not isinstance(status, str) else (status,)
        total_half = UngroupedSubquery(cls.snapshot_half_count_subquery(outer_ref="snapshot_id"), output_field=models.IntegerField())
        return (
            cls.objects.filter(status__in=statuses)
            .order_by()
            .values("snapshot_id")
            .annotate(
                matching_results=models.Count("*"),
                total_half=total_half,
            )
            .filter(matching_results__gt=models.F("total_half"))
            .values("snapshot_id")
        )

    @classmethod
    def cached_snapshot_ids_with_majority_status(cls, status: str | Iterable[str], *, timeout: int = 60) -> tuple[str, ...]:
        statuses = tuple(status) if not isinstance(status, str) else (status,)
        cache_key = f"archivebox:archiveresult:majority_status:{':'.join(sorted(statuses))}"
        cached_ids = cache.get(cache_key)
        if cached_ids is not None:
            return tuple(cached_ids)

        snapshot_ids = tuple(
            str(snapshot_id) for snapshot_id in cls.snapshot_ids_with_majority_status(statuses).values_list("snapshot_id", flat=True)
        )
        cache.set(cache_key, snapshot_ids, timeout=timeout)
        return snapshot_ids

    @classmethod
    def clear_majority_status_cache(cls) -> None:
        cache.delete_many(
            [
                *(f"archivebox:archiveresult:majority_status:{status}" for status in cls.StatusChoices.values),
                f"archivebox:archiveresult:majority_status:{':'.join(sorted((cls.StatusChoices.BACKOFF, cls.StatusChoices.QUEUED)))}",
            ],
        )

    # UUID primary key (migrated from integer in 0029)
    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    snapshot: Snapshot = models.ForeignKey(Snapshot, on_delete=models.CASCADE)  # type: ignore
    # No choices= constraint - plugin names come from plugin system and can be any string
    plugin = models.CharField(max_length=32, blank=False, null=False, db_index=True, default="")
    hook_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="Full filename of the hook that executed (e.g., on_Snapshot__50_wget.py)",
    )

    # Process FK - tracks execution details (cmd, pwd, stdout, stderr, etc.)
    # Added POST-v0.9.0, will be added in a separate migration
    process = models.OneToOneField(
        "machine.Process",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archiveresult",
        help_text="Process execution details for this archive result",
    )

    # New output fields (replacing old 'output' field)
    output_str = models.TextField(blank=True, default="", help_text="Human-readable output summary")
    output_json = models.JSONField(null=True, blank=True, default=None, help_text="Structured metadata (headers, redirects, etc.)")
    output_files = models.JSONField(default=dict, help_text="Dict of {relative_path: {metadata}}")
    output_size = models.BigIntegerField(default=0, help_text="Total bytes of all output files")
    output_mimetypes = models.CharField(max_length=512, blank=True, default="", help_text="CSV of mimetypes sorted by size")

    start_ts = models.DateTimeField(default=None, null=True, blank=True)
    end_ts = models.DateTimeField(default=None, null=True, blank=True)

    status = models.CharField(max_length=16, choices=StatusChoices.choices, default=StatusChoices.QUEUED, db_index=True)
    retry_at = models.DateTimeField(default=None, null=True, blank=True, db_index=True)
    notes = models.TextField(blank=True, null=False, default="")
    # output_dir is computed via @property from snapshot.output_dir / plugin

    snapshot_id: uuid.UUID
    process_id: uuid.UUID | None

    class Meta(
        ModelWithDeleteAfter.Meta,
        ModelWithOutputDir.Meta,
        ModelWithNotes.Meta,
    ):
        app_label = "core"
        verbose_name = "Archive Result"
        verbose_name_plural = "Archive Results Log"
        indexes = [
            models.Index(fields=["snapshot", "status"], name="archiveresult_snap_status_idx"),
            models.Index(fields=["status", "snapshot"], name="archiveresult_status_snap_idx"),
            models.Index(fields=["-start_ts", "-id"], name="archiveresult_start_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "plugin", "hook_name"], name="unique_archiveresult_per_snapshot_hook"),
        ]

    def __str__(self):
        return f"[{self.id}] {self.snapshot.url[:64]} -> {self.plugin}"

    @staticmethod
    def _format_output_line_for_display(line: str) -> str:
        raw_line = str(line or "")
        stripped = raw_line.strip()
        if not stripped or "://" in stripped or not stripped.startswith(("/", "~/")):
            return raw_line
        try:
            data_dir = CONSTANTS.DATA_DIR.expanduser().resolve(strict=False)
            rel_path = Path(stripped).expanduser().resolve(strict=False).relative_to(data_dir)
        except (OSError, ValueError):
            return raw_line
        return f"{raw_line[: len(raw_line) - len(raw_line.lstrip())]}./{rel_path}{raw_line[len(raw_line.rstrip()) :]}"

    def output_str_for_display(self) -> str:
        return "\n".join(self._format_output_line_for_display(line) for line in str(self.output_str or "").splitlines())

    def get_delete_after_config_value(self):
        snapshot = self.snapshot
        from archivebox.config.common import resolve_delete_after_config_value

        return resolve_delete_after_config_value(snapshot.config, snapshot.crawl.config)

    @classmethod
    def missing_delete_at_candidates(cls):
        return cls.objects.filter(delete_at__isnull=True).filter(
            Q(snapshot__config__has_key="DELETE_AFTER") | Q(snapshot__crawl__config__has_key="DELETE_AFTER"),
        )

    @property
    def created_by(self):
        """Convenience property to access the user who created this archive result via its snapshot's crawl."""
        return self.snapshot.crawl.created_by

    def to_json(self, *, snapshot_output_dir: Path | None = None) -> dict:
        """
        Convert ArchiveResult model instance to a JSON-serializable dict.
        """
        from archivebox.config import VERSION

        process = self.process_record
        pwd = (
            process.pwd
            if process and process.pwd
            else str((snapshot_output_dir / self.plugin) if snapshot_output_dir is not None else self.output_dir)
        )
        cmd = process.cmd if process else []
        cmd_version = process.cmd_version if process else ""

        record = {
            "type": "ArchiveResult",
            "schema_version": VERSION,
            "id": str(self.id),
            "snapshot_id": str(self.snapshot_id),
            "plugin": self.plugin,
            "hook_name": self.hook_name,
            "status": self.status,
            "output_str": self.output_str,
            "start_ts": self.start_ts.isoformat() if self.start_ts else None,
            "end_ts": self.end_ts.isoformat() if self.end_ts else None,
        }
        # Include optional fields if set
        if self.output_json:
            record["output_json"] = self.output_json
        if self.output_files:
            record["output_files"] = self.output_files
        if self.output_size:
            record["output_size"] = self.output_size
        if self.output_mimetypes:
            record["output_mimetypes"] = self.output_mimetypes
        if pwd:
            record["pwd"] = pwd
        if cmd:
            record["cmd"] = cmd
        if cmd_version:
            record["cmd_version"] = cmd_version
        if process:
            record["process_id"] = str(process.id)
        return record

    @staticmethod
    def from_json(record: dict[str, Any], overrides: dict[str, Any] | None = None):
        """
        Create/update ArchiveResult from JSON dict.

        Args:
            record: JSON dict with 'snapshot_id', 'plugin', etc.
            overrides: Optional dict of field overrides

        Returns:
            ArchiveResult instance or None
        """
        snapshot_id = record.get("snapshot_id")
        plugin = record.get("plugin")

        if not snapshot_id or not plugin:
            return None

        # Try to get existing by ID first
        result_id = record.get("id")
        if result_id:
            try:
                return ArchiveResult.objects.get(id=result_id)
            except ArchiveResult.DoesNotExist:
                pass

        # Get or create by snapshot_id + plugin + hook_name. The filesystem has a
        # single output dir for each hook, so retries update that same DB row.
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)

            result, _ = ArchiveResult.objects.get_or_create(
                snapshot=snapshot,
                plugin=plugin,
                hook_name=record.get("hook_name", ""),
                defaults={
                    "status": record.get("status", "queued"),
                    "output_str": record.get("output_str", ""),
                },
            )
            return result
        except Snapshot.DoesNotExist:
            return None

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        update_fields = kwargs.get("update_fields")
        refresh_snapshot_size = (
            is_new
            or update_fields is None
            or "output_size" in update_fields
            or "snapshot" in update_fields
            or "snapshot_id" in update_fields
        )
        old_snapshot_id = None
        old_output_size = 0
        if refresh_snapshot_size and not is_new:
            old_values = type(self).objects.filter(pk=self.pk).values("snapshot_id", "output_size").first()
            if old_values:
                old_snapshot_id = old_values["snapshot_id"]
                old_output_size = int(old_values["output_size"] or 0)

        # ArchiveResult rows are updated on every plugin event. Resolving
        # DELETE_AFTER here is deceptively expensive because the effective
        # value lives on Snapshot/Crawl config, so a save of an already-loaded
        # result can still materialize parent objects and parse config. The
        # orchestrator owns the repair pass for these rows instead: it fills
        # missing delete_at values from fresh Snapshot/Crawl config when the
        # queue is idle, outside the hook-result write hot path.
        # Skip ModelWithOutputDir.save() to avoid creating index.json in plugin directories
        # Call the Django Model.save() directly instead
        models.Model.save(self, *args, **kwargs)
        if refresh_snapshot_size:
            current_snapshot_id = self.snapshot_id
            snapshot_ids = {snapshot_id for snapshot_id in (old_snapshot_id, current_snapshot_id) if snapshot_id}
            current_output_size = int(self.output_size or 0)
            if len(snapshot_ids) > 1:
                # Moving an ArchiveResult between Snapshots is rare and cannot
                # be represented as a single delta on one parent row. Keep the
                # conservative aggregate fallback for that shape.
                transaction.on_commit(lambda: type(self).refresh_snapshot_output_sizes(snapshot_ids))
            elif current_snapshot_id:
                # Hook-result projection updates ArchiveResult rows at very
                # high frequency during indexing. Re-aggregating every sibling
                # row for the parent Snapshot on each save turns those short
                # writes into a table-scan hot path. For the common case where
                # the result stays attached to the same Snapshot, the persisted
                # parent total is exactly the old total plus this row's size
                # delta; F() keeps that update atomic with concurrent result
                # saves for other plugins on the same Snapshot.
                size_delta = current_output_size if is_new else current_output_size - old_output_size
                if size_delta:
                    transaction.on_commit(
                        lambda: Snapshot.objects.filter(pk=current_snapshot_id).update(
                            output_size=F("output_size") + size_delta,
                            modified_at=timezone.now(),
                        ),
                    )
        if is_new or update_fields is None or "status" in update_fields or "snapshot" in update_fields or "snapshot_id" in update_fields:
            transaction.on_commit(type(self).clear_majority_status_cache)

        # if is_new:
        #     from archivebox.misc.logging_util import log_worker_event
        #     log_worker_event(
        #         worker_type='DB',
        #         event='Created ArchiveResult',
        #         indent_level=3,
        #         plugin=self.plugin,
        #         metadata={
        #             'id': str(self.id),
        #             'snapshot_id': str(self.snapshot_id),
        #             'snapshot_url': str(self.snapshot.url)[:64],
        #             'status': self.status,
        #         },
        #     )

    def delete(self, *args, **kwargs):
        snapshot_id = self.snapshot_id
        deleted = super().delete(*args, **kwargs)
        if snapshot_id:
            transaction.on_commit(lambda: type(self).refresh_snapshot_output_sizes({snapshot_id}))
            transaction.on_commit(type(self).clear_majority_status_cache)
        return deleted

    @staticmethod
    def refresh_snapshot_output_sizes(snapshot_ids):
        for snapshot_id in snapshot_ids:
            total_size = ArchiveResult.objects.filter(snapshot_id=snapshot_id).aggregate(total_size=Sum("output_size"))["total_size"] or 0
            Snapshot.objects.filter(pk=snapshot_id).update(
                output_size=total_size,
                modified_at=timezone.now(),
            )

    @cached_property
    def snapshot_dir(self):
        return Path(self.snapshot.output_dir)

    @cached_property
    def url(self):
        return self.snapshot.url

    @property
    def api_url(self) -> str:
        return str(reverse_lazy("api-1:get_archiveresult", args=[self.id]))

    def get_absolute_url(self):
        return f"/{self.snapshot.archive_path}/{self.plugin}"

    def reset_for_retry(self, *, save: bool = True) -> None:
        self.status = self.StatusChoices.QUEUED
        self.retry_at = None
        self.output_str = ""
        self.output_json = None
        self.output_files = {}
        self.output_size = 0
        self.output_mimetypes = ""
        self.start_ts = None
        self.end_ts = None
        if save:
            self.save(
                update_fields=[
                    "status",
                    "retry_at",
                    "output_str",
                    "output_json",
                    "output_files",
                    "output_size",
                    "output_mimetypes",
                    "start_ts",
                    "end_ts",
                    "modified_at",
                ],
            )

    @property
    def is_paused(self) -> bool:
        return self.status == self.StatusChoices.PAUSED

    @classmethod
    def pause_queryset(cls, queryset) -> int:
        return queryset.exclude(status__in=[*cls.FINAL_STATES, cls.StatusChoices.PAUSED]).update(
            status=cls.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
            modified_at=timezone.now(),
        )

    @classmethod
    def resume_queryset(cls, queryset, *, when: datetime | None = None) -> int:
        return queryset.filter(status=cls.StatusChoices.PAUSED).update(
            status=cls.StatusChoices.QUEUED,
            retry_at=when or timezone.now(),
            modified_at=timezone.now(),
        )

    def pause(self, *, save: bool = True) -> bool:
        if self.status in self.FINAL_STATES:
            return False
        if self.is_paused:
            return False
        self.status = self.StatusChoices.PAUSED
        self.retry_at = RETRY_AT_MAX
        if save:
            self.pause_queryset(type(self).objects.filter(pk=self.pk))
            self.refresh_from_db()
        return True

    def resume(self, *, when: datetime | None = None, save: bool = True) -> bool:
        if not self.is_paused:
            return False
        self.status = self.StatusChoices.QUEUED
        self.retry_at = when or timezone.now()
        if save:
            self.resume_queryset(type(self).objects.filter(pk=self.pk), when=self.retry_at)
            self.refresh_from_db()
        return True

    @property
    def plugin_module(self) -> Any | None:
        # Hook scripts are now used instead of Python plugin modules
        # The plugin name maps to hooks in abx_plugins/plugins/{plugin}/
        return None

    @staticmethod
    def _normalize_output_files(raw_output_files: Any) -> dict[str, dict[str, Any]]:
        def _enrich_metadata(path: str, metadata: dict[str, Any]) -> dict[str, Any]:
            normalized = dict(metadata)
            if "extension" not in normalized:
                normalized["extension"] = Path(path).suffix.lower().lstrip(".")
            if "mimetype" not in normalized:
                from abx_dl.output_files import guess_mimetype

                guessed = guess_mimetype(path)
                if guessed:
                    normalized["mimetype"] = guessed
            return normalized

        if raw_output_files is None:
            return {}
        if isinstance(raw_output_files, str):
            try:
                raw_output_files = json.loads(raw_output_files)
            except json.JSONDecodeError:
                return {}
        if isinstance(raw_output_files, dict):
            normalized: dict[str, dict[str, Any]] = {}
            for path, metadata in raw_output_files.items():
                if not path:
                    continue
                metadata_dict = dict(metadata) if isinstance(metadata, dict) else {}
                metadata_dict.pop("path", None)
                normalized[str(path)] = _enrich_metadata(str(path), metadata_dict)
            return normalized
        if isinstance(raw_output_files, (list, tuple, set)):
            normalized: dict[str, dict[str, Any]] = {}
            for item in raw_output_files:
                if isinstance(item, str):
                    normalized[item] = _enrich_metadata(item, {})
                    continue
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "").strip()
                if not path:
                    continue
                normalized[path] = _enrich_metadata(
                    path,
                    {key: value for key, value in item.items() if key != "path" and value not in (None, "")},
                )
            return normalized
        return {}

    @staticmethod
    def _coerce_output_file_size(value: Any) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    def output_file_map(self) -> dict[str, dict[str, Any]]:
        return self._normalize_output_files(self.output_files)

    def output_file_paths(self) -> list[str]:
        return list(self.output_file_map().keys())

    def output_file_count(self) -> int:
        return len(self.output_file_paths())

    def output_size_from_files(self) -> int:
        return sum(self._coerce_output_file_size(metadata.get("size")) for metadata in self.output_file_map().values())

    def update_output_metadata_from_filesystem(self, snapshot_dir: Path | None = None, save: bool = True) -> bool:
        from collections import defaultdict
        from abx_dl.output_files import guess_mimetype

        if self.plugin == "title":
            return False

        snapshot_dir = Path(snapshot_dir or self.snapshot.output_dir)
        exclude_names = {"stdout.log", "stderr.log", "process.pid", "hook.pid", "listener.pid"}
        output_files: dict[str, dict[str, Any]] = {}
        mime_sizes: dict[str, int] = defaultdict(int)
        total_size = 0

        def add_file(file_path: Path, rel_path: str, *, root_relative: bool = False) -> None:
            nonlocal total_size
            try:
                if not file_path.is_file() or file_path.name in exclude_names:
                    return
                stat = file_path.stat()
            except OSError:
                return
            mime_type = guess_mimetype(file_path) or "application/octet-stream"
            metadata = {
                "extension": file_path.suffix.lower().lstrip("."),
                "mimetype": mime_type,
                "size": stat.st_size,
            }
            if root_relative:
                metadata["root_relative"] = True
            output_files[rel_path] = metadata
            mime_sizes[mime_type] += stat.st_size
            total_size += stat.st_size

        for raw_line in str(self.output_str or "").splitlines():
            raw_output = raw_line.strip().lstrip("/")
            if not raw_output or raw_output in {".", "./", "/"} or "://" in raw_output or raw_output.startswith("/"):
                continue
            if not self._looks_like_output_path(raw_output, self.plugin):
                continue

            raw_path = Path(raw_output)
            if raw_output.startswith(f"{self.plugin}/"):
                plugin_relative = raw_output.removeprefix(f"{self.plugin}/")
                add_file(snapshot_dir / raw_output, plugin_relative)
            elif len(raw_path.parts) == 1:
                add_file(snapshot_dir / self.plugin / raw_output, raw_output)
                add_file(snapshot_dir / raw_output, raw_output, root_relative=True)
            else:
                add_file(snapshot_dir / self.plugin / raw_output, raw_output)
                add_file(snapshot_dir / raw_output, raw_output, root_relative=True)

        plugin_dir = snapshot_dir / self.plugin
        if not output_files and plugin_dir.is_dir():
            for file_path in plugin_dir.rglob("*"):
                if not file_path.is_file() or ".hooks" in file_path.parts:
                    continue
                add_file(file_path, str(file_path.relative_to(plugin_dir)))

        if not output_files:
            return False

        sorted_mimes = sorted(mime_sizes.items(), key=lambda item: item[1], reverse=True)
        output_mimetypes = ",".join(mime for mime, _ in sorted_mimes)
        if self.output_files == output_files and self.output_size == total_size and self.output_mimetypes == output_mimetypes:
            return False

        self.output_files = output_files
        self.output_size = total_size
        self.output_mimetypes = output_mimetypes
        self.modified_at = timezone.now()
        if save:
            self.save(update_fields=["output_files", "output_size", "output_mimetypes", "modified_at"])
        return True

    def output_exists(self) -> bool:
        return os.path.exists(Path(self.snapshot_dir) / self.plugin)

    @staticmethod
    def _looks_like_output_path(raw_output: str | None, plugin_name: str | None = None) -> bool:
        value = str(raw_output or "").strip()
        if value in ("", ".", "./", "/"):
            return False
        if plugin_name and value.startswith(f"{plugin_name}/"):
            return True
        if Path(value).is_absolute():
            return True
        if Path(value).suffix:
            return True
        if "/" in value and "\\" not in value and " " not in value:
            left, _, right = value.partition("/")
            if left and right and all(ch.isalnum() or ch in "+-." for ch in left + right):
                return False
        return False

    def _existing_output_path(self, raw_output: str | None) -> str | None:
        value = str(raw_output or "").strip()
        if not value:
            return None

        output_path = Path(value)
        snapshot_dir = Path(self.snapshot_dir).resolve(strict=False)
        candidates: list[str] = []

        if output_path.is_absolute():
            try:
                candidates.append(str(output_path.resolve(strict=False).relative_to(snapshot_dir)))
            except (OSError, ValueError):
                return None
        elif value.startswith(f"{self.plugin}/"):
            candidates.append(value)
        elif len(output_path.parts) == 1:
            candidates.append(f"{self.plugin}/{value}")
        else:
            candidates.append(value)

        output_file_map = self.output_file_map()
        hashes_index = self.snapshot.hashes_index
        for relative_path in candidates:
            if relative_path in hashes_index:
                return relative_path

            if relative_path in output_file_map:
                return relative_path

            plugin_relative = relative_path.removeprefix(f"{self.plugin}/")
            if plugin_relative in output_file_map:
                return relative_path

            candidate = snapshot_dir / relative_path
            try:
                if candidate.is_file():
                    return relative_path
            except OSError:
                continue

        return None

    @staticmethod
    def _fallback_output_file_path(
        output_file_paths: Sequence[str],
        plugin_name: str | None = None,
        output_file_map: dict[str, dict[str, Any]] | None = None,
    ) -> str | None:
        ignored = {"stdout.log", "stderr.log", "hook.pid", "listener.pid"}
        candidates = [
            path
            for path in output_file_paths
            if Path(path).name not in ignored and Path(path).suffix.lower() not in (".pid", ".log", ".sh")
        ]
        if not candidates:
            return None

        output_file_map = output_file_map or {}
        preferred_names = [
            "index.html",
            "index.htm",
            "output.html",
            "content.html",
            "article.html",
            "snapshot.mhtml",
            "snapshot.mht",
            "output.pdf",
            "index.pdf",
            "content.txt",
            "output.txt",
            "index.txt",
            "index.md",
            "index.json",
            "article.json",
        ]
        for preferred_name in preferred_names:
            for candidate in candidates:
                if Path(candidate).name.lower() == preferred_name:
                    return candidate

        ext_groups = (
            (".html", ".htm", ".mhtml", ".mht", ".pdf"),
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"),
            (".json", ".jsonl", ".txt", ".md", ".csv", ".tsv"),
            (".mp4", ".webm", ".mp3", ".opus", ".ogg", ".wav"),
        )
        for ext_group in ext_groups:
            group_candidates = [candidate for candidate in candidates if Path(candidate).suffix.lower() in ext_group]
            if group_candidates:
                return max(
                    group_candidates,
                    key=lambda path: ArchiveResult._coerce_output_file_size(output_file_map.get(path, {}).get("size")),
                )

        return None

    @staticmethod
    def _find_best_output_file(dir_path: Path, plugin_name: str | None = None) -> Path | None:
        if not dir_path.exists() or not dir_path.is_dir():
            return None
        file_map: dict[str, dict[str, Any]] = {}
        file_count = 0
        max_scan = 500
        for file_path in dir_path.rglob("*"):
            file_count += 1
            if file_count > max_scan:
                break
            if file_path.is_dir() or file_path.name.startswith("."):
                continue
            rel_path = str(file_path.relative_to(dir_path))
            try:
                size = file_path.stat().st_size
            except OSError:
                size = 0
            file_map[rel_path] = {"size": size}

        fallback_path = ArchiveResult._fallback_output_file_path(list(file_map.keys()), plugin_name, file_map)
        if not fallback_path:
            return None
        return dir_path / fallback_path

    def embed_path_db(self, output_file_map: dict[str, dict[str, Any]] | None = None) -> str | None:
        output_file_map = output_file_map if output_file_map is not None else self.output_file_map()

        def is_root_relative(path: str) -> bool:
            metadata = output_file_map.get(path) or {}
            return bool(isinstance(metadata, dict) and metadata.get("root_relative"))

        if self.output_str:
            raw_output = str(self.output_str).strip()
            if self._looks_like_output_path(raw_output, self.plugin):
                output_path = Path(raw_output)
                if output_path.is_absolute():
                    return None

                candidates: list[str] = []
                if raw_output.startswith(f"{self.plugin}/"):
                    candidates.append(raw_output)
                elif len(output_path.parts) == 1:
                    candidates.append(f"{self.plugin}/{raw_output}")
                    candidates.append(raw_output)
                else:
                    candidates.append(raw_output)

                if not output_file_map:
                    return self._existing_output_path(raw_output)

                if raw_output in output_file_map and is_root_relative(raw_output):
                    return raw_output

                for relative_path in candidates:
                    plugin_relative = relative_path.removeprefix(f"{self.plugin}/")
                    if relative_path in output_file_map:
                        return f"{self.plugin}/{relative_path}" if not relative_path.startswith(f"{self.plugin}/") else relative_path
                    if plugin_relative in output_file_map:
                        return f"{self.plugin}/{plugin_relative}"

        output_file_paths = list(output_file_map.keys())
        if output_file_paths:
            fallback_path = self._fallback_output_file_path(output_file_paths, self.plugin, output_file_map)
            if fallback_path:
                if is_root_relative(fallback_path):
                    return fallback_path
                return f"{self.plugin}/{fallback_path}"

        return None

    def embed_path(self) -> str | None:
        """
        Get the relative path to the embeddable output file for this result.

        This is intentionally DB-backed only so snapshot/admin rendering stays
        fast and predictable without filesystem probes.
        """
        return self.embed_path_db()

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
    def process_record(self):
        if not self.process_id:
            return None
        try:
            return self.process
        except ObjectDoesNotExist:
            return None

    @property
    def pwd(self) -> str:
        """Working directory, derived from the snapshot/plugin path if the Process row is gone."""
        process = self.process_record
        return process.pwd if process and process.pwd else str(self.output_dir)

    @property
    def cmd(self) -> list:
        """Command array (from Process)."""
        process = self.process_record
        return process.cmd if process else []

    @property
    def cmd_version(self) -> str:
        """Command version (from Process.binary)."""
        process = self.process_record
        return process.cmd_version if process else ""

    @property
    def binary(self):
        """Binary FK (from Process)."""
        process = self.process_record
        return process.binary if process else None

    @property
    def iface(self):
        """Network interface FK (from Process)."""
        process = self.process_record
        return process.iface if process else None

    @property
    def machine(self):
        """Machine FK (from Process)."""
        process = self.process_record
        return process.machine if process else None

    @property
    def timeout(self) -> int:
        """Timeout in seconds (from Process)."""
        process = self.process_record
        return process.timeout if process else 120

    def save_search_index(self):
        pass

    def update_from_output(self):
        """
        Update this ArchiveResult from filesystem logs and output files.

        Used for Snapshot cleanup / orphan recovery when a hook's output exists
        on disk but the projector did not finalize the row in the database.

        Updates:
        - status, output_str, output_json from ArchiveResult JSONL record
        - output_files, output_size, output_mimetypes by walking filesystem
        - end_ts, cmd, cmd_version, binary FK
        - Processes side-effect records (Snapshot, Tag, etc.) via process_hook_records()
        """
        from collections import defaultdict
        from pathlib import Path
        from django.utils import timezone
        from abx_dl.output_files import guess_mimetype
        from archivebox.plugins.hooks import process_hook_records, extract_records_from_process
        from archivebox.machine.models import Process

        plugin_dir = Path(self.pwd) if self.pwd else None
        if not plugin_dir or not plugin_dir.exists():
            self.status = self.StatusChoices.FAILED
            self.output_str = "Output directory not found"
            self.end_ts = timezone.now()
            self.save()
            return

        records = []
        process = self.process_record
        if process:
            records = extract_records_from_process(process)

        if not records:
            stdout_file = plugin_dir / "stdout.log"
            stdout = stdout_file.read_text(errors="replace") if stdout_file.exists() else ""
            records = Process.parse_records_from_text(stdout)

        # Find ArchiveResult record and update status/output from it
        ar_records = [r for r in records if r.get("type") == "ArchiveResult"]
        if ar_records:
            hook_data = ar_records[0]

            # Update status
            status_map = {
                "succeeded": self.StatusChoices.SUCCEEDED,
                "failed": self.StatusChoices.FAILED,
                "skipped": self.StatusChoices.SKIPPED,
                "noresults": self.StatusChoices.NORESULTS,
            }
            self.status = status_map.get(hook_data.get("status", "failed"), self.StatusChoices.FAILED)

            # Update output fields
            self.output_str = hook_data.get("output_str") or hook_data.get("output") or ""
            self.output_json = hook_data.get("output_json")

            # Update cmd fields
            if hook_data.get("cmd"):
                if process:
                    process.cmd = hook_data["cmd"]
                    process.save()
                self._set_binary_from_cmd(hook_data["cmd"])
            # Note: cmd_version is derived from binary.version, not stored on Process
        else:
            # No ArchiveResult record: treat background hooks or clean exits as skipped
            is_background = False
            try:
                from archivebox.plugins.hooks import is_background_hook

                is_background = bool(self.hook_name and is_background_hook(self.hook_name))
            except Exception:
                pass

            if is_background or (process and process.exit_code == 0):
                self.status = self.StatusChoices.SKIPPED
                self.output_str = "Hook did not output ArchiveResult record"
            else:
                self.status = self.StatusChoices.FAILED
                self.output_str = "Hook did not output ArchiveResult record"

        # Walk filesystem and populate output_files, output_size, output_mimetypes
        exclude_names = {"stdout.log", "stderr.log", "process.pid", "hook.pid", "listener.pid"}
        mime_sizes = defaultdict(int)
        total_size = 0
        output_files = {}

        for file_path in plugin_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if ".hooks" in file_path.parts:
                continue
            if file_path.name in exclude_names:
                continue

            try:
                stat = file_path.stat()
                mime_type = guess_mimetype(file_path) or "application/octet-stream"

                relative_path = str(file_path.relative_to(plugin_dir))
                output_files[relative_path] = {
                    "extension": file_path.suffix.lower().lstrip("."),
                    "mimetype": mime_type,
                    "size": stat.st_size,
                }
                mime_sizes[mime_type] += stat.st_size
                total_size += stat.st_size
            except OSError:
                continue

        self.output_files = output_files
        self.output_size = total_size
        sorted_mimes = sorted(mime_sizes.items(), key=lambda x: x[1], reverse=True)
        self.output_mimetypes = ",".join(mime for mime, _ in sorted_mimes)

        # Update timestamps
        self.end_ts = timezone.now()

        self.save()

        # Process side-effect records (filter Snapshots for depth/URL)
        filtered_records = []
        for record in records:
            record_type = record.get("type")

            # Skip ArchiveResult records (already processed above)
            if record_type == "ArchiveResult":
                continue

            # Filter Snapshot records for depth/URL constraints
            if record_type == "Snapshot":
                url = record.get("url")
                if not url:
                    continue

                depth = record.get("depth", self.snapshot.depth + 1)
                if depth > self.snapshot.crawl.max_depth:
                    continue

                if not self._url_passes_filters(url):
                    continue

            filtered_records.append(record)

        # Process filtered records with unified dispatcher
        overrides = {
            "snapshot": self.snapshot,
            "crawl": self.snapshot.crawl,
            "created_by_id": self.created_by.pk,
        }
        process_hook_records(filtered_records, overrides=overrides)

        # Cleanup PID files (keep logs even if empty so they can be tailed)
        pid_file = plugin_dir / "hook.pid"
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
            machine=machine,
        ).first()

        if binary:
            process = self.process_record
            if process:
                process.binary = binary
                process.save()
            return

        # Fallback: match by binary name
        bin_name = Path(bin_path_or_name).name
        binary = Binary.objects.filter(
            name=bin_name,
            machine=machine,
        ).first()

        if binary:
            process = self.process_record
            if process:
                process.binary = binary
                process.save()

    def _url_passes_filters(self, url: str) -> bool:
        """Check if URL passes URL_ALLOWLIST and URL_DENYLIST config filters.

        Uses the centralized config resolver so frozen crawl/snapshot values
        and live Machine/Persona execution values apply in their scoped order.
        """
        return self.snapshot.crawl.url_passes_filters(url, snapshot=self.snapshot)

    @property
    def output_dir(self) -> Path:
        """Get the output directory for this plugin's results."""
        return Path(self.snapshot.output_dir) / self.plugin


# =============================================================================
# State Machine Registration
# =============================================================================

# Manually register state machines with python-statemachine registry
# (normally auto-discovered from statemachines.py, but we define them here for clarity)
registry.register(SnapshotMachine)
