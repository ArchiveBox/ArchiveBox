import pytest


pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
def test_process_completed_persists_with_uncached_network_interface(monkeypatch, tmp_path):
    import asyncio
    from uuid import uuid4

    from abx_dl.events import ProcessCompletedEvent
    from abx_dl.orchestrator import create_bus
    from archivebox.machine.models import Machine, NetworkInterface, Process
    from archivebox.services.process_service import ProcessService

    machine = Machine.objects.create(
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
    iface = NetworkInterface.objects.create(
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
    monkeypatch.setattr(
        NetworkInterface,
        "current",
        classmethod(lambda cls, refresh=False: NetworkInterface.objects.get(id=iface.id)),
    )

    output_dir = tmp_path / "headers"
    output_dir.mkdir()
    bus = create_bus(name="test_process_completed_uncached_iface")
    ProcessService(bus)

    async def run_event() -> None:
        event = bus.emit(
            ProcessCompletedEvent(
                plugin_name="headers",
                hook_name="on_Snapshot__27_headers.daemon.bg",
                hook_path="/bin/echo",
                hook_args=["--url=https://example.com"],
                is_background=True,
                output_dir=str(output_dir),
                env={},
                timeout=60,
                pid=123,
                stdout="",
                stderr="",
                exit_code=0,
                status="succeeded",
                output_files=[],
                start_ts="2026-05-13T07:22:00+00:00",
                end_ts="2026-05-13T07:22:01+00:00",
            ),
        )
        await event.now()
        await event.event_results_list()

    asyncio.run(run_event())

    process = Process.objects.get(pwd=str(output_dir), cmd=["/bin/echo", "--url=https://example.com"])
    assert process.machine_id == machine.id
    assert process.iface_id == iface.id
    assert process.process_type == Process.TypeChoices.HOOK
    assert process.status == Process.StatusChoices.EXITED
