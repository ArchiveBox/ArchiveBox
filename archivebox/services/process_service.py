from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from django.utils import timezone

from abx_dl.events import ProcessCompletedEvent, ProcessStartedEvent
from abx_dl.services.base import BaseService

from .db import run_db_op

if TYPE_CHECKING:
    from archivebox.machine.models import Process


def parse_event_datetime(value: str | None):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


class ProcessService(BaseService):
    LISTENS_TO = [ProcessStartedEvent, ProcessCompletedEvent]
    EMITS = []

    def __init__(self, bus):
        self.process_ids: dict[str, str] = {}
        super().__init__(bus)

    async def on_ProcessStartedEvent__Outer(self, event: ProcessStartedEvent) -> None:
        await run_db_op(self._project_started, event)

    async def on_ProcessCompletedEvent__Outer(self, event: ProcessCompletedEvent) -> None:
        await run_db_op(self._project_completed, event)

    def get_db_process_id(self, process_id: str) -> str | None:
        return self.process_ids.get(process_id)

    def _get_or_create_process(self, event: ProcessStartedEvent | ProcessCompletedEvent) -> Process:
        from archivebox.machine.models import NetworkInterface, Process

        db_process_id = self.process_ids.get(event.process_id)
        iface = NetworkInterface.current(refresh=True)
        if db_process_id:
            process = Process.objects.filter(id=db_process_id).first()
            if process is not None:
                if process.iface_id != iface.id or process.machine_id != iface.machine_id:
                    process.iface = iface
                    process.machine = iface.machine
                    process.save(update_fields=["iface", "machine", "modified_at"])
                return process

        process_type = getattr(event, "process_type", "") or (
            Process.TypeChoices.BINARY if event.hook_name.startswith("on_BinaryRequest") else Process.TypeChoices.HOOK
        )
        worker_type = getattr(event, "worker_type", "") or ""
        if process_type == Process.TypeChoices.WORKER and worker_type:
            existing = (
                Process.objects.filter(
                    process_type=Process.TypeChoices.WORKER,
                    worker_type=worker_type,
                    pwd=event.output_dir,
                )
                .order_by("-modified_at")
                .first()
            )
            if existing is not None:
                self.process_ids[event.process_id] = str(existing.id)
                return existing
        process = Process.objects.create(
            machine=iface.machine,
            iface=iface,
            process_type=process_type,
            worker_type=worker_type,
            pwd=event.output_dir,
            cmd=[event.hook_path, *event.hook_args],
            env=event.env,
            timeout=getattr(event, "timeout", 60),
            pid=event.pid or None,
            started_at=parse_event_datetime(getattr(event, "start_ts", "")),
            status=Process.StatusChoices.RUNNING,
            retry_at=None,
        )
        self.process_ids[event.process_id] = str(process.id)
        return process

    def _project_started(self, event: ProcessStartedEvent) -> None:
        process = self._get_or_create_process(event)
        process.pwd = event.output_dir
        process.cmd = [event.hook_path, *event.hook_args]
        process.env = event.env
        process.timeout = event.timeout
        process.pid = event.pid or None
        process.process_type = getattr(event, "process_type", "") or process.process_type
        process.worker_type = getattr(event, "worker_type", "") or process.worker_type
        process.started_at = parse_event_datetime(event.start_ts) or process.started_at or timezone.now()
        process.status = process.StatusChoices.RUNNING
        process.retry_at = None
        process.hydrate_binary_from_context(plugin_name=event.plugin_name, hook_path=event.hook_path)
        process.save()

    def _project_completed(self, event: ProcessCompletedEvent) -> None:
        process = self._get_or_create_process(event)
        process.pwd = event.output_dir
        if not process.cmd:
            process.cmd = [event.hook_path, *event.hook_args]
        process.env = event.env
        process.pid = event.pid or process.pid
        process.process_type = getattr(event, "process_type", "") or process.process_type
        process.worker_type = getattr(event, "worker_type", "") or process.worker_type
        process.started_at = parse_event_datetime(event.start_ts) or process.started_at
        process.ended_at = parse_event_datetime(event.end_ts) or timezone.now()
        process.stdout = event.stdout
        process.stderr = event.stderr
        process.exit_code = event.exit_code
        process.status = process.StatusChoices.EXITED
        process.retry_at = None
        process.hydrate_binary_from_context(plugin_name=event.plugin_name, hook_path=event.hook_path)
        process.save()
