from __future__ import annotations

import json

from abx_dl.events import ProcessStdoutEvent


def register_sonic_daemon_event_handler(bus) -> None:
    async def on_ProcessStdoutEvent__require_sonic_daemon(event: ProcessStdoutEvent) -> None:
        try:
            record = json.loads(event.line)
        except (json.JSONDecodeError, ValueError):
            return
        if not isinstance(record, dict) or record.get("type") != "SonicDaemonStartEvent":
            return

        from abx_plugins.plugins.search_backend_sonic.daemon import (
            SonicDaemonStartEvent,
            is_port_listening,
        )
        from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker

        daemon_event = SonicDaemonStartEvent.from_record(record)
        supervisor = get_existing_supervisord_process()
        if supervisor is None:
            raise RuntimeError("Sonic search backend is required, but ArchiveBox supervisord is not running")

        worker = get_worker(supervisor, daemon_event.worker_name)
        if not worker:
            raise RuntimeError(f"Sonic search backend worker is not configured: {daemon_event.worker_name}")
        if worker.get("statename") != "RUNNING":
            raise RuntimeError(
                f"Sonic search backend worker is {worker.get('statename')}: {worker.get('description')}",
            )
        if not is_port_listening(daemon_event.host, daemon_event.port):
            raise RuntimeError(f"Sonic search backend is not listening at {daemon_event.url}")

    bus.on(ProcessStdoutEvent, on_ProcessStdoutEvent__require_sonic_daemon)
