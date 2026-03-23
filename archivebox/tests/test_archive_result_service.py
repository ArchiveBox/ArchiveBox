from pathlib import Path
from uuid import uuid4

import pytest
from django.db import connection


from abx_dl.events import BinaryRequestEvent, ProcessCompletedEvent, ProcessStartedEvent
from abx_dl.orchestrator import create_bus
from abx_dl.output_files import OutputFile


pytestmark = pytest.mark.django_db


def _cleanup_machine_process_rows() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM machine_process")


def _create_snapshot():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
    )
    return Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )


def _create_machine():
    from archivebox.machine.models import Machine

    return Machine.objects.create(
        guid=f"test-guid-{uuid4()}",
        hostname="test-host",
        hw_in_docker=False,
        hw_in_vm=False,
        hw_manufacturer="Test",
        hw_product="Test Product",
        hw_uuid=f"test-hw-{uuid4()}",
        os_arch="arm64",
        os_family="darwin",
        os_platform="macOS",
        os_release="14.0",
        os_kernel="Darwin",
        stats={},
        config={},
    )


def _create_iface(machine):
    from archivebox.machine.models import NetworkInterface

    return NetworkInterface.objects.create(
        machine=machine,
        mac_address="00:11:22:33:44:55",
        ip_public="203.0.113.10",
        ip_local="10.0.0.10",
        dns_server="1.1.1.1",
        hostname="test-host",
        iface="en0",
        isp="Test ISP",
        city="Test City",
        region="Test Region",
        country="Test Country",
    )


def test_process_completed_projects_inline_archiveresult():
    from archivebox.core.models import ArchiveResult
    from archivebox.services.archive_result_service import ArchiveResultService, _collect_output_metadata
    from archivebox.services.process_service import ProcessService

    snapshot = _create_snapshot()
    plugin_dir = Path(snapshot.output_dir) / "wget"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "index.html").write_text("<html>ok</html>")

    bus = create_bus(name="test_inline_archiveresult")
    process_service = ProcessService(bus)
    service = ArchiveResultService(bus, process_service=process_service)

    event = ProcessCompletedEvent(
        plugin_name="wget",
        hook_name="on_Snapshot__06_wget.finite.bg",
        stdout='{"snapshot_id":"%s","type":"ArchiveResult","status":"succeeded","output_str":"wget/index.html"}\n' % snapshot.id,
        stderr="",
        exit_code=0,
        output_dir=str(plugin_dir),
        output_files=[OutputFile(path="index.html", extension="html", mimetype="text/html", size=15)],
        process_id="proc-inline",
        snapshot_id=str(snapshot.id),
        start_ts="2026-03-22T12:00:00+00:00",
        end_ts="2026-03-22T12:00:01+00:00",
    )

    output_files, output_size, output_mimetypes = _collect_output_metadata(plugin_dir)
    service._project_from_process_completed(
        event,
        {
            "snapshot_id": str(snapshot.id),
            "plugin": "wget",
            "hook_name": "on_Snapshot__06_wget.finite.bg",
            "status": "succeeded",
            "output_str": "wget/index.html",
        },
        output_files,
        output_size,
        output_mimetypes,
    )

    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="wget", hook_name="on_Snapshot__06_wget.finite.bg")
    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert result.output_str == "wget/index.html"
    assert "index.html" in result.output_files
    assert result.output_files["index.html"] == {"extension": "html", "mimetype": "text/html", "size": 15}
    assert result.output_size == 15
    _cleanup_machine_process_rows()


def test_process_completed_projects_synthetic_failed_archiveresult():
    from archivebox.core.models import ArchiveResult
    from archivebox.services.archive_result_service import ArchiveResultService, _collect_output_metadata
    from archivebox.services.process_service import ProcessService

    snapshot = _create_snapshot()
    plugin_dir = Path(snapshot.output_dir) / "chrome"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    bus = create_bus(name="test_synthetic_archiveresult")
    process_service = ProcessService(bus)
    service = ArchiveResultService(bus, process_service=process_service)

    event = ProcessCompletedEvent(
        plugin_name="chrome",
        hook_name="on_Snapshot__11_chrome_wait",
        stdout="",
        stderr="Hook timed out after 60 seconds",
        exit_code=-1,
        output_dir=str(plugin_dir),
        output_files=[],
        process_id="proc-failed",
        snapshot_id=str(snapshot.id),
        start_ts="2026-03-22T12:00:00+00:00",
        end_ts="2026-03-22T12:01:00+00:00",
    )

    output_files, output_size, output_mimetypes = _collect_output_metadata(plugin_dir)
    service._project_from_process_completed(
        event,
        {
            "plugin": "chrome",
            "hook_name": "on_Snapshot__11_chrome_wait",
            "status": "failed",
            "output_str": "Hook timed out after 60 seconds",
            "error": "Hook timed out after 60 seconds",
        },
        output_files,
        output_size,
        output_mimetypes,
    )

    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="chrome", hook_name="on_Snapshot__11_chrome_wait")
    assert result.status == ArchiveResult.StatusChoices.FAILED
    assert result.output_str == "Hook timed out after 60 seconds"
    assert "Hook timed out" in result.notes
    _cleanup_machine_process_rows()


