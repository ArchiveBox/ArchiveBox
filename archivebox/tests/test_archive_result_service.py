from pathlib import Path
from uuid import uuid4

import pytest
from django.db import connection

from abx_dl.events import ProcessCompletedEvent, ProcessStartedEvent
from abx_dl.orchestrator import create_bus


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
        guid=f'test-guid-{uuid4()}',
        hostname='test-host',
        hw_in_docker=False,
        hw_in_vm=False,
        hw_manufacturer='Test',
        hw_product='Test Product',
        hw_uuid=f'test-hw-{uuid4()}',
        os_arch='arm64',
        os_family='darwin',
        os_platform='macOS',
        os_release='14.0',
        os_kernel='Darwin',
        stats={},
        config={},
    )


def _create_iface(machine):
    from archivebox.machine.models import NetworkInterface

    return NetworkInterface.objects.create(
        machine=machine,
        mac_address='00:11:22:33:44:55',
        ip_public='203.0.113.10',
        ip_local='10.0.0.10',
        dns_server='1.1.1.1',
        hostname='test-host',
        iface='en0',
        isp='Test ISP',
        city='Test City',
        region='Test Region',
        country='Test Country',
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
        output_files=["index.html"],
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
    _cleanup_machine_process_rows()


def test_process_started_hydrates_binary_and_iface_from_existing_binary_records(monkeypatch):
    from archivebox.machine.models import Binary, NetworkInterface
    from archivebox.services.process_service import ProcessService

    machine = _create_machine()
    iface = _create_iface(machine)
    monkeypatch.setattr(NetworkInterface, 'current', classmethod(lambda cls, refresh=False: iface))

    binary = Binary.objects.create(
        machine=machine,
        name='postlight-parser',
        abspath='/tmp/postlight-parser',
        version='2.2.3',
        binprovider='npm',
        binproviders='npm',
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
    monkeypatch.setattr(NetworkInterface, 'current', classmethod(lambda cls, refresh=False: iface))

    node = Binary.objects.create(
        machine=machine,
        name='node',
        abspath='/tmp/node',
        version='22.0.0',
        binprovider='env',
        binproviders='env',
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
