"""Takeover preserves a capture; an explicit user abort ends its attempt."""

import asyncio

import pytest


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("user_initiated", [False, True], ids=["takeover", "user-abort"])
def test_abort_before_first_snapshot_hook_preserves_capture_intent(recursive_test_site, user_initiated):
    from abx_dl.events import CrawlAbortEvent, CrawlCompletedEvent, ProcessStartedEvent, SnapshotCompletedEvent, SnapshotEvent
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
    completed_crawls = []

    async def abort_on_snapshot(event: SnapshotEvent) -> None:
        # Observe the real snapshot command after its DB owner is recorded but
        # before the hook service consumes it. This is the takeover window that
        # used to turn shutdown cleanup into a successful, empty capture.
        await event.emit(CrawlAbortEvent(user_initiated=user_initiated)).now()

    runner.bus.on(SnapshotEvent, abort_on_snapshot)
    runner.bus.on(SnapshotCompletedEvent, lambda event: completed.append(event))
    runner.bus.on(ProcessStartedEvent, lambda event: started.append(event))
    runner.bus.on(CrawlCompletedEvent, lambda event: completed_crawls.append(event))
    if user_initiated:
        with pytest.raises(KeyboardInterrupt):
            asyncio.run(runner.run())
    else:
        asyncio.run(runner.run())

    assert len(completed) == 1, "Aborting must still finish the real snapshot cleanup phase"
    assert not [event for event in started if event.hook_name.startswith("on_Snapshot")]
    snapshot = Snapshot.objects.get(crawl=crawl)
    crawl.refresh_from_db()
    assert len(completed_crawls) == int(user_initiated)
    assert snapshot.archiveresult_set.count() == 0
    if user_initiated:
        # Preserve the historical point-in-time boundary for an explicit abort.
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert snapshot.downloaded_at is not None
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None
    else:
        assert snapshot.status in Snapshot.RUNNABLE_STATES, "Takeover must leave the capture resumable"
        assert snapshot.retry_at is not None
        assert snapshot.downloaded_at is None
        assert crawl.status in Crawl.RUNNABLE_STATES
        assert crawl.retry_at is not None
