__package__ = "archivebox.ideas"

import asyncio
import importlib
import json
import os
import shlex
import signal
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from collections.abc import Callable, Mapping, MutableMapping

from pydantic import BaseModel, Field

try:
    bubus = importlib.import_module("bubus")
    BaseEvent = bubus.BaseEvent
    EventBus = bubus.EventBus
except Exception as exc:  # pragma: no cover - optional dependency
    raise ImportError("ProcessPlugin requires bubus to be installed") from exc

try:
    uuid7str = importlib.import_module("bubus.service").uuid7str
except Exception:  # pragma: no cover - optional dependency
    from uuid import uuid4 as _uuid4

    def uuid7str() -> str:
        return str(_uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProcessRecord(BaseModel):
    id: str = Field(default_factory=uuid7str)
    cmd: list[str]
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    pid: int | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    cmd_path: str | None = None
    pid_path: str | None = None
    is_background: bool = False
    parent_process_id: str | None = None


class ProcessLaunch(BaseEvent[ProcessRecord]):
    cmd: list[str]
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout: float | None = None
    output_dir: str | None = None
    log_prefix: str | None = None
    is_background: bool = False
    parent_process_id: str | None = None
    parse_stdout_events: bool = True


class ProcessStarted(BaseEvent[None]):
    process: ProcessRecord


class ProcessExited(BaseEvent[None]):
    process: ProcessRecord


class ProcessKill(BaseEvent[ProcessRecord]):
    process_id: str
    signal: int = signal.SIGTERM
    timeout: float | None = 10.0


@dataclass
class _RunningProcess:
    process: asyncio.subprocess.Process
    record: ProcessRecord
    stdout_task: asyncio.Task[None] | None
    stderr_task: asyncio.Task[None] | None
    watcher_task: asyncio.Task[None] | None
    parent_event_id: str | None


JsonEventAdapter = Callable[[dict[str, Any], str | None], Optional[BaseEvent[Any]]]


class ProcessPlugin:
    """Spawn and monitor processes using events (no Django required)."""

    def __init__(
        self,
        bus: EventBus,
        *,
        env: Mapping[str, str] | None = None,
        json_event_adapter: JsonEventAdapter | None = None,
    ) -> None:
        self.bus = bus
        self.env = dict(env or os.environ)
        self.json_event_adapter = json_event_adapter
        self._running: MutableMapping[str, _RunningProcess] = {}

    def register_event_handlers(self) -> None:
        self.bus.on(ProcessLaunch, self.on_ProcessLaunch)
        self.bus.on(ProcessKill, self.on_ProcessKill)

    async def on_ProcessLaunch(self, event: ProcessLaunch) -> ProcessRecord:
        parent_event_id = event.event_id
        proc_id = uuid7str()
        cwd = event.cwd or event.output_dir or os.getcwd()
        output_dir = Path(event.output_dir or cwd)
        output_dir.mkdir(parents=True, exist_ok=True)

        env = {**self.env, **(event.env or {})}

        log_prefix = event.log_prefix or proc_id
        stdout_path = output_dir / f"{log_prefix}.stdout.log"
        stderr_path = output_dir / f"{log_prefix}.stderr.log"
        cmd_path = output_dir / f"{log_prefix}.sh"
        pid_path = output_dir / f"{log_prefix}.pid"

        self._write_cmd_file(cmd_path, event.cmd)

        proc = await asyncio.create_subprocess_exec(
            *event.cmd,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        self._write_pid_file(pid_path, proc.pid)

        record = ProcessRecord(
            id=proc_id,
            cmd=event.cmd,
            cwd=str(cwd),
            env=env,
            pid=proc.pid,
            started_at=_utcnow(),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            cmd_path=str(cmd_path),
            pid_path=str(pid_path),
            is_background=event.is_background,
            parent_process_id=event.parent_process_id,
        )

        await event.event_bus.dispatch(
            ProcessStarted(process=record, event_parent_id=parent_event_id),
        )

        stdout_task = asyncio.create_task(
            self._consume_stream(
                proc.stdout,
                stdout_path,
                parent_event_id,
                event.parse_stdout_events,
            ),
        )
        stderr_task = asyncio.create_task(
            self._consume_stream(proc.stderr, stderr_path, parent_event_id, False),
        )

        running = _RunningProcess(
            process=proc,
            record=record,
            stdout_task=stdout_task,
            stderr_task=stderr_task,
            watcher_task=None,
            parent_event_id=parent_event_id,
        )
        self._running[proc_id] = running

        if event.is_background:
            running.watcher_task = asyncio.create_task(
                self._watch_process(proc_id, event.timeout),
            )
            return record

        await self._watch_process(proc_id, event.timeout)
        return self._running.get(proc_id, running).record

    async def on_ProcessKill(self, event: ProcessKill) -> ProcessRecord:
        running = self._running.get(event.process_id)
        if not running:
            raise RuntimeError(f"Process not found: {event.process_id}")

        proc = running.process
        self._terminate_process(proc, event.signal)

        if event.timeout is not None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=event.timeout)
            except TimeoutError:
                self._terminate_process(proc, signal.SIGKILL)
        else:
            await proc.wait()

        await self._finalize_process(event.process_id)
        return self._running.get(event.process_id, running).record

    async def _watch_process(self, process_id: str, timeout: float | None) -> None:
        running = self._running.get(process_id)
        if not running:
            return
        proc = running.process
        try:
            if timeout is not None:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            else:
                await proc.wait()
        except TimeoutError:
            self._terminate_process(proc, signal.SIGTERM)
            await asyncio.sleep(2)
            if proc.returncode is None:
                self._terminate_process(proc, signal.SIGKILL)
                await proc.wait()
        await self._finalize_process(process_id)

    async def _finalize_process(self, process_id: str) -> None:
        running = self._running.get(process_id)
        if not running:
            return

        proc = running.process
        record = running.record

        if running.stdout_task:
            await running.stdout_task
        if running.stderr_task:
            await running.stderr_task

        record.exit_code = proc.returncode
        record.ended_at = _utcnow()

        await self.bus.dispatch(
            ProcessExited(process=record, event_parent_id=running.parent_event_id),
        )

        self._running.pop(process_id, None)

    async def _consume_stream(
        self,
        stream: asyncio.StreamReader | None,
        path: Path,
        parent_event_id: str | None,
        parse_events: bool,
    ) -> None:
        if stream is None:
            return
        with path.open("w", encoding="utf-8") as fh:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                fh.write(text)
                fh.flush()
                if parse_events:
                    await self._maybe_dispatch_json_event(text, parent_event_id)

    async def _maybe_dispatch_json_event(self, line: str, parent_event_id: str | None) -> None:
        text = line.strip()
        if not text.startswith("{") or not text.endswith("}"):
            return
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return

        event = None
        if self.json_event_adapter:
            event = self.json_event_adapter(data, parent_event_id)
        elif isinstance(data, dict) and "event_type" in data:
            try:
                event = BaseEvent.model_validate(data)
            except Exception:
                event = None

        if event is None:
            return

        if not getattr(event, "event_parent_id", None) and parent_event_id:
            event.event_parent_id = parent_event_id
        await self.bus.dispatch(event)

    @staticmethod
    def _write_cmd_file(path: Path, cmd: list[str]) -> None:
        cmd_line = shlex.join(cmd)
        path.write_text(cmd_line + "\n", encoding="utf-8")

    @staticmethod
    def _write_pid_file(path: Path, pid: int) -> None:
        path.write_text(str(pid), encoding="utf-8")
        ts = datetime.now().timestamp()
        os.utime(path, (ts, ts))

    @staticmethod
    def _terminate_process(proc: asyncio.subprocess.Process, sig: int) -> None:
        if proc.returncode is not None:
            return
        try:
            os.killpg(proc.pid, sig)
        except Exception:
            try:
                os.kill(proc.pid, sig)
            except Exception:
                pass


__all__ = [
    "ProcessRecord",
    "ProcessLaunch",
    "ProcessStarted",
    "ProcessExited",
    "ProcessKill",
    "ProcessPlugin",
]
