from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import signal
import sys
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.utils import timezone

from abx_dl.events import PROCESS_EXIT_SKIPPED, ArchiveResultEvent, ProcessCompletedEvent, ProcessStartedEvent, SnapshotEvent
from abx_dl.output_files import OutputManifest
from abx_dl.services.base import BaseService

from .process_service import parse_event_datetime


def _perf_trace(label):
    def decorator(func):
        if inspect.iscoroutinefunction(func):

            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                if os.environ.get("ARCHIVEBOX_PERF_TRACE") != "1":
                    return await func(*args, **kwargs)
                started_at = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    elapsed_ms = (time.perf_counter() - started_at) * 1000
                    print(f"PERF_TRACE label={label} ms={elapsed_ms:.3f}", file=sys.stderr, flush=True)

            return async_wrapper

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if os.environ.get("ARCHIVEBOX_PERF_TRACE") != "1":
                return func(*args, **kwargs)
            started_at = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                print(f"PERF_TRACE label={label} ms={elapsed_ms:.3f}", file=sys.stderr, flush=True)

        return sync_wrapper

    return decorator


@contextmanager
def _perf_span(label: str):
    if os.environ.get("ARCHIVEBOX_PERF_TRACE") != "1":
        yield
        return
    started_at = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        print(f"PERF_TRACE label={label} ms={elapsed_ms:.3f}", file=sys.stderr, flush=True)


def _manifest_metadata(manifest: OutputManifest) -> tuple[dict[str, dict], int, str]:
    return manifest.as_mapping(), manifest.total_size, ",".join(manifest.mimetypes)


def _resolve_output_metadata(raw_output_files: Any, plugin_dir: Path) -> tuple[dict[str, dict], int, str]:
    manifest = OutputManifest.from_value(raw_output_files)
    if manifest.files and any(output_file.size for output_file in manifest.files):
        return _manifest_metadata(manifest)
    return _manifest_metadata(OutputManifest.scan(plugin_dir, containment_root=plugin_dir.parent))


def _normalize_status(status: str) -> str:
    if status == "noresult":
        return "noresults"
    return status or "failed"


def _snapshot_hook_order(hook_name: str) -> int:
    match = re.match(r"^on_Snapshot__(\d+)", hook_name or "")
    return int(match.group(1)) if match else -1


def _normalize_snapshot_title(candidate: str, *, snapshot_url: str) -> str:
    title = " ".join(line.strip() for line in str(candidate or "").splitlines() if line.strip()).strip()
    if not title:
        return ""
    if title.lower() in {"pending...", "no title found"}:
        return ""
    if title == snapshot_url:
        return ""
    if "/" in title and title.lower().endswith(".txt"):
        return ""
    return title


def _extract_snapshot_title(snapshot_output_dir: str, plugin: str, output_str: str, *, snapshot_url: str) -> str:
    if plugin != "title":
        return ""

    title_file = Path(snapshot_output_dir) / "title" / "title.txt"
    if title_file.exists():
        try:
            file_title = _normalize_snapshot_title(title_file.read_text(encoding="utf-8"), snapshot_url=snapshot_url)
        except OSError:
            file_title = ""
        if file_title:
            return file_title

    return _normalize_snapshot_title(output_str, snapshot_url=snapshot_url)


def _should_update_snapshot_title(current_title: str, next_title: str, *, snapshot_url: str) -> bool:
    current = (current_title or "").strip()
    if not current or current.lower() == "pending..." or current == snapshot_url:
        return True
    return len(next_title) > len(current)


def _status_for_process_without_archive_result(event: ProcessCompletedEvent) -> str:
    if event.exit_code == PROCESS_EXIT_SKIPPED:
        return "skipped"
    if event.exit_code in {128 + signal.SIGHUP, 128 + signal.SIGINT, 128 + signal.SIGTERM}:
        # This fallback only runs when a snapshot hook exited before emitting a
        # structured ArchiveResult. A polite shutdown signal means the runner
        # was interrupted during ownership transfer, not that the extractor
        # produced a durable negative result. Keep the hook queued so the next
        # runner can retry the exact work item instead of sealing in a transient
        # process-lifecycle failure.
        return "queued"
    if event.exit_code != 0:
        return "failed"
    return "noresults"


def _iter_archiveresult_records(stdout: str) -> list[dict]:
    records: list[dict] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") == "ArchiveResult":
            records.append(record)
    return records


