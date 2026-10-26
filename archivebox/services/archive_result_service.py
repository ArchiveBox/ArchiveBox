from __future__ import annotations

import asyncio
import inspect
import os
import sys
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any
from weakref import WeakValueDictionary

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import ArchiveResultEvent, ProcessCompletedEvent, ProcessStartedEvent
from abx_dl.output_files import OutputManifest
from abx_dl.services.base import BaseService

from .process_service import parse_event_datetime

if TYPE_CHECKING:
    from archivebox.core.models import Snapshot


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


def _resolve_output_metadata(raw_output_files: Any) -> tuple[dict[str, dict], int, str]:
    # Persist the manifest emitted by abx-dl. An empty report must stay empty:
    # the plugin directory also contains other hooks' and earlier runs' files,
    # so scanning it here would invent outputs the hook did not report.
    return _manifest_metadata(OutputManifest.from_value(raw_output_files))


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
    # The shipped hook already reports the extracted title. Project that fact
    # without waiting for a second read through remote archive storage (or
    # accidentally reading a later attempt's file). Older records may report
    # only the artifact filename; keep their existing saved-file fallback.
    reported_title = _normalize_snapshot_title(output_str, snapshot_url=snapshot_url)
    if reported_title and reported_title != title_file.name:
        return reported_title
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
    process_started: ProcessStartedEvent | ProcessCompletedEvent | None,
) -> Snapshot | None:
    """Project one ArchiveResultEvent with a single thread-sensitive ORM hop.

    Django's async ORM still delegates each query to sync Django work. The hot
    search/index maintenance path was paying that handoff separately for
    Snapshot lookup, Process lookup, ArchiveResult lookup, and update.
    Keep the public ArchiveResultEvent path intact, but run the DB
    projection as one short synchronous block so SQLite sees the same indexed
    reads/writes without per-query asyncio/threadpool churn. Return the loaded
    snapshot for subsequent output reads outside the shared DB executor.
    """
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.snapshot_lookup"):
        snapshot = Snapshot.objects.filter(id=event.snapshot_id).select_related("crawl", "crawl__created_by").first()
    if snapshot is None:
        return

    if event.status == "cancelled":
        # User cancellation supplies no new capture outcome: preserve prior
        # final results and every saved byte. It does end the interrupted
        # attempt, however; retaining STARTED here would leave a running card
        # under a sealed snapshot after Ctrl+C -> skip/abort. Retry starts the
        # same row again through ProcessStarted, without a persisted pause.
        if process_started is not None:
            started_at = parse_event_datetime(process_started.start_ts)
            if started_at is None:
                raise ValueError("ProcessStartedEvent.start_ts is required")
            # Match the actual attempt, not just the plugin: a late cancellation
            # from an earlier hook must not stop its newer retry's projection.
            snapshot.archiveresult_set.filter(
                plugin=event.plugin,
                hook_name=event.hook_name,
                status=ArchiveResult.StatusChoices.STARTED,
                start_ts=started_at,
            ).update(
                status=ArchiveResult.StatusChoices.SKIPPED,
                end_ts=parse_event_datetime(event.end_ts) or timezone.now(),
                modified_at=timezone.now(),
            )
        return

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.resolve_output_metadata"):
        output_files, output_size, output_mimetypes = _resolve_output_metadata(event.output_files)

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
            "output_str": event.output_str or event.error,
            "output_json": event.output_json,
            "output_files": output_files,
            "output_size": output_size,
            "output_mimetypes": output_mimetypes,
            "start_ts": start_ts or timezone.now(),
            "end_ts": end_ts,
            "notes": event.error or "",
        }
        if process is not None:
            defaults["process_id"] = process.id

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_get_or_create"):
        result, _created = ArchiveResult.get_or_create_by_hook(
            snapshot,
            event.plugin,
            event.hook_name,
            defaults=defaults,
        )

    with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.diff_fields"):
        update_fields = []
        # This runner already loaded the Snapshot/Crawl for the event. Resolve
        # retention here without extra parent reads so new results do not wait
        # for the bounded legacy-repair sweep to traverse historical rows.
        result.snapshot = snapshot
        if result.set_delete_at_from_config():
            update_fields.append("delete_at")
        for field, value in defaults.items():
            if result.__dict__[field] != value:
                setattr(result, field, value)
                update_fields.append(field)
    if update_fields:
        with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_update"):
            result.save(update_fields=[*update_fields, "modified_at"])

    if result.status in (ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.NORESULTS):
        return snapshot
    return None


