from __future__ import annotations

import asyncio
import inspect
import os
import sys
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import ArchiveResultEvent, ProcessStartedEvent
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

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_get_or_create"):
        result, _created = ArchiveResult.get_or_create_by_hook(
            snapshot,
            event.plugin,
            event.hook_name,
            defaults=defaults,
        )

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.diff_fields"):
        update_fields = []
        for field, value in defaults.items():
            if result.__dict__[field] != value:
                setattr(result, field, value)
                update_fields.append(field)
    if update_fields:
        with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_update"):
            result.save(update_fields=[*update_fields, "modified_at"])

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
    """Project a running abx-dl hook after its OS process is persisted."""
    from archivebox.core.models import ArchiveResult, Snapshot

    started_at = parse_event_datetime(event.start_ts)
    if started_at is None:
        raise ValueError("ProcessStartedEvent.start_ts is required")
    snapshot = Snapshot.objects.filter(id=snapshot_id).first()
    if snapshot is None:
        return
    result, _created = ArchiveResult.get_or_create_by_hook(
        snapshot,
        event.plugin_name,
        event.hook_name,
        defaults={
            "status": ArchiveResult.StatusChoices.STARTED,
            "start_ts": started_at,
            "end_ts": None,
            "process_id": process_id,
        },
    )
    if result.start_ts is not None and started_at <= result.start_ts:
        return
    result.status = ArchiveResult.StatusChoices.STARTED
    result.start_ts = started_at
    result.end_ts = None
    result.process_id = process_id
    result.save(update_fields=["status", "start_ts", "end_ts", "process_id", "modified_at"])


class ArchiveResultService(BaseService):
    """Project abx-dl ArchiveResult facts into Django models."""

    LISTENS_TO = [ArchiveResultEvent]
    EMITS = []

    def __init__(self, bus):
        self._save_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        super().__init__(bus)
        self.bus.on(ArchiveResultEvent, self.on_ArchiveResultEvent__save_to_db)

    @_perf_trace("archivebox.ArchiveResultService.on_ArchiveResultEvent__save_to_db")
    async def on_ArchiveResultEvent__save_to_db(self, event: ArchiveResultEvent) -> None:
        with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.find_process_started"):
            process_started = await self.bus.find(
                ProcessStartedEvent,
                past=True,
                future=False,
                where=lambda candidate: self.bus.event_is_child_of(event, candidate),
            )

        key = (str(event.snapshot_id), event.plugin, event.hook_name)
        lock = self._save_locks.setdefault(key, asyncio.Lock())
        async with lock:
            await sync_to_async(_save_archiveresult_event_to_db, thread_sensitive=True)(event, process_started)