@_perf_trace("archivebox.ArchiveResultService._save_archiveresult_event_sync")
def _save_archiveresult_event_to_db(
    event: ArchiveResultEvent,
    process_started: ProcessStartedEvent | None,
) -> None:
    """Project one ArchiveResultEvent with a single thread-sensitive ORM hop.

    Django's async ORM still delegates each query to sync Django work. The hot
    search/index maintenance path was paying that handoff separately for
    Snapshot lookup, Process lookup, ArchiveResult lookup, update, and title
    checks. Keep the public ArchiveResultEvent path intact, but run the DB
    projection as one short synchronous block so SQLite sees the same indexed
    reads/writes without per-query asyncio/threadpool churn.
    """
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.snapshot_lookup"):
        snapshot = Snapshot.objects.filter(id=event.snapshot_id).select_related("crawl", "crawl__created_by").first()
    if snapshot is None:
        return

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.plugin_dir"):
        plugin_dir = (
            Path(process_started.output_dir)
            if process_started is not None and process_started.output_dir
            else Path(snapshot.output_dir) / event.plugin
        )
    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.resolve_output_metadata"):
        output_files, output_size, output_mimetypes = _resolve_output_metadata(event.output_files, plugin_dir)

    process = None
    if process_started is not None:
        with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.process_lookup"):
            started_at = parse_event_datetime(process_started.start_ts)
            if started_at is None:
                raise ValueError("ProcessStartedEvent.start_ts is required")
            process_query = Process.objects.filter(
                pwd=process_started.output_dir,
                cmd=[process_started.hook_path, *process_started.hook_args],
                started_at=started_at,
            )
            if process_started.pid:
                process_query = process_query.filter(pid=process_started.pid)
            process = process_query.order_by("-modified_at").first()

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.prepare_defaults"):
        start_ts = parse_event_datetime(event.start_ts)
        end_ts = parse_event_datetime(event.end_ts) or timezone.now()
        defaults = {
            "hook_name": event.hook_name,
            "status": _normalize_status(event.status),
            "output_str": event.output_str,
            "output_json": event.output_json,
            "output_files": output_files,
            "output_size": output_size,
            "output_mimetypes": output_mimetypes,
            "start_ts": start_ts or timezone.now(),
            "end_ts": end_ts,
        }
        if process is not None:
            defaults["process_id"] = process.id
        if event.error:
            defaults["notes"] = event.error

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_lookup"):
        result = ArchiveResult.objects.filter(
            snapshot=snapshot,
            plugin=event.plugin,
        ).first()
    if result is None:
        try:
            with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_create"):
                result = ArchiveResult.objects.create(
                    snapshot=snapshot,
                    plugin=event.plugin,
                    **defaults,
                )
        except IntegrityError:
            with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_get_after_integrity"):
                result = ArchiveResult.objects.get(
                    snapshot=snapshot,
                    plugin=event.plugin,
                )

    if result.output_files:
        merged_output_files = {**result.output_files, **defaults["output_files"]}
        defaults["output_files"], defaults["output_size"], defaults["output_mimetypes"] = _manifest_metadata(
            OutputManifest.from_value(merged_output_files),
        )
        defaults["output_size"] = max(defaults["output_size"], int(result.output_size or 0))
        defaults["output_mimetypes"] = ",".join(
            dict.fromkeys(
                mimetype.strip()
                for value in (defaults["output_mimetypes"], result.output_mimetypes)
                for mimetype in value.split(",")
                if mimetype.strip()
            ),
        )
    if result.start_ts and defaults["start_ts"]:
        defaults["start_ts"] = min(result.start_ts, defaults["start_ts"])
    if result.end_ts and defaults["end_ts"]:
        defaults["end_ts"] = max(result.end_ts, defaults["end_ts"])
    if _snapshot_hook_order(result.hook_name) > _snapshot_hook_order(event.hook_name):
        for field in ("hook_name", "status", "output_str", "output_json", "process_id", "notes"):
            if field in result.__dict__:
                defaults[field] = result.__dict__[field]

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.diff_fields"):
        update_fields = []
        for field, value in defaults.items():
            if result.__dict__[field] != value:
                setattr(result, field, value)
                update_fields.append(field)
    if update_fields:
        with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_update"):
            result.save(update_fields=[*update_fields, "modified_at"])

    if result.status == ArchiveResult.StatusChoices.QUEUED:
        # ArchiveResult has no retry_at column. If a shutdown/takeover projects
        # a killed hook back to QUEUED, wake the parent Snapshot/Crawl so the
        # next runner retries that exact hook instead of waiting on a stale
        # active-state lease.
        snapshot.update_and_requeue(retry_at=timezone.now())

    if result.status in (ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.NORESULTS):
        with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.title_update"):
            title_output_str = result.output_str if result.status == ArchiveResult.StatusChoices.SUCCEEDED else ""
            next_title = _extract_snapshot_title(str(plugin_dir.parent), event.plugin, title_output_str, snapshot_url=snapshot.url)
            if next_title and _should_update_snapshot_title(snapshot.title or "", next_title, snapshot_url=snapshot.url):
                snapshot.title = next_title
                snapshot.save(update_fields=["title", "modified_at"])

    # Parser output becomes durable when its ArchiveResult reaches a final
    # state. Project at that same lifecycle boundary so every completed parser
    # can enrich an already-discovered URL before Snapshot/Crawl completion.
    # create_discovered_snapshots() owns cross-parser dedupe and metadata merge.
    if (
        result.status in (ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.NORESULTS)
        and (plugin_dir / "urls.jsonl").exists()
    ):
        from .snapshot_service import project_discovered_snapshots

        with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.project_discovered_snapshots"):
            project_discovered_snapshots(str(snapshot.id))


