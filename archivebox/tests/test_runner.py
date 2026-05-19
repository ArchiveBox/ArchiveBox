import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from asgiref.sync import sync_to_async
from django.test import RequestFactory


pytestmark = pytest.mark.django_db


class _DummyBus:
    def __init__(self, name: str):
        self.name = name
        self.registrations = []
        self.emitted = []

    def on(self, event_pattern, handler):
        registration = SimpleNamespace(event_pattern=event_pattern, handler=handler)
        self.registrations.append(registration)
        return registration

    def off(self, event_pattern, registration):
        self.registrations = [existing for existing in self.registrations if existing is not registration]

    def emit(self, event):
        self.emitted.append(event)
        bus = self

        class _Pending:
            def __getattr__(self, name):
                return getattr(event, name)

            async def now(self, *args, **kwargs):
                from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent

                if isinstance(event, SnapshotEvent):
                    completed = SnapshotCompletedEvent(
                        url=event.url,
                        snapshot_id=event.snapshot_id,
                        output_dir=event.output_dir,
                        event_parent_id=event.event_id,
                    )
                    completed._mark_completed()
                    bus.emitted.append(completed)
                return event

            async def wait(self, *args, **kwargs):
                return event

            async def event_results_list(self):
                return []

        return _Pending()

    async def find(self, event_type, where=None, child_of=None, **kwargs):
        for event in reversed(self.emitted):
            if not isinstance(event, event_type):
                continue
            if child_of is not None and event.event_parent_id != child_of.event_id:
                continue
            if where is not None and not where(event):
                continue
            return event
        return None

    async def stop(self):
        return None

    async def wait_until_idle(self):
        return None


class _NoIdleBus(_DummyBus):
    async def wait_until_idle(self):
        raise AssertionError("run_snapshot should not wait on the whole crawl bus")


class _DummyService:
    def __init__(self, *args, **kwargs):
        pass


@pytest.mark.django_db(transaction=True)
def test_run_snapshot_reuses_crawl_bus_for_all_snapshots(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://blog.sweeting.me\nhttps://sweeting.me",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot_a = Snapshot.objects.create(
        url="https://blog.sweeting.me",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
    )
    snapshot_b = Snapshot.objects.create(
        url="https://sweeting.me",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
    )

    created_buses: list[_DummyBus] = []

    original_create_bus = runner_module.create_bus

    def fake_create_bus(*, name, total_timeout=3600.0, **kwargs):
        bus = original_create_bus(name=name, total_timeout=total_timeout, **kwargs)
        created_buses.append(bus)
        return bus

    monkeypatch.setattr(runner_module, "create_bus", fake_create_bus)
    monkeypatch.setattr(runner_module, "discover_plugins", lambda: {})
    monkeypatch.setattr(runner_module, "HookProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "PersistedProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)
    monkeypatch.setattr(runner_module, "_emit_machine_config", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: None)

    crawl_runner = runner_module.CrawlRunner(crawl)
    snapshot_data = {
        str(snapshot_a.id): {
            "id": str(snapshot_a.id),
            "url": snapshot_a.url,
            "status": snapshot_a.status,
            "title": snapshot_a.title,
            "timestamp": snapshot_a.timestamp,
            "bookmarked_at": snapshot_a.bookmarked_at.isoformat() if snapshot_a.bookmarked_at else "",
            "created_at": snapshot_a.created_at.isoformat() if snapshot_a.created_at else "",
            "tags": snapshot_a.tags_str(),
            "depth": snapshot_a.depth,
            "output_dir": str(snapshot_a.output_dir),
            "config": crawl_runner.load_snapshot_payload(str(snapshot_a.id))["config"],
        },
        str(snapshot_b.id): {
            "id": str(snapshot_b.id),
            "url": snapshot_b.url,
            "status": snapshot_b.status,
            "title": snapshot_b.title,
            "timestamp": snapshot_b.timestamp,
            "bookmarked_at": snapshot_b.bookmarked_at.isoformat() if snapshot_b.bookmarked_at else "",
            "created_at": snapshot_b.created_at.isoformat() if snapshot_b.created_at else "",
            "tags": snapshot_b.tags_str(),
            "depth": snapshot_b.depth,
            "output_dir": str(snapshot_b.output_dir),
            "config": crawl_runner.load_snapshot_payload(str(snapshot_b.id))["config"],
        },
    }
    monkeypatch.setattr(crawl_runner, "load_snapshot_payload", lambda snapshot_id: snapshot_data[snapshot_id])
    monkeypatch.setattr(crawl_runner, "enqueue_discovered_snapshots_from_outputs", lambda snapshot: asyncio.sleep(0))

    asyncio.run(crawl_runner.run_crawl(str(snapshot_a.id), [str(snapshot_a.id), str(snapshot_b.id)]))

    from abx_dl.events import SnapshotEvent

    snapshot_events = asyncio.run(crawl_runner.bus.filter(SnapshotEvent, past=True))
    assert len(snapshot_events) == 2
    assert {event.snapshot_id for event in snapshot_events} == {str(snapshot_a.id), str(snapshot_b.id)}
    assert {event.url for event in snapshot_events} == {snapshot_a.url, snapshot_b.url}
    assert crawl_runner.bus is created_buses[0]
    assert len(created_buses) == 1


