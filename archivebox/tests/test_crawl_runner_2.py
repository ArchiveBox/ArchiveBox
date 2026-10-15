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
def test_recovery_restarts_repeated_interruptions_without_inferring_attempts(cached_abxpkg_lib_dir):
    from datetime import timedelta

    from django.utils import timezone

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.core.recovery_util import recover_orchestrator_state
    from archivebox.crawls.models import Crawl

    from archivebox.core.models import ArchiveResult
    from archivebox.services.runner import run_crawl

    now = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com/retried\nhttps://example.com/once",
        created_by_id=get_or_create_system_user_pk(),
        config={"PLUGINS": "hashes", "TIMEOUT": 3600},
        status=Crawl.StatusChoices.STARTED,
        retry_at=now,
    )
    retried = _interrupted_snapshot(crawl, "https://example.com/retried", retry_at=now - timedelta(hours=1))
    _exited_hook_run(retried, started_at=now - timedelta(hours=2))
    _exited_hook_run(retried, started_at=now - timedelta(minutes=10))
    once = _interrupted_snapshot(crawl, "https://example.com/once", retry_at=now - timedelta(hours=59))
    _exited_hook_run(once, started_at=now - timedelta(hours=59))
    # A deployment or config change can reduce today's timeout. Old process
    # timestamps cannot establish how many whole captures were interrupted.
    crawl.config["TIMEOUT"] = 60
    crawl.save(update_fields=["config"])

    recovered_at = timezone.now()
    recover_orchestrator_state()

    for snapshot in (retried, once):
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at <= timezone.now()
        assert snapshot.downloaded_at is None

    run_crawl(str(crawl.id), show_progress=False)

    for snapshot in (retried, once):
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.downloaded_at >= recovered_at
        result = ArchiveResult.objects.get(snapshot=snapshot, plugin="hashes")
        assert result.start_ts >= recovered_at
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert result.process.exit_code == 0
        assert (snapshot.output_dir / "hashes" / "hashes.json").is_file()


def _create_crawl(data_dir, env, *urls):
    from archivebox.tests.conftest import parse_jsonl_output, run_archivebox_cmd

    created = run_archivebox_cmd(["crawl", "create", *urls], cwd=data_dir, env=env)
    assert created.returncode == 0, created.stdout + created.stderr
    return next(record["id"] for record in parse_jsonl_output(created.stdout) if record.get("type") == "Crawl")


@pytest.mark.django_db(transaction=True)
def test_snapshot_whose_hook_processing_raises_is_sealed_once_and_its_crawl_continues(initialized_archive, cached_abxpkg_lib_dir):
    """A real output-directory failure must not strand the crawl's remaining work."""
    import hashlib
    import json

    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Process
    from archivebox.tests.conftest import cli_env, run_archivebox_cmd
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(PLUGINS="hashes", CRAWL_MAX_CONCURRENT_SNAPSHOTS="1")
    urls = ["https://example.com/broken", "https://example.com/after-1", "https://example.com/after-2"]
    crawl_id = _create_crawl(initialized_archive, env, *urls)
    with use_archivebox_db(initialized_archive):
        Crawl.objects.get(pk=crawl_id).create_snapshots_from_urls()
        snapshots = {snapshot.url: snapshot for snapshot in Snapshot.objects.filter(crawl_id=crawl_id)}
        assert set(snapshots) == set(urls)
        for url, snapshot in snapshots.items():
            snapshot.output_dir.mkdir(parents=True, exist_ok=True)
            (snapshot.output_dir / "input.txt").write_text(url)
        # The same real filesystem failure covered by the one-snapshot CLI test,
        # now followed by two captures that must still run their shipped hook.
        (snapshots[urls[0]].output_dir / "hashes").symlink_to("hashes")

    run = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "FileExistsError: [Errno 17]" in run.stderr
    with use_archivebox_db(initialized_archive):
        snapshots = {snapshot.url: snapshot for snapshot in Snapshot.objects.filter(crawl_id=crawl_id)}
        for url, snapshot in snapshots.items():
            assert snapshot.status == Snapshot.StatusChoices.SEALED, url
            assert snapshot.retry_at is None, url
            assert (snapshot.output_dir / "input.txt").read_text() == url
        for url in urls[1:]:
            result = ArchiveResult.objects.get(snapshot=snapshots[url], plugin="hashes")
            assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
            hashes = json.loads((snapshots[url].output_dir / "hashes/hashes.json").read_text())
            file_hash = next(row for row in hashes["files"] if row["path"] == "input.txt")
            assert file_hash["hash"] == hashlib.sha256(url.encode()).hexdigest()
        broken = snapshots[urls[0]]
        assert not broken.archiveresult_set.exists(), "The obstructed hook never started"
        hooks = Process.objects.filter(process_type=Process.TypeChoices.HOOK)
        assert hooks.count() == 2
        assert not hooks.filter(status=Process.StatusChoices.RUNNING).exists()
        sealed_at = broken.modified_at

    rerun = run_archivebox_cmd(["run", "--no-stdin"], cwd=initialized_archive, env=env, timeout=120)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    assert "Recovering" not in rerun.stderr
    with use_archivebox_db(initialized_archive):
        broken = Snapshot.objects.get(id=broken.id)
        assert broken.status == Snapshot.StatusChoices.SEALED
        assert broken.retry_at is None
        assert broken.modified_at == sealed_at
        assert Process.objects.filter(process_type=Process.TypeChoices.HOOK).count() == 2


