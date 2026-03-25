from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import ArchiveResultEvent, ProcessCompletedEvent, ProcessStartedEvent, SnapshotEvent
from abx_dl.output_files import guess_mimetype
from abx_dl.services.base import BaseService

from .process_service import parse_event_datetime


def _collect_output_metadata(plugin_dir: Path) -> tuple[dict[str, dict], int, str]:
    exclude_names = {"stdout.log", "stderr.log", "process.pid", "hook.pid", "listener.pid", "cmd.sh"}
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
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        elif hasattr(item, "path"):
            item = {
                "path": getattr(item, "path", ""),
                "extension": getattr(item, "extension", ""),
                "mimetype": getattr(item, "mimetype", ""),
                "size": getattr(item, "size", 0),
            }
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


class ArchiveResultService(BaseService):
    LISTENS_TO = [ArchiveResultEvent, ProcessCompletedEvent]
    EMITS = []

    def __init__(self, bus):
        super().__init__(bus)
        self.bus.on(ArchiveResultEvent, self.on_ArchiveResultEvent__save_to_db)
        self.bus.on(ProcessCompletedEvent, self.on_ProcessCompletedEvent__save_to_db)

    async def on_ArchiveResultEvent__save_to_db(self, event: ArchiveResultEvent) -> None:
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.machine.models import Process

        snapshot = await Snapshot.objects.filter(id=event.snapshot_id).select_related("crawl", "crawl__created_by").afirst()
        if snapshot is None:
            return
        plugin_dir = Path(snapshot.output_dir) / event.plugin
        output_files, output_size, output_mimetypes = await sync_to_async(_resolve_output_metadata)(event.output_files, plugin_dir)
        process_started = await self.bus.find(
            ProcessStartedEvent,
            past=True,
            future=False,
            where=lambda candidate: self.bus.event_is_child_of(event, candidate),
        )
        process = None
        if process_started is not None:
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
            process = await process_query.order_by("-modified_at").afirst()

        result, _created = await ArchiveResult.objects.aget_or_create(
            snapshot=snapshot,
            plugin=event.plugin,
            hook_name=event.hook_name,
            defaults={
                "status": ArchiveResult.StatusChoices.STARTED,
                "process": process,
            },
        )

        result.process = process or result.process
        result.status = _normalize_status(event.status)
        result.output_str = event.output_str
        result.output_json = event.output_json
        result.output_files = output_files
        result.output_size = output_size
        result.output_mimetypes = output_mimetypes
        result.start_ts = parse_event_datetime(event.start_ts) or result.start_ts or timezone.now()
        result.end_ts = parse_event_datetime(event.end_ts) or timezone.now()
        if event.error:
            result.notes = event.error
        await result.asave()

        next_title = _extract_snapshot_title(str(snapshot.output_dir), event.plugin, result.output_str, snapshot_url=snapshot.url)
        if next_title and _should_update_snapshot_title(snapshot.title or "", next_title, snapshot_url=snapshot.url):
            snapshot.title = next_title
            await snapshot.asave(update_fields=["title", "modified_at"])

    async def on_ProcessCompletedEvent__save_to_db(self, event: ProcessCompletedEvent) -> None:
        if not event.hook_name.startswith("on_Snapshot"):
            return
        snapshot_event = await self.bus.find(
            SnapshotEvent,
            past=True,
            future=False,
            where=lambda candidate: self.bus.event_is_child_of(event, candidate),
        )
        if snapshot_event is None:
            return

        records = _iter_archiveresult_records(event.stdout)
        if records:
            for record in records:
                await self.bus.emit(
                    ArchiveResultEvent(
                        snapshot_id=record.get("snapshot_id") or snapshot_event.snapshot_id,
                        plugin=record.get("plugin") or event.plugin_name,
                        hook_name=record.get("hook_name") or event.hook_name,
                        status=record.get("status") or "",
                        output_str=record.get("output_str") or "",
                        output_json=record.get("output_json") if isinstance(record.get("output_json"), dict) else None,
                        output_files=event.output_files,
                        start_ts=event.start_ts,
                        end_ts=event.end_ts,
                        error=record.get("error") or (event.stderr if event.exit_code != 0 else ""),
                    ),
                )
            return

        await self.bus.emit(
            ArchiveResultEvent(
                snapshot_id=snapshot_event.snapshot_id,
                plugin=event.plugin_name,
                hook_name=event.hook_name,
                status="failed" if event.exit_code != 0 else ("succeeded" if _has_content_files(event.output_files) else "skipped"),
                output_str=event.stderr if event.exit_code != 0 else "",
                output_files=event.output_files,
                start_ts=event.start_ts,
                end_ts=event.end_ts,
                error=event.stderr if event.exit_code != 0 else "",
            ),
        )