@pytest.mark.django_db(transaction=True)
def test_run_snapshot_does_not_wait_for_crawl_background_daemons(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
    )

    monkeypatch.setattr(runner_module, "discover_plugins", lambda: {})
    monkeypatch.setattr(runner_module, "HookProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "PersistedProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)
    monkeypatch.setattr(runner_module, "_emit_machine_config", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: None)

    crawl_runner = runner_module.CrawlRunner(crawl)
    snapshot_payload = crawl_runner.load_snapshot_payload(str(snapshot.id))
    monkeypatch.setattr(crawl_runner, "load_snapshot_payload", lambda snapshot_id: snapshot_payload)
    monkeypatch.setattr(crawl_runner, "enqueue_discovered_snapshots_from_outputs", lambda snapshot: asyncio.sleep(0))

    crawl_runner.bus.wait_until_idle = _NoIdleBus("unused").wait_until_idle
    asyncio.run(crawl_runner.run_crawl(str(snapshot.id), [str(snapshot.id)]))


@pytest.mark.django_db(transaction=True)
def test_cancelled_crawl_projection_emits_abort_event_from_runner_bus():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.runner import CrawlRunner
    from abx_dl.events import CrawlAbortEvent, CrawlEvent

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )
    runner = CrawlRunner(crawl)

    async def run() -> CrawlAbortEvent | None:
        abort_event_holder: dict[str, CrawlAbortEvent | None] = {"event": None}

        async def on_CrawlEvent(event: CrawlEvent) -> None:
            watcher = asyncio.create_task(runner.watch_for_cancelled_crawl(event, poll_interval=0.01))
            await asyncio.sleep(0.02)
            await sync_to_async(Crawl.objects.filter(id=crawl.id).update, thread_sensitive=True)(
                status=Crawl.StatusChoices.SEALED,
                retry_at=None,
            )
            abort_event = await runner.bus.find(CrawlAbortEvent, child_of=event, past=True, future=1.0)
            abort_event_holder["event"] = abort_event if isinstance(abort_event, CrawlAbortEvent) else None
            await watcher

        runner.bus.on(CrawlEvent, on_CrawlEvent)
        await runner.bus.emit(
            CrawlEvent(
                url=snapshot.url,
                snapshot_id=str(snapshot.id),
                output_dir=str(crawl.output_dir),
            ),
        ).now()
        await runner.bus.wait_until_idle()
        return abort_event_holder["event"]

    abort_event = asyncio.run(run())

    assert abort_event is not None


@pytest.mark.django_db(transaction=True)
def test_enqueue_discovered_snapshots_refreshes_crawl_limits(tmp_path):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.runner import CrawlRunner

    crawl = Crawl.objects.create(
        urls="https://example.com",
        max_depth=0,
        max_urls=5,
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        depth=0,
    )
    parser_dir = Path(snapshot.output_dir) / "parse_html_urls"
    parser_dir.mkdir(parents=True, exist_ok=True)
    (parser_dir / "urls.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "Snapshot", "url": "https://example.com/child-a", "depth": 1}),
                json.dumps({"type": "Snapshot", "url": "https://example.com/child-b", "depth": 1}),
                "",
            ],
        ),
    )

    runner = CrawlRunner(crawl)
    Crawl.objects.filter(id=crawl.id).update(max_depth=1)
    payload = runner.load_snapshot_payload(str(snapshot.id))

    asyncio.run(runner.enqueue_discovered_snapshots_from_outputs(payload))

    child_snapshots = list(crawl.snapshot_set.filter(depth=1).order_by("url").values_list("url", "status"))
    assert child_snapshots == [
        ("https://example.com/child-a", Snapshot.StatusChoices.QUEUED),
        ("https://example.com/child-b", Snapshot.StatusChoices.QUEUED),
    ]


def test_ensure_background_runner_starts_when_none_running(monkeypatch):
    import archivebox.machine.models as machine_models
    import archivebox.workers.supervisord_util as supervisord_util
    from archivebox.services import runner as runner_module

    popen_calls = []

    class DummyPopen:
        def __init__(self, args, **kwargs):
            popen_calls.append((args, kwargs))

    monkeypatch.setattr(supervisord_util, "get_existing_supervisord_process", lambda: None)
    monkeypatch.setattr(machine_models.Process, "cleanup_stale_running", classmethod(lambda cls, machine=None: 0))
    monkeypatch.setattr(machine_models.Process, "cleanup_orphaned_workers", classmethod(lambda cls: 0))
    monkeypatch.setattr(machine_models.Machine, "current", classmethod(lambda cls: SimpleNamespace(id="machine-1")))
    monkeypatch.setattr(
        machine_models.Process.objects,
        "filter",
        lambda **kwargs: SimpleNamespace(exists=lambda: False),
    )
    monkeypatch.setattr(runner_module.subprocess, "Popen", DummyPopen)

    started = runner_module.ensure_background_runner(allow_under_pytest=True)

    assert started is True
    assert len(popen_calls) == 1
    assert popen_calls[0][0] == [runner_module.sys.executable, "-m", "archivebox", "run", "--daemon"]
    assert popen_calls[0][1]["stdin"] is subprocess.DEVNULL


def test_ensure_background_runner_skips_when_orchestrator_running(monkeypatch):
    import archivebox.machine.models as machine_models
    import archivebox.workers.supervisord_util as supervisord_util
    from archivebox.services import runner as runner_module

    monkeypatch.setattr(supervisord_util, "get_existing_supervisord_process", lambda: None)
    monkeypatch.setattr(machine_models.Process, "cleanup_stale_running", classmethod(lambda cls, machine=None: 0))
    monkeypatch.setattr(machine_models.Process, "cleanup_orphaned_workers", classmethod(lambda cls: 0))
    monkeypatch.setattr(machine_models.Machine, "current", classmethod(lambda cls: SimpleNamespace(id="machine-1")))
    monkeypatch.setattr(
        machine_models.Process.objects,
        "filter",
        lambda **kwargs: SimpleNamespace(exists=lambda: True),
    )
    monkeypatch.setattr(
        runner_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runner should not be spawned")),
    )

    started = runner_module.ensure_background_runner(allow_under_pytest=True)

    assert started is False


