import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.urls import reverse
import html
from uuid import uuid4


pytestmark = pytest.mark.django_db


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


def test_archiveresult_admin_links_plugin_and_process():
    from archivebox.core.admin_archiveresults import ArchiveResultAdmin
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Process

    snapshot = _create_snapshot()
    iface = _create_iface(_create_machine())
    process = Process.objects.create(
        machine=iface.machine,
        iface=iface,
        process_type=Process.TypeChoices.HOOK,
        pwd=str(snapshot.output_dir / "wget"),
        cmd=["/tmp/on_Snapshot__06_wget.finite.bg.py", "--url=https://example.com"],
        status=Process.StatusChoices.EXITED,
    )
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        hook_name="on_Snapshot__06_wget.finite.bg.py",
        process=process,
        status=ArchiveResult.StatusChoices.SUCCEEDED,
    )

    admin = ArchiveResultAdmin(ArchiveResult, AdminSite())

    plugin_html = str(admin.plugin_with_icon(result))
    process_html = str(admin.process_link(result))

    assert "/admin/environment/plugins/builtin.wget/" in plugin_html
    assert f"/admin/machine/process/{process.id}/change" in process_html


def test_snapshot_admin_zip_links():
    from archivebox.core.admin_snapshots import SnapshotAdmin
    from archivebox.core.models import Snapshot

    snapshot = _create_snapshot()
    admin = SnapshotAdmin(Snapshot, AdminSite())

    zip_url = admin.get_snapshot_zip_url(snapshot)

    assert html.escape(zip_url, quote=True) not in str(admin.files(snapshot))
    assert html.escape(zip_url, quote=True) in str(admin.size_with_stats(snapshot))
    assert html.escape(zip_url, quote=True) in str(admin.admin_actions(snapshot))


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
    zip_url = admin.get_output_zip_url(result)

    assert html.escape(zip_url, quote=True) in str(admin.zip_link(result))
    assert html.escape(zip_url, quote=True) in str(admin.admin_actions(result))


def test_archiveresult_admin_copy_command_redacts_sensitive_env_keys():
    from archivebox.core.admin_archiveresults import ArchiveResultAdmin
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Process

    snapshot = _create_snapshot()
    iface = _create_iface(_create_machine())
    process = Process.objects.create(
        machine=iface.machine,
        iface=iface,
        process_type=Process.TypeChoices.HOOK,
        pwd=str(snapshot.output_dir / "wget"),
        cmd=["/tmp/on_Snapshot__06_wget.finite.bg.py", "--url=https://example.com"],
        env={
            "SOURCE_URL": "https://example.com",
            "SAFE_FLAG": "1",
            "API_KEY": "super-secret-key",
            "ACCESS_TOKEN": "super-secret-token",
            "SHARED_SECRET": "super-secret-secret",
        },
        status=Process.StatusChoices.EXITED,
    )
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        hook_name="on_Snapshot__06_wget.finite.bg.py",
        process=process,
        status=ArchiveResult.StatusChoices.SUCCEEDED,
    )

    admin = ArchiveResultAdmin(ArchiveResult, AdminSite())
    cmd_html = str(admin.cmd_str(result))

    assert "SAFE_FLAG=1" in cmd_html
    assert "SOURCE_URL=https://example.com" in cmd_html
    assert "API_KEY" not in cmd_html
    assert "ACCESS_TOKEN" not in cmd_html
    assert "SHARED_SECRET" not in cmd_html
    assert "super-secret-key" not in cmd_html
    assert "super-secret-token" not in cmd_html
    assert "super-secret-secret" not in cmd_html


def test_process_admin_links_binary_and_iface():
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Binary, Process

    machine = _create_machine()
    iface = _create_iface(machine)
    binary = Binary.objects.create(
        machine=machine,
        name="wget",
        abspath="/usr/local/bin/wget",
        version="1.21.2",
        binprovider="env",
        binproviders="env",
        status=Binary.StatusChoices.INSTALLED,
    )
    process = Process.objects.create(
        machine=machine,
        iface=iface,
        binary=binary,
        process_type=Process.TypeChoices.HOOK,
        pwd="/tmp/wget",
        cmd=["/tmp/on_Snapshot__06_wget.finite.bg.py", "--url=https://example.com"],
        status=Process.StatusChoices.EXITED,
    )

    admin = ProcessAdmin(Process, AdminSite())

    binary_html = str(admin.binary_link(process))
    iface_html = str(admin.iface_link(process))

    assert f"/admin/machine/binary/{binary.id}/change" in binary_html
    assert f"/admin/machine/networkinterface/{iface.id}/change" in iface_html


