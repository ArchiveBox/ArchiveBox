import pytest


pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("historical_interface", [False, True])
def test_process_completed_persists_with_uncached_network_interface(tmp_path, recursive_test_site, historical_interface):
    import archivebox.machine.models as machine_models
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine, NetworkInterface, Process
    from archivebox.services.runner import run_crawl

    machine = Machine.current()
    iface = NetworkInterface.current()
    if historical_interface:
        # A collection can retain an interface from an earlier network. Use a
        # real persisted row, while leaving live network detection untouched.
        iface.ip_public = "192.0.2.1"
        iface.save(update_fields=["ip_public"])
    prior_interface = NetworkInterface.objects.filter(pk=iface.pk).values().get()
    crawl = Crawl.objects.create(
        urls=recursive_test_site["root_url"],
        config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "PLUGINS": "headers"},
        created_by_id=get_or_create_system_user_pk(),
    )

    machine_models._CURRENT_INTERFACE = None
    # Use the foreground boundary: one-shot admission can defer under real
    # host pressure before any hook (and therefore its Process row) exists.
    run_crawl(str(crawl.id), selected_plugins=["headers"], show_progress=False)

    process = next(
        process
        for process in Process.objects.filter(process_type=Process.TypeChoices.HOOK)
        if process.cmd and "on_Snapshot__27_headers.daemon.bg.js" in str(process.cmd[0])
    )
    # Foreground admission refreshes the live network after the cache is
    # cleared. Attribution must match that selected interface, not a row
    # registered before the refresh (public IP or DNS can have changed).
    current_iface = NetworkInterface.current()
    owner = Process.current()
    owner.refresh_from_db()
    assert process.machine_id == machine.id
    assert process.iface_id == owner.iface_id == current_iface.id
    assert process.parent_id == owner.id
    assert current_iface.machine_id == machine.id
    if historical_interface:
        assert current_iface.id != iface.id
        assert NetworkInterface.objects.filter(pk=iface.pk).values().get() == prior_interface
    assert process.process_type == Process.TypeChoices.HOOK
    assert process.status == Process.StatusChoices.EXITED
    assert process.started_at is not None
    assert process.ended_at is not None
    assert process.pid is not None


@pytest.mark.django_db(transaction=True)
def test_real_hook_persists_exact_runtime_logs_across_completion(tmp_path, cached_abxpkg_lib_dir):
    import asyncio
    import os
    from pathlib import Path

    from abx_dl.events import ProcessEvent, ProcessStartedEvent
    from abx_dl.orchestrator import create_bus
    from abx_dl.services.process_service import ProcessService as HookProcessService
    from archivebox.machine.models import Process
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.services.process_service import ProcessService
    from archivebox.tests.conftest import resolve_abxpkg_binary_env

    plugin = get_plugin_catalog()["hashes"]
    hook = plugin.filter_hooks("Snapshot")[0]
    output_dir = tmp_path / "snapshot" / "hashes"
    output_dir.mkdir(parents=True)
    (output_dir.parent / "source.txt").write_text("Real captured content")
    # A real invalid output destination makes the shipped hook fail after
    # producing stdout/stderr, so its original diagnostics must remain readable.
    (output_dir / "hashes.json").mkdir()
    unrelated = tmp_path / "unrelated.log"
    unrelated.write_text("This user-supplied path must never become a process log")
    binary_env = resolve_abxpkg_binary_env(cached_abxpkg_lib_dir, deps_from=hook.path.parent / "config.json")
    started = []
    bus = create_bus(name=f"exact_runtime_logs_{tmp_path.name}")
    HookProcessService(bus, emit_jsonl=False, interactive_tty=False)
    ProcessService(bus)

    async def capture_started(event: ProcessStartedEvent):
        started.append(event)
        # Started observers run in parallel. Wait for the real DB observer,
        # retaining this lifecycle barrier until its recorded paths are checked.
        async with asyncio.timeout(5):
            while (process := await Process.objects.filter(pid=event.pid, pwd=str(output_dir)).afirst()) is None:
                await asyncio.sleep(0.01)
        assert process.status == Process.StatusChoices.RUNNING
        assert process.stdout_file == event.stdout_file
        assert process.stderr_file == event.stderr_file
        assert process.stdout_file.is_file()
        assert process.stderr_file.is_file()

    bus.on(ProcessStartedEvent, capture_started)

    async def run():
        try:
            for _ in range(2):
                await bus.emit(
                    ProcessEvent(
                        plugin_name=plugin.name,
                        hook_name=hook.name,
                        hook_path=str(hook.path),
                        hook_args=["--url=https://archivebox.io/tests/"],
                        output_dir=str(output_dir),
                        env={
                            **binary_env,
                            "PATH": f"{Path(os.sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
                            "ABXPKG_LIB_DIR": str(cached_abxpkg_lib_dir),
                            "TMP_DIR": str(tmp_path / "runtime"),
                            "SNAP_DIR": str(output_dir.parent),
                            "_ARCHIVEBOX_STDOUT_FILE": str(unrelated),
                            "_ARCHIVEBOX_STDERR_FILE": str(unrelated),
                        },
                        timeout=30,
                        is_background=False,
                        process_type="hook",
                    ),
                ).now()
            await bus.wait_until_idle()
        finally:
            await bus.destroy(clear=False)

    asyncio.run(run())
    processes = list(Process.objects.filter(pwd=str(output_dir)).order_by("created_at"))
    assert len(processes) == len(started) == 2
    assert started[0].stdout_file != started[1].stdout_file
    for process, event in zip(processes, started, strict=True):
        assert process.exit_code == 1, process.stderr
        assert "IsADirectoryError" in process.stderr
        assert process.stdout_file == output_dir / event.stdout_file.name
        assert process.stderr_file == output_dir / event.stderr_file.name
        assert process.stdout_file.read_text() == process.stdout
        assert process.stderr_file.read_text() == process.stderr
        assert "ArchiveResult" in process.stdout
        # Persisted paths support diagnostics after the original worker/bus dies.
        process.stdout = ""
        process.stderr = ""
        assert process.get_records()[0]["status"] == "failed"
        assert "IsADirectoryError" in "\n".join(process.tail_stderr())
        assert unrelated.read_text() not in "\n".join(process.tail_stderr())


def test_process_runtime_log_paths_keep_legacy_fallback(tmp_path):
    from archivebox.machine.models import Process

    process = Process(process_type="hook", pwd=str(tmp_path), cmd=["/plugins/hashes/on_Snapshot__93_hashes.py"], env={})
    assert process.stdout_file == tmp_path / ".hooks" / "on_Snapshot__93_hashes.py" / "stdout.log"
    assert process.stderr_file == tmp_path / ".hooks" / "on_Snapshot__93_hashes.py" / "stderr.log"