def test_ensure_background_runner_skips_when_supervisord_runner_running(monkeypatch):
    import archivebox.machine.models as machine_models
    import archivebox.workers.supervisord_util as supervisord_util
    from archivebox.services import runner as runner_module

    supervisor = object()

    monkeypatch.setattr(supervisord_util, "get_existing_supervisord_process", lambda: supervisor)
    monkeypatch.setattr(supervisord_util, "get_worker", lambda supervisor_arg, name: {"statename": "RUNNING"})
    monkeypatch.setattr(
        machine_models.Process,
        "cleanup_stale_running",
        classmethod(lambda cls, machine=None: (_ for _ in ()).throw(AssertionError("db process cleanup should not run"))),
    )
    monkeypatch.setattr(
        runner_module.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runner should not be spawned")),
    )

    started = runner_module.ensure_background_runner(allow_under_pytest=True)

    assert started is False


def test_runner_task_context_clears_inherited_abxbus_handler_context(tmp_path):
    from abx_dl.events import CrawlEvent, MachineEvent
    from abx_dl.orchestrator import create_bus
    from abxbus.event_bus import in_handler_context
    from archivebox.services import runner as runner_module

    bus = create_bus(name="test_runner_task_context_clears_inherited_abxbus_handler_context")
    observations = []

    async def emit_from_runner_task():
        observations.append(("in_handler_context", in_handler_context()))
        machine_event = bus.emit(MachineEvent(config={"ABX_RUNTIME": "archivebox"}, config_type="user"))
        await machine_event.now()
        observations.append(("machine_event_path", bool(machine_event.event_path)))

    async def on_crawl(event):
        assert in_handler_context() is True
        task = asyncio.create_task(emit_from_runner_task(), context=runner_module._runner_task_context())
        await task

    bus.on(CrawlEvent, on_crawl)

    async def run_test():
        try:
            await bus.emit(
                CrawlEvent(
                    url="https://example.com",
                    snapshot_id="snapshot-1",
                    output_dir=str(tmp_path),
                ),
            ).now()
            await bus.wait_until_idle()
        finally:
            await bus.destroy()

    asyncio.run(run_test())

    assert observations == [
        ("in_handler_context", False),
        ("machine_event_path", True),
    ]


@pytest.mark.django_db(transaction=True)
def test_machine_service_persists_only_derived_config_events(tmp_path):
    from abx_dl.events import MachineEvent
    from abx_dl.orchestrator import create_bus
    from archivebox.machine.models import Machine
    from archivebox.services.machine_service import MachineService

    machine = Machine.current()
    machine.config = {}
    machine.save(update_fields=["config"])
    wget_binary = tmp_path / "wget"
    wget_binary.write_text("#!/bin/sh\n")
    wget_binary.chmod(0o755)

    async def run_test():
        bus = create_bus(name="test_machine_service_persists_only_derived_config_events")
        try:
            MachineService(bus)
            user_event = bus.emit(
                MachineEvent(
                    config={
                        "CHROME_ISOLATION": "snapshot",
                        "CHROME_USER_DATA_DIR": "/tmp/stale-profile",
                        "ABX_RUNTIME": "archivebox",
                    },
                    config_type="user",
                ),
            )
            await user_event.now()
            await user_event.event_results_list()
            derived_event = bus.emit(
                MachineEvent(
                    config={
                        "WGET_BINARY": str(wget_binary),
                        "ABX_INSTALL_CACHE": {"wget": "2026-03-24T00:00:00+00:00"},
                        "CHROME_USER_DATA_DIR": "/tmp/stale-derived-profile",
                    },
                    config_type="derived",
                ),
            )
            await derived_event.now()
            await derived_event.event_results_list()
            unset_event = bus.emit(
                MachineEvent(
                    method="unset",
                    key="config/WGET_BINARY",
                    config_type="derived",
                ),
            )
            await unset_event.now()
            await unset_event.event_results_list()
            await bus.wait_until_idle()
        finally:
            await bus.destroy()

    asyncio.run(run_test())

    machine.refresh_from_db()
    assert machine.config == {
        "ABX_INSTALL_CACHE": {"wget": "2026-03-24T00:00:00+00:00"},
    }


