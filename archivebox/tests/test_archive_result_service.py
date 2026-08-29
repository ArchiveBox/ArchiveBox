from pathlib import Path
from importlib.resources import files
import json
import os
import shutil

import pytest


from abxpkg.binary_service import BinaryRequestEvent
from abx_dl.events import ProcessCompletedEvent, ProcessEvent, ProcessStartedEvent, SnapshotEvent
from abx_dl.orchestrator import create_bus
from abx_dl.output_files import OutputFile
from archivebox.tests.conftest import resolve_abxpkg_binary_env
from archivebox.tests.conftest import install_real_binary


pytestmark = pytest.mark.django_db(transaction=True)


def _snapshot_hook_name(plugin_name: str) -> str:
    from abx_dl.models import discover_plugins

    plugin = discover_plugins().get(plugin_name)
    assert plugin is not None, f"missing test plugin {plugin_name}"
    hooks = plugin.filter_hooks("Snapshot")
    assert hooks, f"missing Snapshot hooks for {plugin_name}"
    return hooks[0].name


def _cleanup_machine_process_rows() -> None:
    from archivebox.machine.models import Process

    Process.objects.all().delete()


def _run_shipped_snapshot_hook(
    snapshot,
    *,
    plugin: str,
    hook_name: str,
    event_hook_name: str | None = None,
    lib_dir: Path,
    env: dict | None = None,
    expected_exit_codes: tuple[int, ...] = (0,),
):
    """Run one shipped hook through the production process/result bus services."""
    import asyncio

    from abx_dl.models import discover_plugins
    from abx_dl.services.process_service import ProcessService as HookProcessService
    from abx_plugins.plugins.base.utils import get_hydrated_required_binaries
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Process
    from archivebox.services.archive_result_service import ArchiveResultService
    from archivebox.services.process_service import ProcessService as PersistedProcessService

    discovered_plugin = discover_plugins().get(plugin)
    assert discovered_plugin is not None, f"missing test plugin {plugin}"
    matching_hooks = [hook for hook in discovered_plugin.filter_hooks("Snapshot") if hook.name == hook_name or hook.path.name == hook_name]
    assert len(matching_hooks) == 1, f"missing or ambiguous Snapshot hook {plugin}:{hook_name}"
    hook_path = matching_hooks[0].path
    projected_hook_name = event_hook_name or hook_name
    hook_config = hook_path.parent / "config.json"
    for required_binary in get_hydrated_required_binaries(
        hook_config,
        environ={**os.environ, "ABXPKG_LIB_DIR": str(lib_dir)},
    ):
        install_real_binary(
            required_binary["name"],
            binproviders=required_binary["binproviders"],
            overrides=required_binary.get("overrides"),
        )
    binary_env = resolve_abxpkg_binary_env(lib_dir, deps_from=hook_config)
    output_dir = Path(snapshot.output_dir) / plugin
    output_dir.mkdir(parents=True, exist_ok=True)
    bus = create_bus(name=f"test_real_{plugin}_{snapshot.id}")
    HookProcessService(bus, emit_jsonl=False, interactive_tty=False)
    PersistedProcessService(bus)
    ArchiveResultService(bus)

    async def run() -> None:
        try:
            snapshot_event = SnapshotEvent(
                url=snapshot.url,
                snapshot_id=str(snapshot.id),
                output_dir=str(snapshot.output_dir),
            )
            await bus.emit(snapshot_event).now()
            process_event = bus.emit(
                ProcessEvent(
                    plugin_name=plugin,
                    hook_name=projected_hook_name,
                    hook_path=str(hook_path),
                    hook_args=[f"--url={snapshot.url}"],
                    env={
                        **binary_env,
                        "ABXPKG_LIB_DIR": str(lib_dir),
                        "SNAP_DIR": str(snapshot.output_dir),
                        "PATH": f"{Path(os.sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
                        **(env or {}),
                    },
                    output_dir=str(output_dir),
                    timeout=60,
                    is_background=".bg." in hook_name,
                    url=snapshot.url,
                    process_type="hook",
                    worker_type="hook",
                    event_parent_id=snapshot_event.event_id,
                ),
            )
            await process_event.now()
            if ".bg." in hook_name:
                completed_event = await bus.find(
                    ProcessCompletedEvent,
                    child_of=process_event,
                    past=True,
                    future=90,
                )
                assert completed_event is not None
                await completed_event.wait(timeout=90)
                await completed_event.event_results_list()
            await bus.wait_until_idle()
        finally:
            await bus.destroy(clear=False)

    asyncio.run(run())
    process = Process.objects.filter(pwd=str(output_dir)).order_by("-created_at").first()
    assert process is not None
    process.refresh_from_db()
    assert process.exit_code in expected_exit_codes, (process.stdout, process.stderr)
    result = ArchiveResult.objects.get(snapshot=snapshot, plugin=plugin, hook_name=projected_hook_name)
    return process, result


