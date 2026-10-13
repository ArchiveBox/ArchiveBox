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


# A real hook, run by abx-dl as a subprocess like any other plugin hook. Each
# attempt appends a line to attempts.log in its own output dir, so tests can
# count how often a Snapshot actually ran instead of inferring it from status.
CAPTURE_PROBE_HOOK = """#!/usr/bin/env bash
url=""
for arg in "$@"; do
  case "$arg" in --url=*) url="${arg#--url=}" ;; esac
done
echo "$url" >> attempts.log
case "$url" in
  *never-ready*)
    # Alive but silent: abx-dl raises once its readiness wait runs out.
    exec sleep 300 ;;
  *slow-first-attempt*)
    if [ "$(( $(wc -l < attempts.log) ))" -eq 1 ]; then
      echo "capturing"
      exec sleep 300
    fi ;;
esac
echo '{"type":"ArchiveResult","status":"succeeded","output_str":"captured"}'
"""


def _install_custom_hook(data_dir, plugin_name, hook_name, script):
    plugin_dir = data_dir / "custom_plugins" / plugin_name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    hook_path = plugin_dir / hook_name
    hook_path.write_text(script)
    hook_path.chmod(0o755)


def _create_crawl(data_dir, env, *urls):
    from archivebox.tests.conftest import parse_jsonl_output, run_archivebox_cmd

    created = run_archivebox_cmd(["crawl", "create", *urls], cwd=data_dir, env=env)
    assert created.returncode == 0, created.stdout + created.stderr
    return next(record["id"] for record in parse_jsonl_output(created.stdout) if record.get("type") == "Crawl")


def _attempt_urls(snapshot):
    from pathlib import Path

    attempts = Path(snapshot.output_dir) / "capture_probe" / "attempts.log"
    return attempts.read_text().splitlines() if attempts.exists() else []


@pytest.mark.django_db(transaction=True)
def test_snapshot_whose_hook_processing_raises_is_sealed_once_and_its_crawl_continues(initialized_archive):
    """Cabbage: abx-dl raised inside one snapshot's hook processing, which
    killed the crawl run; every rerun picked that snapshot first and died the
    same way, so the crawl's other snapshots never ran."""
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process
    from archivebox.tests.conftest import cli_env, run_archivebox_cmd
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    _install_custom_hook(initialized_archive, "capture_probe", "on_Snapshot__10_capture_probe.bg.sh", CAPTURE_PROBE_HOOK)
    # One capture at a time and the failing URL first: the failure used to
    # end the run before any later snapshot was admitted.
    env = cli_env(PLUGINS="capture_probe", TIMEOUT="10", CRAWL_MAX_CONCURRENT_SNAPSHOTS="1")
    urls = ["https://example.com/never-ready", "https://example.com/after-1", "https://example.com/after-2"]
    crawl_id = _create_crawl(initialized_archive, env, *urls)

    run = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, timeout=240)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Runner error" not in run.stderr

    with use_archivebox_db(initialized_archive):
        snapshots = {snapshot.url: snapshot for snapshot in Snapshot.objects.filter(crawl_id=crawl_id)}
        assert set(snapshots) == set(urls)
        for url, snapshot in snapshots.items():
            assert snapshot.status == Snapshot.StatusChoices.SEALED, url
            assert snapshot.retry_at is None, url
            assert _attempt_urls(snapshot) == [url]
        for url in urls[1:]:
            result = ArchiveResult.objects.get(snapshot=snapshots[url], plugin="capture_probe")
            assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
            assert result.output_str == "captured"
        broken = snapshots[urls[0]]
        # The hook that did run keeps its own (non-successful) record.
        assert not broken.archiveresult_set.filter(status=ArchiveResult.StatusChoices.SUCCEEDED).exists()
        assert not Process.objects.filter(process_type=Process.TypeChoices.HOOK, status=Process.StatusChoices.RUNNING).exists()
        sealed_at = broken.modified_at

    # A later scheduler pass, including its startup recovery, must not run the
    # failed snapshot again: it is finished, not interrupted.
    rerun = run_archivebox_cmd(["run", "--no-stdin"], cwd=initialized_archive, env=env, timeout=120)
    assert rerun.returncode == 0, rerun.stdout + rerun.stderr
    assert "Recovering" not in rerun.stderr
    with use_archivebox_db(initialized_archive):
        broken = Snapshot.objects.get(id=broken.id)
        assert broken.status == Snapshot.StatusChoices.SEALED
        assert broken.retry_at is None
        assert broken.modified_at == sealed_at
        assert _attempt_urls(broken) == [urls[0]]


