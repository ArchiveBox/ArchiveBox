from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlparse

from django.contrib import admin
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, models
from django.db.models import Q, QuerySet, Value
from django.db.models.fields.json import KT
from django.db.models.functions import Coalesce
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe

from archivebox.base_models.models import (
    ModelWithConfig,
    ModelWithDeleteAfter,
    ModelWithHealthStats,
    ModelWithNotes,
    ModelWithOutputDir,
    get_or_create_system_user_pk,
)
from archivebox.config import CONSTANTS
from archivebox.config.common import get_config, rprint
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Binary
from archivebox.misc.system import atomic_write
from archivebox.misc.util import (
    domain as url_domain,
)
from archivebox.misc.util import (
    htmldecode,
    parse_date,
    sanitize_html_text,
    to_json,
    ts_to_date_str,
    validate_url,
)
from archivebox.plugins.discovery import (
    get_plugin_icon,
    get_plugin_name,
    get_plugins,
)
from archivebox.uuid_compat import CompactUUIDField, uuid7
from archivebox.workers.models import DefaultStatusChoices, ACTIVE_STATE_LEASE_SECONDS, RETRY_AT_MAX, ModelWithQueue

if TYPE_CHECKING:
    from archivebox.config.common import ArchiveBoxBaseConfig

    from .archiveresults import ArchiveResult


from .querysets import SnapshotManager
from .tags import SnapshotTag, Tag


class SnapshotMigrationError(RuntimeError):
    """Raised when a snapshot filesystem migration fails validation."""