def _run_real_title_crawl(url: str, lib_dir: Path):
    import asyncio

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.runner import CrawlRunner, run_install

    run_install(plugin_names=["title"])
    crawl = Crawl.objects.create(
        urls=url,
        config={"ABXPKG_LIB_DIR": str(lib_dir), "PLUGINS": "title"},
        created_by_id=get_or_create_system_user_pk(),
    )
    asyncio.run(CrawlRunner(crawl, selected_plugins=["title"], show_progress=False).run())
    return Snapshot.objects.get(crawl=crawl, url=url)


def _create_snapshot():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot

    crawl = Crawl(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    crawl.save()

    snapshot = Snapshot(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )
    snapshot.save()
    return snapshot


def test_process_completed_projects_inline_archiveresult(tmp_path, hermetic_lib_dir):
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    snapshot_dir = Path(snapshot.output_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "source.txt").write_text("real hook input", encoding="utf-8")
    process, result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="hashes",
        hook_name="on_Snapshot__93_hashes.py",
        lib_dir=hermetic_lib_dir,
    )

    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert result.process_id == process.id
    assert result.output_str.endswith(json.loads((snapshot_dir / "hashes" / "hashes.json").read_text())["root_hash"][:12])
    assert result.output_files == {
        "hashes.json": {
            "extension": "json",
            "mimetype": "application/json",
            "size": (snapshot_dir / "hashes" / "hashes.json").stat().st_size,
        },
    }
    assert result.output_size == (snapshot_dir / "hashes" / "hashes.json").stat().st_size
    _cleanup_machine_process_rows()


def test_archiveresult_event_retry_updates_existing_hook_row(tmp_path, hermetic_lib_dir):
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    snapshot_dir = Path(snapshot.output_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "source.txt").write_text("first input", encoding="utf-8")
    _, first_result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="hashes",
        hook_name="on_Snapshot__93_hashes.py",
        lib_dir=hermetic_lib_dir,
        env={"HASHES_ENABLED": "False"},
    )
    first_result_id = first_result.id
    assert first_result.status == ArchiveResult.StatusChoices.SKIPPED

    (snapshot_dir / "source.txt").write_text("retry input", encoding="utf-8")
    _, retry_result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="hashes",
        hook_name="on_Snapshot__93_hashes.py",
        lib_dir=hermetic_lib_dir,
        env={"HASHES_ENABLED": "True"},
    )
    assert retry_result.id == first_result_id
    assert retry_result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert ArchiveResult.objects.filter(snapshot=snapshot, plugin="hashes", hook_name="on_Snapshot__93_hashes.py").count() == 1
    _cleanup_machine_process_rows()


def test_archiveresult_duplicate_plugin_rows_are_rejected():
    from django.db import IntegrityError, transaction
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        hook_name="on_Snapshot__06_wget.finite.bg",
        status=ArchiveResult.StatusChoices.FAILED,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__99_other_wget_hook",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )


