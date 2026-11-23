import asyncio

import pytest


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("permissions", ["public", "unlisted", "private"])
def test_wayback_uses_persisted_snapshot_permissions(permissions, wayback_server):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from abx_dl.events import MachineEvent
    from archivebox.workers.runner import CrawlRunner

    crawl = Crawl.objects.create(
        urls="https://example.com/privacy-regression",
        created_by_id=get_or_create_system_user_pk(),
        config={"PLUGINS": "archivedotorg", "PERMISSIONS": "public", "ARCHIVEDOTORG_ENABLED": True},
    )
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, config={"PERMISSIONS": permissions})
    runner = CrawlRunner(
        crawl,
        snapshot_ids=[str(snapshot.id)],
        selected_plugins=["archivedotorg"],
        show_progress=False,
        config_overrides={"PERMISSIONS": "public", "ARCHIVEDOTORG_ENABLED": True},
    )
    configs = []
    runner.bus.on(MachineEvent, lambda event: configs.append(dict(event.config)) if event.config_type == "user" else None)
    asyncio.run(runner.run())
    snapshot.refresh_from_db()
    assert snapshot.permissions == permissions
    assert snapshot.status == "sealed"
    requests = [request for request, _response in wayback_server.log]
    assert len(requests) == (1 if permissions == "public" else 0)
    if permissions == "public":
        from archivebox.machine.models import Process
        from archivebox.plugins.discovery import get_plugin_catalog

        if "PERMISSIONS" in get_plugin_catalog()["archivedotorg"].config.properties:
            hooks = [process for process in Process.objects.filter(process_type="hook") if "archivedotorg" in str(process.cmd)]
            assert hooks
            assert all(process.env.get("PERMISSIONS") == "public" for process in hooks)
    projected = [config for config in configs if config.get("PERMISSIONS") == permissions]
    assert len(projected) >= 2
    if permissions != "public":
        assert all(config["ARCHIVEDOTORG_ENABLED"] is False for config in projected)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("key", ["ARCHIVEDOTORG_ENABLED", "SAVE_ARCHIVE_DOT_ORG"])
def test_wayback_public_opt_out_still_prevents_submission(key, wayback_server):
    import os
    import subprocess
    from archivebox.config.common import normalize_runtime_config
    from archivebox.plugins.discovery import get_plugin_catalog

    config = normalize_runtime_config({key: False})
    assert config["ARCHIVEDOTORG_ENABLED"] is False
    hook = get_plugin_catalog()["archivedotorg"].path / "on_Snapshot__00_archivedotorg.finite.bg.py"
    result = subprocess.run(
        ["uv", "run", "--no-sync", "python", str(hook), "--url=https://example.com/opt-out"],
        env={**os.environ, "PERMISSIONS": "public", "ARCHIVEDOTORG_ENABLED": "false"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "ARCHIVEDOTORG_ENABLED=False" in result.stdout
    assert wayback_server.log == []


@pytest.mark.django_db(transaction=True)
def test_wayback_refreshes_persisted_privacy_before_hooks(wayback_server):
    from abx_dl.events import MachineEvent
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.workers.runner import CrawlRunner

    crawl = Crawl.objects.create(
        urls="https://example.com/privacy-change",
        created_by_id=get_or_create_system_user_pk(),
        config={"PLUGINS": "archivedotorg", "PERMISSIONS": "public"},
    )
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    runner = CrawlRunner(crawl, selected_plugins=["archivedotorg"], show_progress=False)
    changed = []

    async def make_private_after_initial_config(event):
        if event.config_type == "user" and event.config.get("PERMISSIONS") == "public" and not changed:
            await Snapshot.objects.filter(pk=snapshot.pk).aupdate(config={"PERMISSIONS": "private"})
            changed.append(True)

    runner.bus.on(MachineEvent, make_private_after_initial_config)
    asyncio.run(runner.run())
    snapshot.refresh_from_db()
    assert changed == [True]
    assert snapshot.permissions == "private"
    assert snapshot.status == "sealed"
    assert wayback_server.log == []


@pytest.mark.django_db(transaction=True)
def test_prepared_payload_reloads_persisted_permissions():
    from asgiref.sync import async_to_sync
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.workers.runner import CrawlRunner

    crawl = Crawl.objects.create(urls="https://example.com/reload", created_by_id=get_or_create_system_user_pk())
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, config={"PERMISSIONS": "public"})
    runner = CrawlRunner(crawl, show_progress=False)
    try:
        runner.load_run_state()
        initial = async_to_sync(runner.load_snapshot_payload)(str(snapshot.id), prepare=False)
        assert initial["permissions"] == "public"
        Snapshot.objects.filter(pk=snapshot.pk).update(config={"PERMISSIONS": "private"})
        prepared = initial["_prepare"]()
        assert prepared["permissions"] == "private"
    finally:
        asyncio.run(runner.bus.destroy(clear=False))
