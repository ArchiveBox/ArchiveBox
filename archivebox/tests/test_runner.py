import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import RequestFactory


pytestmark = pytest.mark.django_db


class _DummyBus:
    def __init__(self, name: str):
        self.name = name
        self.registrations = []

    def on(self, event_pattern, handler):
        registration = SimpleNamespace(event_pattern=event_pattern, handler=handler)
        self.registrations.append(registration)
        return registration

    def off(self, event_pattern, registration):
        self.registrations = [existing for existing in self.registrations if existing is not registration]

    async def stop(self):
        return None


class _DummyService:
    def __init__(self, *args, **kwargs):
        pass


class _DummyAbxServices:
    def __init__(self):
        self.process = SimpleNamespace(wait_for_background_monitors=self._wait)

    async def _wait(self):
        return None


async def _call_sync(func, *args, **kwargs):
    return func(*args, **kwargs)


def test_run_snapshot_uses_isolated_bus_per_snapshot(monkeypatch):
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

    def fake_create_bus(*, name, total_timeout=3600.0, **kwargs):
        bus = _DummyBus(name)
        created_buses.append(bus)
        return bus

    monkeypatch.setattr(runner_module, "create_bus", fake_create_bus)
    monkeypatch.setattr(runner_module, "discover_plugins", lambda: {})
    monkeypatch.setattr(runner_module, "ProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "MachineService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "SnapshotService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: _DummyAbxServices())

    download_calls = []

    async def fake_download(*, url, bus, config_overrides, snapshot, **kwargs):
        download_calls.append(
            {
                "url": url,
                "bus": bus,
                "snapshot_id": config_overrides["SNAPSHOT_ID"],
                "source_url": config_overrides["SOURCE_URL"],
                "abx_snapshot_id": snapshot.id,
            },
        )
        await asyncio.sleep(0)
        return []

    monkeypatch.setattr(runner_module, "download", fake_download)

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
            "parent_snapshot_id": str(snapshot_a.parent_snapshot_id) if snapshot_a.parent_snapshot_id else None,
            "output_dir": str(snapshot_a.output_dir),
            "config": crawl_runner._snapshot_config(snapshot_a),
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
            "parent_snapshot_id": str(snapshot_b.parent_snapshot_id) if snapshot_b.parent_snapshot_id else None,
            "output_dir": str(snapshot_b.output_dir),
            "config": crawl_runner._snapshot_config(snapshot_b),
        },
    }
    monkeypatch.setattr(crawl_runner, "_load_snapshot_run_data", lambda snapshot_id: snapshot_data[snapshot_id])

    async def run_both():
        await asyncio.gather(
            crawl_runner._run_snapshot(str(snapshot_a.id)),
            crawl_runner._run_snapshot(str(snapshot_b.id)),
        )

    asyncio.run(run_both())

    assert len(download_calls) == 2
    assert {call["snapshot_id"] for call in download_calls} == {str(snapshot_a.id), str(snapshot_b.id)}
    assert {call["source_url"] for call in download_calls} == {snapshot_a.url, snapshot_b.url}
    assert len({id(call["bus"]) for call in download_calls}) == 2
    assert len(created_buses) == 3  # 1 crawl bus + 2 isolated snapshot buses


