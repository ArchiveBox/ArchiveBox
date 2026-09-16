from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, models, transaction
from django.db.models import F, Q, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.functional import cached_property

from archivebox.base_models.models import (
    ModelWithDeleteAfter,
    ModelWithNotes,
    ModelWithOutputDir,
)
from archivebox.config import CONSTANTS
from archivebox.plugins.discovery import (
    get_plugin_name,
    get_plugins,
)
from archivebox.uuid_compat import CompactUUIDField, uuid7

if TYPE_CHECKING:
    pass


from .querysets import UngroupedSubquery
from .snapshots import Snapshot


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

    @classmethod
    def get_or_create_by_hook(
        cls,
        snapshot: Snapshot,
        plugin: str,
        hook_name: str,
        *,
        defaults: Mapping[str, Any] | None = None,
    ) -> tuple[ArchiveResult, bool]:
        lookup = {"snapshot": snapshot, "plugin": plugin, "hook_name": hook_name}
        result = cls.objects.filter(**lookup).first()
        if result:
            return result, False
        try:
            return cls.objects.create(**lookup, **(defaults or {})), True
        except IntegrityError:
            result = cls.objects.filter(**lookup).first()
            if result is None:
                raise
            return result, False

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
        verbose_name_plural = "Archive Results"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["snapshot", "status"], name="archiveresult_snap_status_idx"),
            models.Index(fields=["status", "snapshot"], name="archiveresult_status_snap_idx"),
            models.Index(fields=["-start_ts", "-id"], name="archiveresult_start_idx"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
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

    def output_file_stats(self) -> tuple[int, int]:
        """Return file count and manifest bytes without probing the filesystem.

        Legacy manifests may be lists or JSON strings; malformed sizes do not
        hide the remaining files. The stored output_size field is independent.
        """
        files = self.output_files or {}
        if isinstance(files, str):
            try:
                files = json.loads(files)
            except (TypeError, ValueError):
                files = {}
        if not isinstance(files, (dict, list, tuple, set)):
            return 0, 0
        total_bytes = 0
        for metadata in files.values() if isinstance(files, dict) else files:
            if isinstance(metadata, dict):
                try:
                    total_bytes += int(metadata.get("size") or 0)
                except (TypeError, ValueError):
                    pass
        return len(files), total_bytes

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

        # Get or create by the durable scheduler identity. Hooks in one plugin
        # share an output directory, while retries update only their exact row.
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)

            result, _ = ArchiveResult.get_or_create_by_hook(
                snapshot,
                plugin,
                record.get("hook_name", ""),
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

    def safe_update(self, update_fields: Mapping[str, Any], *, refresh: bool = True) -> bool:
        """Compare-and-swap one loaded ArchiveResult without opening a transaction."""
        expected_modified_at = self.modified_at
        previous_output_size = int(self.output_size or 0)
        values = dict(update_fields)
        values.setdefault("modified_at", timezone.now())
        updated = type(self).objects.filter(pk=self.pk, modified_at=expected_modified_at).update(**values)
        if updated == 1:
            for field, value in values.items():
                setattr(self, field, value)
            if "output_size" in values:
                size_delta = int(values["output_size"] or 0) - previous_output_size
                if size_delta:
                    Snapshot.objects.filter(pk=self.snapshot_id).update(
                        output_size=F("output_size") + size_delta,
                        modified_at=timezone.now(),
                    )
        if refresh:
            try:
                self.refresh_from_db()
            except type(self).DoesNotExist:
                pass
        return updated == 1

    def schedule_delete_cleanup(self, *, using: str | None = None) -> None:
        """Remove shared plugin output and refresh persisted Snapshot metadata after commit."""
        snapshot_id = self.snapshot_id
        plugin = self.plugin
        paths = self.validate_output_paths_for_delete(self.output_paths_for_delete())

        def cleanup() -> None:
            results = type(self).objects.using(using) if using else type(self).objects
            if not results.filter(snapshot_id=snapshot_id, plugin=plugin).exists():
                type(self).delete_output_paths(paths)
            type(self).refresh_snapshot_output_sizes({snapshot_id})
            snapshot = Snapshot.objects.filter(pk=snapshot_id).first()
            if snapshot:
                snapshot.write_index_jsonl()

        transaction.on_commit(cleanup, using=using)

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

    @property
    def is_paused(self) -> bool:
        return self.status == self.StatusChoices.PAUSED

    @staticmethod
    def _normalize_output_files(raw_output_files: Any) -> dict[str, dict[str, Any]]:
        from abx_dl.output_files import OutputManifest

        return OutputManifest.from_value(raw_output_files).as_mapping()

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

    def update_output_metadata_from_filesystem(self, snapshot_dir: Path | None = None, save: bool = True) -> bool:
        from abx_dl.output_files import OutputManifest, output_file_from_path

        if self.plugin == "title":
            return False

        snapshot_dir = Path(snapshot_dir or self.snapshot.output_dir)
        exclude_names = {"stdout.log", "stderr.log", "process.pid", "hook.pid", "listener.pid"}
        output_files: dict[str, dict[str, Any]] = {}

        def add_file(file_path: Path, rel_path: str, *, root_relative: bool = False) -> None:
            try:
                if not file_path.is_file() or file_path.name in exclude_names:
                    return
            except OSError:
                return
            metadata = output_file_from_path(file_path, relative_to=file_path.parent).model_dump(exclude={"path"})
            if root_relative:
                metadata["root_relative"] = True
            output_files[rel_path] = metadata

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
            output_files = OutputManifest.scan(plugin_dir, containment_root=snapshot_dir).as_mapping()

        if not output_files:
            return False

        manifest = OutputManifest.from_value(output_files)
        total_size = manifest.total_size
        output_mimetypes = ",".join(manifest.mimetypes)
        if self.output_files == output_files and self.output_size == total_size and self.output_mimetypes == output_mimetypes:
            return False

        self.output_files = output_files
        self.output_size = total_size
        self.output_mimetypes = output_mimetypes
        self.modified_at = timezone.now()
        if save:
            self.save(update_fields=["output_files", "output_size", "output_mimetypes", "modified_at"])
        return True

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

        plugin_lower = (plugin_name or "").lower()
        if plugin_lower in ("ytdlp", "yt-dlp", "youtube-dl"):
            # yt-dlp commonly emits a thumbnail plus several media formats.
            # Prefer something browsers can play directly; otherwise cards can
            # select a large MKV or thumbnail that the plugin player cannot use.
            ext_groups = (
                (".mp4", ".webm", ".m4v", ".ogv"),
                (".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".flac"),
                (".mkv", ".mov", ".avi", ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".m2ts", ".mts", ".3gp", ".3g2"),
                (".html", ".htm", ".mhtml", ".mht", ".pdf"),
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"),
                (".json", ".jsonl", ".txt", ".md", ".csv", ".tsv", ".srt", ".vtt"),
            )
        else:
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

    def embed_path_db(
        self,
        output_file_map: dict[str, dict[str, Any]] | None = None,
        *,
        check_filesystem: bool = True,
    ) -> str | None:
        """Select the preview from its manifest, optionally checking legacy files.

        Live polling disables the legacy filesystem fallback so an empty manifest
        cannot turn a status request into a scan of the archive directory.
        """
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

                if not output_file_map and check_filesystem:
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
