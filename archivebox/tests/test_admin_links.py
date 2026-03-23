import pytest
from django.contrib.admin.sites import AdminSite
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
        mac_address='00:11:22:33:44:66',
        ip_public='203.0.113.11',
        ip_local='10.0.0.11',
        dns_server='1.1.1.1',
        hostname='test-host',
        iface='en0',
        isp='Test ISP',
        city='Test City',
        region='Test Region',
        country='Test Country',
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
        pwd=str(snapshot.output_dir / 'wget'),
        cmd=['/tmp/on_Snapshot__06_wget.finite.bg.py', '--url=https://example.com'],
        status=Process.StatusChoices.EXITED,
    )
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin='wget',
        hook_name='on_Snapshot__06_wget.finite.bg.py',
        process=process,
        status=ArchiveResult.StatusChoices.SUCCEEDED,
    )

    admin = ArchiveResultAdmin(ArchiveResult, AdminSite())

    plugin_html = str(admin.plugin_with_icon(result))
    process_html = str(admin.process_link(result))

    assert '/admin/environment/plugins/builtin.wget/' in plugin_html
    assert f'/admin/machine/process/{process.id}/change' in process_html


def test_process_admin_links_binary_and_iface():
    from archivebox.machine.admin import ProcessAdmin
    from archivebox.machine.models import Binary, Process

    machine = _create_machine()
    iface = _create_iface(machine)
    binary = Binary.objects.create(
        machine=machine,
        name='wget',
        abspath='/usr/local/bin/wget',
        version='1.21.2',
        binprovider='env',
        binproviders='env',
        status=Binary.StatusChoices.INSTALLED,
    )
    process = Process.objects.create(
        machine=machine,
        iface=iface,
        binary=binary,
        process_type=Process.TypeChoices.HOOK,
        pwd='/tmp/wget',
        cmd=['/tmp/on_Snapshot__06_wget.finite.bg.py', '--url=https://example.com'],
        status=Process.StatusChoices.EXITED,
    )

    admin = ProcessAdmin(Process, AdminSite())

    binary_html = str(admin.binary_link(process))
    iface_html = str(admin.iface_link(process))

    assert f'/admin/machine/binary/{binary.id}/change' in binary_html
    assert f'/admin/machine/networkinterface/{iface.id}/change' in iface_html
