import pytest
import subprocess
from datetime import datetime, timezone as dt_timezone
from importlib.resources import files
from pathlib import Path
from django.contrib.admin.sites import AdminSite
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse
import html
from uuid import uuid4

from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.conftest import install_real_binary


pytestmark = pytest.mark.django_db


@pytest.fixture
def real_hook_result(tmp_path):
    from archivebox.core.models import ArchiveResult
    from archivebox.plugins.hooks import extract_records_from_process, run_hook

    snapshot = _create_snapshot()
    snap_dir = Path(snapshot.output_dir)
    output_dir = snap_dir / "hashes"
    output_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "source.txt").write_text("real admin link hook input", encoding="utf-8")
    hook_path = Path(str(files("abx_plugins.plugins.hashes").joinpath("on_Snapshot__93_hashes.py")))
    process = run_hook(
        hook_path,
        output_dir,
        config={
            "ABXPKG_LIB_DIR": str(tmp_path / "lib"),
            "SNAP_DIR": str(snap_dir),
            "SAFE_FLAG": "1",
            "API_KEY": "super-secret-key",
            "ACCESS_TOKEN": "super-secret-token",
            "SHARED_SECRET": "super-secret-secret",
        },
        timeout=30,
        url=snapshot.url,
    )
    process.refresh_from_db()
    assert process.exit_code == 0, process.stderr
    record = extract_records_from_process(process)[0]
    hashes_file = output_dir / "hashes.json"
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=record["plugin"],
        hook_name=record["hook_name"],
        process=process,
        status=record["status"],
        output_str=record["output_str"],
        output_files={
            "hashes.json": {
                "extension": "json",
                "mimetype": "application/json",
                "size": hashes_file.stat().st_size,
            },
        },
    )
    return snapshot, process, result


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
        mac_address="00:11:22:33:44:66",
        ip_public="203.0.113.11",
        ip_local="10.0.0.11",
        dns_server="1.1.1.1",
        hostname="test-host",
        iface="en0",
        isp="Test ISP",
        city="Test City",
        region="Test Region",
        country="Test Country",
    )


def _admin_post_request(path):
    request = RequestFactory().post(path)
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def _admin_get_request(path="/"):
    from archivebox.config.common import get_config

    request = RequestFactory().get(path, HTTP_HOST="admin.archivebox.localhost:8000")
    request.archivebox_config = get_config()
    return request


@pytest.fixture
def running_process_record(initialized_archive):
    from archivebox.machine.models import Machine, Process, psutil

    cmd = ["archivebox", "manage", "shell"]
    popen = run_archivebox_cmd(
        ["manage", "shell"],
        cwd=initialized_archive,
        env=cli_env(live=True),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        capture_output=False,
        wait=False,
    )
    try:
        os_process = psutil.Process(popen.pid)
        process = Process.objects.create(
            machine=Machine.current(refresh=True),
            process_type=Process.TypeChoices.ORCHESTRATOR,
            pwd=str(initialized_archive),
            cmd=cmd,
            pid=popen.pid,
            started_at=datetime.fromtimestamp(os_process.create_time(), tz=dt_timezone.utc),
            status=Process.StatusChoices.RUNNING,
        )
        yield process
    finally:
        assert popen.stdin is not None
        popen.stdin.close()
        popen.wait(timeout=20)