def test_ensure_background_runner_starts_when_none_running(monkeypatch):
    import archivebox.machine.models as machine_models
    from archivebox.services import runner as runner_module

    popen_calls = []

    class DummyPopen:
        def __init__(self, args, **kwargs):
            popen_calls.append((args, kwargs))

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
    from archivebox.services import runner as runner_module

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
    monkeypatch.setattr(runner_module, "create_bus", lambda **kwargs: _DummyBus(kwargs["name"]))
    monkeypatch.setattr(runner_module, "ProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "MachineService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "SnapshotService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)

    from archivebox.machine.models import NetworkInterface, Process
    from archivebox.config import configset as configset_module

    refresh_calls = []
    monkeypatch.setattr(NetworkInterface, "current", classmethod(lambda cls, refresh=False: refresh_calls.append(refresh) or _Iface()))
    monkeypatch.setattr(Process, "current", classmethod(lambda cls: proc))
    monkeypatch.setattr(configset_module, "get_config", lambda **kwargs: {})

    crawl_runner = runner_module.CrawlRunner(crawl)
    crawl_runner._prepare()

    assert refresh_calls == [True]
    assert proc.iface is not None
    assert proc.machine == proc.iface.machine
    assert saved_updates == [("iface", "machine", "modified_at")]


def test_installed_binary_config_overrides_include_valid_installed_binaries(monkeypatch):
    from archivebox.machine.models import Binary, Machine
    from archivebox.services import runner as runner_module
    from abx_dl.models import Plugin

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
        config={},
    )
    mercury_binary = Binary.objects.create(
        machine=machine,
        name="postlight-parser",
        abspath=sys.executable,
        version="2.0.0",
        binprovider="pip",
        binproviders="env,pip",
        status=Binary.StatusChoices.INSTALLED,
    )
    wget_binary = Binary.objects.create(
        machine=machine,
        name="wget",
        abspath="/tmp/not-an-executable",
        version="1.0.0",
        binprovider="env",
        binproviders="env",
        status=Binary.StatusChoices.INSTALLED,
    )

    monkeypatch.setattr(Machine, "current", classmethod(lambda cls: machine))
    monkeypatch.setattr(Path, "is_file", lambda self: str(self) in {sys.executable, mercury_binary.abspath, wget_binary.abspath})
    monkeypatch.setattr(
        runner_module.os,
        "access",
        lambda path, mode: str(path) == sys.executable,
    )

    overrides = runner_module._installed_binary_config_overrides(
        {
            "mercury": Plugin(
                name="mercury",
                path=Path("."),
                hooks=[],
                config_schema={"MERCURY_BINARY": {"type": "string", "default": "postlight-parser"}},
            ),
        },
    )

    assert overrides["MERCURY_BINARY"] == sys.executable
    assert overrides["POSTLIGHT_PARSER_BINARY"] == sys.executable
    assert "WGET_BINARY" not in overrides


def test_run_snapshot_skips_descendant_when_max_size_already_reached(monkeypatch):
    import asgiref.sync

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.services import runner as runner_module

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        max_size=16,
    )

    monkeypatch.setattr(runner_module, "discover_plugins", lambda: {})
    monkeypatch.setattr(runner_module, "create_bus", lambda **kwargs: _DummyBus(kwargs["name"]))
    monkeypatch.setattr(runner_module, "ProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "MachineService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "SnapshotService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)
    monkeypatch.setattr(runner_module, "_limit_stop_reason", lambda config: "max_size")
    monkeypatch.setattr(
        asgiref.sync,
        "sync_to_async",
        lambda func, thread_sensitive=True: lambda *args, **kwargs: _call_sync(func, *args, **kwargs),
    )
    monkeypatch.setattr(
        runner_module,
        "download",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("snapshot download should have been skipped")),
    )

    crawl_runner = runner_module.CrawlRunner(crawl)
    cancelled: list[str] = []
    crawl_runner._load_snapshot_run_data = lambda snapshot_id: {
        "id": snapshot_id,
        "url": "https://example.com/child",
        "title": "",
        "timestamp": "",
        "bookmarked_at": "",
        "created_at": "",
        "tags": "",
        "depth": 1,
        "status": "queued",
        "parent_snapshot_id": None,
        "output_dir": "/tmp/child",
        "config": {"CRAWL_DIR": "/tmp/crawl", "MAX_SIZE": 16},
    }
    crawl_runner._cancel_snapshot_due_to_limit = lambda snapshot_id: cancelled.append(snapshot_id)

    asyncio.run(crawl_runner._run_snapshot("child-1"))

    assert cancelled == ["child-1"]


