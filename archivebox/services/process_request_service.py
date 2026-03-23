from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import socket
import time
from typing import ClassVar

from abxbus import BaseEvent
from abx_dl.events import ProcessCompletedEvent, ProcessEvent, ProcessStartedEvent, ProcessStdoutEvent
from abx_dl.services.base import BaseService


def _is_port_listening(host: str, port: int) -> bool:
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _supervisor_env(env: dict[str, str]) -> str:
    pairs = []
    for key, value in env.items():
        escaped = value.replace('"', '\\"')
        pairs.append(f'{key}="{escaped}"')
    return ",".join(pairs)


def _iso_from_epoch(value: object) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return ""
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _ensure_worker(process_event: ProcessEvent) -> dict[str, object]:
    from archivebox.workers.supervisord_util import get_or_create_supervisord_process, get_worker, start_worker

    output_dir = Path(process_event.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    worker_name = process_event.hook_name
    supervisor = get_or_create_supervisord_process(daemonize=True)

    existing = get_worker(supervisor, worker_name)
    if (
        isinstance(existing, dict)
        and existing.get("statename") == "RUNNING"
        and (
            not process_event.daemon_startup_host
            or not process_event.daemon_startup_port
            or _is_port_listening(process_event.daemon_startup_host, process_event.daemon_startup_port)
        )
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
    deadline = time.monotonic() + max(float(process_event.daemon_startup_timeout), 0.5)
    while time.monotonic() < deadline:
        current = get_worker(supervisor, worker_name)
        if isinstance(current, dict) and current.get("statename") == "RUNNING":
            if (
                not process_event.daemon_startup_host
                or not process_event.daemon_startup_port
                or _is_port_listening(process_event.daemon_startup_host, process_event.daemon_startup_port)
            ):
                return current
        time.sleep(0.1)
    return proc if isinstance(proc, dict) else {}


class ProcessRequestService(BaseService):
    LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [ProcessStdoutEvent]
    EMITS: ClassVar[list[type[BaseEvent]]] = [ProcessEvent, ProcessStartedEvent, ProcessCompletedEvent]

    async def on_ProcessStdoutEvent(self, event: ProcessStdoutEvent) -> None:
        try:
            record = json.loads(event.line)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(record, dict) or record.pop("type", "") != "ProcessEvent":
            return

        process_event = ProcessEvent(
            plugin_name=record.get("plugin_name") or event.plugin_name,
            hook_name=record.get("hook_name") or "process_request",
            hook_path=record["hook_path"],
            hook_args=[str(arg) for arg in record.get("hook_args", [])],
            is_background=bool(record.get("is_background", True)),
            output_dir=record.get("output_dir") or event.output_dir,
            env={str(key): str(value) for key, value in (record.get("env") or {}).items()},
            snapshot_id=record.get("snapshot_id") or event.snapshot_id,
            timeout=int(record.get("timeout") or 60),
            daemon=bool(record.get("daemon", False)),
            daemon_startup_host=str(record.get("daemon_startup_host") or ""),
            daemon_startup_port=int(record.get("daemon_startup_port") or 0),
            daemon_startup_timeout=float(record.get("daemon_startup_timeout") or 0.0),
            process_type=str(record.get("process_type") or ""),
            worker_type=str(record.get("worker_type") or ""),
            event_timeout=float(record.get("event_timeout") or 360.0),
            event_handler_timeout=float(record.get("event_handler_timeout") or 390.0),
        )
        if not process_event.daemon:
            await self.bus.emit(process_event)
            return

        proc = await asyncio.to_thread(_ensure_worker, process_event)
        process_id = str(record.get("process_id") or f"worker:{process_event.hook_name}")
        start_ts = _iso_from_epoch(proc.get("start"))
        pid = int(proc.get("pid") or 0)
        statename = str(proc.get("statename") or "")
        exitstatus = int(proc.get("exitstatus") or 0)
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
                    process_type=process_type,
                    worker_type=worker_type,
                    start_ts=start_ts,
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
                process_type=process_type,
                worker_type=worker_type,
                start_ts=start_ts,
                end_ts=datetime.now(tz=timezone.utc).isoformat(),
            ),
        )
        raise RuntimeError(stderr)