def test_archivewebpage_lifecycle_hooks_project_one_plugin_output():
    from abx_dl.events import ArchiveResultEvent
    from archivebox.core.models import ArchiveResult
    from archivebox.services.archive_result_service import _save_archiveresult_event_to_db

    snapshot = _create_snapshot()
    _save_archiveresult_event_to_db(
        ArchiveResultEvent(
            snapshot_id=str(snapshot.id),
            plugin="archivewebpage",
            hook_name="on_Snapshot__16_archivewebpage_start",
            status="succeeded",
            output_str="recording started",
            output_files=[OutputFile(path="recording.json", extension="json", mimetype="application/json", size=175)],
        ),
        None,
    )
    _save_archiveresult_event_to_db(
        ArchiveResultEvent(
            snapshot_id=str(snapshot.id),
            plugin="archivewebpage",
            hook_name="on_Snapshot__65_archivewebpage_stop",
            status="succeeded",
            output_str="archivewebpage.wacz",
            output_files=[OutputFile(path="archivewebpage.wacz", extension="wacz", size=2048)],
        ),
        None,
    )

    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="archivewebpage")
    assert result.hook_name == "on_Snapshot__65_archivewebpage_stop"
    assert result.output_str == "archivewebpage.wacz"
    assert set(result.output_files) == {"recording.json", "archivewebpage.wacz"}
    assert ArchiveResult.objects.filter(snapshot=snapshot, plugin="archivewebpage").count() == 1


def test_process_completed_projects_failed_archiveresult_from_shipped_hook(tmp_path, hermetic_lib_dir):
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    process, result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="title",
        hook_name="on_Snapshot__54_title.js",
        lib_dir=hermetic_lib_dir,
        expected_exit_codes=(1,),
    )
    assert result.status == ArchiveResult.StatusChoices.FAILED
    assert result.process_id == process.id
    assert "Chrome session" in result.output_str
    assert result.output_str in result.notes
    _cleanup_machine_process_rows()


def test_failed_title_archiveresult_does_not_overwrite_snapshot_title(tmp_path, hermetic_lib_dir):
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    _, result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="title",
        hook_name="on_Snapshot__54_title.js",
        lib_dir=hermetic_lib_dir,
        expected_exit_codes=(1,),
    )
    assert result.status == ArchiveResult.StatusChoices.FAILED
    assert "Chrome session" in result.output_str
    snapshot.refresh_from_db()
    assert snapshot.title in (None, "")
    assert snapshot.resolved_title == ""
    _cleanup_machine_process_rows()


def test_snapshot_resolved_title_ignores_failed_title_output_str():
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="title",
        hook_name="on_Snapshot__54_title.js",
        status=ArchiveResult.StatusChoices.FAILED,
        output_str="No Chrome session found (chrome plugin must run first)",
    )

    snapshot.refresh_from_db()
    assert snapshot.title in (None, "")
    assert snapshot.resolved_title == ""
    _cleanup_machine_process_rows()


def test_snapshot_title_ignores_noresults_hook_output_str(tmp_path, hermetic_lib_dir):
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    staticfile_dir = Path(snapshot.output_dir) / "staticfile"
    staticfile_dir.mkdir(parents=True, exist_ok=True)
    (staticfile_dir / "input.txt").write_text("plain text without links", encoding="utf-8")
    _, result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="parse_txt_urls",
        hook_name="on_Snapshot__71_parse_txt_urls.py",
        lib_dir=hermetic_lib_dir,
    )
    assert result.status == ArchiveResult.StatusChoices.NORESULTS
    assert result.output_str == "0 URLs parsed"
    snapshot.refresh_from_db()
    assert snapshot.title in (None, "")
    assert snapshot.resolved_title == ""
    _cleanup_machine_process_rows()