@pytest.mark.django_db(transaction=True)
def test_crawl_level_failure_finishes_one_snapshot_per_run_instead_of_rerunning_it(initialized_archive):
    """A crawl that fails before any capture must not rerun the same snapshot
    forever: each failed run finishes the snapshot it was started for."""
    from archivebox.core.models import Snapshot
    from archivebox.tests.conftest import cli_env, run_archivebox_cmd
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    _install_custom_hook(initialized_archive, "capture_probe", "on_Snapshot__10_capture_probe.bg.sh", CAPTURE_PROBE_HOOK)
    # Like a browser that cannot launch: crawl setup exits before readiness.
    _install_custom_hook(initialized_archive, "setup_probe", "on_CrawlSetup__10_setup_probe.bg.sh", "#!/usr/bin/env bash\nexit 1\n")
    env = cli_env(PLUGINS="setup_probe,capture_probe", TIMEOUT="10", CRAWL_MAX_CONCURRENT_SNAPSHOTS="1")
    urls = ["https://example.com/first", "https://example.com/second"]
    crawl_id = _create_crawl(initialized_archive, env, *urls)

    def statuses():
        with use_archivebox_db(initialized_archive):
            return {snapshot.url: snapshot.status for snapshot in Snapshot.objects.filter(crawl_id=crawl_id)}

    first_run = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, timeout=120)
    # The crawl-level error still surfaces; it just cannot pin one snapshot.
    assert first_run.returncode == 1, first_run.stdout + first_run.stderr
    assert "Runner error" in first_run.stderr
    assert statuses() == {urls[0]: Snapshot.StatusChoices.SEALED, urls[1]: Snapshot.StatusChoices.QUEUED}

    second_run = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, timeout=120)
    assert second_run.returncode == 1, second_run.stdout + second_run.stderr
    assert statuses() == {urls[0]: Snapshot.StatusChoices.SEALED, urls[1]: Snapshot.StatusChoices.SEALED}
    with use_archivebox_db(initialized_archive):
        for snapshot in Snapshot.objects.filter(crawl_id=crawl_id):
            assert snapshot.retry_at is None
            # Setup failed before any capture hook could run.
            assert _attempt_urls(snapshot) == []


@pytest.mark.django_db(transaction=True)
def test_snapshot_interrupted_by_process_death_starts_over_on_recovery(initialized_archive):
    import os
    import signal
    import time

    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process
    from archivebox.tests.conftest import cleanup_process_group, cli_env, run_archivebox_cmd, wait_for_pid_to_disappear
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    _install_custom_hook(initialized_archive, "capture_probe", "on_Snapshot__10_capture_probe.bg.sh", CAPTURE_PROBE_HOOK)
    env = cli_env(PLUGINS="capture_probe", TIMEOUT="120")
    url = "https://example.com/slow-first-attempt"
    crawl_id = _create_crawl(initialized_archive, env, url)

    runner = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, wait=False, start_new_session=True)
    hook_pid = None
    try:
        deadline = time.monotonic() + 90
        while hook_pid is None and time.monotonic() < deadline:
            assert runner.poll() is None, runner.stdout + runner.stderr
            with use_archivebox_db(initialized_archive):
                snapshot = Snapshot.objects.filter(crawl_id=crawl_id).first()
                if snapshot is not None and _attempt_urls(snapshot) == [url]:
                    hook_pid = (
                        Process.objects.filter(
                            process_type=Process.TypeChoices.HOOK,
                            status=Process.StatusChoices.RUNNING,
                            cmd__0__endswith="on_Snapshot__10_capture_probe.bg.sh",
                        )
                        .values_list("pid", flat=True)
                        .first()
                    )
            time.sleep(0.2)
        assert hook_pid, "the capture hook never started"
        # Power loss: the runner and its hook die together, with no cleanup.
        os.killpg(runner.pid, signal.SIGKILL)
        os.killpg(hook_pid, signal.SIGKILL)
        wait_for_pid_to_disappear(runner.pid)
        wait_for_pid_to_disappear(hook_pid)
    finally:
        cleanup_process_group(runner.pid, hook_pid)

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(crawl_id=crawl_id)
        assert snapshot.status == Snapshot.StatusChoices.STARTED

    restarted = run_archivebox_cmd(["run", "--no-stdin"], cwd=initialized_archive, env=env, timeout=180)
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr
    assert "Recovering 1 Snapshot(s) that were interrupted" in restarted.stderr

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(crawl_id=crawl_id)
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        # The interrupted attempt started over from scratch and completed.
        assert _attempt_urls(snapshot) == [url, url]
        result = ArchiveResult.objects.get(snapshot=snapshot, plugin="capture_probe")
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
