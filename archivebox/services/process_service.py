from __future__ import annotations

import asyncio
from datetime import datetime
from typing import ClassVar

from asgiref.sync import sync_to_async
from django.utils import timezone

from abxbus import BaseEvent
from abx_dl.events import CrawlCleanupEvent, CrawlCompletedEvent, ProcessCompletedEvent, ProcessStartedEvent
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


def current_network_interface_with_machine():
    from archivebox.machine.models import NetworkInterface

    current_iface = NetworkInterface.current()
    return NetworkInterface.objects.select_related("machine").get(id=current_iface.id)


class ProcessService(BaseService):
    LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
        ProcessStartedEvent,
        ProcessCompletedEvent,
        CrawlCleanupEvent,
        CrawlCompletedEvent,
    ]
    EMITS: ClassVar[list[type[BaseEvent]]] = []

    def __init__(self, bus):
        self._iface = None
        self._completed_queue: asyncio.Queue[ProcessCompletedEvent | None] = asyncio.Queue()
        self._completed_worker: asyncio.Task | None = None
        super().__init__(bus)
        self.bus.on(ProcessStartedEvent, self.on_ProcessStartedEvent__save_to_db)
        self.bus.on(ProcessCompletedEvent, self.on_ProcessCompletedEvent__save_to_db)
        self.bus.on(CrawlCleanupEvent, self.on_CrawlCleanupEvent__flush_completed)
        self.bus.on(CrawlCompletedEvent, self.on_CrawlCompletedEvent__flush_completed)

    async def current_iface(self):
        if self._iface is None:
            self._iface = await sync_to_async(current_network_interface_with_machine, thread_sensitive=True)()
        return self._iface

    async def on_ProcessStartedEvent__save_to_db(self, event: ProcessStartedEvent) -> None:
        from archivebox.machine.models import Process

        iface = await self.current_iface()
        process_type = event.process_type or (
            Process.TypeChoices.BINARY if event.hook_name.startswith("on_BinaryRequest") else Process.TypeChoices.HOOK
        )
        worker_type = event.worker_type or ""
        started_at = parse_event_datetime(event.start_ts)
        if started_at is None:
            raise ValueError("ProcessStartedEvent.start_ts is required")
        if event.pid:
            process_query = Process.objects.filter(pid=event.pid, started_at=started_at)
        else:
            process_query = Process.objects.filter(
                process_type=process_type,
                worker_type=worker_type,
                pwd=event.output_dir,
                started_at=started_at,
            )
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
        await Process.objects.filter(id=process.id).aupdate(
            pwd=process.pwd,
            cmd=process.cmd,
            env=process.env,
            timeout=process.timeout,
            pid=process.pid,
            url=process.url,
            process_type=process.process_type,
            worker_type=process.worker_type,
            started_at=process.started_at,
            status=process.status,
            retry_at=process.retry_at,
            binary_id=process.binary_id,
            modified_at=timezone.now(),
        )

    async def _completed_worker_loop(self) -> None:
        while True:
            event = await self._completed_queue.get()
            try:
                if event is None:
                    return
                await self._save_completed_process_to_db(event)
            finally:
                self._completed_queue.task_done()

    def _ensure_completed_worker(self) -> None:
        if self._completed_worker is None or self._completed_worker.done():
            self._completed_worker = asyncio.create_task(self._completed_worker_loop())

    async def on_ProcessCompletedEvent__save_to_db(self, event: ProcessCompletedEvent) -> None:
        self._ensure_completed_worker()
        await self._completed_queue.put(event)

    async def flush_completed(self) -> None:
        await self._completed_queue.join()

    async def on_CrawlCleanupEvent__flush_completed(self, event: CrawlCleanupEvent) -> None:
        await self.flush_completed()

    async def on_CrawlCompletedEvent__flush_completed(self, event: CrawlCompletedEvent) -> None:
        await self.flush_completed()

    async def _save_completed_process_to_db(self, event: ProcessCompletedEvent) -> None:
        from archivebox.machine.models import Process

        iface = await self.current_iface()
        process_type = event.process_type or (
            Process.TypeChoices.BINARY if event.hook_name.startswith("on_BinaryRequest") else Process.TypeChoices.HOOK
        )
        worker_type = event.worker_type or ""
        started_at = parse_event_datetime(event.start_ts)
        if started_at is None:
            raise ValueError("ProcessCompletedEvent.start_ts is required")
        if event.pid:
            process_query = Process.objects.filter(pid=event.pid, started_at=started_at)
        else:
            process_query = Process.objects.filter(
                process_type=process_type,
                worker_type=worker_type,
                pwd=event.output_dir,
                started_at=started_at,
            )
        process = await process_query.order_by("-modified_at").afirst()
        if process is None:
            await Process.objects.acreate(
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
            process = await process_query.order_by("-modified_at").afirst()
            if process is None:
                return

        missing_cmd = not process.cmd
        updates = {
            "machine_id": iface.machine_id,
            "iface_id": iface.id,
            "pwd": event.output_dir,
            "pid": event.pid or process.pid,
            "url": event.url or process.url,
            "process_type": process_type or process.process_type,
            "worker_type": worker_type or process.worker_type,
            "started_at": started_at,
            "ended_at": parse_event_datetime(event.end_ts) or timezone.now(),
            "stdout": event.stdout,
            "stderr": event.stderr,
            "exit_code": event.exit_code,
            "status": Process.StatusChoices.EXITED,
            "retry_at": None,
            "modified_at": timezone.now(),
        }
        if missing_cmd:
            updates["cmd"] = [event.hook_path, *event.hook_args]
        await Process.objects.filter(id=process.id).aupdate(**updates)