def test_snapshot_save_normalizes_url_title_to_none():
    from archivebox.core.models import Snapshot

    snapshot = _create_snapshot()
    snapshot.title = snapshot.url
    snapshot.save(update_fields=["title", "modified_at"])

    snapshot.refresh_from_db()
    assert snapshot.title is None
    assert snapshot.resolved_title == ""

    created = Snapshot.objects.create(
        url="https://example.com/title-normalize-create",
        title="https://example.com/title-normalize-create",
        crawl=snapshot.crawl,
    )

    created.refresh_from_db()
    assert created.title is None
    assert created.resolved_title == ""
    _cleanup_machine_process_rows()


@pytest.mark.parametrize(
    ("candidate", "expected"),
    (
        ("Nick Sweeting: Blog & Projects", "Nick Sweeting: Blog & Projects"),
        ("Nick Sweeting: Blog &amp; Projects", "Nick Sweeting: Blog & Projects"),
        ("Safe &lt;script&gt;alert(1)&lt;/script&gt; title", "Safe alert(1) title"),
    ),
)
def test_snapshot_title_normalization_decodes_entities_without_restoring_markup(candidate, expected):
    from archivebox.core.models import Snapshot

    assert Snapshot._normalize_title_candidate(candidate, snapshot_url="https://example.com") == expected


def test_process_completed_projects_noresults_archiveresult(tmp_path, hermetic_lib_dir):
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    staticfile_dir = Path(snapshot.output_dir) / "staticfile"
    staticfile_dir.mkdir(parents=True, exist_ok=True)
    (staticfile_dir / "input.txt").write_text("plain text without links", encoding="utf-8")
    process, result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="parse_txt_urls",
        hook_name="on_Snapshot__71_parse_txt_urls.py",
        lib_dir=hermetic_lib_dir,
    )
    assert result.status == ArchiveResult.StatusChoices.NORESULTS
    assert result.output_str == "0 URLs parsed"
    assert result.process_id == process.id


def test_skipped_shipped_hook_does_not_infer_success_from_snapshot_files(snapshot, hermetic_lib_dir):
    from archivebox.core.models import ArchiveResult

    snapshot_dir = Path(snapshot.output_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "source.txt").write_text("real input remains present", encoding="utf-8")
    _, result = _run_shipped_snapshot_hook(
        snapshot,
        plugin="hashes",
        hook_name="on_Snapshot__93_hashes.py",
        lib_dir=hermetic_lib_dir,
        env={"HASHES_ENABLED": "False"},
    )
    assert result.status == ArchiveResult.StatusChoices.SKIPPED
    assert result.output_str == "HASHES_ENABLED=False"
    assert "hashes.json" not in result.output_files
    assert not (snapshot_dir / "hashes" / "hashes.json").exists()
    _cleanup_machine_process_rows()


def test_retry_failed_archiveresults_requeues_snapshot_in_queued_state():
    from archivebox.core.models import ArchiveResult, Snapshot

    snapshot = _create_snapshot()
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="chrome",
        hook_name="on_Snapshot__11_chrome_wait",
        status=ArchiveResult.StatusChoices.FAILED,
        output_str="timed out",
        output_files={"stderr.log": {}},
        output_size=123,
        output_mimetypes="text/plain",
    )
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="ublock",
        hook_name="on_Snapshot__12_ublock",
        status=ArchiveResult.StatusChoices.SKIPPED,
        output_str="not applicable",
    )
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="forumdl",
        hook_name="on_Snapshot__50_forumdl",
        status=ArchiveResult.StatusChoices.NORESULTS,
        output_str="0 outputs",
    )

    reset_count = snapshot.retry_failed_archiveresults()

    snapshot.refresh_from_db()
    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="chrome")
    assert reset_count == 1
    assert snapshot.status == Snapshot.StatusChoices.QUEUED
    assert snapshot.retry_at is not None
    assert snapshot.current_step == 0
    assert result.status == ArchiveResult.StatusChoices.QUEUED
    assert result.hook_name == ""
    assert result.output_str == ""
    assert result.output_json is None
    assert result.output_files == {}
    assert result.output_size == 0
    assert result.output_mimetypes == ""
    assert result.start_ts is None
    assert result.end_ts is None
    assert ArchiveResult.objects.get(snapshot=snapshot, plugin="ublock").status == ArchiveResult.StatusChoices.SKIPPED
    assert ArchiveResult.objects.get(snapshot=snapshot, plugin="forumdl").status == ArchiveResult.StatusChoices.NORESULTS
    snapshot.refresh_from_db()
    assert snapshot.title in (None, "")
    _cleanup_machine_process_rows()