def test_archiveresult_admin_links_plugin_and_process(real_hook_result):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.core.admin_archiveresults import ArchiveResultAdmin, render_archiveresults_list
    from archivebox.core.models import ArchiveResult

    snapshot, process, result = real_hook_result
    iface = process.iface
    assert iface is not None

    admin = ArchiveResultAdmin(ArchiveResult, AdminSite())

    plugin_html = str(admin.plugin_with_icon(result))
    process_html = str(admin.process_link(result))

    assert "/admin/environment/plugins/builtin.hashes/" in plugin_html
    assert f"/admin/machine/process/{process.id}/change" in process_html
    assert f"<code>{process.pid}</code>" in process_html
    assert "<code>-</code>" not in process_html

    machine_html = str(admin.machine_link(result))
    assert f"/admin/machine/machine/{iface.machine.id}/change" in machine_html
    assert machine_html == f'<a href="/admin/machine/machine/{iface.machine.id}/change/">{iface.machine.hostname}</a>'

    ArchiveResult.objects.filter(id=result.id).update(end_ts=datetime(2026, 8, 1, 12, 34, 56, tzinfo=dt_timezone.utc))
    with CaptureQueriesContext(connection) as captured_queries:
        inline_html = str(render_archiveresults_list(ArchiveResult.objects.filter(id=result.id)))
    result_queries = [query for query in captured_queries if 'FROM "core_archiveresult"' in query["sql"]]
    assert len(result_queries) == 1, [query["sql"] for query in result_queries]
    assert f"/admin/machine/process/{process.id}/change" in inline_html
    assert f">{process.pid}</a>" in inline_html
    assert ">-</a>" not in inline_html
    assert "overflow-x: auto; overflow-y: hidden" in inline_html
    assert "min-width: 1100px" in inline_html
    assert inline_html.count('class="archive-results-plugin"') == 2
    assert inline_html.count('class="archive-results-output"') == 2
    assert inline_html.count('class="archive-results-files"') == 2
    assert inline_html.count('class="archive-results-completed"') == 2
    assert 'class="archive-results-actions"' in inline_html
    assert "display: block; max-width: 280px; overflow: hidden; text-overflow: ellipsis;" in inline_html
    assert '<wbr> <span style="white-space: nowrap;">' in inline_html

    admin_css = (Path(__file__).parents[1] / "templates" / "static" / "admin.css").read_text()
    assert ".archive-results-table th,\n.archive-results-table td {\n    word-break: normal;" in admin_css
    assert ".archive-results-table .archive-results-plugin {\n    min-width: 120px;" in admin_css
    assert ".archive-results-table .archive-results-output {\n    min-width: 180px;" in admin_css
    assert ".archive-results-table .archive-results-files {\n    width: 52px;\n    min-width: 52px;" in admin_css
    assert ".archive-results-table .archive-results-completed {\n    min-width: 96px;\n    white-space: normal;" in admin_css
    assert ".archive-results-table .archive-results-actions a,\n.archive-results-table .archive-results-actions button {" in admin_css
    assert "margin: 0;\n    width: 28px;\n    height: 28px;" in admin_css


@pytest.mark.django_db(transaction=True)
def test_deleting_binary_and_process_records_preserves_results(real_hook_result):
    from archivebox.core.admin_archiveresults import ArchiveResultAdmin, build_abx_dl_replay_command, render_archiveresults_list
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Process

    snapshot, process, result = real_hook_result
    binary = install_real_binary("python3", machine=process.machine)
    process.binary = binary
    process.save(update_fields=["binary"])

    binary.delete()
    process.refresh_from_db()
    assert process.binary_id is None
    assert process.cmd_version == ""
    assert process.bin_abspath == ""
    assert "binary_id" not in process.to_json()
    assert ProcessAdmin(Process, AdminSite()).binary_link(process) == "-"

    process.delete()
    result.refresh_from_db()
    assert result.process_id is None
    assert ArchiveResult.objects.filter(id=result.id).exists()
    assert result.pwd == str(result.output_dir)
    assert result.cmd == []
    assert result.cmd_version == ""
    assert result.binary is None
    assert result.iface is None
    assert result.machine is None
    assert result.timeout == 120
    result_json = result.to_json()
    assert result_json["pwd"] == str(result.output_dir)
    assert "process_id" not in result_json

    admin = ArchiveResultAdmin(ArchiveResult, AdminSite())
    assert admin.process_link(result) == "-"
    assert admin.machine_link(result) == "-"
    assert "cd " in build_abx_dl_replay_command(result)
    assert "hashes" in render_archiveresults_list(ArchiveResult.objects.filter(id=result.id))


def test_snapshot_admin_zip_links():
    from archivebox.core.admin_snapshots import SnapshotAdmin
    from archivebox.core.models import Snapshot

    snapshot = _create_snapshot()
    admin = SnapshotAdmin(Snapshot, AdminSite())
    admin.request = _admin_get_request()

    files_url = admin.get_snapshot_files_url(snapshot)
    zip_url = admin.get_snapshot_zip_url(snapshot)

    assert html.escape(zip_url, quote=True) not in str(admin.files(snapshot))
    assert html.escape(files_url, quote=True) in str(admin.size_with_stats(snapshot))
    assert html.escape(zip_url, quote=True) in str(admin.admin_actions(snapshot))