@pytest.mark.django_db(transaction=True)
def test_snapshot_interrupted_by_process_death_starts_over_on_recovery(initialized_archive, cached_abxpkg_lib_dir, recursive_test_site):
    import os
    import signal
    import time

    import psutil

    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process
    from archivebox.tests.conftest import cleanup_process_group, cli_env, run_archivebox_cmd, wait_for_pid_to_disappear
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    # wget's supported bandwidth limit makes this real local download long
    # enough to observe and interrupt without inventing a test-only hook.
    env = cli_env(wget=True, WGET_ARGS_EXTRA='["--limit-rate=64"]', TIMEOUT="120")
    url = recursive_test_site["root_url"]
    crawl_id = _create_crawl(initialized_archive, env, url)
    runner = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, wait=False, start_new_session=True)
    hook_pid = None
    try:
        deadline = time.monotonic() + 90
        while hook_pid is None and time.monotonic() < deadline:
            assert runner.poll() is None, runner.stdout + runner.stderr
            with use_archivebox_db(initialized_archive):
                hook = Process.objects.filter(
                    process_type=Process.TypeChoices.HOOK,
                    status=Process.StatusChoices.RUNNING,
                    cmd__0__endswith="_wget.finite.bg.py",
                ).first()
                if hook is not None and hook.pid:
                    children = psutil.Process(hook.pid).children(recursive=True)
                    if any(child.name() == "wget" for child in children):
                        hook_pid = hook.pid
            if hook_pid is None:
                time.sleep(0.1)
        assert hook_pid, "the shipped wget hook never started"
        os.killpg(runner.pid, signal.SIGKILL)
        os.killpg(hook_pid, signal.SIGKILL)
        wait_for_pid_to_disappear(runner.pid)
        wait_for_pid_to_disappear(hook_pid)
    finally:
        cleanup_process_group(runner.pid, hook_pid)

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(crawl_id=crawl_id)
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        first_hook_id = hook.id

    restarted = run_archivebox_cmd(["run", "--no-stdin"], cwd=initialized_archive, env=env, timeout=180)
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr
    assert "Recovering 1 Snapshot(s) that were interrupted" in restarted.stderr

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(crawl_id=crawl_id)
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        result = ArchiveResult.objects.get(snapshot=snapshot, plugin="wget")
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert result.process_id != first_hook_id
        hooks = Process.objects.filter(process_type=Process.TypeChoices.HOOK, cmd__0__endswith="_wget.finite.bg.py")
        assert hooks.count() == 2
        assert not hooks.filter(status=Process.StatusChoices.RUNNING).exists()
        html_files = list((snapshot.output_dir / "wget").rglob("*.html"))
        assert html_files
        assert any("<title>Root</title>" in path.read_text() for path in html_files)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("request_during_capture", [False, True], ids=["already-queued", "while-running"])
def test_running_crawl_consumes_explicit_sealed_plugin_requests(cached_abxpkg_lib_dir, request_during_capture):
    from django.utils import timezone

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.services.runner import CrawlRunner
    from abx_dl.events import SnapshotCompletedEvent
    from asgiref.sync import sync_to_async

    crawl = Crawl.objects.create(
        urls="https://archivebox.io/tests/",
        created_by_id=get_or_create_system_user_pk(),
        config={"PLUGINS": "hashes", "CRAWL_MAX_CONCURRENT_SNAPSHOTS": 1},
        status=Crawl.StatusChoices.STARTED,
        retry_at=timezone.now(),
    )
    requested = Snapshot.objects.create(
        crawl=crawl,
        url="https://archivebox.io/tests/",
        status=Snapshot.StatusChoices.SEALED,
        downloaded_at=timezone.now(),
        retry_at=None,
    )
    maintenance = Snapshot.objects.create(
        crawl=crawl,
        url="https://archivebox.io/tests/maintenance",
        status=Snapshot.StatusChoices.SEALED,
        downloaded_at=timezone.now(),
        retry_at=timezone.now(),
    )
    queued = Snapshot.objects.create(crawl=crawl, url="https://archivebox.io/tests/second/")
    requested.output_dir.mkdir(parents=True, exist_ok=True)
    preserved = requested.output_dir / "preserved.txt"
    preserved.write_text("Already archived bytes must survive the requested hash run.\n")
    downloaded_at = requested.downloaded_at
    runner = CrawlRunner(crawl, show_progress=False)
    if request_during_capture:

        async def request_hashes(event: SnapshotCompletedEvent) -> None:
            if str(event.snapshot_id) == str(queued.id):
                await sync_to_async(requested.schedule_plugin_run, thread_sensitive=True)(["hashes"])

        runner.bus.on(SnapshotCompletedEvent, request_hashes)
    else:
        requested.schedule_plugin_run(["hashes"])

    asyncio.run(runner.run())

    requested.refresh_from_db()
    queued.refresh_from_db()
    assert requested.status == Snapshot.StatusChoices.SEALED
    assert requested.downloaded_at == downloaded_at
    assert requested.retry_at is None
    assert "RETRY_PLUGINS" not in requested.config
    assert preserved.read_text() == "Already archived bytes must survive the requested hash run.\n"
    assert (requested.output_dir / "hashes/hashes.json").is_file()
    request_result = ArchiveResult.objects.get(snapshot=requested, plugin="hashes")
    queued_result = ArchiveResult.objects.get(snapshot=queued, plugin="hashes")
    assert request_result.status == queued_result.status == ArchiveResult.StatusChoices.SUCCEEDED
    if request_during_capture:
        assert queued_result.end_ts <= request_result.start_ts
    else:
        assert request_result.end_ts <= queued_result.start_ts
    assert not ArchiveResult.objects.filter(snapshot=maintenance).exists()