def test_process_completed_projects_snapshot_title_from_output_str(recursive_test_site, hermetic_lib_dir):
    snapshot = _run_real_title_crawl(recursive_test_site["root_url"], hermetic_lib_dir)
    result = snapshot.archiveresult_set.get(plugin="title")

    assert result.status == result.StatusChoices.SUCCEEDED
    assert result.output_str == "Root"
    assert snapshot.title == "Root"
    _cleanup_machine_process_rows()


def test_process_completed_projects_snapshot_title_from_title_file(recursive_test_site, hermetic_lib_dir):
    snapshot = _run_real_title_crawl(recursive_test_site["root_url"], hermetic_lib_dir)
    title_file = Path(snapshot.output_dir) / "title" / "title.txt"
    result = snapshot.archiveresult_set.get(plugin="title")

    assert title_file.read_text() == "Root"
    assert result.output_files["title.txt"]["size"] == title_file.stat().st_size
    assert snapshot.resolved_title == title_file.read_text()
    _cleanup_machine_process_rows()


def test_snapshot_resolved_title_falls_back_to_title_file_without_db_title():
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    plugin_dir = Path(snapshot.output_dir) / "title"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "title.txt").write_text("Example Domain")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="title",
        hook_name="on_Snapshot__54_title.js",
        status="noresults",
        output_str="No title found",
        output_files={"title.txt": {}},
    )

    snapshot.refresh_from_db()
    assert snapshot.title in (None, "")
    assert snapshot.resolved_title == "Example Domain"
    _cleanup_machine_process_rows()


def test_collect_output_metadata_preserves_file_metadata():
    from archivebox.services.archive_result_service import _resolve_output_metadata

    output_files, output_size, output_mimetypes = _resolve_output_metadata(
        [OutputFile(path="index.html", extension="html", mimetype="text/html", size=42)],
        Path("/tmp/does-not-need-to-exist"),
    )

    assert output_files == {
        "index.html": {
            "extension": "html",
            "mimetype": "text/html",
            "size": 42,
        },
    }
    assert output_size == 42
    assert output_mimetypes == "text/html"


def test_collect_output_metadata_detects_warc_gz_mimetype(tmp_path):
    from archivebox.services.archive_result_service import _collect_output_metadata

    plugin_dir = tmp_path / "wget"
    warc_file = plugin_dir / "warc" / "capture.warc.gz"
    warc_file.parent.mkdir(parents=True, exist_ok=True)
    warc_file.write_bytes(b"warc-bytes")

    output_files, output_size, output_mimetypes = _collect_output_metadata(plugin_dir)

    assert output_files["warc/capture.warc.gz"] == {
        "extension": "gz",
        "mimetype": "application/warc",
        "size": 10,
    }
    assert output_size == 10
    assert output_mimetypes == "application/warc"