def test_runner_prepare_refreshes_network_interface_and_attaches_current_process(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )

    class _Iface:
        id = "iface-1"
        machine = SimpleNamespace(id="machine-1")
        machine_id = "machine-1"

    saved_updates = []

    class _Proc:
        iface_id = None
        machine_id = "machine-1"
        iface = None
        machine = None

        def save(self, *, update_fields):
            saved_updates.append(tuple(update_fields))

    proc = _Proc()

    monkeypatch.setattr(runner_module, "discover_plugins", lambda: {})
    monkeypatch.setattr(runner_module, "HookProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "PersistedProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "SnapshotService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)

    from archivebox.machine.models import NetworkInterface, Process
    from archivebox.config import common as config_common

    refresh_calls = []
    monkeypatch.setattr(NetworkInterface, "current", classmethod(lambda cls, refresh=False: refresh_calls.append(refresh) or _Iface()))
    monkeypatch.setattr(Process, "current", classmethod(lambda cls: proc))
    original_get_config = config_common.get_config
    monkeypatch.setattr(
        config_common,
        "get_config",
        lambda **kwargs: original_get_config(
            overrides={"PLUGINS": "", "CHROME_BINARY": "", "CHROME_KEEPALIVE": False, "TIMEOUT": 60},
            **kwargs,
        ),
    )

    crawl_runner = runner_module.CrawlRunner(crawl)
    crawl_runner.load_run_state()

    assert refresh_calls == [True]
    assert proc.iface is not None
    assert proc.machine == proc.iface.machine
    assert saved_updates == [("iface", "machine", "modified_at")]


def test_load_run_state_uses_machine_config_as_derived_config(monkeypatch, tmp_path):
    from archivebox.machine.models import Machine, NetworkInterface, Process
    from archivebox.services import runner as runner_module
    from archivebox.config import common as config_common
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl

    wget_binary = tmp_path / "wget"
    wget_binary.write_text("#!/bin/sh\n")
    wget_binary.chmod(0o755)
    machine = Machine.objects.create(
        guid="test-guid-runner-overrides",
        hostname="runner-host",
        hw_in_docker=False,
        hw_in_vm=False,
        hw_manufacturer="Test",
        hw_product="Test Product",
        hw_uuid="test-hw-runner-overrides",
        os_arch="arm64",
        os_family="darwin",
        os_platform="macOS",
        os_release="14.0",
        os_kernel="Darwin",
        stats={},
        config={
            "WGET_BINARY": str(wget_binary),
            "ABX_INSTALL_CACHE": {"wget": "2026-03-24T00:00:00+00:00"},
            "CHROME_ISOLATION": "snapshot",
            "CHROME_USER_DATA_DIR": "/tmp/stale-profile",
        },
    )
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    proc = SimpleNamespace(iface_id=str(machine.id), machine_id=str(machine.id), iface=None, machine=machine, save=lambda **kwargs: None)

    monkeypatch.setattr(
        NetworkInterface,
        "current",
        classmethod(lambda cls, refresh=False: SimpleNamespace(id=machine.id, machine=machine)),
    )
    monkeypatch.setattr(Process, "current", classmethod(lambda cls: proc))
    monkeypatch.setattr(Machine, "current", classmethod(lambda cls: machine))
    original_get_config = config_common.get_config
    monkeypatch.setattr(
        config_common,
        "get_config",
        lambda **kwargs: original_get_config(overrides={"PLUGINS": "", "CHROME_BINARY": "", "TIMEOUT": 60}, **kwargs),
    )

    crawl_runner = runner_module.CrawlRunner(crawl)
    crawl_runner.load_run_state()

    assert crawl_runner.derived_config == {
        "WGET_BINARY": str(wget_binary),
        "ABX_INSTALL_CACHE": {"wget": "2026-03-24T00:00:00+00:00"},
    }


def test_load_run_state_does_not_force_chrome_keepalive(monkeypatch):
    from archivebox.machine.models import Machine, NetworkInterface, Process
    from archivebox.services import runner as runner_module
    from archivebox.config import common as config_common
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl

    machine = Machine.objects.create(
        guid="test-guid-runner-chrome-keepalive",
        hostname="runner-host-chrome-keepalive",
        hw_in_docker=False,
        hw_in_vm=False,
        hw_manufacturer="Test",
        hw_product="Test Product",
        hw_uuid="test-hw-runner-chrome-keepalive",
        os_arch="arm64",
        os_family="darwin",
        os_platform="macOS",
        os_release="14.0",
        os_kernel="Darwin",
        stats={},
        config={},
    )
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    proc = SimpleNamespace(iface_id=str(machine.id), machine_id=str(machine.id), iface=None, machine=machine, save=lambda **kwargs: None)

    monkeypatch.setattr(
        NetworkInterface,
        "current",
        classmethod(lambda cls, refresh=False: SimpleNamespace(id=machine.id, machine=machine)),
    )
    monkeypatch.setattr(Process, "current", classmethod(lambda cls: proc))
    monkeypatch.setattr(Machine, "current", classmethod(lambda cls: machine))
    original_get_config = config_common.get_config
    monkeypatch.setattr(
        config_common,
        "get_config",
        lambda **kwargs: original_get_config(overrides={"PLUGINS": "", "CHROME_BINARY": "", "TIMEOUT": 60}, **kwargs),
    )

    crawl_runner = runner_module.CrawlRunner(crawl)
    crawl_runner.load_run_state()

    assert crawl_runner.base_config["CHROME_KEEPALIVE"] is False


def test_load_run_state_uses_enabled_plugins_when_plugins_key_missing(monkeypatch):
    from archivebox.machine.models import Machine, NetworkInterface, Process
    from archivebox.services import runner as runner_module
    from archivebox.config import common as config_common
    from archivebox import hooks as hooks_module
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from pathlib import Path

    machine = Machine.objects.create(
        guid="test-guid-runner-missing-plugins",
        hostname="runner-host-missing-plugins",
        hw_in_docker=False,
        hw_in_vm=False,
        hw_manufacturer="Test",
        hw_product="Test Product",
        hw_uuid="test-hw-runner-missing-plugins",
        os_arch="arm64",
        os_family="darwin",
        os_platform="macOS",
        os_release="14.0",
        os_kernel="Darwin",
        stats={},
        config={},
    )
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    proc = SimpleNamespace(iface_id=str(machine.id), machine_id=str(machine.id), iface=None, machine=machine, save=lambda **kwargs: None)

    monkeypatch.setattr(
        NetworkInterface,
        "current",
        classmethod(lambda cls, refresh=False: SimpleNamespace(id=machine.id, machine=machine)),
    )
    monkeypatch.setattr(Process, "current", classmethod(lambda cls: proc))
    monkeypatch.setattr(Machine, "current", classmethod(lambda cls: machine))
    original_get_config = config_common.get_config
    monkeypatch.setattr(
        config_common,
        "get_config",
        lambda **kwargs: original_get_config(overrides={"CHROME_BINARY": "", "TIMEOUT": 60}, **kwargs),
    )
    monkeypatch.setattr(
        hooks_module,
        "discover_hooks",
        lambda event_name, config=None: (
            [
                Path(f"/tmp/{event_name.lower()}/wget/on_{event_name}__test.py"),
                Path(f"/tmp/{event_name.lower()}/favicon/on_{event_name}__test.py"),
            ]
            if event_name in {"CrawlSetup", "Snapshot"}
            else []
        ),
    )

    crawl_runner = runner_module.CrawlRunner(crawl)
    snapshot_ids = crawl_runner.load_run_state()

    assert crawl_runner.selected_plugins == ["favicon", "wget"]
    assert len(snapshot_ids) == 1


@pytest.mark.django_db(transaction=True)
def test_run_snapshot_skips_descendant_when_max_size_already_reached(monkeypatch, tmp_path):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        max_size=16,
    )

    monkeypatch.setattr(runner_module, "discover_plugins", lambda: {})
    monkeypatch.setattr(runner_module, "HookProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "PersistedProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "SnapshotService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)
    crawl_runner = runner_module.CrawlRunner(crawl)
    state_dir = tmp_path / ".abx-dl"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "limits.json").write_text(
        json.dumps(
            {
                "admitted_snapshot_ids": ["child-1"],
                "counted_process_ids": ["proc-1"],
                "total_size": 32,
                "stop_reason": "max_size",
            },
        ),
        encoding="utf-8",
    )
    cancelled: list[str] = []
    crawl_runner.load_snapshot_payload = lambda snapshot_id: {
        "id": snapshot_id,
        "url": "https://example.com/child",
        "title": "",
        "timestamp": "",
        "bookmarked_at": "",
        "created_at": "",
        "tags": "",
        "depth": 1,
        "status": "queued",
        "output_dir": "/tmp/child",
        "config": {"CRAWL_DIR": str(tmp_path), "MAX_SIZE": 16},
    }
    crawl_runner.seal_snapshot_due_to_limit = lambda snapshot_id: cancelled.append(snapshot_id)

    async def run_in_crawl_start_context() -> None:
        from abx_dl.events import CrawlStartEvent

        async def run_child_snapshot(event: CrawlStartEvent) -> None:
            await crawl_runner.run_snapshot("child-1")

        crawl_runner.bus.on(CrawlStartEvent, run_child_snapshot)
        await crawl_runner.bus.emit(
            CrawlStartEvent(
                url="https://example.com",
                snapshot_id="child-1",
                output_dir=str(tmp_path),
                event_timeout=30,
                event_handler_timeout=30,
            ),
        ).now()

    asyncio.run(run_in_crawl_start_context())

    assert cancelled == ["child-1"]


