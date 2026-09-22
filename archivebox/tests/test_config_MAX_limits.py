"""Tests for MAX/SIZE crawl limit config behavior."""

import asyncio
import json
from importlib.resources import files
from pathlib import Path

import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_create_snapshots_from_urls_respects_max_urls(admin_user):
    crawl = Crawl.objects.create(
        urls="\n".join(
            [
                "https://example.com/root",
                "https://example.com/about",
                "https://example.com/contact",
            ],
        ),
        config={"CRAWL_MAX_URLS": 2},
        created_by=admin_user,
    )

    created = crawl.create_snapshots_from_urls()

    assert [snapshot.url for snapshot in created] == [
        "https://example.com/root",
        "https://example.com/about",
    ]
    assert crawl.snapshot_set.count() == 2
    assert crawl.remaining_snapshot_capacity() == 0
    assert crawl.limit_stop_reason() == "crawl_max_urls"
    assert crawl.add_url({"url": "https://example.com/extra", "depth": 1}) is False


def test_crawl_stop_reason_keeps_specific_limit_reason_over_lifecycle_fallback(admin_user):
    crawl = Crawl.objects.create(
        urls="\n".join(
            [
                "https://example.com/root",
                "https://example.com/about",
            ],
        ),
        config={"CRAWL_MAX_URLS": 1},
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
        created_by=admin_user,
    )
    Snapshot.objects.create(
        url="https://example.com/root",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        timestamp="1700000000.011",
    )

    assert crawl.stop_reason() == "crawl_max_urls"


def test_enqueue_discovered_snapshots_refreshes_crawl_limits(tmp_path):
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.tests.conftest import run_test_hook
    from archivebox.services.runner import CrawlRunner

    crawl = Crawl.objects.create(
        urls="https://example.com",
        max_depth=0,
        config={"CRAWL_MAX_URLS": 5},
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        depth=0,
    )
    snap_dir = Path(snapshot.output_dir)
    staticfile_dir = snap_dir / "staticfile"
    parser_dir = snap_dir / "parse_txt_urls"
    staticfile_dir.mkdir(parents=True, exist_ok=True)
    parser_dir.mkdir(parents=True, exist_ok=True)
    (staticfile_dir / "input.txt").write_text(
        "https://example.com/child-a\nhttps://example.com/child-b\n",
        encoding="utf-8",
    )
    hook_path = Path(str(files("abx_plugins.plugins.parse_txt_urls").joinpath("on_Snapshot__71_parse_txt_urls.py")))
    process = run_test_hook(
        hook_path,
        parser_dir,
        config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
        timeout=30,
        url=snapshot.url,
        depth=snapshot.depth,
    )
    process.refresh_from_db()
    assert process.exit_code == 0, process.stderr

    runner = CrawlRunner(crawl)
    Crawl.objects.filter(id=crawl.id).update(max_depth=1)
    payload = runner.load_snapshot_payload(str(snapshot.id))

    asyncio.run(runner.enqueue_discovered_snapshots_from_outputs(payload))

    child_snapshots = list(crawl.snapshot_set.filter(depth=1).order_by("url").values_list("url", "status"))
    assert child_snapshots == [
        ("https://example.com/child-a", Snapshot.StatusChoices.QUEUED),
        ("https://example.com/child-b", Snapshot.StatusChoices.QUEUED),
    ]


def test_run_snapshot_seals_descendant_when_crawl_max_size_is_reached(tmp_path):
    from abx_dl.events import CrawlStartEvent, SnapshotEvent
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.runner import CrawlRunner

    crawl = Crawl.objects.create(
        urls="https://example.com",
        config={
            "ABXPKG_LIB_DIR": str(tmp_path / "lib"),
            "PLUGINS": "__archivebox_test_no_plugins__",
            "CHROME_BINARY": "",
            "CRAWL_MAX_SIZE": 16,
        },
        created_by_id=get_or_create_system_user_pk(),
    )
    root = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        depth=0,
        status=Snapshot.StatusChoices.SEALED,
    )
    child = Snapshot.objects.create(
        url="https://example.com/child",
        crawl=crawl,
        depth=1,
        parent_snapshot=root,
        status=Snapshot.StatusChoices.QUEUED,
    )
    state_dir = Path(crawl.output_dir) / ".abx-dl"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "limits.json").write_text(
        json.dumps(
            {
                "admitted_snapshot_ids": [str(root.id), str(child.id)],
                "counted_event_ids": ["proc-1"],
                "total_size": 32,
                "stop_reason": "crawl_max_size",
            },
        ),
        encoding="utf-8",
    )

    runner = CrawlRunner(crawl)
    runner.load_run_state()

    async def run_child_from_crawl_start() -> list[SnapshotEvent]:
        async def on_crawl_start(_event: CrawlStartEvent) -> None:
            await runner.run_snapshot(str(child.id))

        runner.bus.on(CrawlStartEvent, on_crawl_start)
        crawl_start = runner.bus.emit(
            CrawlStartEvent(
                url=root.url,
                snapshot_id=str(root.id),
                output_dir=str(crawl.output_dir),
                event_timeout=30,
                event_handler_timeout=30,
            ),
        )
        await crawl_start.now()
        await crawl_start.event_results_list()
        await runner.bus.wait_until_idle()
        return await runner.bus.filter(SnapshotEvent, child_of=crawl_start, past=True)

    snapshot_events = asyncio.run(run_child_from_crawl_start())

    child.refresh_from_db()
    assert child.status == Snapshot.StatusChoices.SEALED
    assert child.retry_at is None
    assert snapshot_events == []


