import asyncio
import json

import pytest

from abx_dl.events import ProcessStartedEvent, ProcessStdoutEvent
from abx_dl.orchestrator import create_bus


pytestmark = pytest.mark.django_db


def test_process_service_emits_process_started_from_inline_process_event(monkeypatch):
    from archivebox.services import process_service as process_service_module
    from archivebox.services.process_service import ProcessService

    bus = create_bus(name="test_process_service_inline_process_event")
    ProcessService(bus)

    monkeypatch.setattr(
        process_service_module,
        "_ensure_worker",
        lambda event: {
            "pid": 4321,
            "start": 1711111111.0,
            "statename": "RUNNING",
            "exitstatus": 0,
        },
    )

    async def run_test():
        await bus.emit(
            ProcessStdoutEvent(
                line=json.dumps(
                    {
                        "type": "ProcessEvent",
                        "plugin_name": "search_backend_sonic",
                        "hook_name": "worker_sonic",
                        "hook_path": "/usr/bin/sonic",
                        "hook_args": ["-c", "/tmp/sonic/config.cfg"],
                        "is_background": True,
                        "daemon": True,
                        "url": "tcp://127.0.0.1:1491",
                        "output_dir": "/tmp/sonic",
                        "env": {},
                        "process_type": "worker",
                        "worker_type": "sonic",
                        "process_id": "worker:sonic",
                        "output_str": "127.0.0.1:1491",
                    },
                ),
                plugin_name="search_backend_sonic",
                hook_name="on_CrawlSetup__55_sonic_start.py",
                output_dir="/tmp/search_backend_sonic",
                snapshot_id="snap-1",
                process_id="proc-hook",
            ),
        )
        started = await bus.find(ProcessStartedEvent, process_id="worker:sonic")
        await bus.stop()
        return started

    started = asyncio.run(run_test())
    assert started is not None
    assert started.hook_name == "worker_sonic"
    assert started.process_type == "worker"
    assert started.worker_type == "sonic"
    assert getattr(started, "url", "") == "tcp://127.0.0.1:1491"
    assert getattr(started, "output_str", "") == "127.0.0.1:1491"
