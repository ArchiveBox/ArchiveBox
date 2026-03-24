from __future__ import annotations

import asyncio
from datetime import datetime, timezone as datetime_timezone
import json
from pathlib import Path
import shlex
import socket
import time
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlparse

from django.utils import timezone

from abxbus import BaseEvent
from abx_dl.events import ProcessCompletedEvent, ProcessEvent, ProcessStartedEvent, ProcessStdoutEvent
from abx_dl.services.base import BaseService

from .db import run_db_op

if TYPE_CHECKING:
    from archivebox.machine.models import Process


WORKER_READY_TIMEOUT = 10.0


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


def _is_port_listening(host: str, port: int) -> bool:
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _worker_socket_from_url(url: str) -> tuple[str, int] | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "tcp" or not parsed.hostname or not parsed.port:
        return None
    return parsed.hostname, parsed.port


def _supervisor_env(env: dict[str, str]) -> str:
    pairs = []
    for key, value in env.items():
        escaped = value.replace('"', '\\"')
        pairs.append(f'{key}="{escaped}"')
    return ",".join(pairs)


def _iso_from_epoch(value: object) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return ""
    return datetime.fromtimestamp(value, tz=datetime_timezone.utc).isoformat()


def _int_from_object(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _ensure_worker(process_event: ProcessEvent) -> dict[str, object]:
    from archivebox.workers.supervisord_util import get_or_create_supervisord_process, get_worker, start_worker

    output_dir = Path(process_event.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    worker_name = process_event.hook_name
    supervisor = get_or_create_supervisord_process(daemonize=True)
    worker_socket = _worker_socket_from_url(getattr(process_event, "url", ""))

    existing = get_worker(supervisor, worker_name)
    if (
        isinstance(existing, dict)
        and existing.get("statename") == "RUNNING"
        and (worker_socket is None or _is_port_listening(*worker_socket))
    ):
        return existing

    daemon = {
        "name": worker_name,
        "command": shlex.join([process_event.hook_path, *process_event.hook_args]),
        "directory": str(output_dir),
        "autostart": "false",
        "autorestart": "true",
        "stdout_logfile": str(output_dir / f"{worker_name}.stdout.log"),
        "redirect_stderr": "true",
    }
    if process_event.env:
        daemon["environment"] = _supervisor_env(process_event.env)

    proc = start_worker(supervisor, daemon)
    deadline = time.monotonic() + WORKER_READY_TIMEOUT
    while time.monotonic() < deadline:
        current = get_worker(supervisor, worker_name)
        if isinstance(current, dict) and current.get("statename") == "RUNNING":
            if worker_socket is None or _is_port_listening(*worker_socket):
                return current
        time.sleep(0.1)
    return proc if isinstance(proc, dict) else {}


class ProcessService(BaseService):
    LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [ProcessStdoutEvent, ProcessStartedEvent, ProcessCompletedEvent]
    EMITS: ClassVar[list[type[BaseEvent]]] = [ProcessEvent, ProcessStartedEvent, ProcessCompletedEvent]

    def __init__(self, bus):
        self.process_ids: dict[str, str] = {}
        super().__init__(bus)

    async def on_ProcessStdoutEvent(self, event: ProcessStdoutEvent) -> None:
        try:
            record = json.loads(event.line)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(record, dict) or record.get("type") != "ProcessEvent":
            return

        passthrough_fields: dict[str, Any] = {
            key: value
            for key, value in record.items()
            if key
            not in {
                "type",
                "plugin_name",
                "hook_name",
                "hook_path",
                "hook_args",
                "is_background",
                "output_dir",
                "env",
                "snapshot_id",
                "process_id",
                "url",
                "timeout",
                "daemon",
                "process_type",
                "worker_type",
                "event_timeout",
                "event_handler_timeout",
            }
        }
        process_event = ProcessEvent(
            plugin_name=record.get("plugin_name") or event.plugin_name,
            hook_name=record.get("hook_name") or "process",
            hook_path=record["hook_path"],
            hook_args=[str(arg) for arg in record.get("hook_args", [])],
            is_background=bool(record.get("is_background", True)),
            output_dir=record.get("output_dir") or event.output_dir,
            env={str(key): str(value) for key, value in (record.get("env") or {}).items()},
            snapshot_id=record.get("snapshot_id") or event.snapshot_id,
            timeout=int(record.get("timeout") or 60),
            daemon=bool(record.get("daemon", False)),
            url=str(record.get("url") or ""),
            process_type=str(record.get("process_type") or ""),
            worker_type=str(record.get("worker_type") or ""),
            event_timeout=float(record.get("event_timeout") or 360.0),
            event_handler_timeout=float(record.get("event_handler_timeout") or 390.0),
            **passthrough_fields,
        )
        if not process_event.daemon:
            await self.bus.emit(process_event)
            return

        proc = await asyncio.to_thread(_ensure_worker, process_event)
        process_id = str(record.get("process_id") or f"worker:{process_event.hook_name}")
        start_ts = _iso_from_epoch(proc.get("start"))
        pid = _int_from_object(proc.get("pid"))
        statename = str(proc.get("statename") or "")
        exitstatus = _int_from_object(proc.get("exitstatus"))
        process_type = process_event.process_type or "worker"
        worker_type = process_event.worker_type or process_event.plugin_name

        if statename == "RUNNING" and pid:
            await self.bus.emit(
                ProcessStartedEvent(
                    plugin_name=process_event.plugin_name,
                    hook_name=process_event.hook_name,
                    hook_path=process_event.hook_path,
                    hook_args=process_event.hook_args,
                    output_dir=process_event.output_dir,
                    env=process_event.env,
                    timeout=process_event.timeout,
                    pid=pid,
                    process_id=process_id,
                    snapshot_id=process_event.snapshot_id,
                    is_background=True,
                    url=process_event.url,
                    process_type=process_type,
                    worker_type=worker_type,
                    start_ts=start_ts,
                    **passthrough_fields,
                ),
            )
            return

        stderr = (
            f"Worker {process_event.hook_name} failed to start"
            if not statename
            else f"Worker {process_event.hook_name} state={statename} exitstatus={exitstatus}"
        )
        await self.bus.emit(
            ProcessCompletedEvent(
                plugin_name=process_event.plugin_name,
                hook_name=process_event.hook_name,
                hook_path=process_event.hook_path,
                hook_args=process_event.hook_args,
                env=process_event.env,
                stdout="",
                stderr=stderr,
                exit_code=exitstatus or 1,
                output_dir=process_event.output_dir,
                is_background=True,
                process_id=process_id,
                snapshot_id=process_event.snapshot_id,
                pid=pid,
                url=process_event.url,
                process_type=process_type,
                worker_type=worker_type,
                start_ts=start_ts,
                end_ts=datetime.now(tz=datetime_timezone.utc).isoformat(),
                **passthrough_fields,
            ),
        )
        raise RuntimeError(stderr)

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
                if getattr(process, "iface_id", None) != iface.id or process.machine_id != iface.machine_id:
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
            url=getattr(event, "url", "") or None,
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
        process.url = getattr(event, "url", "") or process.url
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
        process.url = getattr(event, "url", "") or process.url
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