def test_process_completed_projects_noresults_archiveresult():
    from archivebox.core.models import ArchiveResult
    from archivebox.services.archive_result_service import ArchiveResultService, _collect_output_metadata
    from archivebox.services.process_service import ProcessService

    snapshot = _create_snapshot()
    plugin_dir = Path(snapshot.output_dir) / "title"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    bus = create_bus(name="test_noresults_archiveresult")
    process_service = ProcessService(bus)
    service = ArchiveResultService(bus, process_service=process_service)

    event = ProcessCompletedEvent(
        plugin_name="title",
        hook_name="on_Snapshot__54_title.js",
        stdout='{"snapshot_id":"%s","type":"ArchiveResult","status":"noresults","output_str":"No title found"}\n' % snapshot.id,
        stderr="",
        exit_code=0,
        output_dir=str(plugin_dir),
        output_files=[],
        process_id="proc-noresults",
        snapshot_id=str(snapshot.id),
        start_ts="2026-03-22T12:00:00+00:00",
        end_ts="2026-03-22T12:00:01+00:00",
    )

    output_files, output_size, output_mimetypes = _collect_output_metadata(plugin_dir)
    service._project_from_process_completed(
        event,
        {
            "snapshot_id": str(snapshot.id),
            "plugin": "title",
            "hook_name": "on_Snapshot__54_title.js",
            "status": "noresults",
            "output_str": "No title found",
        },
        output_files,
        output_size,
        output_mimetypes,
    )

    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="title", hook_name="on_Snapshot__54_title.js")
    assert result.status == ArchiveResult.StatusChoices.NORESULTS
    assert result.output_str == "No title found"


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

    reset_count = snapshot.retry_failed_archiveresults()

    snapshot.refresh_from_db()
    result = ArchiveResult.objects.get(snapshot=snapshot, plugin="chrome", hook_name="on_Snapshot__11_chrome_wait")
    assert reset_count == 1
    assert snapshot.status == Snapshot.StatusChoices.QUEUED
    assert snapshot.retry_at is not None
    assert snapshot.current_step == 0
    assert result.status == ArchiveResult.StatusChoices.QUEUED
    assert result.output_str == ""
    assert result.output_json is None
    assert result.output_files == {}
    assert result.output_size == 0
    assert result.output_mimetypes == ""
    assert result.start_ts is None
    assert result.end_ts is None
    snapshot.refresh_from_db()
    assert snapshot.title in (None, "")
    _cleanup_machine_process_rows()


def test_process_completed_projects_snapshot_title_from_output_str():
    from archivebox.services.archive_result_service import ArchiveResultService, _collect_output_metadata
    from archivebox.services.process_service import ProcessService

    snapshot = _create_snapshot()
    plugin_dir = Path(snapshot.output_dir) / "title"
    plugin_dir.mkdir(parents=True, exist_ok=True)

    bus = create_bus(name="test_snapshot_title_output_str")
    process_service = ProcessService(bus)
    service = ArchiveResultService(bus, process_service=process_service)

    event = ProcessCompletedEvent(
        plugin_name="title",
        hook_name="on_Snapshot__54_title.js",
        stdout='{"snapshot_id":"%s","type":"ArchiveResult","status":"succeeded","output_str":"Example Domain"}\n' % snapshot.id,
        stderr="",
        exit_code=0,
        output_dir=str(plugin_dir),
        output_files=[],
        process_id="proc-title-output-str",
        snapshot_id=str(snapshot.id),
        start_ts="2026-03-22T12:00:00+00:00",
        end_ts="2026-03-22T12:00:01+00:00",
    )

    output_files, output_size, output_mimetypes = _collect_output_metadata(plugin_dir)
    service._project_from_process_completed(
        event,
        {
            "snapshot_id": str(snapshot.id),
            "plugin": "title",
            "hook_name": "on_Snapshot__54_title.js",
            "status": "succeeded",
            "output_str": "Example Domain",
        },
        output_files,
        output_size,
        output_mimetypes,
    )

    snapshot.refresh_from_db()
    assert snapshot.title == "Example Domain"
    _cleanup_machine_process_rows()


