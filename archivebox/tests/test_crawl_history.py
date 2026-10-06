"""Completed captures belong in the database, not a crawl-long event history."""

import asyncio
import gc
import json
import threading
import weakref
from collections import Counter

import pytest

from abx_dl.events import ProcessCompletedEvent, SnapshotCompletedEvent, SnapshotEvent
from werkzeug import Response
from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.services.runner import CrawlRunner, run_install


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("timeout_page", [False, True])
def test_completed_snapshots_expire_after_database_projection(tmp_path, httpserver, hermetic_lib_dir, timeout_page):
    urls = []
    response_started = threading.Event()
    release_response = threading.Event()

    def stalled_response(_request):
        def body():
            response_started.set()
            yield b"<html><head><title>Saved page 3</title></head><body>"
            release_response.wait()
            yield b"Completed response after the browser timed out.</body></html>"

        return Response(body(), content_type="text/html")

    httpserver.expect_request("/favicon.ico").respond_with_data("", status=204)
    for index in range(8):
        path = f"/page/{index}"
        if timeout_page and index == 3:
            httpserver.expect_request(path).respond_with_handler(stalled_response)
            urls.append(httpserver.url_for(path))
            continue
        httpserver.expect_request(path).respond_with_data(
            f"<html><head><title>Saved page {index}</title></head><body>"
            "This real page is part of a multi-snapshot crawl whose completed captures "
            "must remain available in the database after their events expire.</body></html>",
            content_type="text/html",
        )
        urls.append(httpserver.url_for(path))
    run_install(plugin_names=["title"])
    crawl = Crawl.objects.create(
        urls="\n".join(urls),
        config={
            "ABXPKG_LIB_DIR": str(hermetic_lib_dir),
            "PLUGINS": "title",
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 1,
            "CHROME_PAGELOAD_TIMEOUT": 5,
        },
        created_by_id=get_or_create_system_user_pk(),
    )
    runner = CrawlRunner(crawl, selected_plugins=["title"], show_progress=False)
    runner.bus.event_history.max_history_size = 120
    sizes = []
    references = []
    counts = Counter()
    retired_ids = set()
    retained_completed = []

    def count_event(event):
        counts[event.event_type] += 1

    def observe_snapshot(event: SnapshotEvent):
        sizes.append(sum(isinstance(previous, SnapshotEvent) for previous in runner.bus.event_history.values()))
        retained_completed.append(len(retired_ids.intersection(runner.bus.event_history)))
        references.append(weakref.ref(event))

    async def observe_completed(event: SnapshotCompletedEvent):
        root = await runner.bus.find(SnapshotEvent, snapshot_id=event.snapshot_id, past=True, future=False)
        assert root is not None
        retired_ids.add(root.event_id)
        retired_ids.update(item.event_id for item in await runner.bus.filter("*", child_of=root, past=True, future=False))

    def release_timed_out_response(event: ProcessCompletedEvent):
        if response_started.is_set() and event.hook_name == "on_Snapshot__30_chrome_navigate" and event.status == "failed":
            release_response.set()

    runner.bus.on("*", count_event)
    runner.bus.on(SnapshotEvent, observe_snapshot)
    runner.bus.on(SnapshotCompletedEvent, observe_completed)
    runner.bus.on(ProcessCompletedEvent, release_timed_out_response)
    try:
        asyncio.run(runner.run())
    finally:
        release_response.set()
    (tmp_path / "event-counts.json").write_text(json.dumps({"events": counts, "snapshots_in_history": sizes}))
    snapshots = list(Snapshot.objects.filter(crawl=crawl).order_by("url"))
    assert len(snapshots) == len(urls)
    assert all(snapshot.status == "sealed" for snapshot in snapshots)
    for index, snapshot in enumerate(snapshots):
        if timeout_page and index == 3:
            assert response_started.is_set()
            result = ArchiveResult.objects.get(snapshot=snapshot, hook_name="on_Snapshot__30_chrome_navigate", status="failed")
            assert "timeout" in result.output_str.lower()
            continue
        result = ArchiveResult.objects.get(snapshot=snapshot, plugin="title", status="succeeded")
        assert result.output_str == f"Saved page {index}"
        assert (snapshot.output_dir / "title" / "title.txt").read_text().strip() == f"Saved page {index}"
    assert sizes == [1] * len(urls), sizes
    assert retained_completed == [0] * len(urls), retained_completed
    gc.collect()
    assert all(reference() is None for reference in references)
