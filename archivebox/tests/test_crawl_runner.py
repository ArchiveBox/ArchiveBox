import asyncio
from importlib.resources import files
from pathlib import Path
import sys

import pytest
from asgiref.sync import sync_to_async

from archivebox.tests.conftest import install_real_binary, resolve_abxpkg_binary_env

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
def test_crawl_runner_creates_progress_reporter_without_a_tty(crawl):
    from archivebox.services.runner import CrawlRunner

    runner = CrawlRunner(crawl)
    runner.load_run_state()

    live_ui = runner._create_live_ui()

    assert live_ui is not None
    assert live_ui.interactive_tty is False
    asyncio.run(runner.bus.destroy(clear=False))


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
            await sync_to_async(Crawl.objects.filter(id=crawl.id).update, thread_sensitive=True)(
                status=Crawl.StatusChoices.SEALED,
                retry_at=None,
            )
            await runner.watch_for_cancelled_crawl(event, poll_interval=0)
            abort_event = await runner.bus.find(CrawlAbortEvent, child_of=event, past=True, future=1.0)
            abort_event_holder["event"] = abort_event if isinstance(abort_event, CrawlAbortEvent) else None

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
def test_snapshot_payload_uses_crawl_chrome_dirs_by_default():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.personas.models import Persona
    from archivebox.services.runner import CrawlRunner

    persona = Persona(name="RuntimePersona")
    persona.save()
    crawl = Crawl(
        urls="https://example.com",
        persona_id=persona.id,
        created_by_id=get_or_create_system_user_pk(),
    )
    crawl.save()
    snapshot = Snapshot(url="https://example.com", crawl=crawl)
    snapshot.save()
    other_snapshot = Snapshot(url="https://example.org", crawl=crawl)
    other_snapshot.save()

    runner = CrawlRunner(crawl)
    runner.load_run_state()
    crawl_downloads_sentinel = persona.runtime_downloads_dir_for_crawl(crawl) / "keep.txt"
    crawl_downloads_sentinel.write_text("keep")
    payload = runner.load_snapshot_payload(str(snapshot.id))
    other_payload = runner.load_snapshot_payload(str(other_snapshot.id))
    config = payload["config"]
    other_config = other_payload["config"]

    personas_dir = Path(config["PERSONAS_DIR"])
    other_personas_dir = Path(other_config["PERSONAS_DIR"])
    assert personas_dir.is_relative_to(crawl.output_dir)
    assert personas_dir == persona.runtime_root_for_crawl(crawl).parent
    assert personas_dir == other_personas_dir
    assert personas_dir / config["ACTIVE_PERSONA"] / "chrome_profile" == persona.runtime_profile_dir_for_crawl(crawl)
    assert personas_dir / config["ACTIVE_PERSONA"] / "chrome_downloads" == persona.runtime_downloads_dir_for_crawl(crawl)
    assert crawl_downloads_sentinel.read_text() == "keep"
    assert config["ACTIVE_PERSONA"] == "RuntimePersona"
    assert Path(config["CRAWL_DIR"]) == crawl.output_dir
    assert Path(config["SNAP_DIR"]) == snapshot.output_dir


@pytest.mark.django_db(transaction=True)
def test_snapshot_payload_uses_snapshot_chrome_dirs_when_snapshot_isolated():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.personas.models import Persona
    from archivebox.services.runner import CrawlRunner

    persona = Persona(name="SnapshotRuntimePersona")
    persona.save()
    crawl = Crawl(
        urls="https://example.com\nhttps://example.org",
        persona_id=persona.id,
        created_by_id=get_or_create_system_user_pk(),
        config={"CHROME_ISOLATION": "snapshot"},
    )
    crawl.save()
    snapshot = Snapshot(url="https://example.com", crawl=crawl)
    snapshot.save()
    other_snapshot = Snapshot(url="https://example.org", crawl=crawl)
    other_snapshot.save()

    runner = CrawlRunner(crawl)
    runner.load_run_state()
    payload = runner.load_snapshot_payload(str(snapshot.id))
    other_payload = runner.load_snapshot_payload(str(other_snapshot.id))
    config = payload["config"]
    other_config = other_payload["config"]

    personas_dir = Path(config["PERSONAS_DIR"])
    other_personas_dir = Path(other_config["PERSONAS_DIR"])
    assert personas_dir.is_relative_to(snapshot.output_dir)
    assert other_personas_dir.is_relative_to(other_snapshot.output_dir)
    assert personas_dir == persona.runtime_root_for_snapshot(snapshot).parent
    assert other_personas_dir == persona.runtime_root_for_snapshot(other_snapshot).parent
    assert personas_dir != other_personas_dir
    assert personas_dir / config["ACTIVE_PERSONA"] / "chrome_profile" == persona.runtime_profile_dir_for_snapshot(snapshot)
    assert personas_dir / config["ACTIVE_PERSONA"] / "chrome_downloads" == persona.runtime_downloads_dir_for_snapshot(snapshot)
    assert Path(config["CRAWL_DIR"]) == crawl.output_dir
    assert Path(config["SNAP_DIR"]) == snapshot.output_dir