def test_seal_snapshot_cancels_queued_descendants_after_crawl_max_size():
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import Snapshot
    from archivebox.services.snapshot_service import SnapshotService
    from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
    from abx_dl.orchestrator import create_bus

    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by_id=get_or_create_system_user_pk(),
        config={"CRAWL_MAX_SIZE": 16},
    )
    root = Snapshot.objects.create(
        url="https://example.com",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )
    child = Snapshot.objects.create(
        url="https://example.com/child",
        crawl=crawl,
        depth=1,
        parent_snapshot_id=root.id,
        status=Snapshot.StatusChoices.QUEUED,
    )

    state_dir = Path(crawl.output_dir) / ".abx-dl"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "limits.json").write_text(
        json.dumps(
            {
                "admitted_snapshot_ids": [str(root.id), str(child.id)],
                "counted_event_ids": ["proc-1"],
                "total_size": 32,
                "stop_reason": "crawl_max_size",
            },
        ),
        encoding="utf-8",
    )

    bus = create_bus(name=f"test_snapshot_limit_cancel_{str(crawl.id).replace('-', '_')}")
    SnapshotService(bus, crawl_id=str(crawl.id))
    try:

        async def emit_event() -> None:
            snapshot_event = bus.emit(
                SnapshotEvent(
                    url=root.url,
                    snapshot_id=str(root.id),
                    output_dir=str(root.output_dir),
                ),
            )
            await snapshot_event.now()
            completed_event = SnapshotCompletedEvent(
                url=root.url,
                snapshot_id=str(root.id),
                output_dir=str(root.output_dir),
            )
            completed_event.event_parent_id = snapshot_event.event_id
            await bus.emit(completed_event).now()

        asyncio.run(emit_event())
    finally:
        asyncio.run(bus.wait_until_idle())
        asyncio.run(bus.destroy())

    root.refresh_from_db()
    child.refresh_from_db()
    assert root.status == Snapshot.StatusChoices.SEALED
    assert child.status == Snapshot.StatusChoices.SEALED
    assert child.retry_at is None


def test_recursive_crawl_respects_max_urls(tmp_path, initialized_archive, recursive_test_site):
    """Test that recursive discovery stops creating snapshots at max_urls."""
    env = cli_env(disable_extractors=True)

    env = env.copy()
    env.update(
        {
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
            "SAVE_WGET": "true",
            "USE_CHROME": "false",
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
        },
    )

    result = run_archivebox_cmd(
        [
            "add",
            "--depth=2",
            "--max-urls=4",
            "--plugins=wget,parse_html_urls",
            recursive_test_site["root_url"],
        ],
        env=env,
        timeout=120,
    )
    stdout, stderr = result.stdout, result.stderr

    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 2000 chars) ===\n{stdout[-2000:]}\n=== END STDOUT ===\n")

    assert result.returncode == 0, result.stderr

    with use_archivebox_db(tmp_path):
        crawl_obj = Crawl.objects.order_by("-created_at").first()
        crawl = (crawl_obj.max_depth, crawl_obj.config["CRAWL_MAX_URLS"]) if crawl_obj else None
        snapshot_rows = list(Snapshot.objects.order_by("depth", "url").values_list("url", "depth", "parent_snapshot_id"))
        depth_counts = {
            depth: Snapshot.objects.filter(depth=depth).count() for depth in set(Snapshot.objects.values_list("depth", flat=True))
        }

    assert crawl == (2, 4)
    assert len(snapshot_rows) == 4
    assert depth_counts.get(0, 0) == 1
    assert depth_counts.get(1, 0) == 3
    assert depth_counts.get(2, 0) == 0
    assert depth_counts.get(3, 0) == 0
    assert set(recursive_test_site["child_urls"]).issubset({url for url, depth, _parent in snapshot_rows if depth == 1})