@pytest.mark.django_db(transaction=True)
def test_seal_snapshot_cancels_queued_descendants_after_max_size():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.snapshot_service import SnapshotService
    from abx_dl.events import SnapshotCompletedEvent
    from abx_dl.orchestrator import create_bus

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        max_size=16,
    )
    root = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )
    child = Snapshot.objects.create(
        url="https://example.com/child",
        crawl=crawl,
        depth=1,
        parent_snapshot_id=root.id,
        status=Snapshot.StatusChoices.QUEUED,
    )

    state_dir = Path(crawl.output_dir) / ".abx-dl"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "limits.json").write_text(
        json.dumps(
            {
                "admitted_snapshot_ids": [str(root.id), str(child.id)],
                "counted_process_ids": ["proc-1"],
                "total_size": 32,
                "stop_reason": "max_size",
            },
        ),
        encoding="utf-8",
    )

    bus = create_bus(name=f"test_snapshot_limit_cancel_{str(crawl.id).replace('-', '_')}")
    service = SnapshotService(bus, crawl_id=str(crawl.id), schedule_snapshot=lambda snapshot_id: None)
    try:

        async def emit_event() -> None:
            await service.on_SnapshotCompletedEvent(
                SnapshotCompletedEvent(
                    url=root.url,
                    snapshot_id=str(root.id),
                    output_dir=str(root.output_dir),
                ),
            )

        asyncio.run(emit_event())
    finally:
        asyncio.run(bus.wait_until_idle())
        asyncio.run(bus.destroy())

    root.refresh_from_db()
    child.refresh_from_db()
    assert root.status == Snapshot.StatusChoices.SEALED
    assert child.status == Snapshot.StatusChoices.SEALED
    assert child.retry_at is None


def test_sealed_crawl_does_not_create_discovered_snapshots():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
        max_depth=3,
    )
    root = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
    )

    assert crawl.create_snapshots_from_urls() == []
    assert crawl.create_discovered_snapshot(root, url="https://example.com/child", depth=1) is None
    assert crawl.snapshot_set.count() == 1


def test_create_crawl_api_queues_crawl_without_spawning_runner(monkeypatch):
    from django.contrib.auth import get_user_model
    from archivebox.api.v1_crawls import CrawlCreateSchema, create_crawl

    user = get_user_model().objects.create_superuser(
        username="runner-api-admin",
        email="runner-api-admin@example.com",
        password="testpassword",
    )
    request = RequestFactory().post("/api/v1/crawls")
    request.user = user

    crawl = create_crawl(
        request,
        CrawlCreateSchema(
            urls=["https://example.com"],
            max_depth=0,
            tags=[],
            tags_str="",
            label="",
            notes="",
            config={},
        ),
    )

    assert str(crawl.id)
    assert crawl.status == "queued"
    assert crawl.retry_at is not None