def test_process_completed_projects_snapshot_title_from_title_file():
    from archivebox.services.archive_result_service import ArchiveResultService, _collect_output_metadata
    from archivebox.services.process_service import ProcessService

    snapshot = _create_snapshot()
    plugin_dir = Path(snapshot.output_dir) / "title"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "title.txt").write_text("Example Domain")

    bus = create_bus(name="test_snapshot_title_file")
    process_service = ProcessService(bus)
    service = ArchiveResultService(bus, process_service=process_service)

    event = ProcessCompletedEvent(
        plugin_name="title",
        hook_name="on_Snapshot__54_title.js",
        stdout='{"snapshot_id":"%s","type":"ArchiveResult","status":"noresults","output_str":"No title found"}\n' % snapshot.id,
        stderr="",
        exit_code=0,
        output_dir=str(plugin_dir),
        output_files=[OutputFile(path="title.txt", extension="txt", mimetype="text/plain", size=14)],
        process_id="proc-title-file",
        snapshot_id=str(snapshot.id),
        start_ts="2026-03-22T12:00:00+00:00",
        end_ts="2026-03-22T12:00:01+00:00",
    )

    output_files, output_size, output_mimetypes = _collect_output_metadata(plugin_dir)
    service._project_from_process_completed(
        event,
        {
            "snapshot_id": str(snapshot.id),
            "plugin": "title",
            "hook_name": "on_Snapshot__54_title.js",
            "status": "noresults",
            "output_str": "No title found",
        },
        output_files,
        output_size,
        output_mimetypes,
    )

    snapshot.refresh_from_db()
    assert snapshot.title == "Example Domain"
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


def test_process_started_hydrates_binary_and_iface_from_existing_binary_records(monkeypatch):
    from archivebox.machine.models import Binary, NetworkInterface
    from archivebox.services.process_service import ProcessService

    machine = _create_machine()
    iface = _create_iface(machine)
    monkeypatch.setattr(NetworkInterface, "current", classmethod(lambda cls, refresh=False: iface))

    binary = Binary.objects.create(
        machine=machine,
        name="postlight-parser",
        abspath="/tmp/postlight-parser",
        version="2.2.3",
        binprovider="npm",
        binproviders="npm",
        status=Binary.StatusChoices.INSTALLED,
    )

    bus = create_bus(name="test_process_started_binary_hydration")
    service = ProcessService(bus)
    event = ProcessStartedEvent(
        plugin_name="mercury",
        hook_name="on_Snapshot__57_mercury.py",
        hook_path="/plugins/mercury/on_Snapshot__57_mercury.py",
        hook_args=["--url=https://example.com"],
        output_dir="/tmp/mercury",
        env={
            "MERCURY_BINARY": binary.abspath,
            "NODE_BINARY": "/tmp/node",
        },
        timeout=60,
        pid=4321,
        process_id="proc-mercury",
        snapshot_id="",
        start_ts="2026-03-22T12:00:00+00:00",
    )

    service._project_started(event)

    process = service._get_or_create_process(event)
    assert process.binary_id == binary.id
    assert process.iface_id == iface.id


def test_process_started_uses_node_binary_for_js_hooks_without_plugin_binary(monkeypatch):
    from archivebox.machine.models import Binary, NetworkInterface
    from archivebox.services.process_service import ProcessService

    machine = _create_machine()
    iface = _create_iface(machine)
    monkeypatch.setattr(NetworkInterface, "current", classmethod(lambda cls, refresh=False: iface))

    node = Binary.objects.create(
        machine=machine,
        name="node",
        abspath="/tmp/node",
        version="22.0.0",
        binprovider="env",
        binproviders="env",
        status=Binary.StatusChoices.INSTALLED,
    )

    bus = create_bus(name="test_process_started_node_fallback")
    service = ProcessService(bus)
    event = ProcessStartedEvent(
        plugin_name="parse_dom_outlinks",
        hook_name="on_Snapshot__75_parse_dom_outlinks.js",
        hook_path="/plugins/parse_dom_outlinks/on_Snapshot__75_parse_dom_outlinks.js",
        hook_args=["--url=https://example.com"],
        output_dir="/tmp/parse-dom-outlinks",
        env={
            "NODE_BINARY": node.abspath,
        },
        timeout=60,
        pid=9876,
        process_id="proc-parse-dom-outlinks",
        snapshot_id="",
        start_ts="2026-03-22T12:00:00+00:00",
    )

    service._project_started(event)

    process = service._get_or_create_process(event)
    assert process.binary_id == node.id
    assert process.iface_id == iface.id


def test_binary_event_reuses_existing_installed_binary_row(monkeypatch):
    from archivebox.machine.models import Binary, Machine
    from archivebox.services.binary_service import BinaryService as ArchiveBoxBinaryService

    machine = _create_machine()
    monkeypatch.setattr(Machine, "current", classmethod(lambda cls: machine))

    binary = Binary.objects.create(
        machine=machine,
        name="wget",
        abspath="/bin/sh",
        version="9.9.9",
        binprovider="env",
        binproviders="env,apt,brew",
        status=Binary.StatusChoices.INSTALLED,
    )

    service = ArchiveBoxBinaryService(create_bus(name="test_binary_event_reuses_existing_installed_binary_row"))
    event = BinaryRequestEvent(
        name="wget",
        plugin_name="wget",
        hook_name="on_Install__10_wget.finite.bg",
        output_dir="/tmp/wget",
        binproviders="provider",
    )

    service._project_binary(event)

    binary.refresh_from_db()
    assert Binary.objects.filter(machine=machine, name="wget").count() == 1
    assert binary.status == Binary.StatusChoices.INSTALLED
    assert binary.abspath == "/bin/sh"
    assert binary.version == "9.9.9"
    assert binary.binprovider == "env"
    assert binary.binproviders == "provider"
