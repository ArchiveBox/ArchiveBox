from __future__ import annotations

import mimetypes
from collections import defaultdict
from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone

from abx_dl.events import ArchiveResultEvent
from abx_dl.services.base import BaseService

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
        return "skipped"
    return status or "failed"


class ArchiveResultService(BaseService):
    LISTENS_TO = [ArchiveResultEvent]
    EMITS = []

    def __init__(self, bus, *, process_service: ProcessService):
        self.process_service = process_service
        super().__init__(bus)

    async def on_ArchiveResultEvent(self, event: ArchiveResultEvent) -> None:
        await sync_to_async(self._project, thread_sensitive=True)(event)

    def _project(self, event: ArchiveResultEvent) -> None:
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

        plugin_dir = Path(snapshot.output_dir) / event.plugin
        output_files, output_size, output_mimetypes = _collect_output_metadata(plugin_dir)
        result.process = process or result.process
        result.status = _normalize_status(event.status)
        result.output_str = event.output_str
        result.output_json = event.output_json
        result.output_files = output_files
        result.output_size = output_size
        result.output_mimetypes = output_mimetypes
        result.start_ts = parse_event_datetime(event.start_ts) or result.start_ts or timezone.now()
        result.end_ts = parse_event_datetime(event.end_ts) or timezone.now()
        result.retry_at = None
        if event.error:
            result.notes = event.error
        result.save()