@pytest.mark.django_db(transaction=True)
def test_process_started_hydrates_binary_and_iface_from_existing_binary_records(
    tmp_path,
    hermetic_lib_dir,
    recursive_test_site,
):
    from abx_plugins.plugins.base.utils import get_hydrated_required_binary
    from archivebox.machine.models import NetworkInterface
    from archivebox.machine.models import Process as MachineProcess
    from archivebox.services.process_service import ProcessService as ArchiveBoxProcessService
    from abx_dl.services.process_service import ProcessService as DlProcessService

    iface = NetworkInterface.current()
    machine = iface.machine

    lib_dir = hermetic_lib_dir
    mercury_config = Path(str(files("abx_plugins.plugins.mercury").joinpath("config.json")))
    required_binary = get_hydrated_required_binary(
        "postlight-parser",
        mercury_config,
        environ=os.environ,
    )
    binary = install_real_binary(
        "postlight-parser",
        machine=machine,
        binproviders=required_binary["binproviders"],
        overrides=required_binary["overrides"],
    )
    mercury_env = resolve_abxpkg_binary_env(
        lib_dir,
        deps_from=mercury_config,
    )
    mercury_path = Path(mercury_env["MERCURY_BINARY"])
    provider_path = Path(binary.abspath)
    assert binary.binprovider == "npm"
    assert provider_path == lib_dir / "npm" / "packages" / "mercury" / "node_modules" / ".bin" / "postlight-parser"
    assert provider_path.is_file()
    assert os.access(provider_path, os.X_OK)
    assert mercury_path == lib_dir / "env" / "bin" / "postlight-parser"
    assert mercury_path.is_symlink()
    assert mercury_path.resolve().is_file()
    assert os.access(mercury_path, os.X_OK)

    hook_path = Path(str(files("abx_plugins.plugins.mercury").joinpath("on_Snapshot__57_mercury.py")))
    output_dir = tmp_path / "mercury"
    output_dir.mkdir()

    bus = create_bus(name="test_process_started_binary_hydration")
    DlProcessService(bus, emit_jsonl=False, interactive_tty=False)
    ArchiveBoxProcessService(bus)

    async def run_test() -> None:
        await bus.emit(
            ProcessEvent(
                plugin_name="mercury",
                hook_name="on_Snapshot__57_mercury.py",
                hook_path=str(hook_path),
                hook_args=[f"--url={recursive_test_site['root_url']}"],
                is_background=False,
                output_dir=str(output_dir),
                env={
                    **mercury_env,
                    "ABXPKG_LIB_DIR": str(lib_dir),
                    "SNAP_DIR": str(tmp_path),
                },
                timeout=60,
                url=recursive_test_site["root_url"],
            ),
        ).now()
        started = await bus.find(
            ProcessStartedEvent,
            past=True,
            future=False,
            hook_name="on_Snapshot__57_mercury.py",
            output_dir=str(output_dir),
        )
        assert started is not None
        await started.wait()
        await started.event_results_list()

    import asyncio

    asyncio.run(run_test())

    process = MachineProcess.objects.get(
        pwd=str(output_dir),
        cmd=[str(hook_path), f"--url={recursive_test_site['root_url']}"],
    )
    assert process.binary_id == binary.id
    assert process.iface_id == iface.id
    assert process.exit_code == 0, process.stderr
    assert (output_dir / "content.html").read_text() == (
        '<body> <a href="/about">About</a> <a href="/blog">Blog</a> <a href="/contact">Contact</a> </body>'
    )
    assert (output_dir / "content.txt").read_text() == "About Blog Contact"
    article = json.loads((output_dir / "article.json").read_text())
    assert article["title"] == "Root"
    assert article["url"] == recursive_test_site["root_url"]
    assert article["word_count"] == 3