def test_process_admin_kill_actions_only_terminate_running_processes(monkeypatch):
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Process

    machine = _create_machine()
    running = Process.objects.create(
        machine=machine,
        process_type=Process.TypeChoices.HOOK,
        pwd="/tmp/running",
        cmd=["/tmp/on_Snapshot__06_wget.finite.bg.py", "--url=https://example.com"],
        status=Process.StatusChoices.RUNNING,
    )
    exited = Process.objects.create(
        machine=machine,
        process_type=Process.TypeChoices.HOOK,
        pwd="/tmp/exited",
        cmd=["/tmp/on_Snapshot__06_wget.finite.bg.py", "--url=https://example.com"],
        status=Process.StatusChoices.EXITED,
    )

    admin = ProcessAdmin(Process, AdminSite())
    request = RequestFactory().post("/admin/machine/process/")

    terminated = []
    flashed = []

    monkeypatch.setattr(Process, "is_running", property(lambda self: self.pk == running.pk), raising=False)
    monkeypatch.setattr(Process, "terminate", lambda self, graceful_timeout=5.0: terminated.append(self.pk) or True)
    monkeypatch.setattr(admin, "message_user", lambda req, msg, level=None: flashed.append((msg, level)))

    admin.kill_processes(request, Process.objects.filter(pk__in=[running.pk, exited.pk]).order_by("created_at"))

    assert terminated == [running.pk]
    assert any("Killed 1 running process" in msg for msg, _level in flashed)
    assert any("Skipped 1 process" in msg for msg, _level in flashed)


def test_process_admin_object_kill_action_redirects_and_skips_exited(monkeypatch):
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Process

    machine = _create_machine()
    process = Process.objects.create(
        machine=machine,
        process_type=Process.TypeChoices.HOOK,
        pwd="/tmp/exited",
        cmd=["/tmp/on_Snapshot__06_wget.finite.bg.py", "--url=https://example.com"],
        status=Process.StatusChoices.EXITED,
    )

    admin = ProcessAdmin(Process, AdminSite())
    request = RequestFactory().post(f"/admin/machine/process/{process.pk}/change/")

    terminated = []
    flashed = []

    monkeypatch.setattr(Process, "is_running", property(lambda self: False), raising=False)
    monkeypatch.setattr(Process, "terminate", lambda self, graceful_timeout=5.0: terminated.append(self.pk) or True)
    monkeypatch.setattr(admin, "message_user", lambda req, msg, level=None: flashed.append((msg, level)))

    response = admin.kill_process(request, process)

    assert response.status_code == 302
    assert response.url == reverse("admin:machine_process_change", args=[process.pk])
    assert terminated == []
    assert any("Skipped 1 process" in msg for msg, _level in flashed)


def test_process_admin_output_summary_uses_archiveresult_output_files():
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Process

    snapshot = _create_snapshot()
    machine = _create_machine()
    process = Process.objects.create(
        machine=machine,
        process_type=Process.TypeChoices.HOOK,
        pwd=str(snapshot.output_dir / "wget"),
        cmd=["/tmp/on_Snapshot__06_wget.finite.bg.py", "--url=https://example.com"],
        status=Process.StatusChoices.EXITED,
    )
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        hook_name="on_Snapshot__06_wget.finite.bg.py",
        process=process,
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_files={
            "index.html": {"extension": "html", "mimetype": "text/html", "size": 1024},
            "title.txt": {"extension": "txt", "mimetype": "text/plain", "size": "512"},
        },
    )

    admin = ProcessAdmin(Process, AdminSite())

    output_html = str(admin.output_summary(process))

    assert "2 files" in output_html
    assert "1.5 KB" in output_html