class Snapshot(ModelWithDeleteAfter, ModelWithOutputDir, ModelWithConfig, ModelWithNotes, ModelWithHealthStats, ModelWithQueue):
    BROWSER_EXTENSION_UPLOAD_HOOK_NAME = "on_Snapshot__archivebox_browser_extension_upload"

    id = CompactUUIDField(primary_key=True, default=uuid7, editable=False, unique=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    # Stored as a variable-length TextField so short URLs don't reserve space and very long
    # URLs (up to MAX_URL_LENGTH chars, enforced in save()) are supported, while keeping a
    # normal index so exact, prefix, and substring lookups all stay fast.
    url = models.TextField(db_index=True)  # URLs can appear in multiple crawls
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
        db_index=True,
        help_text='Filesystem version of this snapshot (e.g., "0.7.0", "0.8.0", "0.9.4").',
    )
    retry_at = ModelWithQueue.RetryAtField(default=timezone.now)
    status = ModelWithQueue.StatusField(
        choices=ModelWithQueue.StatusChoices,
        default=ModelWithQueue.StatusChoices.QUEUED,
    )
    config = models.JSONField(default=dict, null=False, blank=False, editable=True)
    permissions = models.GeneratedField(
        expression=Coalesce(KT("config__PERMISSIONS"), Value("private"), output_field=models.CharField(max_length=16)),
        output_field=models.CharField(max_length=16, null=False),
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

    state_field_name = "status"
    retry_at_field_name = "retry_at"
    StatusChoices: ClassVar[type[DefaultStatusChoices]] = DefaultStatusChoices
    INITIAL_STATE = StatusChoices.QUEUED
    ACTIVE_STATE = StatusChoices.STARTED
    FINAL_STATES = (StatusChoices.SEALED,)
    FINAL_OR_ACTIVE_STATES = (*FINAL_STATES, ACTIVE_STATE)
    active_state = StatusChoices.STARTED
    delete_after_final_statuses = (StatusChoices.SEALED,)
    RUNNABLE_STATES = (StatusChoices.QUEUED, StatusChoices.STARTED)
    OPEN_STATES = (*RUNNABLE_STATES, StatusChoices.PAUSED)

    crawl_id: uuid.UUID
    parent_snapshot_id: uuid.UUID | None
    _prefetched_objects_cache: dict[str, Any]

    objects = SnapshotManager()
    archiveresult_set: models.Manager[ArchiveResult]

    def add_tag_ids(self, tag_ids: Iterable[int | str]) -> None:
        tag_ids = [tag_id for tag_id in dict.fromkeys(tag_ids) if tag_id]
        for tag_id in tag_ids:
            try:
                SnapshotTag(snapshot_id=self.pk, tag_id=tag_id).save(force_insert=True)
            except IntegrityError:
                # Only the unique (snapshot, tag) conflict is idempotent. Do
                # not hide foreign-key or other integrity failures.
                if SnapshotTag.objects.filter(snapshot_id=self.pk, tag_id=tag_id).exists():
                    continue
                raise

    def remove_tag_ids(self, tag_ids: Iterable[int | str]) -> int:
        tag_ids = [tag_id for tag_id in dict.fromkeys(tag_ids) if tag_id]
        if not tag_ids:
            return 0
        # QuerySet.delete() wraps even a fast through-table DELETE in atomic().
        # SnapshotTag has no delete hooks or child rows, so issue the same
        # idempotent DELETE as one autocommit statement.
        return SnapshotTag.objects.filter(snapshot_id=self.pk, tag_id__in=tag_ids)._raw_delete(SnapshotTag.objects.db)

    class Meta(
        ModelWithDeleteAfter.Meta,
        ModelWithOutputDir.Meta,
        ModelWithConfig.Meta,
        ModelWithNotes.Meta,
        ModelWithHealthStats.Meta,
        ModelWithQueue.Meta,
    ):
        app_label = "core"
        verbose_name = "Snapshot"
        verbose_name_plural = "Snapshots"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["-bookmarked_at", "-created_at"], name="snapshot_public_order_idx"),
            models.Index(fields=["crawl", "status", "modified_at"], name="snapshot_progress_idx"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
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
        )

    def schedule_plugin_run(self, plugins: Iterable[str], *, when=None) -> bool:
        """Persist one snapshot-scoped plugin request until abx-dl completes it."""
        plugin_names = sorted({name.strip() for name in plugins if name.strip()})
        if not plugin_names:
            return False
        retry_at = when or timezone.now()
        for _attempt in range(8):
            current = type(self).objects.select_related("crawl").get(pk=self.pk)
            pending_plugins = {str(name).strip() for name in (current.config or {}).get("RETRY_PLUGINS", []) if str(name).strip()}
            config = {**(current.config or {}), "RETRY_PLUGINS": sorted(pending_plugins | set(plugin_names))}
            status = current.status if current.status == self.StatusChoices.SEALED else self.StatusChoices.QUEUED
            updated = (
                type(self)
                .objects.filter(
                    pk=self.pk,
                    config=current.config,
                    status=current.status,
                    retry_at=current.retry_at,
                )
                .update(
                    config=config,
                    status=status,
                    retry_at=retry_at,
                    modified_at=timezone.now(),
                )
            )
            if updated:
                crawl = current.crawl
                break
        else:
            raise RuntimeError(f"Snapshot {self.pk} changed repeatedly while scheduling plugins")

        self.refresh_from_db()
        if status in self.RUNNABLE_STATES and self.crawl_id:
            crawl_status = crawl.StatusChoices.STARTED if crawl.status == crawl.StatusChoices.STARTED else crawl.StatusChoices.QUEUED
            crawl.update_and_requeue(status=crawl_status, retry_at=retry_at)
        return True

    def pause(self, *, save: bool = True) -> bool:
        return super().pause(save=save)

    def resume(self, *, when: datetime | None = None, save: bool = True) -> bool:
        return super().resume(when=when, save=save)

    def restore_paused_scheduler_marker(self) -> None:
        """
        Restore the indefinite scheduler marker owned by the PAUSED lifecycle.
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
        lifecycle owner.
        """
        parent_status = Crawl.objects.filter(id=self.crawl_id).values_list("status", flat=True).first()
        if parent_status == Crawl.StatusChoices.SEALED and self.status != self.StatusChoices.SEALED:
            if not self.claim_processing_lock(lock_seconds=lock_seconds):
                return False
            self.refresh_from_db()
            parent_status = Crawl.objects.filter(id=self.crawl_id).values_list("status", flat=True).first()
            if parent_status == Crawl.StatusChoices.SEALED and self.status != self.StatusChoices.SEALED:
                self.seal()
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

    def queue_output_maintenance(self) -> None:
        """Mark uploaded outputs dirty without finalizing this snapshot.

        Upload API handlers are allowed to persist files and ArchiveResult rows, but
        Snapshot save() side effects, sealing, symlink creation, and index/details
        rewrites belong to the runner. retry_at is the scheduler signal the runner
        already watches, so only bump rows that are final or otherwise invisible.
        """
        # ArchiveResult.save() updates parent snapshot health/mtime before this
        # helper runs. Re-read the scheduler columns so the short CAS update below
        # does not lose to our own earlier ArchiveResult write.
        snapshot = Snapshot.objects.only("id", "status", "retry_at", "downloaded_at", "modified_at").get(id=self.id)
        now = timezone.now()
        updates = {"modified_at": now}
        if snapshot.downloaded_at is None:
            updates["downloaded_at"] = now
        if snapshot.status == Snapshot.StatusChoices.SEALED or snapshot.retry_at is None:
            updates["retry_at"] = now
        snapshot.safe_update(updates, refresh=False)

    def finalize_completed_upload_results(self) -> int:
        from archivebox.core.models import ArchiveResult

        now = timezone.now()
        result_ids = []
        upload_results = (
            self.archiveresult_set.filter(
                status=ArchiveResult.StatusChoices.QUEUED,
                hook_name=self.BROWSER_EXTENSION_UPLOAD_HOOK_NAME,
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

    def start_processing(self) -> bool:
        """Atomically move a claimed queued Snapshot into its active lease."""
        owned_retry_at = self.retry_at
        now = timezone.now()
        lease_until = now + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS)
        updated = (
            type(self)
            .objects.filter(
                pk=self.pk,
                retry_at=owned_retry_at,
                status=self.StatusChoices.QUEUED,
            )
            .update(
                status=self.StatusChoices.STARTED,
                retry_at=lease_until,
                modified_at=now,
            )
        )
        self.refresh_from_db()
        return updated == 1

    def seal(self) -> bool:
        """Atomically finalize this Snapshot and reconcile its output metadata."""
        if self.status == self.StatusChoices.SEALED:
            return True
        now = timezone.now()
        updated = (
            type(self)
            .objects.filter(
                pk=self.pk,
                retry_at=self.retry_at,
                status__in=self.OPEN_STATES,
            )
            .update(
                status=self.StatusChoices.SEALED,
                retry_at=None,
                modified_at=now,
            )
        )
        self.refresh_from_db()
        if updated == 1:
            self.finalize_output_metadata()
        return updated == 1

    def advance_lifecycle(self) -> bool:
        """Advance one explicit lifecycle step after the runner claims this row."""
        if self.status == self.StatusChoices.PAUSED:
            return False
        if self.status == self.StatusChoices.QUEUED:
            return bool(self.url) and self.start_processing()
        # abx-dl emits SnapshotCompletedEvent after the complete hook sequence;
        # ArchiveResult projection state never drives Snapshot completion.
        return False

    def cancel(self) -> None:
        if self.status != self.StatusChoices.SEALED:
            self.seal()

    def get_delete_after_config_value(self):
        from archivebox.config.common import resolve_delete_after_config_value

        return resolve_delete_after_config_value(self.config, self.crawl.config)

    @classmethod
    def missing_delete_at_candidates(cls):
        return cls.objects.filter(delete_at__isnull=True).filter(
            Q(config__has_key="DELETE_AFTER") | Q(crawl__config__has_key="DELETE_AFTER"),
        )

    @classmethod
    def is_archivebox_internal_url(cls, url: str, *, config: Mapping[str, Any] | Any | None = None) -> bool:
        parsed = urlparse((url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False

        from archivebox.core.routes_util import (
            get_admin_host,
            get_api_host,
            get_base_host,
            get_listen_host,
            get_web_host,
            split_host_port,
        )

        if config is None:
            config = get_config()
        elif isinstance(config, Mapping):
            route_config = config

            class RouteConfig:
                BIND_ADDR = str(route_config.get("BIND_ADDR") or "")
                BASE_URL = str(route_config.get("BASE_URL") or "")
                CSRF_TRUSTED_ORIGINS = str(route_config.get("CSRF_TRUSTED_ORIGINS") or "")
                SERVER_SECURITY_MODE = str(route_config.get("SERVER_SECURITY_MODE") or "")

                @property
                def USES_SUBDOMAIN_ROUTING(self) -> bool:
                    return self.SERVER_SECURITY_MODE == "safe-subdomains-fullreplay"

            config = RouteConfig()
        host = parsed.hostname.lower().strip(".")
        port = str(parsed.port) if parsed.port else None
        protected_subdomains = {"admin", "web", "api"}
        protected_hosts: set[tuple[str, str | None]] = set()
        protected_roots: set[tuple[str, str | None]] = set()
        protected_local_roots: set[tuple[str, str | None]] = set()
        for host_value in (
            get_listen_host(config=config),
            get_base_host(config=config),
            get_admin_host(config=config),
            get_web_host(config=config),
            get_api_host(config=config),
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
                protected_local_roots.add(("archivebox.localhost", protected_port))
            elif protected_host == "archivebox.localhost":
                protected_local_roots.add((protected_host, protected_port))
            parts = protected_host.split(".", 1)
            if len(parts) == 2 and (parts[0] in protected_subdomains or parts[0].startswith("snap-")):
                protected_roots.add((parts[1], protected_port))
            else:
                protected_roots.add((protected_host, protected_port))

        for protected_host, protected_port in protected_hosts:
            if host == protected_host and (protected_port is None or port == protected_port):
                return True

        role_roots = protected_roots if config.USES_SUBDOMAIN_ROUTING else protected_local_roots
        for protected_root, protected_port in role_roots:
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

        return Binary.objects.filter(process_set__archiveresult__snapshot_id=self.id).distinct()

    def ensure_permissions_config(self, crawl_permissions: str | None = None) -> bool:
        config = dict(self.config or {})
        permission = str(config.get("PERMISSIONS") or "").strip().lower()
        from archivebox.core.permissions import PERMISSIONS_PUBLIC, PERMISSIONS_VALUES, normalize_permissions

        if permission not in PERMISSIONS_VALUES:
            if self.crawl_id and not crawl_permissions:
                crawl_permissions = Crawl.objects.filter(pk=self.crawl_id).values_list("permissions", flat=True).first()
            config["PERMISSIONS"] = normalize_permissions(
                crawl_permissions,
                default=PERMISSIONS_PUBLIC,
            )
            self.config = config
            return True
        elif config.get("PERMISSIONS") != permission:
            config["PERMISSIONS"] = permission
            self.config = config
            return True
        return False

    def validate_url_for_archiving(self, *, config: Mapping[str, Any] | Any | None = None) -> None:
        try:
            validate_url(self.url or "")
        except ValueError as err:
            raise ValidationError({"url": str(err)}) from err

        if self.is_archivebox_internal_url(self.url, config=config):
            raise ValidationError({"url": "ArchiveBox cannot archive its own admin, web, api, or snapshot URLs."})

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        validate_url_field = self._state.adding or update_fields is None or "url" in update_fields
        crawl_config_for_save = None
        crawl_permissions_for_save = None
        if self.crawl_id and validate_url_field:
            crawl_row = Crawl.objects.filter(pk=self.crawl_id).values("config", "permissions").first()
            if crawl_row:
                crawl_config_for_save = crawl_row.get("config") or {}
                crawl_permissions_for_save = crawl_row.get("permissions")

        if self.ensure_permissions_config(crawl_permissions=crawl_permissions_for_save) and update_fields is not None:
            kwargs["update_fields"] = tuple(dict.fromkeys([*update_fields, "config"]))

        if validate_url_field:
            self.validate_url_for_archiving(config=crawl_config_for_save if self.crawl_id else None)

        if not self.bookmarked_at:
            self.bookmarked_at = self.created_at or timezone.now()
        if not self.timestamp:
            self.timestamp = str(self.bookmarked_at.timestamp())

        if self._state.adding or update_fields is None or "title" in update_fields:
            self.title = self._normalize_title_candidate(self.title, snapshot_url=self.url or "") or None
        if self._state.adding or update_fields is None or "notes" in update_fields:
            self.notes = sanitize_html_text(self.notes)

        super().save(*args, **kwargs)

        from django.db import transaction

        def finish_snapshot_save():
            self.reconcile_filesystem_links()
            crawl = Crawl.objects.filter(pk=self.crawl_id).first()
            if crawl is None:
                return
            crawl_tag_names = crawl.current_tag_names()
            if crawl_tag_names:
                # Snapshots can be created by parser hook side-effect records,
                # direct ORM creates, or legacy crawl URL expansion. Crawl tags
                # are user-facing metadata on the whole import, so attach them
                # at the Snapshot.save() boundary instead of relying on every
                # caller to remember to duplicate this fanout logic.
                tags_by_name = {tag.name: tag for tag in Tag.objects.filter(name__in=crawl_tag_names)}
                missing_tags = [Tag(name=name) for name in crawl_tag_names if name not in tags_by_name]
                if missing_tags:
                    Tag.objects.bulk_create(missing_tags, ignore_conflicts=True)
                    tags_by_name = {tag.name: tag for tag in Tag.objects.filter(name__in=crawl_tag_names)}
                self.add_tag_ids([tag.pk for name in crawl_tag_names if (tag := tags_by_name.get(name))])
            # Crawl.urls remains the original submitted source. Snapshot rows
            # are the normalized work queue and discovery projection.

        # get_or_create/update_or_create wrap save() in atomic(); defer filesystem
        # work and crawl maintenance so SQLite commits before touching the disk.
        transaction.on_commit(finish_snapshot_save)

    # =========================================================================
    # Filesystem Migration Methods
    # =========================================================================

    @staticmethod
    def _fs_current_version() -> str:
        """Get current ArchiveBox filesystem layout version."""
        return "0.9.4"

    _FS_VERSION_MIGRATION_PATHS: ClassVar[dict[str, str]] = {
        "0.7.0": "0.9.0",
        "0.8.0": "0.9.0",
        "0.8.5": "0.9.0",
        "0.9.0": "0.9.4",
        "0.9.1": "0.9.4",
        "0.9.2": "0.9.4",
        "0.9.3": "0.9.4",
    }

    @property
    def fs_migration_needed(self) -> bool:
        """Check if snapshot needs filesystem migration"""
        return self.fs_version != self._fs_current_version()

    def _fs_next_version(self, version: str) -> str:
        """Get the next declared version in the filesystem migration chain."""
        return self._FS_VERSION_MIGRATION_PATHS.get(version, self._fs_current_version())

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

    def migrate_filesystem_to_current_version(self, source_dir: Path | None = None, config: ArchiveBoxBaseConfig | None = None) -> None:
        """
        Copy legacy snapshot output into the current layout and safely remove the old tree.

        The ordering is intentionally crash-safe:
        1. Copy from the legacy directory into the new directory idempotently.
        2. Verify the new directory has every old file.
        3. Convert metadata in the new directory.
        4. Remove the verified legacy source.
        5. Persist fs_version last, so an interruption remains selected by the
           indexed stale-version query and resumes naturally.

        Re-running this method also reconciles a legacy timestamp directory
        left behind when a machine stopped after the database commit but before
        the on-commit cleanup callback ran.
        """
        current = self.fs_version
        target = self._fs_current_version()
        cleanup: tuple[Path, Path] | None = None
        runtime_config = config or get_config()

        if current == target:
            current_dir = self.get_storage_path_for_version(target)
            legacy_dir = Path(source_dir) if source_dir else CONSTANTS.ARCHIVE_DIR / self.timestamp
            cleanup = self._fs_migrate_legacy_to_0_9_0(source_dir=legacy_dir, target_dir=current_dir)
            crawl_dir = self.crawl.output_dir
            old_crawl_dir = crawl_dir.with_name(str(uuid.UUID(hex=self.crawl.id.hex)))
            if old_crawl_dir.exists() and not crawl_dir.exists() and not old_crawl_dir.is_symlink():
                crawl_dir.parent.mkdir(parents=True, exist_ok=True)
                old_crawl_dir.rename(crawl_dir)
            if current_dir.exists():
                self.hydrate_archiveresult_output_metadata(snapshot_dir=current_dir)
            if cleanup:
                old_dir, new_dir = cleanup
                if not self._cleanup_old_migration_dir(old_dir, new_dir):
                    raise SnapshotMigrationError(f"Could not clean up verified migration directory: {old_dir}")
            self.reconcile_filesystem_links()
            return

        while current != target:
            next_ver = self._fs_next_version(current)
            migrations = {
                ("0.7.0", "0.9.0"): self._fs_migrate_from_0_7_0_to_0_9_0,
                ("0.8.0", "0.9.0"): self._fs_migrate_from_0_8_0_to_0_9_0,
                ("0.8.5", "0.9.0"): self._fs_migrate_from_0_8_0_to_0_9_0,
                ("0.9.0", "0.9.4"): self._fs_migrate_from_0_9_0_to_0_9_4,
                ("0.9.1", "0.9.4"): self._fs_migrate_from_0_9_0_to_0_9_4,
                ("0.9.2", "0.9.4"): self._fs_migrate_from_0_9_0_to_0_9_4,
                ("0.9.3", "0.9.4"): self._fs_migrate_from_0_9_0_to_0_9_4,
            }

            migration = migrations.get((current, next_ver))
            if migration is None:
                raise ValueError(f"No filesystem migration path from {current} to {next_ver}")
            cleanup = migration(source_dir=source_dir, config=runtime_config) or cleanup

            current = next_ver
            self.fs_version = current
            source_dir = None

        target_dir = self.get_storage_path_for_version(target)
        if target_dir.exists():
            self.hydrate_archiveresult_output_metadata(snapshot_dir=target_dir)
        if cleanup:
            old_dir, new_dir = cleanup
            if not self._cleanup_old_migration_dir(old_dir, new_dir):
                raise SnapshotMigrationError(f"Could not clean up verified migration directory: {old_dir}")

        if self.pk:
            now = timezone.now()
            type(self).objects.filter(pk=self.pk).update(fs_version=target, modified_at=now)
            self.modified_at = now
        self.reconcile_filesystem_links()

    def _fs_migrate_from_0_7_0_to_0_9_0(self, source_dir: Path | None = None, config: ArchiveBoxBaseConfig | None = None):
        return self._fs_migrate_legacy_to_0_9_0(source_dir=source_dir, config=config)

    def _fs_migrate_from_0_8_0_to_0_9_0(self, source_dir: Path | None = None, config: ArchiveBoxBaseConfig | None = None):
        return self._fs_migrate_legacy_to_0_9_0(source_dir=source_dir, config=config)

    def _fs_migrate_from_0_9_0_to_0_9_4(self, source_dir: Path | None = None, config: ArchiveBoxBaseConfig | None = None):
        runtime_config = config or get_config()
        target_dir = self.get_storage_path_for_version("0.9.4")
        cleanup = self._fs_migrate_legacy_to_0_9_0(source_dir=source_dir or self.output_dir, target_dir=target_dir, config=runtime_config)
        crawl_dir = self.crawl.output_dir
        old_crawl_dir = crawl_dir.with_name(str(uuid.UUID(hex=self.crawl.id.hex)))
        if old_crawl_dir.exists() and not crawl_dir.exists() and not old_crawl_dir.is_symlink():
            crawl_dir.parent.mkdir(parents=True, exist_ok=True)
            old_crawl_dir.rename(crawl_dir)
        return cleanup

    def hydrate_archiveresult_output_metadata(self, snapshot_dir: Path | None = None) -> int:
        """Populate missing ArchiveResult file metadata from existing outputs."""
        hydrated = 0
        for result in self.archiveresult_set.filter(output_files={}).iterator():
            hydrated += int(result.update_output_metadata_from_filesystem(snapshot_dir=snapshot_dir))
        return hydrated

    def _fs_migrate_legacy_to_0_9_0(
        self,
        source_dir: Path | None = None,
        target_dir: Path | None = None,
        config: ArchiveBoxBaseConfig | None = None,
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
            self.convert_index_json_to_jsonl(output_dir=new_dir)
            return None

        if old_dir.is_symlink():
            try:
                points_to_target = new_dir.exists() and old_dir.resolve() == new_dir.resolve()
            except OSError:
                points_to_target = False
            if not points_to_target:
                raise SnapshotMigrationError(f"Legacy output symlink does not point to the expected target: {old_dir}")
            self.convert_index_json_to_jsonl(output_dir=new_dir)
            return (old_dir, new_dir)

        if not old_dir.exists():
            if new_dir.exists():
                self.convert_index_json_to_jsonl(output_dir=new_dir)
                return None
            return None

        if not new_dir.exists():
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                old_dir.rename(new_dir)
            except OSError:
                pass
            else:
                self.convert_index_json_to_jsonl(output_dir=new_dir)
                return (old_dir, new_dir)

        def copy_file_without_overwriting(source: str, destination: str):
            destination_path = Path(destination)
            if os.path.lexists(destination_path):
                if not destination_path.is_symlink() and destination_path.is_file() and filecmp.cmp(source, destination, shallow=False):
                    return destination
                raise SnapshotMigrationError(f"Migration would overwrite a different output: {destination_path}")
            return shutil.copy2(source, destination)

        # copytree preserves unknown directories and symlinks. Remove only
        # already-copied identical symlinks so interrupted migrations can retry.
        for source in old_dir.rglob("*"):
            if not source.is_symlink():
                continue
            destination = new_dir / source.relative_to(old_dir)
            if destination.is_symlink() and destination.readlink() == source.readlink():
                destination.unlink()
            elif os.path.lexists(destination):
                raise SnapshotMigrationError(f"Migration would overwrite a different output: {destination}")

        shutil.copytree(
            old_dir,
            new_dir,
            copy_function=copy_file_without_overwriting,
            dirs_exist_ok=True,
            symlinks=True,
        )

        # Verify every source entry before the old tree is eligible for cleanup.
        for source in old_dir.rglob("*"):
            destination = new_dir / source.relative_to(old_dir)
            if source.is_symlink():
                copied = destination.is_symlink() and destination.readlink() == source.readlink()
            elif source.is_dir():
                copied = destination.is_dir() and not destination.is_symlink()
            elif source.is_file():
                copied = destination.is_file() and not destination.is_symlink() and filecmp.cmp(source, destination, shallow=False)
            else:
                raise SnapshotMigrationError(f"Migration cannot safely copy special output: {source}")
            if not copied:
                raise SnapshotMigrationError(f"Migration incomplete: {source.relative_to(old_dir)}")

        # Convert index.json to index.jsonl in the new directory.
        self.convert_index_json_to_jsonl(output_dir=new_dir)

        return (old_dir, new_dir)

    @staticmethod
    def _migration_trees_match(old_dir: Path, new_dir: Path) -> bool:
        """Verify every legacy entry exists unchanged at the destination."""
        import filecmp

        if old_dir.is_symlink():
            try:
                return new_dir.exists() and old_dir.resolve() == new_dir.resolve()
            except OSError:
                return False
        if not old_dir.exists():
            return True
        if not new_dir.is_dir() or new_dir.is_symlink():
            return False

        for source in old_dir.rglob("*"):
            destination = new_dir / source.relative_to(old_dir)
            if source.is_symlink():
                copied = destination.is_symlink() and destination.readlink() == source.readlink()
            elif source.is_dir():
                copied = destination.is_dir() and not destination.is_symlink()
            elif source.is_file():
                copied = destination.is_file() and not destination.is_symlink() and filecmp.cmp(source, destination, shallow=False)
            else:
                copied = False
            if not copied:
                return False
        return True

    def _cleanup_old_migration_dir(self, old_dir: Path, new_dir: Path) -> bool:
        """Delete the old directory after its contents are verified at the new path."""
        import logging
        import shutil

        from archivebox.config.permissions import SudoPermission

        if not self._migration_trees_match(old_dir, new_dir):
            logging.getLogger("archivebox.migration").warning(
                f"Refusing to remove unverified migration directory {old_dir}",
            )
            return False

        # Delete old directory
        if old_dir.exists() and not old_dir.is_symlink():
            try:
                # Root-launched commands retain a saved root EUID after dropping
                # privileges, which is needed for legacy trees owned by old UIDs.
                with SudoPermission(uid=0, fallback=True):
                    shutil.rmtree(old_dir)
            except OSError as e:
                logging.getLogger("archivebox.migration").warning(
                    f"Could not remove old migration directory {old_dir}: {e}",
                )
                return False

        # Older migration runs may already have left a timestamp projection.
        if old_dir.is_symlink():
            old_dir.unlink(missing_ok=True)
        return True

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
        except (TypeError, ValueError):
            return "unknown"

    def get_storage_path_for_version(self, version: str) -> Path:
        """
        Calculate storage path for specific filesystem version.
        Centralizes path logic so it's reusable.

        0.7.x/0.8.x: archive/{timestamp}
        0.9.x: archive/users/{username}/snapshots/YYYYMMDD/{domain}/{uuid}/
        """
        if version in ("0.7.0", "0.8.0", "0.8.5"):
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

    @classmethod
    def _merge_snapshots(cls, snapshots: Sequence[Snapshot]):
        """
        Merge exact duplicates.
        Keep oldest, union files + ArchiveResults.
        """
        import shutil
        from archivebox.core.models import ArchiveResult

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
                except OSError:
                    continue

            # Merge tags
            for tag in dup.tags.all():
                keeper.add_tag_ids([tag.pk])

            # Move each hook result, merging only an exact identity collision.
            for result in ArchiveResult.objects.filter(snapshot=dup):
                existing = ArchiveResult.objects.filter(
                    snapshot=keeper,
                    plugin=result.plugin,
                    hook_name=result.hook_name,
                ).first()
                if existing is None:
                    result.snapshot = keeper
                    result.save(update_fields=["snapshot", "modified_at"])
                    continue

                output_files = {**(existing.output_files or {}), **(result.output_files or {})}
                existing.output_files = output_files
                existing.output_size = max(
                    sum(
                        ArchiveResult._coerce_output_file_size(metadata.get("size"))
                        for metadata in output_files.values()
                        if isinstance(metadata, dict)
                    ),
                    existing.output_size,
                    result.output_size,
                )
                if result.modified_at >= existing.modified_at:
                    existing.status = result.status
                    existing.output_str = result.output_str
                    existing.output_json = result.output_json
                    existing.start_ts = result.start_ts
                    existing.end_ts = result.end_ts
                existing.output_mimetypes = ",".join(
                    sorted(
                        {
                            mimetype.strip()
                            for value in (existing.output_mimetypes, result.output_mimetypes)
                            for mimetype in value.split(",")
                            if mimetype.strip()
                        },
                    ),
                )
                existing.save()
                result.delete()

            # Delete
            dup.delete()

    # =========================================================================
    # Loading and Creation from Filesystem (Used by archivebox update ONLY)
    # =========================================================================

    @staticmethod
    def _read_snapshot_record(snapshot_dir: Path) -> dict:
        """Read the first JSONL snapshot, falling back to the preserved legacy JSON."""
        from archivebox.machine.models import Process

        try:
            records = Process.parse_records_from_text((snapshot_dir / CONSTANTS.JSONL_INDEX_FILENAME).read_text())
            record = next((record for record in records if record.get("type") == "Snapshot"), None)
            if record is not None:
                return record
        except OSError:
            pass
        try:
            return json.loads((snapshot_dir / CONSTANTS.JSON_INDEX_FILENAME).read_text()) or {}
        except (json.JSONDecodeError, OSError):
            return {}

    @classmethod
    def load_from_directory(cls, snapshot_dir: Path) -> Snapshot | None:
        """Find an existing snapshot for orphan detection; never create a row."""
        data = cls._read_snapshot_record(snapshot_dir)
        timestamp = cls._select_best_timestamp(data.get("timestamp"), snapshot_dir.name)
        if not timestamp:
            return None
        queryset = cls.objects.select_related("crawl__created_by")
        url = data.get("url")
        if not url:
            return queryset.filter(timestamp=timestamp).first()
        queryset = queryset.filter(url=url)
        snapshot = queryset.filter(timestamp=timestamp).first()
        if snapshot is not None:
            return snapshot
        # Truncated index timestamps may match a DB timestamp prefix. A valid legacy
        # folder name is its own identity: 1508259732 and 1508259732.0 stay distinct.
        folder_timestamp = cls._select_best_timestamp(None, snapshot_dir.name)
        if not folder_timestamp or timestamp != folder_timestamp:
            return queryset.filter(timestamp__startswith=timestamp).first()
        return None

    @classmethod
    def create_from_directory(cls, snapshot_dir: Path) -> Snapshot | None:
        """
        Create new Snapshot from orphaned directory.

        Validates timestamp, ensures uniqueness.
        Returns new UNSAVED Snapshot or None if invalid.

        ONLY used by: archivebox update (for orphan import)
        """
        data = cls._read_snapshot_record(snapshot_dir)

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

        from archivebox.core.models import ArchiveResult

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
        index_tags = set(index_data.get("tags", "").split(",")) if index_data.get("tags") else set()
        index_tags = {t.strip() for t in index_tags if t.strip()}

        db_tags = set(self.tags.values_list("name", flat=True))

        new_tags = index_tags - db_tags
        if new_tags:
            for tag_name in new_tags:
                tag, _ = Tag.get_or_create_by_name(tag_name)
                self.add_tag_ids([tag.pk])

    def _merge_archive_results_from_index(self, index_data: dict, update_existing: bool = True):
        """Merge ArchiveResults one row per hook; retries update the existing row."""
        from archivebox.core.models import ArchiveResult

        existing = {(ar.plugin, ar.hook_name): ar for ar in ArchiveResult.objects.filter(snapshot=self)}
        if update_existing:
            for archiveresult in existing.values():
                normalized_status = ArchiveResult.normalize_status(archiveresult.status)
                if archiveresult.status != normalized_status:
                    archiveresult.status = normalized_status
                    archiveresult.save(update_fields=["status", "modified_at"])

        for result_data in self._iter_index_results(index_data):
            self._create_archive_result_if_missing(result_data, existing, update_existing=update_existing)

    @staticmethod
    def _iter_index_results(data: dict):
        """Yield current result rows, then legacy history entries with their plugin."""
        yield from data.get("archive_results", [])
        history = data.get("history")
        if isinstance(history, dict):
            for plugin, results in history.items():
                if isinstance(results, list):
                    for result in results:
                        yield {**result, "plugin": result.get("plugin") or result.get("extractor") or plugin}

    def _create_archive_result_if_missing(self, result_data: dict, existing: dict, update_existing: bool = True):
        """Create ArchiveResult if not already in DB."""
        from dateutil import parser
        from django.db import transaction

        from archivebox.core.models import ArchiveResult
        from archivebox.machine.models import Machine, Process

        # Support both old 'extractor' and new 'plugin' keys for backwards compat
        plugin = (result_data.get("plugin") or result_data.get("extractor", ""))[:32]
        if not plugin:
            return

        timestamps = {}
        for field in ("start_ts", "end_ts"):
            value = None
            if result_data.get(field):
                try:
                    value = parser.parse(result_data[field])
                    if value and timezone.is_naive(value):
                        value = timezone.make_aware(value, timezone.get_current_timezone())
                except (TypeError, ValueError, OverflowError):
                    pass
            timestamps[field] = value
        start_ts, end_ts = timestamps["start_ts"], timestamps["end_ts"]

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

            values = {
                "output_str": output_str,
                "output_json": output_json,
                "output_files": output_files,
                "output_mimetypes": output_mimetypes,
                "start_ts": start_ts,
                "end_ts": end_ts,
            }
            values = {key: value for key, value in values.items() if value}
            values["status"] = status
            if "output_size" in result_data:
                values["output_size"] = output_size
            update_fields = []
            for field, value in values.items():
                if getattr(existing_result, field) != value:
                    setattr(existing_result, field, value)
                    update_fields.append(field)
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

        archive_results = list(self.archiveresult_set.select_related("process__binary").order_by("start_ts"))

        # Build canonical records before replacing the file so legacy records
        # without a corresponding DB row can be retained byte-for-byte.
        binaries_seen = set()
        processes_seen = set()
        records = [self.to_json()]
        for ar in archive_results:
            process = ar.process_record
            if process and process.binary and process.binary_id not in binaries_seen:
                binaries_seen.add(process.binary_id)
                records.append(process.binary.to_json())
            if process and process.id not in processes_seen:
                processes_seen.add(process.id)
                records.append(process.to_json())
            records.append(ar.to_json(snapshot_output_dir=output_dir))

        canonical_keys = {
            (record.get("type"), str(record.get("id"))) for record in records if record.get("type") and record.get("id") is not None
        }
        preserved_lines = []
        if index_path.exists():
            for line in index_path.read_text(encoding="utf-8").splitlines(keepends=True):
                try:
                    existing_record = json.loads(line)
                except json.JSONDecodeError:
                    preserved_lines.append(line)
                    continue
                if existing_record.get("type") == "Snapshot":
                    records[0] = {**existing_record, **records[0]}
                    continue
                key = (existing_record.get("type"), str(existing_record.get("id")))
                if existing_record.get("id") is None or key not in canonical_keys:
                    preserved_lines.append(line)

        tmp_index_path = index_path.with_name(f".{index_path.name}.tmp")
        with open(tmp_index_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(records[0]) + "\n")
            for line in preserved_lines:
                f.write(line)
                if not line.endswith("\n"):
                    f.write("\n")
            for record in records[1:]:
                f.write(json.dumps(record) + "\n")
        os.replace(tmp_index_path, index_path)

    def read_index_jsonl(self, output_dir: Path | None = None) -> dict:
        """
        Read index.jsonl and return parsed records grouped by type.

        Returns dict with keys: 'snapshot', 'archive_results', 'binaries', 'processes'
        """
        from archivebox.machine.models import Process
        from archivebox.misc.jsonl import (
            TYPE_ARCHIVERESULT,
            TYPE_BINARY,
            TYPE_BINARYREQUEST,
            TYPE_PROCESS,
            TYPE_SNAPSHOT,
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

        Reads existing index.json and creates index.jsonl while preserving the
        original JSON byte-for-byte for unknown legacy metadata.
        Returns True if conversion was performed, False if no conversion needed.
        """
        import json

        from archivebox.core.models import ArchiveResult

        output_dir = Path(output_dir) if output_dir is not None else Path(self.output_dir)
        json_path = output_dir / CONSTANTS.JSON_INDEX_FILENAME
        jsonl_path = output_dir / CONSTANTS.JSONL_INDEX_FILENAME

        # Skip if already converted or no json file exists. Keep a divergent
        # legacy JSON index intact instead of silently discarding its metadata.
        if jsonl_path.exists():
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

        for result_data in self._iter_index_results(data):
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

        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_jsonl_path = jsonl_path.with_name(f".{jsonl_path.name}.tmp")
        with open(tmp_jsonl_path, "w", encoding="utf-8") as f:
            f.write("".join(json.dumps(record) + "\n" for record in records))
        os.replace(tmp_jsonl_path, jsonl_path)

        return True

    def reconcile_with_index_json(self, output_dir: Path | None = None, update_existing_archive_results: bool = True):
        """Deprecated: use reconcile_with_index() instead."""
        return self.reconcile_with_index(output_dir=output_dir, update_existing_archive_results=update_existing_archive_results)

    # =========================================================================
    # Snapshot Utilities
    # =========================================================================

    @staticmethod
    def move_directory_to_invalid(snapshot_dir: Path):
        """
        Move invalid directory to data/invalid/YYYYMMDD/.

        Used by: archivebox update (when encountering invalid directories)
        """
        import shutil

        invalid_dir = CONSTANTS.DATA_DIR / "invalid" / datetime.now(UTC).strftime("%Y%m%d")
        invalid_dir.mkdir(parents=True, exist_ok=True)

        dest = invalid_dir / snapshot_dir.name
        counter = 1
        while dest.exists():
            dest = invalid_dir / f"{snapshot_dir.name}_{counter}"
            counter += 1

        try:
            shutil.move(str(snapshot_dir), str(dest))
        except OSError:
            return

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
    def tags_str(self) -> str | None:
        if "_tags_str_cached" in self.__dict__:
            return self.__dict__["_tags_str_cached"]
        return ",".join(sorted(tag.name for tag in self.tags.all()))

    def icons(self, path: str | None = None, prefix: str = "/", quote_paths: bool = False) -> str:
        """Generate HTML icons showing which extractor plugins have succeeded for this snapshot"""
        from urllib.parse import quote

        from django.utils.html import format_html

        compact_icons = self.__dict__.get("_icons_compact", False)

        def calc_icons():
            if compact_icons and self.status == self.StatusChoices.STARTED:
                from archivebox.core.widgets import render_snapshot_progress

                return render_snapshot_progress(
                    self.__dict__.get("_icons_progress_stats") or self.get_progress_stats(),
                    successful_plugins=self.__dict__.get("_icons_archive_results") or (),
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
            output_template = '<a href="{}{}/{}" class="exists-{}" title="{}">{}</a>'

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
                if not embed_path or str(embed_path).strip() in (".", "/", "./"):
                    continue
                output_path = Path(str(embed_path))
                if (
                    quote_paths
                    and not compact_icons
                    and (output_path.is_absolute() or ".." in output_path.parts or not (Path(self.output_dir) / output_path).exists())
                ):
                    continue
                if quote_paths:
                    embed_path = quote(str(embed_path), safe="/@-._~!$&'()*+,;=")
                output += format_html(
                    output_template,
                    prefix,
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

        return calc_icons()

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
        decoded_candidate = htmldecode(candidate)
        title = htmldecode(sanitize_html_text(decoded_candidate))
        title = " ".join(line.strip() for line in title.splitlines() if line.strip()).strip()
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
        from archivebox.core.models import ArchiveResult

        stored_title = self._normalize_title_candidate(self.title, snapshot_url=self.url)
        if stored_title:
            return stored_title

        loaded_results = self.__dict__.get("_admin_archiveresults")
        if loaded_results is None:
            title_results = (
                self.archiveresult_set.filter(
                    plugin="title",
                    status=ArchiveResult.StatusChoices.SUCCEEDED,
                )
                .exclude(output_str="")
                .order_by("-start_ts", "-end_ts", "-created_at")
                .only("output_str")
            )
        else:
            title_results = reversed(
                [
                    result
                    for result in loaded_results
                    if result.plugin == "title" and result.status == ArchiveResult.StatusChoices.SUCCEEDED and result.output_str
                ],
            )
        for title_result in title_results:
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
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
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

    def remove_legacy_archive_symlink(self) -> None:
        """Remove a stale archive/<timestamp> compatibility projection."""
        legacy_path = CONSTANTS.ARCHIVE_DIR / self.timestamp
        current_path = self.get_storage_path_for_version(self._fs_current_version())
        if not legacy_path.is_symlink() or not current_path.exists():
            return

        try:
            points_to_current_path = legacy_path.resolve(strict=True) == current_path.resolve(strict=True)
        except OSError:
            points_to_current_path = False

        if points_to_current_path:
            legacy_path.unlink(missing_ok=True)

    def reconcile_filesystem_links(self) -> None:
        """Repair filesystem projections after a save or migration."""
        self.remove_legacy_archive_symlink()
        self.ensure_crawl_symlink()

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
        except ValueError:
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
        except ValueError:
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

    def save_tags(self, tags: Iterable[str] = (), *, created_by: Any = None) -> None:
        tag_ids = {Tag.get_or_create_by_name(tag, created_by=created_by)[0].pk for tag in tags if tag.strip()}
        existing_tag_ids = set(SnapshotTag.objects.filter(snapshot_id=self.pk).values_list("tag_id", flat=True))
        self.remove_tag_ids(existing_tag_ids - tag_ids)
        self.add_tag_ids(tag_ids - existing_tag_ids)

    def finalize_output_metadata(self) -> None:
        """
        Clean up background ArchiveResult hooks and empty results.

        Called after entering the sealed state.
        Reconcile late background outputs and hydrate result metadata.
        """
        # Clean up .pid files from output directory.
        output_dir = Path(self.output_dir)
        output_dir_exists = output_dir.exists()
        if output_dir_exists:
            for pid_file in output_dir.glob("**/*.pid"):
                pid_file.unlink(missing_ok=True)

            # Reconcile late background output without re-running hook-record
            # dispatch. The abx-dl event projector is the sole status owner.
            for ar in self.archiveresult_set.filter(hook_name__contains=".bg."):
                ar.update_output_metadata_from_filesystem(snapshot_dir=output_dir)
        else:
            return

        self.hydrate_archiveresult_output_metadata(snapshot_dir=output_dir)

        # Keep empty historical rows. ArchiveResults for the same plugin share
        # one output directory, so deleting any row can remove another row's
        # files, including log-only and otherwise unrecognized outputs.

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
                    if field_name in ("bookmarked_at", "retry_at", "created_at", "modified_at") and value and isinstance(value, str):
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
                from archivebox.config import CONSTANTS
                from archivebox.crawls.models import Crawl

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

        # Parser hooks emit child Snapshot records through this generic
        # dispatcher after crawling an internal import root. Those child rows
        # must inherit crawl-level tags just like direct Crawl.urls snapshots;
        # otherwise `archivebox add --tag ... < bookmarks.html` loses the tag
        # unless the parser format also happened to provide its own tags.
        tags_raw = record.get("tags", "")
        tag_list = list(crawl.current_tag_names()) if crawl else []
        if isinstance(tags_raw, list):
            tag_list.extend(tag.strip() for tag in tags_raw if tag.strip())
        elif tags_raw:
            tag_list.extend(tag.strip() for tag in re.split(config.TAG_SEPARATOR_PATTERN, tags_raw) if tag.strip())
        tag_list = list(dict.fromkeys(tag_list))

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

    def get_progress_stats(self, *, results: Iterable[ArchiveResult] | None = None, expected_total: int = 0) -> dict:
        """Summarize observed hooks, including expected hooks not yet projected.

        Callers with prefetched display rows can supply them to avoid queries;
        those rows use the snapshot's materialized output_size. Otherwise the
        result queryset supplies counts and total bytes.
        """
        from collections import Counter
        from django.db.models import Sum
        from archivebox.core.models import ArchiveResult

        status_fields = {"succeeded": "succeeded", "failed": "failed", "running": "started", "skipped": "skipped", "noresults": "noresults"}
        if results is None:
            queryset = self.archiveresult_set.all()
            counts = ArchiveResult.status_counts(queryset, status_fields.values())
            observed_total = queryset.count()
            output_size = queryset.aggregate(total_size=Sum("output_size"))["total_size"] or 0
        else:
            counts = Counter(result.status for result in results)
            observed_total = sum(counts.values())
            output_size = self.output_size or 0
        stats = {field: counts.get(status, 0) for field, status in status_fields.items()}
        total = max(observed_total, expected_total)
        completed = sum(stats[field] for field in ("succeeded", "failed", "skipped", "noresults"))
        return {
            **stats,
            "total": total,
            "pending": max(total - completed - stats["running"], 0),
            "percent": int(completed / total * 100) if total else 0,
            "output_size": output_size,
            "is_sealed": self.status not in self.OPEN_STATES,
        }

    def retry_failed_archiveresults(self) -> int:
        """Queue the parent Snapshot to rerun plugins with failed facts."""
        from archivebox.core.models import ArchiveResult

        plugins = list(
            self.archiveresult_set.filter(status=ArchiveResult.StatusChoices.FAILED)
            .exclude(plugin="")
            .order_by("plugin")
            .values_list("plugin", flat=True)
            .distinct(),
        )
        if not plugins:
            return 0
        self.schedule_plugin_run(plugins)
        return len(plugins)

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

    def discover_outputs(
        self,
        include_filesystem_fallback: bool = True,
        archive_results: list[ArchiveResult] | None = None,
    ) -> list[dict]:
        """Discover output files from ArchiveResults and filesystem."""
        from archivebox.misc.util import ts_to_date_str

        ArchiveResult = self.archiveresult_set.model
        snap_dir = Path(self.output_dir)
        outputs: list[dict] = []
        seen: set[str] = set()

        text_exts = (".json", ".jsonl", ".txt", ".csv", ".tsv", ".xml", ".yml", ".yaml", ".md", ".log")

        def append_output(name, path, ts, size, result=None):
            is_metadata = path.lower().endswith(text_exts)
            outputs.append(
                {
                    "name": name,
                    "path": path,
                    "ts": ts,
                    "size": size,
                    "is_metadata": is_metadata,
                    "is_compact": is_metadata,
                    "result": result,
                },
            )
            seen.add(name)

        hashes_index = self.hashes_index if include_filesystem_fallback else {}
        results = archive_results if archive_results is not None else self.archiveresult_set.all().order_by("start_ts")
        for result in results:
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
            append_output(result.plugin, embed_path, ts_to_date_str(result.end_ts), size or 0, result)

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
                if not fallback_path or not (snap_dir / root / fallback_path).exists():
                    continue
                fallback_meta = root_entries.get(fallback_path, {})
                append_output(root, f"{root}/{fallback_path}", fallback_ts, int(fallback_meta.get("size") or 0), None)

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
                output_file = ArchiveResult._find_best_output_file(entry, plugin)
                if not output_file:
                    continue
            elif entry.is_file() and entry.suffix.lstrip(".").lower() in embeddable_exts:
                plugin = entry.stem
                if plugin in seen:
                    continue
                output_file = entry
            else:
                continue
            output_stat = output_file.stat()
            append_output(
                plugin,
                str(output_file.relative_to(snap_dir)),
                ts_to_date_str(output_stat.st_mtime or 0),
                output_stat.st_size or 0,
            )

        return outputs

    # =========================================================================
    # Serialization Methods
    # =========================================================================

    @property
    def static_archive_path(self) -> str:
        """Snapshot output path relative to the data root, for portable exports."""
        try:
            return Path(self.output_dir).relative_to(CONSTANTS.DATA_DIR).as_posix()
        except ValueError:
            return Path(self.output_dir).as_posix()

    def to_dict(self, extended: bool = False, static_export: bool = False) -> dict[str, Any]:
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
            "archive_path": self.static_archive_path if static_export else self.archive_path,
            "archive_url": f"./{self.static_archive_path}/index.html" if static_export else build_snapshot_url(str(self.id), "index.html"),
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
        atomic_write(str(path), self.to_dict(extended=True, static_export=True))

    def get_html_details_context(self, request=None, *, static_export_dir: Path | None = None) -> dict[str, Any]:
        """Build the one context used by both served and on-disk snapshot pages."""
        from archivebox.config.common import get_request_config
        from archivebox.core.models import ArchiveResult
        from archivebox.core.permissions import get_snapshot_permissions
        from archivebox.core.widgets import TagEditorWidget
        from archivebox.misc.logging_util import printable_filesize
        from archivebox.progressmonitor.views import progress_endpoint

        runtime_config = get_request_config(request) if request is not None else get_config()
        self._runtime_config = runtime_config
        snapshot_permissions = get_snapshot_permissions(self)
        archive_results = list(self.archiveresult_set.all().order_by("start_ts"))
        tags = list(self.tags.all())
        self.__dict__["_admin_archiveresults"] = archive_results
        self.__dict__["_tags_str_cached"] = ",".join(sorted(tag.name for tag in tags))
        self.__dict__["num_outputs_cached"] = sum(result.status == ArchiveResult.StatusChoices.SUCCEEDED for result in archive_results)
        self.__dict__["num_failures_cached"] = sum(result.status == ArchiveResult.StatusChoices.FAILED for result in archive_results)

        hidden_card_plugins = {"archivedotorg", "favicon", "title"}
        outputs = [
            output
            for output in self.discover_outputs(include_filesystem_fallback=True, archive_results=archive_results)
            if (output.get("size") or 0) > 0 and output.get("name") not in hidden_card_plugins
        ]
        if static_export_dir is not None:

            def static_output_exists(output: dict[str, Any]) -> bool:
                raw_path = str(output.get("path") or "")
                if not raw_path:
                    return False
                output_path = Path(raw_path)
                return not output_path.is_absolute() and ".." not in output_path.parts and (static_export_dir / output_path).exists()

            outputs = [output for output in outputs if static_output_exists(output)]
        outputs_by_name: dict[str, dict[str, Any]] = {}
        result_ids_by_name: dict[str, list[str]] = {}
        for output in outputs:
            if output.get("result"):
                result_ids_by_name.setdefault(output["name"], []).append(str(output["result"].id))
            current = outputs_by_name.get(output["name"])
            if current is None or (output.get("size") or 0) > (current.get("size") or 0):
                outputs_by_name[output["name"]] = output
        for name, output in outputs_by_name.items():
            output["result_ids"] = ",".join(result_ids_by_name.get(name, ()))

        hash_index = self.hashes_index
        loose_items, failed_items = self.get_detail_page_auxiliary_items(
            outputs,
            hidden_card_plugins=hidden_card_plugins,
            archive_results=archive_results,
        )
        preview_priority = ("singlefile", "screenshot", "wget", "dom", "pdf", "readability")
        output_order = {result_type: index for index, result_type in enumerate(outputs_by_name)}
        ordered_outputs = sorted(
            outputs_by_name.values(),
            key=lambda output: (
                preview_priority.index(output["name"]) if output["name"] in preview_priority else len(preview_priority),
                output_order.get(output["name"], len(output_order)),
            ),
        )
        best_result = {"path": "about:blank", "result": None}
        for result_type in preview_priority:
            if result_type in outputs_by_name:
                best_result = outputs_by_name[result_type]
                break
        if best_result["path"] == "about:blank" and ordered_outputs:
            best_result = ordered_outputs[0]

        non_compact_outputs = [output for output in ordered_outputs if not output.get("is_compact") and not output.get("is_metadata")]
        compact_outputs = [output for output in ordered_outputs if output.get("is_compact") or output.get("is_metadata")]
        archive_dates = [result.start_ts for result in archive_results if result.start_ts]
        output_size = sum(int(output.get("size") or 0) for output in ordered_outputs)
        has_outputs = bool(ordered_outputs)
        is_archived = has_outputs or self.status == self.StatusChoices.SEALED
        snapshot_status = str(self.status or "").lower()
        status_label_by_state = {
            "queued": ("queued", "info"),
            "started": ("running", "warning"),
            "paused": ("paused", "default"),
            "sealed": ("archived", "success"),
        }
        if has_outputs:
            status_label, status_color = ("archived", "success") if is_archived else ("partial", "warning")
        else:
            status_label, status_color = status_label_by_state.get(snapshot_status, ("not yet archived", "danger"))

        related_snapshots = list(
            type(self)
            .objects.filter(url=self.url)
            .exclude(id=self.id)
            .only("id", "url", "bookmarked_at", "created_at", "downloaded_at", "output_size")
            .order_by("-bookmarked_at", "-created_at", "-timestamp")[:25],
        )
        related_years_map: dict[int, list[Snapshot]] = {}
        for snapshot in [self, *related_snapshots]:
            snapshot_date = snapshot.bookmarked_at or snapshot.created_at or snapshot.downloaded_at
            if snapshot_date:
                related_years_map.setdefault(snapshot_date.year, []).append(snapshot)
        related_years = []
        for year, snapshots in related_years_map.items():
            snapshots.sort(
                key=lambda snapshot: snapshot.bookmarked_at or snapshot.created_at or snapshot.downloaded_at or timezone.now(),
                reverse=True,
            )
            related_years.append({"year": year, "latest": snapshots[0], "snapshots": snapshots})
        related_years.sort(key=lambda item: item["year"], reverse=True)

        warc_path = next(
            (rel_path for rel_path in hash_index if rel_path.startswith("warc/") and ".warc" in Path(rel_path).name),
            "warc/",
        )
        user = getattr(request, "user", None)
        can_delete_outputs = bool(
            static_export_dir is None
            and request is not None
            and (
                (user and user.is_authenticated and user.is_active and user.is_superuser)
                or request.COOKIES.get("archivebox_admin_logged_in") == "1"
            ),
        )
        tag_widget = TagEditorWidget()
        return {
            "id": str(self.id),
            "snapshot_id": str(self.id),
            "progress_endpoint": progress_endpoint("snapshot", self.id) if request is not None else "",
            "progress_auto_expand": snapshot_status in {"queued", "started", "paused"},
            "url": self.url,
            "archive_path": self.archive_path_from_db,
            "title": htmldecode(self.resolved_title or (self.base_url if is_archived else "Not yet archived...")),
            "extension": self.extension or "html",
            "tags": self.tags_str() or "untagged",
            "size": printable_filesize(output_size) if output_size else "—",
            "status": status_label,
            "status_color": status_color,
            "snapshot_state": snapshot_status,
            "has_outputs": has_outputs,
            "snapshot_permissions": snapshot_permissions,
            "snapshot_permissions_icon": {"public": "👥", "unlisted": "🔗", "private": "🔒"}.get(snapshot_permissions, "👥"),
            "bookmarked_date": self.bookmarked_date,
            "downloaded_datestr": self.downloaded_datestr,
            "num_outputs": self.num_outputs,
            "num_failures": self.num_failures,
            "oldest_archive_date": ts_to_date_str(min(archive_dates) if archive_dates else None),
            "warc_path": warc_path,
            "archiveresults": [*non_compact_outputs, *compact_outputs],
            "best_result": best_result,
            "snapshot": self,
            "CONFIG": runtime_config,
            "related_snapshots": related_snapshots,
            "related_years": related_years,
            "loose_items": loose_items,
            "failed_items": failed_items,
            "can_delete_outputs": can_delete_outputs,
            "title_tags": [{"name": tag.name, "style": tag_widget._tag_style(tag.name)} for tag in sorted(tags, key=lambda tag: tag.name)],
            "STATIC_EXPORT": static_export_dir is not None,
            "STATIC_EXPORT_DIR": static_export_dir,
        }

    def write_html_details(self, out_dir: Path | str | None = None) -> None:
        """Write the unified snapshot detail page with portable filesystem URLs."""
        from django.template.loader import render_to_string

        output_dir = Path(out_dir) if out_dir is not None else self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        context = self.get_html_details_context(static_export_dir=output_dir)
        rendered_html = render_to_string("core/snapshot.html", context)
        atomic_write(str(output_dir / CONSTANTS.HTML_INDEX_FILENAME), rendered_html)

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def get_detail_page_auxiliary_items(
        self,
        outputs: list[dict] | None = None,
        hidden_card_plugins: set[str] | None = None,
        archive_results: list[ArchiveResult] | None = None,
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
        results = archive_results if archive_results is not None else self.archiveresult_set.all().order_by("start_ts")
        for result in results:
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
