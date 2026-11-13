import asyncio

import pytest

from abx_dl.events import TagEvent
from abx_dl.orchestrator import create_bus


pytestmark = pytest.mark.django_db(transaction=True)


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


def test_tag_event_projects_tag_to_snapshot():
    from archivebox.core.models import Tag
    from archivebox.services.tag_service import TagService

    snapshot = _create_snapshot()
    bus = create_bus(name="test_tag_service")
    TagService(bus)

    async def emit_tag_event() -> None:
        event = bus.emit(
            TagEvent(
                name="example",
                snapshot_id=str(snapshot.id),
            ),
        )
        await event.now()
        await event.wait()
        await event.event_results_list()

    asyncio.run(emit_tag_event())

    snapshot.refresh_from_db()
    assert snapshot.tags.filter(name="example").exists()
    assert Tag.objects.filter(name="example").exists()


def test_shipped_hook_stdout_tags_reach_snapshot(tmp_path):
    import json
    import os
    from pathlib import Path

    from abx_dl.execution import execute_hook
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.services.tag_service import TagService

    snapshot = _create_snapshot()
    root = Path(snapshot.output_dir)
    (root / "staticfile").mkdir(parents=True, exist_ok=True)
    (root / "staticfile/stdin.txt").write_text(json.dumps({"url": "https://news.ycombinator.com/", "tags": ["Native hook tag"]}) + "\n")
    plugin = get_plugin_catalog().get("parse_jsonl_urls")
    hook = plugin.filter_hooks("Snapshot")[0]
    bus = create_bus(name="test_native_tag_stdout")
    TagService(bus)

    async def run():
        try:
            result = await execute_hook(
                hook,
                output_dir=root / "parse_jsonl_urls",
                env={**os.environ, "SNAP_DIR": str(root), "EXTRA_CONTEXT": json.dumps({"snapshot_id": str(snapshot.pk)})},
                arguments={"url": snapshot.url},
                bus=bus,
                timeout=30,
            )
            await bus.wait_until_idle()
            assert result.exit_code == 0
        finally:
            await bus.destroy(clear=False)

    asyncio.run(run())
    assert snapshot.tags.filter(name="Native hook tag").exists()
    assert (root / "parse_jsonl_urls/urls.jsonl").is_file()


def test_automatic_analysis_plugins_use_the_opencode_host_runtime():
    from abx_dl.catalog import PluginCatalog

    downloader = PluginCatalog.discover(runtime="abx-dl")
    host = PluginCatalog.discover(runtime="archivebox")
    for name in ("autotag", "autosummary", "opencode"):
        assert name not in downloader
        assert name in host
    for name in ("autotag", "autosummary"):
        assert "opencode" in host[name].config.required_plugins
