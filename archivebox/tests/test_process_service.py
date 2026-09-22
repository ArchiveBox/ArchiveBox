import pytest


pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
def test_process_completed_persists_with_uncached_network_interface(tmp_path, recursive_test_site):
    import asyncio

    import archivebox.machine.models as machine_models
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine, NetworkInterface, Process
    from archivebox.services.runner import CrawlRunner

    machine = Machine.current()
    iface = NetworkInterface.current()
    crawl = Crawl.objects.create(
        urls=recursive_test_site["root_url"],
        config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "PLUGINS": "headers"},
        created_by_id=get_or_create_system_user_pk(),
    )

    machine_models._CURRENT_INTERFACE = None
    runner = CrawlRunner(crawl, selected_plugins=["headers"], show_progress=False)
    asyncio.run(runner.run())

    process = next(
        process
        for process in Process.objects.filter(process_type=Process.TypeChoices.HOOK)
        if process.cmd and "on_Snapshot__27_headers.daemon.bg.js" in str(process.cmd[0])
    )
    assert process.machine_id == machine.id
    assert process.iface_id == iface.id
    assert process.process_type == Process.TypeChoices.HOOK
    assert process.status == Process.StatusChoices.EXITED
    assert process.started_at is not None
    assert process.ended_at is not None
    assert process.pid is not None