def mark_archiveresult_started(event: ProcessStartedEvent, *, snapshot_id: str, process_id: str) -> None:
    """Advance an existing queued plugin row after its OS process is persisted."""
    from archivebox.core.models import ArchiveResult

    started_at = parse_event_datetime(event.start_ts)
    if started_at is None:
        raise ValueError("ProcessStartedEvent.start_ts is required")
    ArchiveResult.objects.filter(
        snapshot_id=snapshot_id,
        plugin=event.plugin_name,
        status=ArchiveResult.StatusChoices.QUEUED,
    ).update(
        hook_name=event.hook_name,
        status=ArchiveResult.StatusChoices.STARTED,
        start_ts=started_at,
        end_ts=None,
        process_id=process_id,
        modified_at=timezone.now(),
    )


class ArchiveResultService(BaseService):
    LISTENS_TO = [ArchiveResultEvent, ProcessCompletedEvent]
    EMITS = []

    def __init__(self, bus):
        self._completed_process_event_ids: set[str] = set()
        self._save_locks: dict[tuple[str, str], asyncio.Lock] = {}
        super().__init__(bus)
        self.bus.on(ArchiveResultEvent, self.on_ArchiveResultEvent__save_to_db)
        self.bus.on(ProcessCompletedEvent, self.on_ProcessCompletedEvent__save_to_db)

    @_perf_trace("archivebox.ArchiveResultService.on_ArchiveResultEvent__save_to_db")
    async def on_ArchiveResultEvent__save_to_db(self, event: ArchiveResultEvent) -> None:
        with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.find_process_started"):
            process_started = await self.bus.find(
                ProcessStartedEvent,
                past=True,
                future=False,
                where=lambda candidate: self.bus.event_is_child_of(event, candidate),
            )

        key = (str(event.snapshot_id), event.plugin)
        lock = self._save_locks.setdefault(key, asyncio.Lock())
        async with lock:
            await sync_to_async(_save_archiveresult_event_to_db, thread_sensitive=True)(event, process_started)

    @_perf_trace("archivebox.ArchiveResultService.on_ProcessCompletedEvent__save_to_db")
    async def on_ProcessCompletedEvent__save_to_db(self, event: ProcessCompletedEvent) -> None:
        if event.event_id in self._completed_process_event_ids:
            return
        self._completed_process_event_ids.add(event.event_id)

        if not event.hook_name.startswith("on_Snapshot"):
            return
        with _perf_span("archivebox.ArchiveResultService.on_ProcessCompletedEvent.find_snapshot_event"):
            snapshot_event = await self.bus.find(
                SnapshotEvent,
                past=True,
                future=False,
                where=lambda candidate: self.bus.event_is_child_of(event, candidate),
            )
        if snapshot_event is None:
            return

        with _perf_span("archivebox.ArchiveResultService.on_ProcessCompletedEvent.parse_stdout_records"):
            records = _iter_archiveresult_records(event.stdout)
        if records:
            if len(records) > 1:
                raise RuntimeError(
                    f"Hook {event.plugin_name}:{event.hook_name} emitted {len(records)} ArchiveResult records; expected exactly one",
                )
            for record in records:
                record_status = _normalize_status(record.get("status") or "")
                record_failed = record_status == "failed" or (not record_status and event.exit_code not in (0, PROCESS_EXIT_SKIPPED))
                with _perf_span("archivebox.ArchiveResultService.on_ProcessCompletedEvent.emit_archive_result_record"):
                    await event.emit(
                        ArchiveResultEvent(
                            snapshot_id=record.get("snapshot_id") or snapshot_event.snapshot_id,
                            plugin=record.get("plugin") or event.plugin_name,
                            hook_name=record.get("hook_name") or event.hook_name,
                            status=record_status,
                            output_str=record.get("output_str") or "",
                            output_json=record.get("output_json") if isinstance(record.get("output_json"), dict) else None,
                            output_files=event.output_files,
                            start_ts=event.start_ts,
                            end_ts=event.end_ts,
                            error=record.get("error") or (event.stderr if record_failed else ""),
                        ),
                    ).now()
            return

        process_failed = _status_for_process_without_archive_result(event) == "failed"
        with _perf_span("archivebox.ArchiveResultService.on_ProcessCompletedEvent.emit_archive_result_fallback"):
            await event.emit(
                ArchiveResultEvent(
                    snapshot_id=snapshot_event.snapshot_id,
                    plugin=event.plugin_name,
                    hook_name=event.hook_name,
                    status=_status_for_process_without_archive_result(event),
                    output_str=event.stderr if process_failed else "",
                    output_files=event.output_files,
                    start_ts=event.start_ts,
                    end_ts=event.end_ts,
                    error=event.stderr if process_failed else "",
                ),
            ).now()