def test_crawl_runner_does_not_seal_unfinished_crawl(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )

    monkeypatch.setattr(runner_module, "_emit_machine_config", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "load_run_state", lambda self: [str(snapshot.id)])
    monkeypatch.setattr(
        runner_module.CrawlRunner,
        "load_snapshot_payload",
        lambda self, _snapshot_id: {
            "id": str(snapshot.id),
            "url": snapshot.url,
            "depth": snapshot.depth,
            "output_dir": str(snapshot.output_dir),
        },
    )
    monkeypatch.setattr(runner_module.CrawlRunner, "_create_live_ui", lambda self: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "run_crawl", lambda self, root_snapshot_id, snapshot_ids: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "finalize_run_state", lambda self: None)

    asyncio.run(runner_module.CrawlRunner(crawl, snapshot_ids=[str(snapshot.id)]).run())

    crawl.refresh_from_db()
    assert crawl.status != Crawl.StatusChoices.SEALED
    assert crawl.retry_at is not None


def test_crawl_runner_calls_load_and_finalize_run_state(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )

    monkeypatch.setattr(runner_module, "create_bus", lambda *args, **kwargs: _DummyBus("runner"))
    monkeypatch.setattr(runner_module, "discover_plugins", lambda: {})
    monkeypatch.setattr(runner_module, "HookProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "PersistedProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "SnapshotService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)
    monkeypatch.setattr(runner_module, "_emit_machine_config", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "load_run_state", lambda self: [str(snapshot.id)])
    monkeypatch.setattr(
        runner_module.CrawlRunner,
        "load_snapshot_payload",
        lambda self, _snapshot_id: {
            "id": str(snapshot.id),
            "url": snapshot.url,
            "depth": snapshot.depth,
            "output_dir": str(snapshot.output_dir),
        },
    )
    monkeypatch.setattr(runner_module.CrawlRunner, "_create_live_ui", lambda self: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "run_crawl", lambda self, root_snapshot_id, snapshot_ids: asyncio.sleep(0))
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

    method_calls: list[str] = []

    def wrapped_finalize(self):
        method_calls.append("finalize_run_state")
        return None

    def wrapped_load(self):
        method_calls.append("load_run_state")
        return [str(snapshot.id)]

    monkeypatch.setattr(runner_module.CrawlRunner, "finalize_run_state", wrapped_finalize)
    monkeypatch.setattr(runner_module.CrawlRunner, "load_run_state", wrapped_load)

    asyncio.run(runner_module.CrawlRunner(crawl, snapshot_ids=[str(snapshot.id)]).run())

    for _ in range(20):
        crawl.refresh_from_db()
        if crawl.retry_at is not None:
            break
        time.sleep(0.1)
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None
    assert method_calls == ["load_run_state", "finalize_run_state"]


def test_wait_for_snapshot_tasks_surfaces_already_failed_task():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    crawl_runner = runner_module.CrawlRunner(crawl)

    async def run_test():
        task = asyncio.get_running_loop().create_future()
        task.set_exception(RuntimeError("snapshot failed"))
        crawl_runner.snapshot_tasks["snap-1"] = task
        with pytest.raises(RuntimeError, match="snapshot failed"):
            await crawl_runner.wait_for_snapshot_tasks()

    asyncio.run(run_test())


def test_wait_for_snapshot_tasks_returns_after_completed_tasks_are_pruned():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    crawl_runner = runner_module.CrawlRunner(crawl)

    async def finish_snapshot() -> None:
        await asyncio.sleep(0)

    async def run_test():
        task = asyncio.create_task(finish_snapshot())
        crawl_runner.snapshot_tasks["snap-1"] = task
        await asyncio.wait_for(crawl_runner.wait_for_snapshot_tasks(), timeout=0.5)
        assert crawl_runner.snapshot_tasks == {}

    asyncio.run(run_test())


def test_crawl_runner_calls_crawl_lifecycle(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )

    monkeypatch.setattr(runner_module, "_emit_machine_config", lambda *args, **kwargs: asyncio.sleep(0))
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "load_run_state", lambda self: [str(snapshot.id)])
    monkeypatch.setattr(
        runner_module.CrawlRunner,
        "load_snapshot_payload",
        lambda self, _snapshot_id: {
            "id": str(snapshot.id),
            "url": snapshot.url,
            "depth": snapshot.depth,
            "output_dir": str(snapshot.output_dir),
        },
    )
    monkeypatch.setattr(runner_module.CrawlRunner, "_create_live_ui", lambda self: None)

    monkeypatch.setattr(runner_module.CrawlRunner, "finalize_run_state", lambda self: None)

    lifecycle_calls = []
    monkeypatch.setattr(
        runner_module.CrawlRunner,
        "run_crawl",
        lambda self, root_snapshot_id, snapshot_ids: lifecycle_calls.append((root_snapshot_id, snapshot_ids)) or asyncio.sleep(0),
    )
    asyncio.run(runner_module.CrawlRunner(crawl, snapshot_ids=[str(snapshot.id)]).run())

    assert lifecycle_calls == [(str(snapshot.id), [str(snapshot.id)])]