@pytest.mark.django_db(transaction=True)
def test_ensure_background_runner_does_not_start_duplicate_orchestrator():
    import os
    from datetime import datetime

    import psutil
    from archivebox.machine.models import Machine, Process
    from archivebox.services.runner import ensure_background_runner
    from archivebox.workers.supervisord_util import get_existing_supervisord_process, stop_existing_supervisord_process
    from django.utils import timezone

    stop_existing_supervisord_process()
    assert get_existing_supervisord_process(quiet=True) is None
    os_proc = psutil.Process(os.getpid())
    process = Process.objects.create(
        machine=Machine.current(),
        process_type=Process.TypeChoices.ORCHESTRATOR,
        status=Process.StatusChoices.RUNNING,
        pid=os.getpid(),
        started_at=datetime.fromtimestamp(os_proc.create_time(), tz=timezone.get_current_timezone()),
        timeout=1,
    )

    assert ensure_background_runner() is False
    process.refresh_from_db()
    assert process.status == Process.StatusChoices.RUNNING


@pytest.mark.django_db(transaction=True)
def test_ensure_background_runner_does_not_spawn_runner_without_supervisord():
    from archivebox.services.runner import ensure_background_runner
    from archivebox.workers.supervisord_util import get_existing_supervisord_process, stop_existing_supervisord_process

    stop_existing_supervisord_process()
    assert get_existing_supervisord_process(quiet=True) is None

    assert ensure_background_runner() is False
    assert get_existing_supervisord_process(quiet=True) is None


def test_runner_task_context_clears_inherited_abxbus_handler_context(tmp_path):
    from abx_dl.events import CrawlEvent, MachineEvent
    from abx_dl.orchestrator import create_bus
    from abxbus.event_bus import in_handler_context
    from archivebox.services import runner as runner_module

    bus = create_bus(name="test_runner_task_context_clears_inherited_abxbus_handler_context")
    observations = []

    async def emit_from_runner_task():
        observations.append(("in_handler_context", in_handler_context()))
        machine_event = bus.emit(MachineEvent(config={"TIMEOUT": "30"}, config_type="user"))
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
def test_snapshot_started_state_keeps_retry_at_lease():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from django.utils import timezone

    before = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
        retry_at=before,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
        retry_at=before,
    )

    assert snapshot.tick_claimed(lock_seconds=60) is True

    snapshot.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.STARTED
    assert snapshot.retry_at is not None
    assert snapshot.retry_at > before


@pytest.mark.django_db(transaction=True)
def test_crawl_start_event_keeps_retry_at_lease():
    from abx_dl.events import CrawlStartEvent
    from abx_dl.orchestrator import create_bus
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.crawl_service import CrawlService
    from django.utils import timezone

    before = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.QUEUED,
        retry_at=before,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
        retry_at=before,
    )
    bus = create_bus(name="test_crawl_start_event_keeps_retry_at_lease")
    CrawlService(bus, crawl_id=str(crawl.id))

    async def run_event():
        try:
            await bus.emit(
                CrawlStartEvent(
                    url=snapshot.url,
                    snapshot_id=str(snapshot.id),
                    output_dir=str(crawl.output_dir),
                ),
            ).now()
            await bus.wait_until_idle()
        finally:
            await bus.destroy(clear=False)

    asyncio.run(run_event())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None
    assert crawl.retry_at > before