def test_seal_snapshot_cancels_queued_descendants_after_max_size():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.snapshot_service import SnapshotService
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

    bus = create_bus(name="test_snapshot_limit_cancel")
    service = SnapshotService(bus, crawl_id=str(crawl.id), schedule_snapshot=lambda snapshot_id: None)
    try:
        sealed_id = service._seal_snapshot(str(root.id))
    finally:
        asyncio.run(bus.stop())

    root.refresh_from_db()
    child.refresh_from_db()
    assert sealed_id == str(root.id)
    assert root.status == Snapshot.StatusChoices.SEALED
    assert child.status == Snapshot.StatusChoices.SEALED
    assert child.retry_at is None


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
    import asgiref.sync
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

    monkeypatch.setattr(runner_module, "_attach_bus_trace", lambda bus: None)
    monkeypatch.setattr(runner_module, "_stop_bus_trace", lambda bus: asyncio.sleep(0))
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: _DummyAbxServices())
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    monkeypatch.setattr(
        asgiref.sync,
        "sync_to_async",
        lambda func, thread_sensitive=True: lambda *args, **kwargs: _call_sync(func, *args, **kwargs),
    )
    monkeypatch.setattr(Crawl.objects, "get", lambda id: crawl)
    monkeypatch.setattr(crawl, "is_finished", lambda: False)
    monkeypatch.setattr(crawl, "save", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_prepare", lambda self: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_create_live_ui", lambda self: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_initial_snapshot_ids", lambda self: [str(snapshot.id)])
    monkeypatch.setattr(runner_module.CrawlRunner, "_run_crawl_setup", lambda self, snapshot_id: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "enqueue_snapshot", lambda self, snapshot_id: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "_wait_for_snapshot_tasks", lambda self: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "_run_crawl_cleanup", lambda self, snapshot_id: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "_cleanup_persona", lambda self: None)

    asyncio.run(runner_module.CrawlRunner(crawl, snapshot_ids=[str(snapshot.id)]).run())

    assert crawl.status != Crawl.StatusChoices.SEALED
    assert crawl.retry_at is not None


def test_crawl_runner_finalizes_with_sync_to_async_for_is_finished(monkeypatch):
    import asgiref.sync
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
    monkeypatch.setattr(runner_module, "ProcessService", _DummyService)
    monkeypatch.setattr(runner_module, "MachineService", _DummyService)
    monkeypatch.setattr(runner_module, "BinaryService", _DummyService)
    monkeypatch.setattr(runner_module, "TagService", _DummyService)
    monkeypatch.setattr(runner_module, "CrawlService", _DummyService)
    monkeypatch.setattr(runner_module, "SnapshotService", _DummyService)
    monkeypatch.setattr(runner_module, "ArchiveResultService", _DummyService)
    monkeypatch.setattr(runner_module, "_attach_bus_trace", lambda bus: None)
    monkeypatch.setattr(runner_module, "_stop_bus_trace", lambda bus: asyncio.sleep(0))
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: _DummyAbxServices())
    monkeypatch.setattr(Crawl.objects, "get", lambda id: crawl)
    monkeypatch.setattr(crawl, "save", lambda *args, **kwargs: None)
    monkeypatch.setattr(crawl, "cleanup", lambda: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_prepare", lambda self: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_create_live_ui", lambda self: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_initial_snapshot_ids", lambda self: [str(snapshot.id)])
    monkeypatch.setattr(runner_module.CrawlRunner, "_run_crawl_setup", lambda self, snapshot_id: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "enqueue_snapshot", lambda self, snapshot_id: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "_wait_for_snapshot_tasks", lambda self: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "_run_crawl_cleanup", lambda self, snapshot_id: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "_cleanup_persona", lambda self: None)

    sync_to_async_wrapped: list[str] = []
    sync_to_async_active = False

    def fake_sync_to_async(func, thread_sensitive=True):
        async def wrapper(*args, **kwargs):
            nonlocal sync_to_async_active
            sync_to_async_wrapped.append(getattr(func, "__name__", repr(func)))
            previous = sync_to_async_active
            sync_to_async_active = True
            try:
                return func(*args, **kwargs)
            finally:
                sync_to_async_active = previous

        return wrapper

    def guarded_is_finished():
        assert sync_to_async_active is True
        return False

    monkeypatch.setattr(asgiref.sync, "sync_to_async", fake_sync_to_async)
    monkeypatch.setattr(crawl, "is_finished", guarded_is_finished)

    asyncio.run(runner_module.CrawlRunner(crawl, snapshot_ids=[str(snapshot.id)]).run())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None
    assert "guarded_is_finished" in sync_to_async_wrapped


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
            await crawl_runner._wait_for_snapshot_tasks()

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
        await asyncio.wait_for(crawl_runner._wait_for_snapshot_tasks(), timeout=0.5)
        assert crawl_runner.snapshot_tasks == {}

    asyncio.run(run_test())


def test_crawl_runner_calls_crawl_cleanup_after_snapshot_phase(monkeypatch):
    import asgiref.sync
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

    monkeypatch.setattr(runner_module, "_attach_bus_trace", lambda bus: None)
    monkeypatch.setattr(runner_module, "_stop_bus_trace", lambda bus: asyncio.sleep(0))
    monkeypatch.setattr(runner_module, "setup_abx_services", lambda *args, **kwargs: _DummyAbxServices())
    monkeypatch.setenv("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    monkeypatch.setattr(
        asgiref.sync,
        "sync_to_async",
        lambda func, thread_sensitive=True: lambda *args, **kwargs: _call_sync(func, *args, **kwargs),
    )
    monkeypatch.setattr(Crawl.objects, "get", lambda id: crawl)
    monkeypatch.setattr(crawl, "is_finished", lambda: False)
    monkeypatch.setattr(crawl, "save", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_prepare", lambda self: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_create_live_ui", lambda self: None)
    monkeypatch.setattr(runner_module.CrawlRunner, "_initial_snapshot_ids", lambda self: [str(snapshot.id)])
    monkeypatch.setattr(runner_module.CrawlRunner, "_run_crawl_setup", lambda self, snapshot_id: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "enqueue_snapshot", lambda self, snapshot_id: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "_wait_for_snapshot_tasks", lambda self: asyncio.sleep(0))
    monkeypatch.setattr(runner_module.CrawlRunner, "_cleanup_persona", lambda self: None)

    cleanup_calls = []
    monkeypatch.setattr(
        runner_module.CrawlRunner,
        "_run_crawl_cleanup",
        lambda self, snapshot_id: cleanup_calls.append("abx_cleanup") or asyncio.sleep(0),
    )
    monkeypatch.setattr(crawl, "cleanup", lambda: cleanup_calls.append("crawl_cleanup"))

    asyncio.run(runner_module.CrawlRunner(crawl, snapshot_ids=[str(snapshot.id)]).run())

    assert cleanup_calls == ["crawl_cleanup", "abx_cleanup"]


def test_abx_process_service_background_monitor_finishes_after_process_exit(monkeypatch, tmp_path):
    from abx_dl.models import Process as AbxProcess, now_iso
    from abx_dl.services.process_service import ProcessService
    from abx_dl.events import ProcessCompletedEvent

    service = object.__new__(ProcessService)
    service.emit_jsonl = False
    emitted_events = []

    async def fake_emit_event(event, *, detach_from_parent):
        emitted_events.append((event, detach_from_parent))

    async def fake_stream_stdout(**kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return ["daemon output\n"]

    service._emit_event = fake_emit_event
    monkeypatch.setattr(service, "_stream_stdout", fake_stream_stdout)

    class FakeAsyncProcess:
        def __init__(self):
            self.pid = 42424
            self.returncode = None

        async def wait(self):
            await asyncio.sleep(0)
            self.returncode = 0
            return 0

    plugin_output_dir = tmp_path / "chrome"
    plugin_output_dir.mkdir()
    stdout_file = plugin_output_dir / "on_Crawl__90_chrome_launch.daemon.bg.stdout.log"
    stderr_file = plugin_output_dir / "on_Crawl__90_chrome_launch.daemon.bg.stderr.log"
    stderr_file.write_text("")
    pid_file = plugin_output_dir / "on_Crawl__90_chrome_launch.daemon.bg.pid"
    pid_file.write_text("12345")

    proc = AbxProcess(
        cmd=["hook"],
        pwd=str(plugin_output_dir),
        timeout=60,
        started_at=now_iso(),
        plugin="chrome",
        hook_name="on_Crawl__90_chrome_launch.daemon.bg",
    )
    process = FakeAsyncProcess()
    event = SimpleNamespace(
        plugin_name="chrome",
        hook_name="on_Crawl__90_chrome_launch.daemon.bg",
        hook_path="hook",
        hook_args=["--url=https://example.org/"],
        env={},
        output_dir=str(plugin_output_dir),
        timeout=60,
        snapshot_id="snap-1",
        is_background=True,
    )

    async def run_test():
        await asyncio.wait_for(
            service._monitor_background_process(
                event=event,
                proc=proc,
                process=process,
                plugin_output_dir=plugin_output_dir,
                stdout_file=stdout_file,
                stderr_file=stderr_file,
                pid_file=pid_file,
                files_before=set(),
            ),
            timeout=0.5,
        )

    asyncio.run(run_test())

    assert pid_file.exists() is False
    assert any(isinstance(event, ProcessCompletedEvent) for event, _ in emitted_events)


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
    assert run_calls == [(str(crawl.id), [str(snapshot.id)], False)]


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

    assert run_calls == [(str(newer_crawl.id), None, False)]
