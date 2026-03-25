from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from asgiref.sync import sync_to_async
from django.utils import timezone

from abxbus import BaseEvent
from abx_dl.events import ProcessCompletedEvent, ProcessStartedEvent
from abx_dl.services.base import BaseService


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
    LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [ProcessStartedEvent, ProcessCompletedEvent]
    EMITS: ClassVar[list[type[BaseEvent]]] = []

    def __init__(self, bus):
        super().__init__(bus)
        self.bus.on(ProcessStartedEvent, self.on_ProcessStartedEvent__save_to_db)
        self.bus.on(ProcessCompletedEvent, self.on_ProcessCompletedEvent__save_to_db)

    async def on_ProcessStartedEvent__save_to_db(self, event: ProcessStartedEvent) -> None:
        from archivebox.machine.models import NetworkInterface, Process

        iface = await sync_to_async(NetworkInterface.current, thread_sensitive=True)(refresh=True)
        process_type = event.process_type or (
            Process.TypeChoices.BINARY if event.hook_name.startswith("on_BinaryRequest") else Process.TypeChoices.HOOK
        )
        worker_type = event.worker_type or ""
        started_at = parse_event_datetime(event.start_ts)
        if started_at is None:
            raise ValueError("ProcessStartedEvent.start_ts is required")
        process_query = Process.objects.filter(
            process_type=process_type,
            worker_type=worker_type,
            pwd=event.output_dir,
            cmd=[event.hook_path, *event.hook_args],
            started_at=started_at,
        )
        if event.pid:
            process_query = process_query.filter(pid=event.pid)
        process = await process_query.order_by("-modified_at").afirst()
        if process is None:
            process = await Process.objects.acreate(
                machine=iface.machine,
                iface=iface,
                process_type=process_type,
                worker_type=worker_type,
                pwd=event.output_dir,
                cmd=[event.hook_path, *event.hook_args],
                env=event.env,
                timeout=event.timeout,
                pid=event.pid or None,
                url=event.url or None,
                started_at=started_at,
                status=Process.StatusChoices.RUNNING,
                retry_at=None,
            )
        elif process.iface_id != iface.id or process.machine_id != iface.machine_id:
            process.iface = iface
            process.machine = iface.machine
            await process.asave(update_fields=["iface", "machine", "modified_at"])

        process.pwd = event.output_dir
        process.cmd = [event.hook_path, *event.hook_args]
        process.env = event.env
        process.timeout = event.timeout
        process.pid = event.pid or None
        process.url = event.url or process.url
        process.process_type = process_type or process.process_type
        process.worker_type = worker_type or process.worker_type
        process.started_at = started_at
        process.status = process.StatusChoices.RUNNING
        process.retry_at = None
        await sync_to_async(process.hydrate_binary_from_context, thread_sensitive=True)(
            plugin_name=event.plugin_name,
            hook_path=event.hook_path,
        )
        await process.asave()

    async def on_ProcessCompletedEvent__save_to_db(self, event: ProcessCompletedEvent) -> None:
        from archivebox.machine.models import NetworkInterface, Process

        iface = await sync_to_async(NetworkInterface.current, thread_sensitive=True)(refresh=True)
        process_type = event.process_type or (
            Process.TypeChoices.BINARY if event.hook_name.startswith("on_BinaryRequest") else Process.TypeChoices.HOOK
        )
        worker_type = event.worker_type or ""
        started_at = parse_event_datetime(event.start_ts)
        if started_at is None:
            raise ValueError("ProcessCompletedEvent.start_ts is required")
        process_query = Process.objects.filter(
            process_type=process_type,
            worker_type=worker_type,
            pwd=event.output_dir,
            cmd=[event.hook_path, *event.hook_args],
            started_at=started_at,
        )
        if event.pid:
            process_query = process_query.filter(pid=event.pid)
        process = await process_query.order_by("-modified_at").afirst()
        if process is None:
            process = await Process.objects.acreate(
                machine=iface.machine,
                iface=iface,
                process_type=process_type,
                worker_type=worker_type,
                pwd=event.output_dir,
                cmd=[event.hook_path, *event.hook_args],
                env=event.env,
                timeout=event.timeout,
                pid=event.pid or None,
                url=event.url or None,
                started_at=started_at,
                status=Process.StatusChoices.RUNNING,
                retry_at=None,
            )
        elif process.iface_id != iface.id or process.machine_id != iface.machine_id:
            process.iface = iface
            process.machine = iface.machine
            await process.asave(update_fields=["iface", "machine", "modified_at"])

        process.pwd = event.output_dir
        if not process.cmd:
            process.cmd = [event.hook_path, *event.hook_args]
        process.env = event.env
        process.pid = event.pid or process.pid
        process.url = event.url or process.url
        process.process_type = process_type or process.process_type
        process.worker_type = worker_type or process.worker_type
        process.started_at = started_at
        process.ended_at = parse_event_datetime(event.end_ts) or timezone.now()
        process.stdout = event.stdout
        process.stderr = event.stderr
        process.exit_code = event.exit_code
        process.status = process.StatusChoices.EXITED
        process.retry_at = None
        await sync_to_async(process.hydrate_binary_from_context, thread_sensitive=True)(
            plugin_name=event.plugin_name,
            hook_path=event.hook_path,
        )
        await process.asave()