@pytest.mark.django_db(transaction=True)
def test_crawl_start_event_does_not_reschedule_sealed_parent_until_explicit_requeue():
    from abx_dl.events import CrawlStartEvent
    from abx_dl.orchestrator import create_bus
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.crawl_service import CrawlService
    from django.utils import timezone

    before = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.SEALED,
        retry_at=before,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=before,
    )
    crawl_output_dir = str(crawl.output_dir)

    async def emit_start(name: str) -> None:
        bus = create_bus(name=name)
        try:
            CrawlService(bus, crawl_id=str(crawl.id))
            emitted = bus.emit(
                CrawlStartEvent(
                    url=snapshot.url,
                    snapshot_id=str(snapshot.id),
                    output_dir=crawl_output_dir,
                ),
            )
            await emitted.now()
            await emitted.event_results_list()
            await bus.wait_until_idle()
        finally:
            await bus.destroy(clear=False)

    asyncio.run(emit_start("test_crawl_start_event_sealed_parent_noop"))

    crawl.refresh_from_db()
    snapshot.refresh_from_db()
    # CrawlStartEvent on a sealed parent is a no-op — neither the parent nor
    # its sealed child gets resurrected by the handler.
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at == before
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert snapshot.retry_at == before

    # The orchestrator's seal-cleanup pass picks the sealed row up via
    # retry_at, runs cleanup, and clears retry_at — that's how the
    # ``retry_at != None`` invariant the handler intentionally preserves
    # eventually drains to ``None``.
    from archivebox.services.runner import run_due_crawl

    assert run_due_crawl(crawl, lock_seconds=10) is True
    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None

    crawl.update_and_requeue(status=Crawl.StatusChoices.QUEUED, retry_at=timezone.now())
    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.QUEUED

    asyncio.run(emit_start("test_crawl_start_event_after_explicit_requeue"))

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None
    assert crawl.retry_at > before


@pytest.mark.django_db(transaction=True)
def test_snapshot_queue_selection_is_retry_at_only_for_sealed_maintenance():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from django.utils import timezone

    now = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=now,
    )

    assert Snapshot.get_queue().filter(id=snapshot.id).exists()


