from __future__ import annotations

import json
import mimetypes
from collections import defaultdict
from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import ArchiveResultEvent, ProcessCompletedEvent
from abx_dl.services.base import BaseService

from .db import run_db_op
from .process_service import ProcessService, parse_event_datetime


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
        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or "application/octet-stream"
        relative_path = str(file_path.relative_to(plugin_dir))
        output_files[relative_path] = {}
        mime_sizes[mime_type] += stat.st_size
        total_size += stat.st_size

    output_mimetypes = ",".join(
        mime for mime, _size in sorted(mime_sizes.items(), key=lambda item: item[1], reverse=True)
    )
    return output_files, total_size, output_mimetypes


def _normalize_status(status: str) -> str:
    if status == "noresult":
        return "noresults"
    return status or "failed"


def _has_content_files(output_files: list[str]) -> bool:
    return any(Path(path).suffix not in {".log", ".pid", ".sh"} for path in output_files)


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

    def __init__(self, bus, *, process_service: ProcessService):
        self.process_service = process_service
        super().__init__(bus)

    async def on_ArchiveResultEvent__Outer(self, event: ArchiveResultEvent) -> None:
        snapshot_output_dir = await run_db_op(self._get_snapshot_output_dir, event.snapshot_id)
        if snapshot_output_dir is None:
            return
        plugin_dir = Path(snapshot_output_dir) / event.plugin
        output_files, output_size, output_mimetypes = await sync_to_async(_collect_output_metadata)(plugin_dir)
        await run_db_op(self._project, event, output_files, output_size, output_mimetypes)

    async def on_ProcessCompletedEvent__Outer(self, event: ProcessCompletedEvent) -> None:
        if not event.snapshot_id or not event.hook_name.startswith("on_Snapshot"):
            return

        plugin_dir = Path(event.output_dir)
        output_files, output_size, output_mimetypes = await sync_to_async(_collect_output_metadata)(plugin_dir)
        records = _iter_archiveresult_records(event.stdout)
        if records:
            for record in records:
                await run_db_op(
                    self._project_from_process_completed,
                    event,
                    record,
                    output_files,
                    output_size,
                    output_mimetypes,
                )
            return

        synthetic_record = {
            "plugin": event.plugin_name,
            "hook_name": event.hook_name,
            "status": "failed" if event.exit_code != 0 else ("succeeded" if _has_content_files(event.output_files) else "skipped"),
            "output_str": event.stderr if event.exit_code != 0 else "",
            "error": event.stderr if event.exit_code != 0 else "",
        }
        await run_db_op(
            self._project_from_process_completed,
            event,
            synthetic_record,
            output_files,
            output_size,
            output_mimetypes,
        )

    def _get_snapshot_output_dir(self, snapshot_id: str) -> str | None:
        from archivebox.core.models import Snapshot

        snapshot = Snapshot.objects.filter(id=snapshot_id).only("output_dir").first()
        return str(snapshot.output_dir) if snapshot is not None else None

    def _project(
        self,
        event: ArchiveResultEvent,
        output_files: dict[str, dict],
        output_size: int,
        output_mimetypes: str,
    ) -> None:
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.machine.models import Process

        snapshot = Snapshot.objects.filter(id=event.snapshot_id).first()
        if snapshot is None:
            return

        process = None
        db_process_id = self.process_service.get_db_process_id(event.process_id)
        if db_process_id:
            process = Process.objects.filter(id=db_process_id).first()

        result, _created = ArchiveResult.objects.get_or_create(
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
        result.save()

    def _project_from_process_completed(
        self,
        event: ProcessCompletedEvent,
        record: dict,
        output_files: dict[str, dict],
        output_size: int,
        output_mimetypes: str,
    ) -> None:
        archive_result_event = ArchiveResultEvent(
            snapshot_id=record.get("snapshot_id") or event.snapshot_id,
            plugin=record.get("plugin") or event.plugin_name,
            hook_name=record.get("hook_name") or event.hook_name,
            status=record.get("status") or "",
            process_id=event.process_id,
            output_str=record.get("output_str") or "",
            output_json=record.get("output_json") if isinstance(record.get("output_json"), dict) else None,
            start_ts=event.start_ts,
            end_ts=event.end_ts,
            error=record.get("error") or (event.stderr if event.exit_code != 0 else ""),
        )
        self._project(archive_result_event, output_files, output_size, output_mimetypes)
