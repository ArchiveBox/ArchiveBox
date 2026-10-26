"""The terminal DB projection must follow publication of capture metadata."""

import asyncio
import hashlib
import json

import pytest

from abx_dl.events import ProcessStartedEvent
from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.services.runner import CrawlRunner

pytestmark = pytest.mark.django_db(transaction=True)


def test_snapshot_index_write_failure_seals_with_failure(cached_abxpkg_lib_dir):
    crawl = Crawl.objects.create(
        urls="https://example.com/index-publication",
        config={"PLUGINS": "hashes"},
        created_by_id=get_or_create_system_user_pk(),
    )
    snapshot = Snapshot.objects.create(crawl=crawl, url=crawl.urls)
    output_dir = snapshot.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    source = output_dir / "source.txt"
    source.write_text("Keep this real captured content.\n" * 100)
    # The shipped hook can write its real output, but the canonical manifest's
    # atomic replacement cannot start. No event or filesystem call is mocked.
    runner = CrawlRunner(crawl, show_progress=False)

    def obstruct_completed_manifest(event: ProcessStartedEvent):
        if event.plugin_name == "hashes":
            (output_dir / ".index.jsonl.tmp").mkdir()

    runner.bus.on(ProcessStartedEvent, obstruct_completed_manifest)

    with pytest.raises(RuntimeError, match="1 snapshot attempt") as failure:
        asyncio.run(runner.run())

    snapshot.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert snapshot.retry_at is None
    assert "IsADirectoryError" in snapshot.notes
    assert "index.jsonl.tmp" in snapshot.notes
    assert "IsADirectoryError" in "\n".join(getattr(failure.value, "__notes__", []))
    result = snapshot.archiveresult_set.get(plugin="hashes")
    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert result.process.exit_code == 0
    hashes = json.loads((output_dir / "hashes/hashes.json").read_text())
    assert any(item["path"] == "source.txt" and item["hash"] == hashlib.sha256(source.read_bytes()).hexdigest() for item in hashes["files"])
    crawl.refresh_from_db()
    assert crawl.status == Crawl.StatusChoices.SEALED


@pytest.mark.parametrize("maintenance", [False, True], ids=["capture", "explicit-plugin-run"])
def test_killed_manifest_writer_restarts_entire_snapshot(initialized_archive, cached_abxpkg_lib_dir, recursive_test_site, maintenance):
    import array
    import fcntl
    import os
    import signal
    import termios
    import time

    from archivebox.machine.models import Process
    from archivebox.tests.conftest import cleanup_process_group, cli_env, run_archivebox_cmd, wait_for_pid_to_disappear
    from archivebox.tests.test_crawl_runner_2 import _create_crawl
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(wget=True, WGET_ARGS_EXTRA='["--limit-rate=64"]', TIMEOUT="120")
    crawl_id = _create_crawl(initialized_archive, env, recursive_test_site["root_url"])
    if maintenance:
        first = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=cli_env(wget=True), timeout=120)
        assert first.returncode == 0, first.stdout + first.stderr
    with use_archivebox_db(initialized_archive):
        Crawl.objects.get(pk=crawl_id).create_snapshots_from_urls()
        snapshot = Snapshot.objects.get(crawl_id=crawl_id)
        # A real manifest larger than a pipe buffer ensures its writer cannot
        # finish while our reader deliberately leaves all bytes unread.
        snapshot.notes = "Persist the whole snapshot before sealing.\n" * 32768
        snapshot.save(update_fields=["notes"])
        if maintenance:
            assert snapshot.status == Snapshot.StatusChoices.SEALED
            snapshot.schedule_plugin_run(["wget"])
        output_dir = snapshot.output_dir

    runner = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, wait=False, start_new_session=True)
    pipe = output_dir / ".index.jsonl.tmp"
    reader = None
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
                    hook_pid = hook.pid
            if hook_pid is None:
                time.sleep(0.05)
        assert hook_pid, "the actual wget hook never started"
        # Initial metadata has already been published before ProcessStarted.
        # Only the final canonical write encounters this real blocked pipe.
        os.mkfifo(pipe)
        reader = os.open(pipe, os.O_RDONLY | os.O_NONBLOCK)
        buffered = array.array("i", [0])
        while time.monotonic() < deadline:
            assert runner.poll() is None, runner.stdout + runner.stderr
            fcntl.ioctl(reader, termios.FIONREAD, buffered, True)
            if buffered[0]:
                break
            time.sleep(0.05)
        assert buffered[0] > 0, "final manifest write never reached the pipe"
        os.killpg(runner.pid, signal.SIGKILL)
        wait_for_pid_to_disappear(runner.pid)
        with use_archivebox_db(initialized_archive):
            snapshot = Snapshot.objects.get(crawl_id=crawl_id)
            assert snapshot.status == (Snapshot.StatusChoices.SEALED if maintenance else Snapshot.StatusChoices.STARTED)
            assert snapshot.retry_at is not None
            if maintenance:
                # The requested run is still durable until its final write
                # completes; a preexisting seal must not hide an interrupted run.
                assert snapshot.config["RETRY_PLUGINS"] == ["wget"]
            result = snapshot.archiveresult_set.get(plugin="wget")
            assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
            assert result.process.exit_code == 0
            original_process_id = result.process_id
    finally:
        if reader is not None:
            os.close(reader)
        cleanup_process_group(runner.pid, hook_pid)
        pipe.unlink(missing_ok=True)

    if maintenance:
        # A sealed snapshot's retry_at can also be a deliberate future plugin
        # schedule. Startup must not guess that every future timestamp was a
        # dead owner's lease and start those requests early. Let this real
        # lease expire, then prove the ordinary queue reruns the durable request.
        from django.utils import timezone

        time.sleep(max(0, (snapshot.retry_at - timezone.now()).total_seconds()))
    restarted = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=cli_env(wget=True), timeout=120)
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr
    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(crawl_id=crawl_id)
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert "RETRY_PLUGINS" not in snapshot.config
        result = snapshot.archiveresult_set.get(plugin="wget")
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert result.process_id != original_process_id
        assert Process.objects.filter(process_type=Process.TypeChoices.HOOK, cmd__0__endswith="_wget.finite.bg.py").count() == (
            3 if maintenance else 2
        )
        records = [json.loads(line) for line in (output_dir / "index.jsonl").read_text().splitlines()]
        record = next(record for record in records if record["type"] == "Snapshot")
        assert record["status"] == "sealed"
        assert record["notes"] == snapshot.notes
        assert record == snapshot.to_json()
        assert any("<title>Root</title>" in path.read_text() for path in (output_dir / "wget").rglob("*.html"))
