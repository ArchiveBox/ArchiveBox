"""Measure actual allocations while the runner executes real parser captures."""

import asyncio
import json
import subprocess

import pytest

from abx_dl.events import SnapshotCompletedEvent, SnapshotEvent
from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.services.runner import CrawlRunner


@pytest.mark.django_db(transaction=True)
def test_parallel_capture_growth_is_not_reused_as_one_snapshot_cost(tmp_path):
    crawl = Crawl.objects.create(
        urls="\n".join(f"https://example.com/admission/{index}" for index in range(4)),
        config={"PLUGINS": "parse_txt_urls", "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 2},
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshots = []
    for index, url in enumerate(crawl.get_urls_list()):
        snapshot = Snapshot.objects.create(crawl=crawl, url=url)
        source = snapshot.output_dir / "staticfile" / "links.txt"
        source.parent.mkdir(parents=True)
        source.write_text(f"https://example.com/saved/{index}\n")
        snapshots.append(snapshot)
    snapshot_ids = [str(snapshot.id) for snapshot in snapshots]
    runner = CrawlRunner(crawl, snapshot_ids=snapshot_ids, selected_plugins=["parse_txt_urls"], show_progress=False)
    children = {}
    measurements = []
    size = 96 * 1024 * 1024

    def observe(event: SnapshotEvent) -> None:
        index = snapshot_ids.index(event.snapshot_id)
        previous_cost = runner._observed_snapshot_cost
        # Real allocations expose the accounting error independently of how
        # much RAM the installed parser happens to need on this platform.
        allocation_size = size * (3 if index == 3 else 1)
        child = subprocess.Popen(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import sys; data=bytearray(int(sys.argv[1])); print(len(data), flush=True); sys.stdin.read()",
                str(allocation_size),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        children[event.snapshot_id] = child
        assert child.stdout is not None
        assert child.stdout.readline().strip() == str(allocation_size)
        runner._observe_snapshot_memory()
        measurements.append(
            {"index": index, "active_allocations": len(children), "previous_cost": previous_cost, "cost": runner._observed_snapshot_cost},
        )

    def release(event: SnapshotCompletedEvent) -> None:
        runner._observe_snapshot_memory()
        child = children.pop(event.snapshot_id)
        assert child.stdin is not None
        child.stdin.close()
        assert child.wait(timeout=10) == 0

    runner.bus.on(SnapshotEvent, observe)
    runner.bus.on(SnapshotCompletedEvent, release)
    try:
        asyncio.run(runner.run())
    finally:
        for child in children.values():
            assert child.stdin is not None
            child.stdin.close()
            assert child.wait(timeout=10) == 0
    (tmp_path / "memory-observations.json").write_text(json.dumps(measurements, indent=2))
    assert [item["index"] for item in measurements] == [0, 1, 2, 3]
    assert measurements[2]["active_allocations"] == 2, measurements
    isolated_cost = measurements[1]["cost"]
    assert isolated_cost > size // 2, measurements
    assert measurements[2]["cost"] == measurements[2]["previous_cost"], measurements
    assert measurements[3]["previous_cost"] == measurements[2]["cost"], measurements
    # The final batch contains just one heavier capture; it must still teach
    # admission a larger cost rather than freezing the initial warmup forever.
    assert measurements[3]["active_allocations"] == 1
    assert runner._observed_snapshot_cost > isolated_cost + size, measurements
    assert Snapshot.objects.filter(crawl=crawl, status="sealed").count() == 4
    assert ArchiveResult.objects.filter(snapshot__crawl=crawl, plugin="parse_txt_urls", status="succeeded").count() == 4