def test_abx_process_service_background_process_finishes_after_process_exit(monkeypatch, tmp_path):
    from abx_dl.events import ProcessCompletedEvent, ProcessEvent
    from abx_dl.orchestrator import create_bus
    from abx_dl.services.process_service import ProcessService

    bus = create_bus(name="test_abx_process_service_background_process_finishes_after_process_exit")
    service = ProcessService(bus, emit_jsonl=False, interactive_tty=False)
    emitted_events = []

    async def collect_completed(event):
        emitted_events.append(event)

    bus.on(ProcessCompletedEvent, collect_completed)

    async def fake_stream_stdout(**kwargs):
        return ["daemon output\n"]

    monkeypatch.setattr(service, "_stream_stdout", fake_stream_stdout)

    plugin_output_dir = tmp_path / "chrome"
    plugin_output_dir.mkdir()

    async def run_test():
        try:
            event = ProcessEvent(
                plugin_name="chrome",
                hook_name="on_CrawlSetup__90_chrome_launch.daemon.bg",
                hook_path=sys.executable,
                hook_args=["-c", "pass"],
                env={},
                output_dir=str(plugin_output_dir),
                timeout=60,
                is_background=True,
                url="https://example.org/",
                process_type="hook",
                worker_type="hook",
            )
            await asyncio.wait_for(bus.emit(event).now(), timeout=0.5)
            completed = await bus.find(ProcessCompletedEvent, past=True, future=5.0)
            assert isinstance(completed, ProcessCompletedEvent)
            await completed.event_results_list()
        finally:
            await bus.destroy()

    asyncio.run(run_test())

    assert not list(plugin_output_dir.glob("on_CrawlSetup__90_chrome_launch.daemon.bg.*.pid"))
    assert any(isinstance(event, ProcessCompletedEvent) for event in emitted_events)


def test_run_pending_crawls_runs_due_snapshot_in_place(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.SEALED,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
        retry_at=runner_module.timezone.now(),
    )

    monkeypatch.setattr(type(snapshot), "claim_processing_lock", lambda self, lock_seconds=60: True)
    monkeypatch.setattr(type(crawl), "claim_processing_lock", lambda self, lock_seconds=60: True)

    run_calls: list[tuple[str, list[str] | None, bool]] = []

    def fake_run_crawl(crawl_id, snapshot_ids=None, selected_plugins=None, process_discovered_snapshots_inline=True):
        run_calls.append((crawl_id, snapshot_ids, process_discovered_snapshots_inline))
        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.retry_at = None
        snapshot.save(update_fields=["status", "retry_at", "modified_at"])

    monkeypatch.setattr(runner_module, "run_crawl", fake_run_crawl)

    result = runner_module.run_pending_crawls(daemon=False)

    assert result == 0
    assert run_calls == [(str(crawl.id), [str(snapshot.id)], True)]


def test_run_pending_crawls_prioritizes_new_queued_crawl_before_snapshot_backlog(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services import runner as runner_module

    older_crawl = Crawl.objects.create(
        urls="https://older.example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
    )
    older_snapshot = Snapshot.objects.create(
        url="https://older.example.com",
        crawl=older_crawl,
        status=Snapshot.StatusChoices.QUEUED,
        retry_at=runner_module.timezone.now(),
    )
    newer_crawl = Crawl.objects.create(
        urls="https://newer.example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.QUEUED,
        retry_at=runner_module.timezone.now(),
    )

    monkeypatch.setattr(type(older_snapshot), "claim_processing_lock", lambda self, lock_seconds=60: True)
    monkeypatch.setattr(type(older_crawl), "claim_processing_lock", lambda self, lock_seconds=60: True)
    monkeypatch.setattr(type(newer_crawl), "claim_processing_lock", lambda self, lock_seconds=60: True)

    run_calls: list[tuple[str, list[str] | None, bool]] = []

    class _StopScheduling(Exception):
        pass

    def fake_run_crawl(crawl_id, snapshot_ids=None, selected_plugins=None, process_discovered_snapshots_inline=True):
        run_calls.append((crawl_id, snapshot_ids, process_discovered_snapshots_inline))
        raise _StopScheduling

    monkeypatch.setattr(runner_module, "run_crawl", fake_run_crawl)

    with pytest.raises(_StopScheduling):
        runner_module.run_pending_crawls(daemon=False)

    assert run_calls == [(str(newer_crawl.id), None, True)]


def test_run_pending_crawls_prioritizes_queued_crawl_before_unrelated_binary_backlog(monkeypatch):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Binary, Machine
    from archivebox.services import runner as runner_module

    queued_crawl = Crawl.objects.create(
        urls="https://scheduled.example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.QUEUED,
        retry_at=runner_module.timezone.now(),
    )
    unrelated_binary = Binary.objects.create(
        machine=Machine.current(),
        name="papers-dl",
        status=Binary.StatusChoices.QUEUED,
        retry_at=runner_module.timezone.now(),
    )

    monkeypatch.setattr(type(queued_crawl), "claim_processing_lock", lambda self, lock_seconds=60: True)
    monkeypatch.setattr(type(unrelated_binary), "claim_processing_lock", lambda self, lock_seconds=60: True)

    run_calls: list[tuple[str, list[str] | None, bool]] = []
    binary_calls: list[str] = []

    class _StopScheduling(Exception):
        pass

    def fake_run_crawl(crawl_id, snapshot_ids=None, selected_plugins=None, process_discovered_snapshots_inline=True):
        run_calls.append((crawl_id, snapshot_ids, process_discovered_snapshots_inline))
        raise _StopScheduling

    def fake_run_binary(binary_id):
        binary_calls.append(binary_id)

    monkeypatch.setattr(runner_module, "run_crawl", fake_run_crawl)
    monkeypatch.setattr(runner_module, "run_binary", fake_run_binary)

    with pytest.raises(_StopScheduling):
        runner_module.run_pending_crawls(daemon=False)

    assert run_calls == [(str(queued_crawl.id), None, True)]
    assert binary_calls == []


def test_run_pending_crawls_disables_missing_absolute_binary_backlog(monkeypatch, tmp_path):
    from archivebox.machine.models import Binary, Machine
    from archivebox.services import runner as runner_module

    missing_binary = tmp_path / "missing-node"
    binary = Binary.objects.create(
        machine=Machine.current(),
        name=str(missing_binary),
        status=Binary.StatusChoices.QUEUED,
        retry_at=runner_module.timezone.now(),
        binproviders="env,apt",
        overrides={"apt": {"install_args": ["nodejs"]}},
    )

    monkeypatch.setattr(
        runner_module,
        "run_binary",
        lambda binary_id: (_ for _ in ()).throw(AssertionError("missing absolute binary should not be retried")),
    )

    result = runner_module.run_pending_crawls(daemon=False)

    binary.refresh_from_db()
    assert result == 0
    assert binary.status == Binary.StatusChoices.QUEUED
    assert binary.retry_at is None


@pytest.mark.django_db(transaction=True)
def test_crawl_completed_event_requeues_active_snapshots():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.crawl_service import CrawlService
    from abx_dl.events import CrawlCompletedEvent
    from abx_dl.orchestrator import create_bus

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
        retry_at=None,
    )
    Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
        retry_at=None,
    )

    bus = create_bus(name=f"test_crawl_completed_active_snapshots_{str(crawl.id).replace('-', '_')}")
    CrawlService(bus, crawl_id=str(crawl.id))
    try:

        async def emit_completed() -> None:
            event = CrawlCompletedEvent(
                url="https://example.com",
                snapshot_id="",
                output_dir=str(crawl.output_dir),
            )
            emitted = bus.emit(event)
            await emitted.now()
            await emitted.event_results_list()

        asyncio.run(emit_completed())
    finally:
        asyncio.run(bus.wait_until_idle())
        asyncio.run(bus.destroy())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None