@pytest.mark.django_db(transaction=True)
def test_process_started_uses_node_binary_for_js_hooks_without_plugin_binary(tmp_path, hermetic_lib_dir):
    from archivebox.machine.models import Binary, NetworkInterface
    from archivebox.machine.models import Process as MachineProcess
    from archivebox.services.process_service import ProcessService as ArchiveBoxProcessService
    from archivebox.services.runner import run_install
    from abx_dl.services.process_service import ProcessService as DlProcessService

    lib_dir = hermetic_lib_dir
    run_install(plugin_names=["chrome"])
    installed_node_ids = set(
        Binary.objects.filter(name="node", status=Binary.StatusChoices.INSTALLED).values_list("id", flat=True),
    )
    assert installed_node_ids
    iface = NetworkInterface.current()
    node_env = resolve_abxpkg_binary_env(lib_dir, "node")
    node_path = lib_dir / "env" / "bin" / "node"

    hook_path = Path(str(files("abx_plugins.plugins.chrome").joinpath("on_CrawlSetup__89_chrome_kill_zombies.js")))
    crawl_dir = tmp_path / "crawl"
    output_dir = crawl_dir / "chrome"
    output_dir.mkdir(parents=True)

    bus = create_bus(name="test_process_started_node_fallback")
    DlProcessService(bus, emit_jsonl=False, interactive_tty=False)
    ArchiveBoxProcessService(bus)

    async def run_test() -> None:
        await bus.emit(
            ProcessEvent(
                plugin_name="chrome",
                hook_name="on_CrawlSetup__89_chrome_kill_zombies.js",
                hook_path=str(hook_path),
                hook_args=[],
                is_background=False,
                output_dir=str(output_dir),
                env={
                    **node_env,
                    "ABXPKG_LIB_DIR": str(lib_dir),
                    "NODE_BINARY": str(node_path),
                    "CRAWL_DIR": str(crawl_dir),
                    "SNAP_DIR": str(crawl_dir / "snapshot"),
                    "CHROME_USER_DATA_DIR": str(output_dir / "profile"),
                },
                timeout=60,
                url="https://example.com",
            ),
        ).now()
        started = await bus.find(
            ProcessStartedEvent,
            past=True,
            future=False,
            hook_name="on_CrawlSetup__89_chrome_kill_zombies.js",
            output_dir=str(output_dir),
        )
        assert started is not None
        await started.wait()
        await started.event_results_list()

    import asyncio

    asyncio.run(run_test())

    process = MachineProcess.objects.get(
        pwd=str(output_dir),
        cmd=[str(hook_path)],
    )
    assert process.binary_id is not None
    assert process.binary_id in installed_node_ids
    assert process.binary.name == "node"
    assert process.binary.status == process.binary.StatusChoices.INSTALLED
    assert Path(process.binary.abspath).resolve() == node_path.resolve()
    assert process.iface_id == iface.id
    assert process.exit_code == 0, process.stderr
    assert "chrome zombies. cpu usage:" in process.stdout


def test_binary_event_updates_existing_row_from_native_abxpkg_resolution():
    from archivebox.machine.models import Binary, Machine
    from archivebox.services.binary_service import ArchiveBoxBinaryService
    from abxpkg.binary_service import BinaryService
    import asyncio

    machine = Machine.current()
    binary = install_real_binary("wget", machine=machine, binproviders="env,apt,brew")
    native_wget = shutil.which("wget")
    assert native_wget is not None
    binary.abspath = "/bin/sh"
    binary.save(update_fields=["abspath", "modified_at"])
    stale_abspath = binary.abspath

    bus = create_bus(name="test_binary_event_reuses_existing_installed_binary_row")
    ArchiveBoxBinaryService(bus)
    BinaryService(bus)
    event = BinaryRequestEvent(
        name="wget",
        binproviders=binary.binproviders,
        extra_context={
            "plugin_name": "wget",
            "output_dir": str(binary.output_dir),
        },
    )

    async def run_event():
        await bus.emit(event).now()
        await bus.wait_until_idle()

    asyncio.run(run_event())

    binary.refresh_from_db()
    assert Binary.objects.filter(machine=machine, name="wget").count() == 1
    assert binary.status == Binary.StatusChoices.INSTALLED
    assert Path(binary.abspath).resolve() == Path(native_wget).resolve()
    assert binary.abspath != stale_abspath
    assert binary.version
    assert binary.binprovider == "env"
    assert binary.binproviders == "env,apt,brew"
