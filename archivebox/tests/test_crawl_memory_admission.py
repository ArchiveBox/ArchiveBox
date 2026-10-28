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
        urls="\n".join(f"https://example.com/admission/{index}" for index in range(3)),
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
    runner = CrawlRunner(crawl, selected_plugins=["parse_txt_urls"], show_progress=False)
    children = {}
    measurements = []
    size = 96 * 1024 * 1024
    overlap_started = asyncio.Event()

    async def observe(event: SnapshotEvent) -> None:
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
        # The parser is too fast to guarantee overlap: real CI pressure can
        # temporarily reduce admission to one slot. Keep both pair allocations
        # alive until the projected scheduler admits both captures.
        # Each SnapshotEvent has its own serial handler chain, so awaiting
        # here leaves the scheduler and the other capture free to proceed.
        # Never hold the first capture: it must finish to establish warmup cost.
        # DB preparation can reorder their events; either member may arrive first.
        if index in (1, 2):
            if all(snapshot_id in children for snapshot_id in snapshot_ids[1:3]):
                overlap_started.set()
            await overlap_started.wait()

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
    assert Snapshot.objects.filter(crawl=crawl, status="sealed").count() == 3
    assert ArchiveResult.objects.filter(snapshot__crawl=crawl, plugin="parse_txt_urls", status="succeeded").count() == 3

    # A separate one-snapshot crawl guarantees an isolated heavier sample.
    # Depending on a fourth fast parser to fall into its own batch races the
    # same adaptive admission that this integration test must keep enabled.
    from archivebox.services.resource_admission import resource_admission

    learned_before_heavy = resource_admission.observed_snapshot_cost
    heavy_crawl = Crawl.objects.create(
        urls="https://example.com/admission/3",
        config={"PLUGINS": "parse_txt_urls", "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 2},
        created_by_id=get_or_create_system_user_pk(),
    )
    heavy_snapshot = Snapshot.objects.create(crawl=heavy_crawl, url=heavy_crawl.urls)
    source = heavy_snapshot.output_dir / "staticfile" / "links.txt"
    source.parent.mkdir(parents=True)
    source.write_text("https://example.com/saved/3\n")
    snapshot_ids.append(str(heavy_snapshot.id))
    runner = CrawlRunner(heavy_crawl, selected_plugins=["parse_txt_urls"], show_progress=False)
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
    assert len(measurements) == 4, measurements
    assert measurements[0]["index"] == 0 and measurements[3]["index"] == 3, measurements
    assert {item["index"] for item in measurements[1:3]} == {1, 2}, measurements
    assert measurements[2]["active_allocations"] == 2, measurements
    isolated_cost = measurements[1]["cost"]
    assert isolated_cost > size // 2, measurements
    assert measurements[2]["cost"] == measurements[2]["previous_cost"], measurements
    assert measurements[3]["previous_cost"] == learned_before_heavy, measurements
    # The final crawl contains just one heavier capture; it must still teach
    # admission a larger cost rather than freezing the initial warmup forever.
    assert measurements[3]["active_allocations"] == 1
    assert runner._observed_snapshot_cost > isolated_cost + size, measurements
    assert Snapshot.objects.filter(crawl=heavy_crawl, status="sealed").count() == 1
    assert ArchiveResult.objects.filter(snapshot__crawl=heavy_crawl, plugin="parse_txt_urls", status="succeeded").count() == 1

    # A subsequent automatic crawl reuses the real allocation measurement.
    learned = resource_admission.observed_snapshot_cost
    assert learned is not None and learned > size
    next_crawl = Crawl.objects.create(
        urls="https://example.com/next",
        config={"PLUGINS": "parse_txt_urls", "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 0},
        created_by_id=get_or_create_system_user_pk(),
    )
    next_snapshot = Snapshot.objects.create(crawl=next_crawl, url=next_crawl.urls)
    source = next_snapshot.output_dir / "staticfile" / "links.txt"
    source.parent.mkdir(parents=True)
    source.write_text("https://example.com/next-saved\n")
    next_runner = CrawlRunner(next_crawl, show_progress=False)
    observed = []
    next_runner.bus.on(SnapshotEvent, lambda event: observed.append(next_runner._observed_snapshot_cost))
    asyncio.run(next_runner.run())
    assert observed == [learned]
    assert ArchiveResult.objects.filter(snapshot=next_snapshot, plugin="parse_txt_urls", status="succeeded").count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("explicit_snapshots", [False, True], ids=["projected", "explicit"])
@pytest.mark.parametrize("requirement", ["capture", "reserve"])
def test_memory_deferral_keeps_durable_work_and_recovers(explicit_snapshots, requirement):
    import psutil
    from django.utils import timezone
    from archivebox.services.runner import defer_crawl_for_resources
    from archivebox.services.resource_admission import resource_admission

    crawl = Crawl.objects.create(
        urls="https://archivebox.io/tests/memory-admission",
        config={"PLUGINS": "parse_txt_urls", "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 1},
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(crawl=crawl, url=crawl.urls)
    source = snapshot.output_dir / "staticfile" / "links.txt"
    source.parent.mkdir(parents=True)
    source.write_text("https://archivebox.io/tests/retained-memory-output\n")
    before = timezone.now()
    impossible_cost = psutil.virtual_memory().total + psutil.swap_memory().total + 1
    if requirement == "reserve":
        # Set the real hook guard's reserve above this host's capacity without
        # allocating RAM. Admission must defer before a hook can be killed for
        # entering that same reserve, including the first unmeasured capture.
        crawl.config["MEMORY_MIN_FREE"] = impossible_cost
        crawl.save(update_fields=["config"])
    assert defer_crawl_for_resources(crawl, required_memory=impossible_cost if requirement == "capture" else 0)
    snapshot.refresh_from_db()
    crawl.refresh_from_db()
    assert snapshot.status == "queued" and snapshot.downloaded_at is None
    assert snapshot.retry_at > before and crawl.retry_at > before
    assert not ArchiveResult.objects.filter(snapshot=snapshot).exists()
    assert source.read_text() == "https://archivebox.io/tests/retained-memory-output\n"

    if requirement == "reserve":
        crawl.config["MEMORY_MIN_FREE"] = 0
        crawl.save(update_fields=["config"])

    # The memory requirement fits again, but real host CPU/IO pressure can
    # still defer admission. Let the foreground runner exercise its normal
    # pressure wait instead of assuming the CI host is idle at this instant.
    assert resource_admission.memory_headroom() > 0
    runner = CrawlRunner(
        crawl,
        snapshot_ids=[str(snapshot.id)] if explicit_snapshots else None,
        selected_plugins=["parse_txt_urls"],
        show_progress=False,
    )

    async def run_when_due():
        # The collection scheduler respects the real retry_at written above.
        await asyncio.sleep(max(0, (snapshot.retry_at - timezone.now()).total_seconds()))
        await runner.run()

    asyncio.run(run_when_due())
    assert not runner._resource_deferred
    snapshot.refresh_from_db()
    assert snapshot.status == "sealed" and snapshot.downloaded_at is not None
    assert Snapshot.objects.filter(crawl=crawl).count() == 1
    assert ArchiveResult.objects.filter(snapshot=snapshot, plugin="parse_txt_urls", status="succeeded").count() == 1
    output = snapshot.output_dir / "parse_txt_urls" / "urls.jsonl"
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert any(record["url"] == "https://archivebox.io/tests/retained-memory-output" for record in records)
