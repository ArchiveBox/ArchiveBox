from __future__ import annotations

import asyncio
import json
import time

from abx_dl.events import ProcessStdoutEvent


def register_sonic_daemon_event_handler(bus) -> None:
    async def on_ProcessStdoutEvent__require_sonic_daemon(event: ProcessStdoutEvent) -> None:
        try:
            record = json.loads(event.line)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(record, dict) or record.get("type") != "SonicDaemonStartEvent":
            return

        from abx_plugins.plugins.search_backend_sonic.daemon import SonicDaemonStartEvent

        await asyncio.to_thread(wait_for_sonic_daemon, SonicDaemonStartEvent.from_record(record))

    bus.on(ProcessStdoutEvent, on_ProcessStdoutEvent__require_sonic_daemon)


def wait_for_sonic_daemon(daemon_event) -> None:
    """Wait for the Sonic handshake used by both search commands and crawl hooks.

    Supervisord RUNNING only means the process was spawned; its socket can still
    be opening. Fail immediately for a stopped worker and retain the existing
    30-second startup deadline for a live worker.
    """
    from abx_plugins.plugins.search_backend_sonic.daemon import is_port_listening
    from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker

    deadline = time.monotonic() + 30.0
    last_worker = None

    while time.monotonic() < deadline:
        if is_port_listening(daemon_event.host, daemon_event.port):
            return

        supervisor = get_existing_supervisord_process(quiet=True)
        worker = get_worker(supervisor, daemon_event.worker_name) if supervisor is not None else None
        if isinstance(worker, dict):
            last_worker = worker
            if worker.get("statename") not in {"STARTING", "RUNNING", "BACKOFF", "STOPPING"}:
                break

        time.sleep(0.5)

    if is_port_listening(daemon_event.host, daemon_event.port):
        return

    supervisor = get_existing_supervisord_process(quiet=True)
    if supervisor is None:
        raise RuntimeError("Sonic search backend is required, but ArchiveBox supervisord is not running")

    worker = get_worker(supervisor, daemon_event.worker_name)
    if worker is None and last_worker is not None:
        worker = last_worker
    if not worker:
        raise RuntimeError(f"Sonic search backend worker is not configured: {daemon_event.worker_name}")
    if worker.get("statename") != "RUNNING":
        raise RuntimeError(
            f"Sonic search backend worker is {worker.get('statename')}: {worker.get('description')}",
        )
    raise RuntimeError(f"Sonic search backend is not listening at {daemon_event.url}")