def test_admin_navigation_hides_agent_link_when_opencode_is_disabled(client, admin_user):
    from archivebox.machine.models import Machine

    Machine.from_json({"config": {"OPENCODE_ENABLED": False}})
    client.force_login(admin_user)

    response = client.get(reverse("admin:index"), HTTP_HOST="admin.archivebox.localhost:8000")

    assert response.status_code == 200
    assert b"/admin/agent" not in response.content
    assert b">\xf0\x9f\x92\xac AI<" not in response.content


def test_archiveresult_admin_zip_links():
    from archivebox.core.admin_archiveresults import ArchiveResultAdmin
    from archivebox.core.models import ArchiveResult

    snapshot = _create_snapshot()
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        hook_name="on_Snapshot__06_wget.finite.bg.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="Saved output",
    )

    admin = ArchiveResultAdmin(ArchiveResult, AdminSite())
    admin.request = _admin_get_request()
    zip_url = admin.get_output_zip_url(result)

    assert html.escape(zip_url, quote=True) in str(admin.zip_link(result))
    assert html.escape(zip_url, quote=True) in str(admin.admin_actions(result))


def test_archiveresult_admin_copy_command_redacts_sensitive_env_keys(real_hook_result):
    from archivebox.core.admin_archiveresults import ArchiveResultAdmin
    from archivebox.core.models import ArchiveResult

    _, process, result = real_hook_result
    assert process.env["SAFE_FLAG"] == "1"

    admin = ArchiveResultAdmin(ArchiveResult, AdminSite())
    admin.request = _admin_get_request()
    cmd_html = str(admin.cmd_str(result))

    assert "SAFE_FLAG=1" in cmd_html
    assert "https://example.com" in cmd_html
    assert "API_KEY" not in cmd_html
    assert "ACCESS_TOKEN" not in cmd_html
    assert "SHARED_SECRET" not in cmd_html
    assert "super-secret-key" not in cmd_html
    assert "super-secret-token" not in cmd_html
    assert "super-secret-secret" not in cmd_html


@pytest.mark.django_db(transaction=True)
def test_process_admin_links_binary_and_iface(real_hook_result):
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Process

    _, process, _ = real_hook_result
    iface = process.iface
    assert iface is not None
    binary = install_real_binary("python3", machine=process.machine)
    process.binary = binary
    process.save(update_fields=["binary"])

    admin = ProcessAdmin(Process, AdminSite())

    binary_html = str(admin.binary_link(process))
    iface_html = str(admin.iface_link(process))

    assert f"/admin/machine/binary/{binary.id}/change" in binary_html
    assert f"/admin/machine/networkinterface/{iface.id}/change" in iface_html


def test_process_admin_kill_actions_only_terminate_running_processes(running_process_record):
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Machine, Process

    running = running_process_record
    exited = Process.objects.create(
        machine=Machine.current(),
        process_type=Process.TypeChoices.ORCHESTRATOR,
        pwd=running.pwd,
        cmd=running.cmd,
        status=Process.StatusChoices.EXITED,
    )

    admin = ProcessAdmin(Process, AdminSite())
    request = _admin_post_request("/admin/machine/process/")

    admin.kill_processes(request, Process.objects.filter(pk__in=[running.pk, exited.pk]).order_by("created_at"))

    running.refresh_from_db()
    assert running.status == Process.StatusChoices.EXITED
    assert running.exit_code is not None
    messages = [message.message for message in get_messages(request)]
    assert any("Killed 1 running process" in msg for msg in messages)
    assert any("Skipped 1 process" in msg for msg in messages)


def test_process_admin_object_kill_action_redirects_and_skips_exited(real_hook_result):
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Process

    _, process, _ = real_hook_result

    admin = ProcessAdmin(Process, AdminSite())
    request = _admin_post_request(f"/admin/machine/process/{process.pk}/change/")

    response = admin.kill_process(request, process)

    assert response.status_code == 302
    assert response.url == reverse("admin:machine_process_change", args=[process.pk])
    process.refresh_from_db()
    assert process.status == Process.StatusChoices.EXITED
    messages = [message.message for message in get_messages(request)]
    assert any("Skipped 1 process" in msg for msg in messages)


def test_process_admin_output_summary_uses_archiveresult_output_files(real_hook_result):
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Process
    from archivebox.misc.logging_util import printable_filesize

    _, process, result = real_hook_result
    expected_size = sum(int(metadata["size"]) for metadata in result.output_files.values())

    admin = ProcessAdmin(Process, AdminSite())

    output_html = str(admin.output_summary(process))

    assert f"{len(result.output_files)} file" in output_html
    assert printable_filesize(expected_size) in output_html