@pytest.mark.django_db(transaction=True)
def test_machine_service_persists_only_derived_config_events(tmp_path, hermetic_lib_dir):
    from abx_dl.events import MachineEvent
    from abx_dl.orchestrator import create_bus
    from archivebox.machine.models import Machine
    from archivebox.services.machine_service import MachineService

    machine = Machine.current()
    machine.config = {}
    machine.save(update_fields=["config"])
    install_real_binary("wget", machine=machine, binproviders="env,apt,brew")
    resolve_abxpkg_binary_env(hermetic_lib_dir, "wget")
    wget_binary = hermetic_lib_dir / "env" / "bin" / "wget"
    assert wget_binary.is_symlink()

    async def run_test():
        bus = create_bus(name="test_machine_service_persists_only_derived_config_events")
        try:
            MachineService(bus)
            user_event = bus.emit(
                MachineEvent(
                    config={
                        "CHROME_ISOLATION": "snapshot",
                        "CHROME_USER_DATA_DIR": "/tmp/stale-profile",
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
                        "ABX_UV_CACHE": "/tmp/uv-cache",
                        "ABX_PNPM_CACHE": "/tmp/pnpm-cache",
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
    # User events are dropped (handler ignores non-derived). At the event
    # projector ``machine_service.py`` strips anything that isn't a binary
    # path / install cache — that's the security boundary that stops plugins
    # from rewriting arbitrary user config via events. So CHROME_USER_DATA_DIR
    # from the derived payload is dropped; WGET_BINARY made it in (inside
    # ABXPKG_LIB_DIR) then the unset removed it; ABX_INSTALL_CACHE survives.
    assert machine.config == {
        "ABX_INSTALL_CACHE": {"wget": "2026-03-24T00:00:00+00:00"},
        "ABX_PNPM_CACHE": "/tmp/pnpm-cache",
        "ABX_UV_CACHE": "/tmp/uv-cache",
    }


@pytest.mark.django_db(transaction=True)
def test_load_run_state_uses_real_lib_dir_for_machine_binary_config(tmp_path, hermetic_lib_dir):
    import archivebox.machine.models as machine_models
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.config.common import get_config
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine
    from archivebox.services.runner import CrawlRunner

    resolved_lib_dir = get_config(include_machine=False).ABXPKG_LIB_DIR
    assert resolved_lib_dir == hermetic_lib_dir, f"ABXPKG_LIB_DIR override not applied: {resolved_lib_dir!r} != {hermetic_lib_dir!r}"

    install_real_binary("wget", binproviders="env,apt,brew")
    resolve_abxpkg_binary_env(resolved_lib_dir, "wget")
    wget_binary = resolved_lib_dir / "env" / "bin" / "wget"
    assert wget_binary.is_symlink()
    external_binary = Path(sys.executable)

    machine = Machine.current()
    machine.config = {
        "WGET_BINARY": str(wget_binary),
        "YTDLP_BINARY": str(external_binary),
        "ABX_INSTALL_CACHE": {"wget": "2026-03-24T00:00:00+00:00"},
        "CHROME_ISOLATION": "snapshot",
        "CHROME_USER_DATA_DIR": "/tmp/stale-profile",
    }
    machine.save(update_fields=["config"])
    machine_models._CURRENT_MACHINE = machine

    crawl = Crawl.objects.create(
        urls="https://example.com",
        config={
            "PLUGINS": "__archivebox_test_no_plugins__",
            "CHROME_BINARY": "",
        },
        created_by_id=get_or_create_system_user_pk(),
    )

    runner = CrawlRunner(crawl)
    snapshot_ids = runner.load_run_state()

    # ``derived_config`` is Machine.config sanitized against ABXPKG_LIB_DIR. Binary
    # paths outside ABXPKG_LIB_DIR drop out (YTDLP_BINARY → ``/tmp/...``); the
    # ArchiveBox.conf mirror values (CHROME_ISOLATION, CHROME_USER_DATA_DIR,
    # ABX_INSTALL_CACHE) survive so plugin hooks see the same runtime cache
    # the user/runner persisted.
    assert runner.derived_config == {
        "WGET_BINARY": str(wget_binary),
        "ABX_INSTALL_CACHE": {"wget": "2026-03-24T00:00:00+00:00"},
        "CHROME_ISOLATION": "snapshot",
        "CHROME_USER_DATA_DIR": "/tmp/stale-profile",
    }
    assert runner.base_config["ABXPKG_LIB_DIR"] == resolved_lib_dir
    assert runner.base_config["CHROME_KEEPALIVE"] is False
    assert runner.selected_plugins == ["__archivebox_test_no_plugins__"]
    assert Snapshot.objects.filter(id__in=snapshot_ids, crawl=crawl, url="https://example.com").count() == 1


@pytest.mark.django_db(transaction=True)
def test_crawl_runner_empty_plugin_selection_emits_lifecycle_and_seals_crawl(tmp_path):
    from abx_dl.events import CrawlCleanupEvent, CrawlCompletedEvent, CrawlEvent, CrawlSetupEvent, CrawlStartEvent, MachineEvent
    from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.runner import CrawlRunner

    crawl = Crawl.objects.create(
        urls="https://example.com",
        config={
            "ABXPKG_LIB_DIR": str(tmp_path / "lib"),
            "PLUGINS": "__archivebox_test_no_plugins__",
            "CHROME_BINARY": "",
        },
        created_by_id=get_or_create_system_user_pk(),
    )
    runner = CrawlRunner(crawl)

    seen_events = {
        CrawlEvent: [],
        CrawlSetupEvent: [],
        CrawlStartEvent: [],
        SnapshotEvent: [],
        SnapshotCompletedEvent: [],
        CrawlCleanupEvent: [],
        CrawlCompletedEvent: [],
        MachineEvent: [],
    }
    for event_type, events in seen_events.items():
        runner.bus.on(event_type, lambda event, events=events: events.append(event))

    asyncio.run(runner.run())

    crawl_events = seen_events[CrawlEvent]
    setup_events = seen_events[CrawlSetupEvent]
    start_events = seen_events[CrawlStartEvent]
    snapshot_events = seen_events[SnapshotEvent]
    snapshot_completed_events = seen_events[SnapshotCompletedEvent]
    cleanup_events = seen_events[CrawlCleanupEvent]
    completed_events = seen_events[CrawlCompletedEvent]
    machine_events = seen_events[MachineEvent]

    assert len(crawl_events) == 1
    assert len(setup_events) == 1
    assert len(start_events) == 1
    assert len(snapshot_events) == 1
    assert len(snapshot_completed_events) == 1
    assert len(cleanup_events) == 1
    assert len(completed_events) == 1
    assert runner.bus.event_is_child_of(setup_events[0], crawl_events[0])
    assert runner.bus.event_is_child_of(start_events[0], crawl_events[0])
    assert runner.bus.event_is_child_of(cleanup_events[0], crawl_events[0])
    assert runner.bus.event_is_child_of(completed_events[0], crawl_events[0])
    assert runner.bus.event_is_child_of(snapshot_events[0], start_events[0])
    assert runner.bus.event_is_child_of(snapshot_completed_events[0], snapshot_events[0])
    assert any(event.config_type == "user" for event in machine_events)

    crawl.refresh_from_db()
    snapshot = Snapshot.objects.get(crawl=crawl)
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert snapshot.retry_at is None
    assert snapshot.archiveresult_set.count() == 0


@pytest.mark.django_db(transaction=True)
def test_crawl_runner_resolves_persona_and_crawl_config_for_each_live_snapshot():
    from abx_dl.events import SnapshotCompletedEvent
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process
    from archivebox.personas.models import Persona
    from archivebox.services.runner import CrawlRunner

    persona = Persona.objects.create(
        name="RuntimeConfig",
        config={
            "FAVICON_PROVIDER": "https://example.com/persona-first.ico",
            "FAVICON_TIMEOUT": 10,
        },
    )
    persona.ensure_dirs()
    crawl = Crawl.objects.create(
        urls="\n".join(
            [
                "https://www.python.org/",
                "https://www.djangoproject.com/",
                "https://www.wikipedia.org/",
            ],
        ),
        config={
            "PLUGINS": "favicon",
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 1,
        },
        persona_id=persona.id,
        created_by_id=get_or_create_system_user_pk(),
    )
    runner = CrawlRunner(crawl)
    completed_snapshot_ids: list[str] = []

    async def update_config_between_snapshots(event: SnapshotCompletedEvent) -> None:
        if event.snapshot_id in completed_snapshot_ids:
            return
        completed_snapshot_ids.append(event.snapshot_id)
        if len(completed_snapshot_ids) == 1:
            persona.config = {
                **(persona.config or {}),
                "FAVICON_PROVIDER": "https://example.com/persona-second.ico",
            }
            await persona.asave(update_fields=["config"])
        elif len(completed_snapshot_ids) == 2:
            fresh_crawl = await Crawl.objects.aget(id=crawl.id)
            fresh_crawl.config = {
                **(fresh_crawl.config or {}),
                "FAVICON_PROVIDER": "https://example.com/crawl-third.ico",
            }
            await fresh_crawl.asave(update_fields=["config"])

    runner.bus.on(SnapshotCompletedEvent, update_config_between_snapshots)

    asyncio.run(runner.run())

    favicon_processes = [
        process
        for process in Process.objects.filter(process_type=Process.TypeChoices.HOOK).order_by("started_at")
        if process.cmd and "on_Snapshot__37_favicon.finite.bg.py" in str(process.cmd[0])
    ]
    providers = [process.env.get("FAVICON_PROVIDER") for process in favicon_processes]

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert Snapshot.objects.filter(crawl=crawl, status=Snapshot.StatusChoices.SEALED).count() == 3
    assert (
        ArchiveResult.objects.filter(snapshot__crawl=crawl, plugin="favicon").exclude(status=ArchiveResult.StatusChoices.FAILED).count()
        == 3
    )
    assert providers == [
        "https://example.com/persona-first.ico",
        "https://example.com/persona-second.ico",
        "https://example.com/crawl-third.ico",
    ]


@pytest.mark.django_db(transaction=True)
def test_run_pending_crawls_processes_queued_crawl_and_real_binary(tmp_path):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Binary, Machine
    from archivebox.services.runner import run_pending_crawls
    from django.utils import timezone

    crawl = Crawl.objects.create(
        urls="https://example.com",
        config={
            "ABXPKG_LIB_DIR": str(tmp_path / "lib"),
            "PLUGINS": "__archivebox_test_no_plugins__",
            "CHROME_BINARY": "",
        },
        status=Crawl.StatusChoices.QUEUED,
        retry_at=timezone.now(),
        created_by_id=get_or_create_system_user_pk(),
    )
    binary = Binary.objects.create(
        machine=Machine.current(),
        name="bash",
        status=Binary.StatusChoices.QUEUED,
        retry_at=timezone.now(),
        binproviders="env",
    )

    result = run_pending_crawls(daemon=False)

    crawl.refresh_from_db()
    binary.refresh_from_db()
    assert result == 0
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None
    assert Snapshot.objects.filter(crawl=crawl, status=Snapshot.StatusChoices.SEALED).count() == 1
    assert binary.status == Binary.StatusChoices.INSTALLED
    assert binary.retry_at is None
    assert Path(binary.abspath).is_file()
    assert binary.version
    assert binary.binprovider == "env"


@pytest.mark.django_db(transaction=True)
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

    async def run_test():
        task = asyncio.get_running_loop().create_future()
        task.set_result(None)
        crawl_runner.snapshot_tasks["snap-1"] = task
        await asyncio.wait_for(crawl_runner.wait_for_snapshot_tasks(), timeout=0.5)
        assert crawl_runner.snapshot_tasks == {}

    asyncio.run(run_test())


@pytest.mark.django_db(transaction=True)
def test_abx_process_service_background_process_finishes_after_process_exit(tmp_path, recursive_test_site, hermetic_lib_dir):
    from abx_dl.events import ProcessCompletedEvent, ProcessEvent
    from abx_dl.orchestrator import create_bus
    from abx_dl.services.process_service import ProcessService
    from archivebox.machine.models import Process

    bus = create_bus(name="test_abx_process_service_background_process_finishes_after_process_exit")
    ProcessService(bus, emit_jsonl=False, interactive_tty=False)
    emitted_events = []

    async def collect_completed(event):
        emitted_events.append(event)

    bus.on(ProcessCompletedEvent, collect_completed)

    snap_dir = tmp_path / "snapshot"
    plugin_output_dir = snap_dir / "wget"
    plugin_output_dir.mkdir(parents=True)
    hook_path = Path(str(files("abx_plugins.plugins.wget").joinpath("on_Snapshot__35_wget.finite.bg.py")))
    wget_config = Path(str(files("abx_plugins.plugins.wget").joinpath("config.json")))
    install_real_binary("wget", binproviders="env,apt,brew")
    hook_env = resolve_abxpkg_binary_env(hermetic_lib_dir, deps_from=wget_config)

    async def run_test():
        try:
            event = ProcessEvent(
                plugin_name="wget",
                hook_name=hook_path.name,
                hook_path=str(hook_path),
                hook_args=[f"--url={recursive_test_site['root_url']}"],
                env={
                    **hook_env,
                    "ABXPKG_LIB_DIR": str(hermetic_lib_dir),
                    "SNAP_DIR": str(snap_dir),
                },
                output_dir=str(plugin_output_dir),
                timeout=60,
                is_background=True,
                url=recursive_test_site["root_url"],
                process_type="hook",
                worker_type="hook",
            )
            await asyncio.wait_for(bus.emit(event).now(), timeout=0.5)
            completed = await bus.find(ProcessCompletedEvent, past=True, future=5.0)
            assert isinstance(completed, ProcessCompletedEvent)
            await completed.event_results_list()
            assert completed.status == "succeeded"
            records = [record for record in Process.parse_records_from_text(completed.stdout) if record.get("type") == "ArchiveResult"]
            assert records == [
                {
                    "type": "ArchiveResult",
                    "status": "succeeded",
                    "output_str": f"wget/127.0.0.1+{recursive_test_site['base_url'].rsplit(':', 1)[-1]}/index.html",
                },
            ]
            assert completed.output_dir == str(plugin_output_dir)
            assert bus.event_is_child_of(completed, event)
        finally:
            await bus.destroy()

    asyncio.run(run_test())

    assert list(plugin_output_dir.rglob("index.html"))
    assert not list(plugin_output_dir.glob(f"{hook_path.name}.*.pid"))
    assert any(isinstance(event, ProcessCompletedEvent) for event in emitted_events)


@pytest.mark.django_db(transaction=True)
def test_run_pending_crawls_resolves_real_binary_through_abxpkg(tmp_path):
    from archivebox.machine.models import Binary, Machine
    from archivebox.services import runner as runner_module

    binary = Binary.objects.create(
        machine=Machine.current(),
        name="bash",
        status=Binary.StatusChoices.QUEUED,
        retry_at=runner_module.timezone.now(),
        binproviders="env",
    )

    result = runner_module.run_pending_crawls(daemon=False)

    binary.refresh_from_db()
    assert result == 0
    assert binary.status == Binary.StatusChoices.INSTALLED
    assert binary.retry_at is None
    assert Path(binary.abspath).is_file()
    assert binary.version
    assert binary.binprovider == "env"


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
    service = CrawlService(bus, crawl_id=str(crawl.id))
    assert service is not None

    async def emit_completed() -> None:
        try:
            event = CrawlCompletedEvent(
                url="https://example.com",
                snapshot_id="",
                output_dir=str(crawl.output_dir),
            )
            emitted = bus.emit(event)
            await emitted.wait()
            await emitted.event_results_list()
            await bus.wait_until_idle()
        finally:
            await bus.destroy()

    asyncio.run(emit_completed())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None


@pytest.mark.django_db(transaction=True)
def test_crawl_start_event_does_not_resurrect_cancelled_crawl():
    from django.utils import timezone

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.services.crawl_service import CrawlService
    from abx_dl.events import CrawlStartEvent
    from abx_dl.orchestrator import create_bus

    now = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.SEALED,
        retry_at=now,
    )

    bus = create_bus(name=f"test_crawl_start_cancelled_{str(crawl.id).replace('-', '_')}")
    service = CrawlService(bus, crawl_id=str(crawl.id))
    assert service is not None

    async def emit_start() -> None:
        try:
            event = CrawlStartEvent(
                url="https://example.com",
                snapshot_id="",
                output_dir=str(crawl.output_dir),
            )
            emitted = bus.emit(event)
            await emitted.wait()
            await emitted.event_results_list()
            await bus.wait_until_idle()
        finally:
            await bus.destroy()

    asyncio.run(emit_start())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at == now


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
    service = CrawlService(bus, crawl_id=str(crawl.id))
    assert service is not None

    async def emit_cleanup() -> None:
        try:
            event = CrawlCleanupEvent(
                url="https://example.com",
                snapshot_id=str(snapshot.id),
                output_dir=str(crawl.output_dir),
            )
            emitted = bus.emit(event)
            await emitted.wait()
            await emitted.event_results_list()
            await bus.wait_until_idle()
        finally:
            await bus.destroy()

    asyncio.run(emit_cleanup())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None


@pytest.mark.django_db(transaction=True)
def test_crawl_completed_event_seals_finished_crawl():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.crawl_service import CrawlService
    from abx_dl.events import CrawlCompletedEvent
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

    bus = create_bus(name=f"test_crawl_completed_finished_crawl_{str(crawl.id).replace('-', '_')}")
    service = CrawlService(bus, crawl_id=str(crawl.id))
    assert service is not None

    async def emit_cleanup() -> None:
        try:
            event = CrawlCompletedEvent(
                url="https://example.com",
                snapshot_id=str(snapshot.id),
                output_dir=str(crawl.output_dir),
            )
            emitted = bus.emit(event)
            await emitted.wait()
            await emitted.event_results_list()
            await bus.wait_until_idle()
        finally:
            await bus.destroy()

    asyncio.run(emit_cleanup())

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None


@pytest.mark.django_db(transaction=True)
def test_snapshot_completed_event_defers_finished_crawl_seal():
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
    service = SnapshotService(bus, crawl_id=str(crawl.id))
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
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None


@pytest.mark.django_db(transaction=True)
def test_snapshot_completed_event_bus_defers_finished_crawl_seal():
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
    service = SnapshotService(bus, crawl_id=str(crawl.id))
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
    assert crawl.status == Crawl.StatusChoices.STARTED
    assert crawl.retry_at is not None
