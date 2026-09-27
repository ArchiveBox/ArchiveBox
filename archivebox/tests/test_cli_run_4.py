"""
Tests for archivebox run CLI command.

Tests cover:
- run with stdin JSONL (Crawl, Snapshot, ArchiveResult)
- create-or-update behavior (records with/without id)
- pass-through output (for chaining)
"""

import os
import pty
import select
import signal
import subprocess
import termios
import time

import psutil
import pytest

from archivebox.tests.conftest import (
    cleanup_process_group,
    cli_env,
    create_test_url,
    parse_jsonl_output,
    pid_is_alive,
    run_archivebox_cmd,
    wait_for_log,
    wait_for_pid_to_disappear,
)

from .test_cli_run_1 import (
    RUN_TEST_ENV as RUN_TEST_ENV,
    _install_real_chrome_for_test as _install_real_chrome_for_test,
)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("choice", ["typed", "signal"])
def test_run_third_interrupt_forces_chosen_abort(initialized_archive, choice):
    """Direct run exits at once when Ctrl+C follows an explicit abort choice."""
    from archivebox.machine.models import Process
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(CHROME_DELAY_AFTER_LOAD="60", CHROME_TIMEOUT="120", CHROME_HEADLESS="True", PLUGINS="chrome")
    _install_real_chrome_for_test(initialized_archive, env, isolation="crawl")
    created = run_archivebox_cmd(["snapshot", "create", create_test_url()], cwd=initialized_archive, env=env)
    assert created.returncode == 0, created.stdout + created.stderr
    crawl_id = next(record["crawl_id"] for record in parse_jsonl_output(created.stdout) if record.get("type") == "Snapshot")
    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, 160))
    output = bytearray()
    result = None

    def read_until(predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            if predicate():
                return
        raise AssertionError(output.decode(errors="replace"))

    def active_hook_pid():
        with use_archivebox_db(initialized_archive):
            hook = Process.objects.filter(
                process_type=Process.TypeChoices.HOOK,
                cmd__0__endswith="on_Snapshot__30_chrome_navigate.js",
                status="running",
            ).first()
            return hook.pid if hook is not None and hook.is_running else None

    try:
        result = run_archivebox_cmd(
            ["run", f"--crawl-id={crawl_id}"],
            cwd=initialized_archive,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            wait=False,
            start_new_session=True,
        )
        read_until(lambda: active_hook_pid() is not None)
        hook_pid = active_hook_pid()
        assert hook_pid is not None
        owned = psutil.Process(result.pid).children(recursive=True)
        result.send_signal(signal.SIGINT)
        read_until(lambda: b"Choice [skip]:" in output)
        read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
        if choice == "typed":
            os.write(master, b"a")
        else:
            result.send_signal(signal.SIGINT)
        read_until(lambda: b"Aborting crawl" in output, timeout=5)
        forced_at = time.monotonic()
        result.send_signal(signal.SIGINT)
        read_until(lambda: result.poll() is not None, timeout=5)
        assert time.monotonic() - forced_at < 2.0
        assert result.returncode == 130, output.decode(errors="replace")
        assert not pid_is_alive(hook_pid)
        assert not [child.pid for child in owned if child.is_running() and child.status() != psutil.STATUS_ZOMBIE]
        assert b"Traceback" not in output
    finally:
        if result is not None and result.poll() is None:
            result.terminate()
            result.wait(timeout=20)
        os.close(slave)
        os.close(master)


@pytest.mark.django_db(transaction=True)
def test_cli_run_retries_snapshot_after_filesystem_failure(initialized_archive):
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(live=True, PLUGINS="hashes")
    created = run_archivebox_cmd(["snapshot", "create", create_test_url()], cwd=initialized_archive, env=env)
    assert created.returncode == 0, created.stdout + created.stderr
    snapshot_id = next(record["id"] for record in parse_jsonl_output(created.stdout) if record.get("type") == "Snapshot")
    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(pk=snapshot_id)
        crawl_id = str(snapshot.crawl_id)
        directory = snapshot.output_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "input.txt").write_text("Capture survives a temporary filesystem failure")
    broken_directory = directory / "hashes"
    broken_directory.symlink_to("hashes")

    failed = run_archivebox_cmd(["run", f"--snapshot-id={snapshot_id}"], cwd=initialized_archive, env=env, timeout=60)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    assert "FileExistsError: [Errno 17]" in failed.stderr
    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(pk=snapshot_id)
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert not ArchiveResult.objects.filter(snapshot=snapshot).exists()

    broken_directory.unlink()
    resumed = run_archivebox_cmd(["run", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, timeout=60)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(pk=snapshot_id)
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        result = snapshot.archiveresult_set.get(plugin="hashes")
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert result.output_size > 0
    assert (directory / "hashes").is_dir()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("precreate_snapshot", [False, True])
def test_newest_crawl_runs_before_older_queued_and_started_crawls(initialized_archive, precreate_snapshot):
    from datetime import timedelta

    from django.utils import timezone

    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(live=True, PLUGINS="hashes")
    old_url, queued_url, newest_url = create_test_url(), create_test_url(), create_test_url()
    old = run_archivebox_cmd(["snapshot", "create", old_url], cwd=initialized_archive, env=env)
    assert old.returncode == 0, old.stdout + old.stderr
    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(url=old_url)
        Crawl.objects.filter(pk=snapshot.crawl_id).update(status=Crawl.StatusChoices.STARTED)
        Snapshot.objects.filter(pk=snapshot.pk).update(retry_at=timezone.now() - timedelta(days=1))
    queued = run_archivebox_cmd(
        ["snapshot" if precreate_snapshot else "crawl", "create", queued_url],
        cwd=initialized_archive,
        env=env,
    )
    assert queued.returncode == 0, queued.stdout + queued.stderr
    newest = run_archivebox_cmd(
        ["snapshot" if precreate_snapshot else "crawl", "create", newest_url],
        cwd=initialized_archive,
        env=env,
    )
    assert newest.returncode == 0, newest.stdout + newest.stderr

    result = run_archivebox_cmd(["run", "--no-stdin"], cwd=initialized_archive, env=env, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(url in result.stdout for url in (old_url, queued_url, newest_url))
    assert result.stdout.index(newest_url) < result.stdout.index(queued_url) < result.stdout.index(old_url), result.stdout
    with use_archivebox_db(initialized_archive):
        assert (
            Snapshot.objects.filter(
                url__in=[old_url, queued_url, newest_url],
                status=Snapshot.StatusChoices.SEALED,
            ).count()
            == 3
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(660)
def test_due_snapshots_share_one_crawl_scoped_chrome(initialized_archive, recursive_test_site):
    from django.utils import timezone

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Process
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(live=True, PLUGINS="chrome", CHROME_ISOLATION="crawl", CHROME_HEADLESS="true", CHROME_SANDBOX="false")
    _install_real_chrome_for_test(initialized_archive, env, isolation="crawl")
    urls = [recursive_test_site["root_url"], recursive_test_site["child_urls"][0]]
    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(
            urls="\n".join(urls),
            config={"PLUGINS": "chrome", "CHROME_ISOLATION": "crawl"},
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        for url in urls:
            Snapshot.objects.create(url=url, crawl=crawl, status=Snapshot.StatusChoices.QUEUED, retry_at=timezone.now())
        crawl_id = str(crawl.id)

    result = run_archivebox_cmd(["run", "--no-stdin", f"--crawl-id={crawl_id}"], cwd=initialized_archive, env=env, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    with use_archivebox_db(initialized_archive):
        snapshots = Snapshot.objects.filter(crawl_id=crawl_id, url__in=urls, status=Snapshot.StatusChoices.SEALED)
        assert snapshots.count() == 2
        assert all((snapshot.output_dir / "chrome" / "navigation.json").is_file() for snapshot in snapshots)
        launches = Process.objects.filter(
            pwd__contains=crawl_id,
            process_type=Process.TypeChoices.HOOK,
            cmd__0__endswith="on_CrawlSetup__90_chrome_launch.daemon.bg.js",
        )
        assert launches.count() == 1, [(process.pid, process.exit_code) for process in launches]
        assert launches.get().exit_code == 0


@pytest.mark.django_db(transaction=True)
def test_busy_crawl_does_not_report_snapshot_progress(initialized_archive):
    from datetime import timedelta
    from django.utils import timezone

    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.services.runner import _run_due_snapshot_id
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(
            urls="https://example.com/",
            config={"PLUGINS": "chrome", "CHROME_ISOLATION": "crawl"},
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now() + timedelta(minutes=1),
        )
        snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, retry_at=timezone.now())
        assert _run_due_snapshot_id(str(snapshot.id), lock_seconds=60, interactive_interrupts=False, runtime_config=None) is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(660)
def test_cli_run_signal_cleans_real_chrome_hook_process_group(initialized_archive, recursive_test_site):
    from archivebox.core.models import Snapshot
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(live=True, PLUGINS="chrome", CHROME_ISOLATION="crawl", CHROME_HEADLESS="true", CHROME_SANDBOX="false")
    _install_real_chrome_for_test(initialized_archive, env, isolation="crawl")

    result = run_archivebox_cmd(
        ["snapshot", "create", recursive_test_site["root_url"]],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    records = parse_jsonl_output(result.stdout)
    snapshot_id = next(record["id"] for record in records if record.get("type") == "Snapshot")
    with use_archivebox_db(initialized_archive):
        browser_state = Snapshot.objects.get(id=snapshot_id).output_dir / "chrome" / "browser.json"

    run_log = initialized_archive / "run-signal-chrome.log"
    run_log_handle = run_log.open("w", encoding="utf-8")
    run_process = run_archivebox_cmd(
        ["run", f"--snapshot-id={snapshot_id}"],
        cwd=initialized_archive,
        env=env,
        stdout=run_log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        wait=False,
    )
    run_log_handle.close()
    try:
        wait_for_log(browser_state, '"ready": true', timeout=120)
        child_pids = [child.pid for child in psutil.Process(run_process.pid).children(recursive=True) if pid_is_alive(child.pid)]
        assert child_pids

        run_process.send_signal(signal.SIGTERM)
        run_process.wait(timeout=30)
        output = run_log.read_text(encoding="utf-8", errors="replace")
        assert "Runner error" not in output
        for pid in child_pids:
            wait_for_pid_to_disappear(pid, timeout=15)
    finally:
        cleanup_process_group(run_process.pid)


class TestRunWithArchiveResult:
    """Tests for `archivebox run` with ArchiveResult input."""

    @pytest.mark.django_db(transaction=True)
    def test_run_treats_no_id_archiveresult_as_parent_snapshot_plugin_request(self, initialized_archive):
        import json

        from archivebox.core.models import ArchiveResult
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        create_result = run_archivebox_cmd(
            ["snapshot", "create", create_test_url()],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        snapshot_id = next(record["id"] for record in parse_jsonl_output(create_result.stdout) if record.get("type") == "Snapshot")
        missing_hook = "on_Snapshot__99_missing_favicon_hook"
        request = json.dumps(
            {
                "type": "ArchiveResult",
                "snapshot_id": snapshot_id,
                "plugin": "favicon",
                "hook_name": missing_hook,
                "status": "queued",
            },
        )

        result = run_archivebox_cmd(
            ["run"],
            stdin=f"{request}\n",
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0, result.stderr or result.stdout
        with use_archivebox_db(initialized_archive):
            rows = list(
                ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin="favicon").values_list(
                    "hook_name",
                    "status",
                    "output_str",
                ),
            )
        assert len(rows) == 1
        assert rows[0][0] != missing_hook
        assert rows[0][0].startswith("on_Snapshot__")
        assert rows[0][1] in ArchiveResult.FINAL_STATES

    def test_run_requeues_failed_archiveresult(self, initialized_archive):
        """Run uses a failed ArchiveResult as a parent Snapshot/plugin reference."""
        url = create_test_url()

        # Create snapshot and archive result
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", url],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        _cmd_result = run_archivebox_cmd(
            ["archiveresult", "create", "--plugin=favicon"],
            stdin=stdout1,
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert any(record.get("type") == "ArchiveResult" for record in parse_jsonl_output(stdout2))

        initial_run = run_archivebox_cmd(
            ["run"],
            stdin=stdout2,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert initial_run.returncode == 0, initial_run.stderr
        persisted_result = run_archivebox_cmd(
            ["archiveresult", "list", "--plugin=favicon"],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert persisted_result.returncode == 0, persisted_result.stderr
        assert any(record.get("type") == "ArchiveResult" for record in parse_jsonl_output(persisted_result.stdout))

        # Update to failed
        update_result = run_archivebox_cmd(
            ["archiveresult", "update", "--status=failed"],
            stdin=persisted_result.stdout,
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert update_result.returncode == 0, update_result.stderr
        failed_result = run_archivebox_cmd(
            ["archiveresult", "list", "--plugin=favicon"],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert failed_result.returncode == 0, failed_result.stderr
        failed_records = [record for record in parse_jsonl_output(failed_result.stdout) if record.get("type") == "ArchiveResult"]
        assert len(failed_records) == 1
        assert failed_records[0]["status"] == "failed"
        failed_jsonl = next(line for line in failed_result.stdout.splitlines() if failed_records[0]["id"] in line) + "\n"

        # Now run should re-queue it
        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=failed_jsonl,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout3, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout3)
        ar_records = [r for r in records if r.get("type") == "ArchiveResult"]
        assert len(ar_records) >= 1


class TestRunMixedInput:
    """Tests for `archivebox run` with mixed record types."""

    def test_run_handles_mixed_records_emitted_by_cli(self, initialized_archive):
        """Run handles real Crawl, Snapshot, and Tag records from CLI stages."""
        tag_result = run_archivebox_cmd(
            ["tag", "create", "mixed-run-tag"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert tag_result.returncode == 0, tag_result.stderr
        crawl_result = run_archivebox_cmd(
            ["crawl", "create", create_test_url()],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert crawl_result.returncode == 0, crawl_result.stderr
        snapshot_result = run_archivebox_cmd(
            ["snapshot", "create"],
            stdin=crawl_result.stdout,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert snapshot_result.returncode == 0, snapshot_result.stderr

        result = run_archivebox_cmd(
            ["run"],
            stdin=tag_result.stdout + snapshot_result.stdout,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0
        records = parse_jsonl_output(result.stdout)

        types = {record.get("type") for record in records}
        assert {"Crawl", "Snapshot", "Tag"}.issubset(types)
