"""Interrupted captures must remain runnable after their execution owner exits."""

import asyncio

import pytest


@pytest.mark.django_db(transaction=True)
def test_abort_before_first_snapshot_hook_preserves_pending_capture(recursive_test_site):
    from abx_dl.events import CrawlAbortEvent, ProcessStartedEvent, SnapshotCompletedEvent, SnapshotEvent
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.services.runner import CrawlRunner

    crawl = Crawl.objects.create(
        urls=recursive_test_site["root_url"],
        config={"PLUGINS": "wget"},
        created_by_id=get_or_create_system_user_pk(),
    )
    runner = CrawlRunner(crawl)
    completed = []
    started = []

    async def abort_on_snapshot(event: SnapshotEvent) -> None:
        # Observe the real snapshot command after its DB owner is recorded but
        # before the hook service consumes it. This is the takeover window that
        # used to turn shutdown cleanup into a successful, empty capture.
        await event.emit(CrawlAbortEvent(user_initiated=False)).now()

    runner.bus.on(SnapshotEvent, abort_on_snapshot)
    runner.bus.on(SnapshotCompletedEvent, completed.append)
    runner.bus.on(ProcessStartedEvent, started.append)
    asyncio.run(runner.run())

    assert len(completed) == 1, "Aborting must still finish the real snapshot cleanup phase"
    assert not [event for event in started if event.hook_name.startswith("on_Snapshot")]
    snapshot = Snapshot.objects.get(crawl=crawl)
    crawl.refresh_from_db()
    assert snapshot.status in Snapshot.RUNNABLE_STATES, "An interrupted hook sequence must remain resumable"
    assert snapshot.retry_at is not None
    assert snapshot.downloaded_at is None
    assert snapshot.archiveresult_set.count() == 0
    assert crawl.status in Crawl.RUNNABLE_STATES
    assert crawl.retry_at is not None