def _read_archiveresult_outputs(
    snapshot: Snapshot,
    event: ArchiveResultEvent,
    process_started: ProcessStartedEvent | ProcessCompletedEvent | None,
) -> tuple[str, bool]:
    # Discovery already rejects roots at max_depth. Do not stat every hook's
    # archive directory when this capture cannot admit any discovered children.
    can_discover = snapshot.depth < snapshot.crawl.max_depth
    if event.plugin != "title" and not can_discover:
        return "", False
    plugin_dir = (
        Path(process_started.output_dir)
        if process_started is not None and process_started.output_dir
        else Path(snapshot.output_dir) / event.plugin
    )
    title_output_str = (event.output_str or event.error) if event.status == "succeeded" else ""
    title = _extract_snapshot_title(str(plugin_dir.parent), event.plugin, title_output_str, snapshot_url=snapshot.url)
    return title, can_discover and (plugin_dir / "urls.jsonl").exists()


def _save_snapshot_title(snapshot_id: str, next_title: str) -> None:
    from archivebox.core.models import Snapshot

    snapshot = Snapshot.objects.filter(pk=snapshot_id).first()
    if snapshot and _should_update_snapshot_title(snapshot.title or "", next_title, snapshot_url=snapshot.url):
        snapshot.title = next_title
        snapshot.save(update_fields=["title", "modified_at"])


def mark_archiveresult_started(event: ProcessStartedEvent, *, snapshot_id: str, process_id: str) -> None:
    """Project a running abx-dl hook after its OS process is persisted.

    This DB state records process execution; the scheduler separately waits for
    stdout readiness before advancing past a background hook. Neither boundary
    proves that an archive was produced. Final status comes from the owning
    hook's ArchiveResultEvent, including corrections after an abnormal exit.
    Rows are per snapshot/plugin/hook: a recorder's start hook cannot declare
    that its separate export hook succeeded.
    """
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
        # A crawl can project hundreds of thousands of hook results. Completed
        # keys must not retain one lock forever; holders and waiters keep their
        # local strong reference until projection ends, preserving serialization.
        self._save_locks: WeakValueDictionary[tuple[str, str, str], asyncio.Lock] = WeakValueDictionary()
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
            if process_started is None:
                # Preparation can fail before spawn. The completed event still
                # identifies its durable failed attempt, without inventing a PID.
                process_started = await self.bus.find(
                    ProcessCompletedEvent,
                    past=True,
                    future=False,
                    where=lambda candidate: self.bus.event_is_child_of(event, candidate),
                )

        key = (str(event.snapshot_id), event.plugin, event.hook_name)
        lock = self._save_locks.setdefault(key, asyncio.Lock())
        async with lock:
            snapshot = await sync_to_async(_save_archiveresult_event_to_db, thread_sensitive=True)(event, process_started)
            if snapshot is None:
                return
            # Archive storage may block on remote reads. Keep title/URL discovery
            # outside Django's shared executor so one hook cannot prevent other
            # hooks from persisting their result before the event deadline.
            title, has_urls = await asyncio.to_thread(_read_archiveresult_outputs, snapshot, event, process_started)
            if title:
                await sync_to_async(_save_snapshot_title, thread_sensitive=True)(str(snapshot.id), title)
            if has_urls:
                from .snapshot_service import aproject_discovered_snapshots

                # Keep discovery at the same durable result boundary: later
                # parsers can still enrich URLs discovered by earlier hooks.
                await aproject_discovered_snapshots(str(snapshot.id))