@pytest.mark.django_db(transaction=True)
def test_crawl_cleanup_event_requeues_unfinished_crawl():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.crawl_service import CrawlService
    from abx_dl.events import CrawlCleanupEvent
    from abx_dl.orchestrator import create_bus

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
        retry_at=None,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
        retry_at=None,
    )

    bus = create_bus(name=f"test_crawl_cleanup_requeues_unfinished_{str(crawl.id).replace('-', '_')}")
    CrawlService(bus, crawl_id=str(crawl.id))
    try:

        async def emit_cleanup() -> None:
            event = CrawlCleanupEvent(
                url="https://example.com",
                snapshot_id=str(snapshot.id),
                output_dir=str(crawl.output_dir),
            )
            emitted = bus.emit(event)
            await emitted.now()
            await emitted.event_results_list()

        asyncio.run(emit_cleanup())
    finally:
        asyncio.run(bus.wait_until_idle())
        asyncio.run(bus.destroy())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None


@pytest.mark.django_db(transaction=True)
def test_crawl_cleanup_event_seals_finished_crawl():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.crawl_service import CrawlService
    from abx_dl.events import CrawlCleanupEvent
    from abx_dl.orchestrator import create_bus
    from django.utils import timezone

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
        retry_at=timezone.now(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
    )

    bus = create_bus(name=f"test_crawl_cleanup_finished_crawl_{str(crawl.id).replace('-', '_')}")
    CrawlService(bus, crawl_id=str(crawl.id))
    try:

        async def emit_cleanup() -> None:
            event = CrawlCleanupEvent(
                url="https://example.com",
                snapshot_id=str(snapshot.id),
                output_dir=str(crawl.output_dir),
            )
            emitted = bus.emit(event)
            await emitted.now()
            await emitted.event_results_list()

        asyncio.run(emit_cleanup())
    finally:
        asyncio.run(bus.wait_until_idle())
        asyncio.run(bus.destroy())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None


@pytest.mark.django_db(transaction=True)
def test_snapshot_completed_event_seals_finished_crawl():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.snapshot_service import SnapshotService
    from abx_dl.events import SnapshotCompletedEvent
    from abx_dl.orchestrator import create_bus
    from django.utils import timezone

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
        retry_at=timezone.now(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
        retry_at=None,
    )

    bus = create_bus(name=f"test_snapshot_completed_finished_crawl_{str(crawl.id).replace('-', '_')}")
    service = SnapshotService(bus, crawl_id=str(crawl.id), schedule_snapshot=lambda snapshot_id: asyncio.sleep(0))
    try:

        async def emit_completed() -> None:
            await service.on_SnapshotCompletedEvent(
                SnapshotCompletedEvent(
                    url="https://example.com",
                    snapshot_id=str(snapshot.id),
                    output_dir=str(snapshot.output_dir),
                ),
            )

        asyncio.run(emit_completed())
    finally:
        asyncio.run(bus.destroy())

    snapshot.refresh_from_db()
    crawl.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None


@pytest.mark.django_db(transaction=True)
def test_snapshot_completed_event_bus_seals_finished_crawl():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.snapshot_service import SnapshotService
    from abx_dl.events import SnapshotCompletedEvent
    from abx_dl.orchestrator import create_bus
    from django.utils import timezone

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
        retry_at=timezone.now(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
        retry_at=None,
    )

    bus = create_bus(name=f"test_snapshot_completed_bus_finished_crawl_{str(crawl.id).replace('-', '_')}")
    service = SnapshotService(bus, crawl_id=str(crawl.id), schedule_snapshot=lambda snapshot_id: asyncio.sleep(0))
    assert service is not None
    try:

        async def emit_completed() -> None:
            emitted = bus.emit(
                SnapshotCompletedEvent(
                    url="https://example.com",
                    snapshot_id=str(snapshot.id),
                    output_dir=str(snapshot.output_dir),
                ),
            )
            await emitted.wait()
            await emitted.event_results_list()

        asyncio.run(emit_completed())
    finally:
        asyncio.run(bus.wait_until_idle())
        asyncio.run(bus.destroy())

    snapshot.refresh_from_db()
    crawl.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None
