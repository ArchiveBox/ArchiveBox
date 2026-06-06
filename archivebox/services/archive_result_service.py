from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from collections.abc import Iterable
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.utils import timezone

from abx_dl.events import PROCESS_EXIT_SKIPPED, ArchiveResultEvent, ProcessCompletedEvent, ProcessStartedEvent, SnapshotEvent
from abx_dl.output_files import guess_mimetype
from abx_dl.services.base import BaseService

from .process_service import parse_event_datetime


def _perf_trace(label):
    def decorator(func):
        if asyncio.iscoroutinefunction(func):

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


@runtime_checkable
class ModelDumpable(Protocol):
    def model_dump(self) -> dict[str, Any]: ...


def _collect_output_metadata(plugin_dir: Path) -> tuple[dict[str, dict], int, str]:
    exclude_names = {"stdout.log", "stderr.log", "process.pid", "hook.pid", "listener.pid"}
    output_files: dict[str, dict] = {}
    mime_sizes: dict[str, int] = defaultdict(int)
    total_size = 0

    if not plugin_dir.exists():
        return output_files, total_size, ""

    for file_path in plugin_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if ".hooks" in file_path.parts:
            continue
        if file_path.name in exclude_names:
            continue
        try:
            stat = file_path.stat()
        except OSError:
            continue
        mime_type = guess_mimetype(file_path) or "application/octet-stream"
        relative_path = str(file_path.relative_to(plugin_dir))
        output_files[relative_path] = {
            "extension": file_path.suffix.lower().lstrip("."),
            "mimetype": mime_type,
            "size": stat.st_size,
        }
        mime_sizes[mime_type] += stat.st_size
        total_size += stat.st_size

    output_mimetypes = ",".join(mime for mime, _size in sorted(mime_sizes.items(), key=lambda item: item[1], reverse=True))
    return output_files, total_size, output_mimetypes


def _coerce_output_file_size(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _normalize_output_files(raw_output_files: Any) -> dict[str, dict]:
    def _enrich_metadata(path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(metadata)
        if "extension" not in normalized:
            normalized["extension"] = Path(path).suffix.lower().lstrip(".")
        if "mimetype" not in normalized:
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
        normalized: dict[str, dict] = {}
        for path, metadata in raw_output_files.items():
            if not path:
                continue
            metadata_dict = dict(metadata) if isinstance(metadata, dict) else {}
            metadata_dict.pop("path", None)
            normalized[str(path)] = _enrich_metadata(str(path), metadata_dict)
        return normalized

    if not isinstance(raw_output_files, Iterable):
        return {}

    normalized: dict[str, dict] = {}
    for item in raw_output_files:
        if isinstance(item, str):
            normalized[item] = _enrich_metadata(item, {})
            continue
        if isinstance(item, ModelDumpable):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        normalized[path] = _enrich_metadata(path, {key: value for key, value in item.items() if key != "path" and value not in (None, "")})

    return normalized


def _has_structured_output_metadata(output_files: dict[str, dict]) -> bool:
    return any(any(key in metadata for key in ("extension", "mimetype", "size")) for metadata in output_files.values())


def _summarize_output_files(output_files: dict[str, dict]) -> tuple[int, str]:
    mime_sizes: dict[str, int] = defaultdict(int)
    total_size = 0

    for metadata in output_files.values():
        if not isinstance(metadata, dict):
            continue
        size = _coerce_output_file_size(metadata.get("size"))
        mimetype = str(metadata.get("mimetype") or "").strip()
        total_size += size
        if mimetype and size:
            mime_sizes[mimetype] += size

    output_mimetypes = ",".join(mime for mime, _size in sorted(mime_sizes.items(), key=lambda item: item[1], reverse=True))
    return total_size, output_mimetypes


def _resolve_output_metadata(raw_output_files: Any, plugin_dir: Path) -> tuple[dict[str, dict], int, str]:
    normalized_output_files = _normalize_output_files(raw_output_files)
    if normalized_output_files and _has_structured_output_metadata(normalized_output_files):
        output_size, output_mimetypes = _summarize_output_files(normalized_output_files)
        return normalized_output_files, output_size, output_mimetypes
    return _collect_output_metadata(plugin_dir)


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


def _has_content_files(output_files: Any) -> bool:
    return any(Path(path).suffix not in {".log", ".pid", ".sh"} for path in _normalize_output_files(output_files))


def _is_signal_interrupted_exit(exit_code: int) -> bool:
    return exit_code < 0 or (exit_code >= 128 and exit_code != PROCESS_EXIT_SKIPPED)


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
            hook_name=event.hook_name,
        ).first()
    if result is None:
        try:
            with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_create"):
                result = ArchiveResult.objects.create(
                    snapshot=snapshot,
                    plugin=event.plugin,
                    hook_name=event.hook_name,
                    **defaults,
                )
        except IntegrityError:
            with _perf_span("archivebox.ArchiveResultService.on_ArchiveResultEvent.result_get_after_integrity"):
                result = ArchiveResult.objects.get(
                    snapshot=snapshot,
                    plugin=event.plugin,
                    hook_name=event.hook_name,
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


class ArchiveResultService(BaseService):
    LISTENS_TO = [ArchiveResultEvent, ProcessCompletedEvent]
    EMITS = []

    def __init__(self, bus):
        self._completed_process_event_ids: set[str] = set()
        self._save_locks: dict[tuple[str, str, str], asyncio.Lock] = {}
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

        key = (str(event.snapshot_id), event.plugin, event.hook_name)
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

        # TODO: consider moving this fallback derivation into abx-dl itself.
        # First try both patterns: if the whole abx-dl process crashes, restarting
        # the snapshot may be enough, but don't guess before validating it.
        process_interrupted = _is_signal_interrupted_exit(event.exit_code)
        process_failed = event.exit_code not in (0, PROCESS_EXIT_SKIPPED) and not process_interrupted
        with _perf_span("archivebox.ArchiveResultService.on_ProcessCompletedEvent.emit_archive_result_fallback"):
            await event.emit(
                ArchiveResultEvent(
                    snapshot_id=snapshot_event.snapshot_id,
                    plugin=event.plugin_name,
                    hook_name=event.hook_name,
                    status=(
                        "queued"
                        if process_interrupted
                        else "failed"
                        if process_failed
                        else ("succeeded" if _has_content_files(event.output_files) else "noresult")
                    ),
                    output_str=event.stderr if process_failed else "",
                    output_files=event.output_files,
                    start_ts=event.start_ts,
                    end_ts=event.end_ts,
                    error=event.stderr if process_failed else "",
                ),
            ).now()
