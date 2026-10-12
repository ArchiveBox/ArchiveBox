"""Takeover preserves a capture; an explicit user abort ends its attempt."""

import asyncio

import pytest


@pytest.mark.django_db(transaction=True)
def test_pending_snapshots_keep_creation_order_when_timestamps_tie(crawl):
    from django.utils import timezone

    from archivebox.core.models import Snapshot
    from archivebox.services.runner import CrawlRunner

    submitted_at = timezone.now()
    snapshots = [
        Snapshot.objects.create(
            crawl=crawl,
            url=f"https://example.com/{index}",
            created_at=submitted_at,
            retry_at=submitted_at,
            status=status,
        )
        for index, status in enumerate(["started", "queued", "queued"])
    ]
    expected = [str(snapshot.id) for snapshot in snapshots]
    # Both supported UUID7 generators preserve generation order, including
    # bulk submissions whose rows all have the same created_at timestamp.
    assert expected == sorted(expected)
    runner = CrawlRunner(crawl)
    try:
        assert runner.load_run_state() == expected
        # A subsequent interruption must not send that row behind its siblings.
        Snapshot.objects.filter(id=snapshots[1].id).update(status="started")
        assert runner.load_run_state() == expected
    finally:
        asyncio.run(runner.bus.destroy(clear=False))


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


def _interrupted_snapshot(crawl, url, *, retry_at):
    from archivebox.core.models import Snapshot

    return Snapshot.objects.create(url=url, crawl=crawl, status=Snapshot.StatusChoices.STARTED, retry_at=retry_at)


def _exited_hook_run(snapshot, *, started_at):
    """A hook Process row left behind by an earlier, interrupted attempt."""
    from pathlib import Path

    from archivebox.machine.models import Machine, Process

    output_dir = Path(snapshot.output_dir) / "hashes"
    return Process.objects.create(
        machine=Machine.current(),
        process_type=Process.TypeChoices.HOOK,
        status=Process.StatusChoices.EXITED,
        pwd=str(output_dir),
        cmd=[str(output_dir / "on_Snapshot__93_hashes.py")],
        env={},
        started_at=started_at,
        ended_at=started_at,
        exit_code=143,
    )


@pytest.mark.django_db(transaction=True)
def test_recovery_restarts_interrupted_captures_from_scratch(cached_abxpkg_lib_dir):
    from datetime import timedelta

    from django.utils import timezone

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.core.recovery_util import recover_orchestrator_state
    from archivebox.crawls.models import Crawl
    from archivebox.services.runner import run_crawl

    now = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com/expired\nhttps://example.com/orphaned",
        created_by_id=get_or_create_system_user_pk(),
        config={"PLUGINS": "hashes"},
        status=Crawl.StatusChoices.STARTED,
        retry_at=now,
    )
    # Cabbage: the owner's lease had already expired when the container
    # restarted, so recovery (which only unlocked future leases) left these
    # STARTED with a past retry_at, shown as running for hours.
    expired = _interrupted_snapshot(crawl, "https://example.com/expired", retry_at=now - timedelta(hours=1))
    orphaned = _interrupted_snapshot(crawl, "https://example.com/orphaned", retry_at=now + timedelta(seconds=45))
    earlier_attempt_at = now - timedelta(minutes=10)
    for snapshot in (expired, orphaned):
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="hashes",
            hook_name="on_Snapshot__93_hashes",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            start_ts=earlier_attempt_at,
            end_ts=earlier_attempt_at,
        )

    recover_orchestrator_state()

    for snapshot in (expired, orphaned):
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at <= timezone.now()

    run_crawl(str(crawl.id), show_progress=False)

    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED
    for snapshot in (expired, orphaned):
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.downloaded_at is not None
        # A restart is a full capture: the already-succeeded hook ran again
        # and overwrote its own row instead of being skipped.
        rerun = ArchiveResult.objects.get(snapshot=snapshot, plugin="hashes")
        assert rerun.start_ts > earlier_attempt_at
        assert rerun.status == ArchiveResult.StatusChoices.SUCCEEDED


@pytest.mark.django_db(transaction=True)
def test_recovery_gives_up_on_capture_that_was_already_restarted_from_scratch():
    from datetime import timedelta

    from django.utils import timezone

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.core.recovery_util import recover_orchestrator_state
    from archivebox.crawls.models import Crawl

    # No selected Snapshot hooks: one attempt may take at most
    # compute_phase_timeout's 60s floor + 120s = 180s.
    now = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com/retried\nhttps://example.com/once",
        created_by_id=get_or_create_system_user_pk(),
        config={"PLUGINS": "__archivebox_test_no_plugins__"},
        status=Crawl.StatusChoices.STARTED,
        retry_at=now,
    )
    retried = _interrupted_snapshot(crawl, "https://example.com/retried", retry_at=now - timedelta(hours=1))
    _exited_hook_run(retried, started_at=now - timedelta(hours=2))
    _exited_hook_run(retried, started_at=now - timedelta(minutes=10))
    # Cabbage: interrupted Oct 9 and never retried since (59h+).
    once = _interrupted_snapshot(crawl, "https://example.com/once", retry_at=now - timedelta(hours=59))
    _exited_hook_run(once, started_at=now - timedelta(hours=59))

    recover_orchestrator_state()

    retried.refresh_from_db()
    once.refresh_from_db()
    assert retried.status == Snapshot.StatusChoices.SEALED
    assert retried.retry_at is None
    assert retried.downloaded_at is None
    assert once.status == Snapshot.StatusChoices.QUEUED
    assert once.retry_at <= timezone.now()
