"""
Tests for archivebox run CLI command.

Tests cover:
- run with stdin JSONL (Crawl, Snapshot, ArchiveResult)
- create-or-update behavior (records with/without id)
- pass-through output (for chaining)
"""

import os
import signal
import subprocess

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

RUN_TEST_ENV = {
    "PLUGINS": "favicon",
    "SAVE_FAVICON": "True",
}


def _install_real_chrome_for_test(data_dir, env, *, isolation):
    env["CHROME_ISOLATION"] = isolation
    env["CHROME_HEADLESS"] = "true"
    env["CHROME_SANDBOX"] = "false"
    install_process = run_archivebox_cmd(
        ["install", "chrome"],
        cwd=data_dir,
        env=env,
        timeout=600,
    )
    assert install_process.returncode == 0, install_process.stderr or install_process.stdout


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(660)
def test_cli_run_signal_cleans_real_chrome_hook_process_group(initialized_archive, recursive_test_site):
    from archivebox.core.models import Snapshot
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(live=True, PLUGINS="chrome", CHROME_ISOLATION="crawl", CHROME_HEADLESS="true", CHROME_SANDBOX="false")
    _install_real_chrome_for_test(initialized_archive, env, isolation="crawl")

    _cmd_result = run_archivebox_cmd(
        ["snapshot", "create", recursive_test_site["root_url"]],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout
    records = parse_jsonl_output(stdout)
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


class TestRunWithCrawl:
    """Tests for `archivebox run` with Crawl input."""

    def test_run_with_new_crawl(self, initialized_archive):
        """Run processes a Crawl emitted by the public create command."""
        create_result = run_archivebox_cmd(
            ["crawl", "create", create_test_url()],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert create_result.returncode == 0, create_result.stderr

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=create_result.stdout,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, f"Command failed: {stderr}"

        # Should output the created Crawl
        records = parse_jsonl_output(stdout)
        crawl_records = [r for r in records if r.get("type") == "Crawl"]
        assert len(crawl_records) >= 1
        assert crawl_records[0].get("id")  # Should have an id now

    def test_run_with_existing_crawl(self, initialized_archive):
        """Run re-queues an existing Crawl (with id)."""
        url = create_test_url()

        # First create a crawl
        _cmd_result = run_archivebox_cmd(
            ["crawl", "create", url],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        # Run with the existing crawl
        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=stdout1,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout2)
        assert len(records) >= 1


class TestRunWithSnapshot:
    """Tests for `archivebox run` with Snapshot input."""

    def test_run_with_new_snapshot(self, initialized_archive):
        """Run processes a Snapshot emitted by the public create command."""
        create_result = run_archivebox_cmd(
            ["snapshot", "create", create_test_url()],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert create_result.returncode == 0, create_result.stderr

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=create_result.stdout,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, f"Command failed: {stderr}"

        records = parse_jsonl_output(stdout)
        snapshot_records = [r for r in records if r.get("type") == "Snapshot"]
        assert len(snapshot_records) >= 1
        assert snapshot_records[0].get("id")

    def test_run_with_existing_snapshot(self, initialized_archive):
        """Run re-queues an existing Snapshot (with id)."""
        url = create_test_url()

        # First create a snapshot
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", url],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        # Run with the existing snapshot
        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=stdout1,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout2)
        assert len(records) >= 1

    def test_run_with_plain_url(self, initialized_archive):
        """Run accepts plain URL records (no type field)."""
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=url + "\n",
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) >= 1


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


@pytest.mark.django_db(transaction=True)
class TestRunRecovery:
    def test_run_maintenance_logs_unfinished_crawl_repair(self, initialized_archive):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        old = timezone.now() - timedelta(hours=13)
        with use_archivebox_db(initialized_archive):
            crawl = Crawl.objects.create(
                urls="https://example.com",
                created_by_id=get_or_create_system_user_pk(),
                status=Crawl.StatusChoices.STARTED,
                retry_at=None,
            )
            snapshot = Snapshot.objects.create(
                url="https://example.com",
                crawl=crawl,
                status=Snapshot.StatusChoices.QUEUED,
                retry_at=None,
            )
            Crawl.objects.filter(id=crawl.id).update(modified_at=old, retry_at=None)
            Snapshot.objects.filter(id=snapshot.id).update(modified_at=old, retry_at=None)
            crawl_id = crawl.id
            snapshot_id = snapshot.id

        _cmd_result = run_archivebox_cmd(
            ["run", "--maintenance-only"],
            cwd=initialized_archive,
            timeout=90,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, stdout + stderr
        assert "Repairing" in stderr
        assert "Resuming 1 Crawl(s) with pending URLs ready to archive" in stderr
        assert "interrupted before" in stderr
        assert "remaining URLs" in stderr

        with use_archivebox_db(initialized_archive):
            crawl = Crawl.objects.get(id=crawl_id)
            snapshot = Snapshot.objects.get(id=snapshot_id)
            assert crawl.status == Crawl.StatusChoices.STARTED
            assert crawl.retry_at is not None
            assert snapshot.status == Snapshot.StatusChoices.QUEUED
            assert snapshot.retry_at is not None


class TestRunPassThrough:
    """Tests for pass-through behavior in `archivebox run`."""

    def test_run_passes_through_tag_emitted_by_cli(self, initialized_archive):
        """Run passes through a real non-runnable Tag record."""
        tag_result = run_archivebox_cmd(
            ["tag", "create", "run-input-tag"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert tag_result.returncode == 0, tag_result.stderr
        tag_record = parse_jsonl_output(tag_result.stdout)[0]

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=tag_result.stdout,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        tag_records = [record for record in records if record.get("type") == "Tag"]
        assert len(tag_records) == 1
        assert tag_records[0]["id"] == tag_record["id"]

    def test_run_outputs_all_processed_records(self, initialized_archive):
        """Run outputs all processed records for chaining."""
        url = create_test_url()
        create_result = run_archivebox_cmd(
            ["crawl", "create", url],
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert create_result.returncode == 0, create_result.stderr

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=create_result.stdout,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        # Should have at least the Crawl in output
        assert len(records) >= 1


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

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=tag_result.stdout + snapshot_result.stdout,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)

        types = {record.get("type") for record in records}
        assert {"Crawl", "Snapshot", "Tag"}.issubset(types)


class TestRunEmpty:
    """Tests for `archivebox run` edge cases."""

    def test_run_empty_stdin(self, initialized_archive):
        """Run with empty stdin returns success."""
        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin="",
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0

    def test_run_no_runnable_records_to_process(self, initialized_archive):
        """Run with only a real non-runnable Tag reports no work."""
        tag_result = run_archivebox_cmd(
            ["tag", "create", "non-runnable-tag"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert tag_result.returncode == 0, tag_result.stderr

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=tag_result.stdout,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "No records to process" in stderr


class TestRunDaemonMode:
    @pytest.mark.parametrize("stdin_kind", ["malformed", "valid-snapshot"])
    def test_run_daemon_ignores_piped_stdin_and_starts_real_runner(
        self,
        initialized_archive,
        tmp_path_factory,
        db,
        stdin_kind,
    ):
        from archivebox.core.models import Snapshot
        from archivebox.machine.models import Process
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        snapshot_url = None
        if stdin_kind == "valid-snapshot":
            piped_source_archive = tmp_path_factory.mktemp("daemon-piped-source")
            init_result = run_archivebox_cmd(
                ["init", "--quick"],
                cwd=piped_source_archive,
                default_cli_env=True,
                disable_extractors=True,
            )
            assert init_result.returncode == 0, init_result.stderr
            snapshot_url = create_test_url()
            snapshot_result = run_archivebox_cmd(
                ["snapshot", "create", snapshot_url],
                cwd=piped_source_archive,
                default_cli_env=True,
                disable_extractors=True,
            )
            assert snapshot_result.returncode == 0, snapshot_result.stderr
            piped_stdin = snapshot_result.stdout
        else:
            piped_stdin = "{this is not jsonl}\n"

        env = cli_env(PLUGINS="__archivebox_test_no_plugins__")
        queued = run_archivebox_cmd(
            ["crawl", "create", create_test_url()],
            cwd=initialized_archive,
            env=env,
            timeout=60,
        )
        assert queued.returncode == 0, queued.stderr or queued.stdout
        daemon_log = initialized_archive / f"run-daemon-{stdin_kind}.log"
        daemon_log_handle = daemon_log.open("w", encoding="utf-8")
        proc = run_archivebox_cmd(
            ["run", "--daemon"],
            cwd=initialized_archive,
            env=env,
            stdin=subprocess.PIPE,
            stdout=daemon_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            wait=False,
        )
        daemon_log_handle.close()
        assert proc.stdin is not None

        try:
            proc.stdin.write(piped_stdin)
            proc.stdin.close()

            wait_for_log(daemon_log, "[Crawl#", timeout=30)
            with use_archivebox_db(initialized_archive):
                started = Process.objects.filter(
                    process_type=Process.TypeChoices.ORCHESTRATOR,
                    status=Process.StatusChoices.RUNNING,
                    pid=proc.pid,
                ).exists()
            assert started
            if snapshot_url is not None:
                with use_archivebox_db(initialized_archive):
                    assert not Snapshot.objects.filter(url=snapshot_url).exists()
        finally:
            os.kill(proc.pid, signal.SIGTERM)
            proc.wait(timeout=15)

        output = daemon_log.read_text(encoding="utf-8", errors="replace")
        assert proc.returncode == 143, output
        assert "No records to process" not in output

    def test_run_daemon_takeover_has_single_active_runner_gate(self, initialized_archive, db):
        from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE
        from archivebox.machine.models import Process
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        env = cli_env(PLUGINS="__archivebox_test_no_plugins__")

        def active_runners():
            with use_archivebox_db(initialized_archive):
                return [
                    proc
                    for proc in Process.objects.filter(
                        process_type=Process.TypeChoices.ORCHESTRATOR,
                        worker_type=RUNNER_ACTIVE_WORKER_TYPE,
                        status=Process.StatusChoices.RUNNING,
                        pwd=str(initialized_archive),
                    )
                    if proc.is_running
                ]

        queued = run_archivebox_cmd(["crawl", "create", create_test_url()], cwd=initialized_archive, env=env, timeout=60)
        assert queued.returncode == 0, queued.stderr or queued.stdout
        procs = []
        logs = []
        for index in range(2):
            log_path = initialized_archive / f"run-daemon-takeover-{index}.log"
            log_handle = log_path.open("w", encoding="utf-8")
            proc = run_archivebox_cmd(
                ["run", "--daemon"],
                cwd=initialized_archive,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                wait=False,
            )
            log_handle.close()
            procs.append(proc)
            logs.append(log_path)
            if index == 0:
                wait_for_log(log_path, "[Crawl#", timeout=30)
        try:
            wait_for_log(logs[1], "Stopping older ArchiveBox runner process", timeout=30)
            queued = run_archivebox_cmd(["crawl", "create", create_test_url()], cwd=initialized_archive, env=env, timeout=60)
            assert queued.returncode == 0, queued.stderr or queued.stdout
            wait_for_log(logs[1], "[Crawl#", timeout=30)
            active = active_runners()
            assert len(active) == 1
            active_pid = active[0].pid
            assert active_pid == procs[1].pid

            os.kill(active_pid, signal.SIGTERM)
            wait_for_pid_to_disappear(active_pid, timeout=15)
            replacement_log = initialized_archive / "run-daemon-takeover-replacement.log"
            replacement_log_handle = replacement_log.open("w", encoding="utf-8")
            replacement = run_archivebox_cmd(
                ["run", "--daemon"],
                cwd=initialized_archive,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=replacement_log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                wait=False,
            )
            replacement_log_handle.close()
            procs.append(replacement)
            queued = run_archivebox_cmd(["crawl", "create", create_test_url()], cwd=initialized_archive, env=env, timeout=60)
            assert queued.returncode == 0, queued.stderr or queued.stdout
            wait_for_log(replacement_log, "[Crawl#", timeout=30)
            recovered = active_runners()
            assert len(recovered) == 1
            assert recovered[0].pid == replacement.pid
            assert recovered[0].pid != active_pid
        finally:
            for proc in procs:
                cleanup_process_group(proc.pid)
                proc.wait(timeout=15)

    def test_run_daemon_retires_runner_from_previous_pid_namespace(self, initialized_archive, db):
        from django.utils import timezone

        from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE
        from archivebox.machine.models import Machine, PROCESS_PID_NAMESPACE_KEY, Process, get_current_pid_namespace
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        env = cli_env(PLUGINS="__archivebox_test_no_plugins__")
        with use_archivebox_db(initialized_archive):
            stopped_runner = Process.objects.create(
                machine=Machine.current(),
                process_type=Process.TypeChoices.ORCHESTRATOR,
                worker_type=RUNNER_ACTIVE_WORKER_TYPE,
                status=Process.StatusChoices.RUNNING,
                pwd=str(initialized_archive),
                pid=1,
                started_at=timezone.now(),
                env={PROCESS_PID_NAMESPACE_KEY: f"{get_current_pid_namespace()}-stopped-container"},
            )
        queued = run_archivebox_cmd(["crawl", "create", create_test_url()], cwd=initialized_archive, env=env, timeout=60)
        assert queued.returncode == 0, queued.stderr or queued.stdout

        daemon_log = initialized_archive / "run-daemon-stopped-container.log"
        daemon_log_handle = daemon_log.open("w", encoding="utf-8")
        replacement = run_archivebox_cmd(
            ["run", "--daemon"],
            cwd=initialized_archive,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=daemon_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            wait=False,
        )
        daemon_log_handle.close()

        try:
            wait_for_log(daemon_log, "[Crawl#", timeout=10)
            assert "Multiple orchestrators sharing a single collection is not officially supported" in daemon_log.read_text()
            with use_archivebox_db(initialized_archive):
                stopped_runner.refresh_from_db()
                assert stopped_runner.status == Process.StatusChoices.EXITED
                active_runner = Process.objects.get(
                    process_type=Process.TypeChoices.ORCHESTRATOR,
                    worker_type=RUNNER_ACTIVE_WORKER_TYPE,
                    status=Process.StatusChoices.RUNNING,
                    pwd=str(initialized_archive),
                )
                assert active_runner.pid == replacement.pid
        finally:
            cleanup_process_group(replacement.pid)
            replacement.wait(timeout=15)


@pytest.mark.django_db
class TestRecoverOrchestratorState:
    def test_recover_orchestrator_state_unlocks_started_crawl_with_pending_snapshot(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        assert recovered["crawls_started_with_due_snapshots"] == 1
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None

    def test_recover_orchestrator_state_unlocks_started_crawl_with_finished_snapshots_for_runner(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        assert "sealed_crawls" not in recovered
        assert recovered["crawls_started_without_active_snapshots"] == 1
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None

        assert run_due_crawl(crawl, lock_seconds=60) is True
        crawl.refresh_from_db()

        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_recover_orchestrator_state_repairs_retry_at_status_invariants(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        user_id = get_or_create_system_user_pk()
        queued_crawl = Crawl.objects.create(
            urls="https://example.com/queued-crawl",
            created_by_id=user_id,
            status=Crawl.StatusChoices.QUEUED,
            retry_at=None,
        )
        sealed_crawl = Crawl.objects.create(
            urls="https://example.com/sealed-crawl",
            created_by_id=user_id,
            status=Crawl.StatusChoices.SEALED,
            retry_at=timezone.now(),
        )
        queued_snapshot = Snapshot.objects.create(
            url="https://example.com/queued-snapshot",
            crawl=queued_crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )
        sealed_snapshot = Snapshot.objects.create(
            url="https://example.com/sealed-snapshot",
            crawl=sealed_crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=timezone.now(),
        )

        recovered = recover_orchestrator_state()

        queued_crawl.refresh_from_db()
        sealed_crawl.refresh_from_db()
        queued_snapshot.refresh_from_db()
        sealed_snapshot.refresh_from_db()

        assert recovered["crawls_queued_without_retry_at"] == 1
        assert recovered["snapshots_queued_without_retry_at"] == 1
        assert queued_crawl.status == Crawl.StatusChoices.QUEUED
        assert queued_crawl.retry_at is not None
        assert sealed_crawl.status == Crawl.StatusChoices.SEALED
        assert sealed_crawl.retry_at is not None
        assert queued_snapshot.status == Snapshot.StatusChoices.QUEUED
        assert queued_snapshot.retry_at is not None
        assert sealed_snapshot.status == Snapshot.StatusChoices.SEALED
        assert sealed_snapshot.retry_at is not None

    def test_recover_orchestrator_state_leaves_due_queued_snapshot_for_runner_even_with_final_results(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert "sealed_queued_snapshots" not in recovered
        assert "sealed_queued_crawls" not in recovered
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at is not None
        assert snapshot.downloaded_at is None
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at is not None

    @pytest.mark.django_db(transaction=True)
    def test_recover_orchestrator_state_leaves_stale_queued_final_rows_for_runner(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

        old = timezone.now() - timedelta(hours=13)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            config={"PLUGINS": "__archivebox_test_no_plugins__"},
            status=Crawl.StatusChoices.QUEUED,
            retry_at=old,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=old,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )
        Crawl.objects.filter(pk=crawl.pk).update(modified_at=old)
        Snapshot.objects.filter(pk=snapshot.pk).update(modified_at=old)
        ArchiveResult.objects.filter(pk=result.pk).update(modified_at=old)

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert "sealed_queued_snapshots" not in recovered
        assert "sealed_queued_crawls" not in recovered
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at == old
        assert snapshot.downloaded_at is None
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == old

        assert run_due_snapshot(snapshot, lock_seconds=60) is True
        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_runs_snapshot_without_consulting_final_result_rows(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            config={"PLUGINS": "__archivebox_test_no_plugins__"},
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert snapshot.downloaded_at is not None

    def test_run_due_snapshot_pauses_child_when_parent_is_paused(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot
        from archivebox.workers.models import RETRY_AT_MAX

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.PAUSED
        assert snapshot.retry_at == RETRY_AT_MAX
        assert result.status == ArchiveResult.StatusChoices.QUEUED
        assert snapshot.archiveresult_set.count() == 1

    def test_parent_status_transitions_schedule_children_to_follow_parent_status(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot
        from archivebox.workers.models import RETRY_AT_MAX

        paused_crawl = Crawl.objects.create(
            urls="https://example.com/paused",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        paused_child = Snapshot.objects.create(
            url="https://example.com/paused",
            crawl=paused_crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        paused_result = ArchiveResult.objects.create(
            snapshot=paused_child,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        paused_crawl.pause()

        sealed_crawl = Crawl.objects.create(
            urls="https://example.com/sealed",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        sealed_child = Snapshot.objects.create(
            url="https://example.com/sealed",
            crawl=sealed_crawl,
            status=Snapshot.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )
        sealed_started_child = Snapshot.objects.create(
            url="https://example.com/sealed-started",
            crawl=sealed_crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        sealed_crawl.cancel()

        paused_child.refresh_from_db()
        paused_result.refresh_from_db()
        sealed_child.refresh_from_db()
        sealed_started_child.refresh_from_db()
        assert paused_child.status == Snapshot.StatusChoices.PAUSED
        assert paused_child.retry_at == RETRY_AT_MAX
        assert paused_result.status == ArchiveResult.StatusChoices.QUEUED
        assert sealed_child.status == Snapshot.StatusChoices.PAUSED
        assert sealed_child.retry_at is not None
        assert sealed_child.retry_at <= timezone.now()
        assert sealed_started_child.status == Snapshot.StatusChoices.STARTED
        assert sealed_started_child.retry_at is not None
        assert sealed_started_child.retry_at <= timezone.now()

        assert run_due_snapshot(sealed_child, lock_seconds=60) is True
        sealed_child.refresh_from_db()
        assert sealed_child.status == Snapshot.StatusChoices.SEALED
        assert sealed_child.retry_at is None

        assert run_due_snapshot(sealed_started_child, lock_seconds=60) is True
        sealed_started_child.refresh_from_db()
        assert sealed_started_child.status == Snapshot.StatusChoices.SEALED
        assert sealed_started_child.retry_at is None

    def test_recover_orchestrator_state_leaves_due_active_crawl_for_runner(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        old = timezone.now() - timedelta(hours=13)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=old,
        )
        Crawl.objects.filter(id=crawl.id).update(modified_at=old, retry_at=old)

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        assert "stale_active_crawls_unlocked" not in recovered
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == old

    def test_recover_orchestrator_state_unlocks_started_snapshot_without_running_result(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        future = timezone.now() + timedelta(seconds=45)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert recovered["snapshots_started_without_running_results"] == 1
        assert "snapshots_active_under_sealed_crawls" not in recovered
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at < future
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_recover_orchestrator_state_unlocks_future_started_crawl_and_snapshot_after_owner_dies(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        future = timezone.now() + timedelta(seconds=45)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=future,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        snapshot.refresh_from_db()

        assert recovered["snapshots_started_without_running_results"] == 1
        assert recovered["crawls_started_with_due_snapshots"] == 1
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert crawl.retry_at is not None
        assert snapshot.retry_at is not None
        assert crawl.retry_at < future
        assert snapshot.retry_at < future

    def test_recover_orchestrator_state_preserves_future_started_snapshot_with_live_result_process(self, initialized_archive):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, NetworkInterface, Process

        worker = run_archivebox_cmd(
            ["manage", "shell"],
            cwd=initialized_archive,
            env=cli_env(live=True),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            capture_output=False,
            start_new_session=True,
            wait=False,
        )
        assert worker.stdin is not None
        assert pid_is_alive(worker.pid)
        try:
            future = timezone.now() + timedelta(seconds=45)
            crawl = Crawl.objects.create(
                urls="https://example.com",
                created_by_id=get_or_create_system_user_pk(),
                status=Crawl.StatusChoices.STARTED,
                retry_at=future,
            )
            snapshot = Snapshot.objects.create(
                url="https://example.com",
                crawl=crawl,
                status=Snapshot.StatusChoices.STARTED,
                retry_at=future,
            )
            process = Process.objects.create(
                machine=Machine.current(refresh=True),
                iface=NetworkInterface.current(refresh=True),
                process_type=Process.TypeChoices.HOOK,
                worker_type="archiveresult",
                pwd=str(snapshot.output_dir / "title"),
                cmd=[],
                status=Process.StatusChoices.RUNNING,
                retry_at=None,
                pid=worker.pid,
                started_at=timezone.now(),
                timeout=120,
            )
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="title",
                hook_name="on_Snapshot__01_title",
                status=ArchiveResult.StatusChoices.STARTED,
                process=process,
            )

            recovered = recover_orchestrator_state()

            snapshot.refresh_from_db()
            assert recovered["snapshots_started_without_running_results"] == 0
            assert snapshot.status == Snapshot.StatusChoices.STARTED
            assert snapshot.retry_at == future
        finally:
            worker.stdin.close()
            worker.wait(timeout=20)
            assert not pid_is_alive(worker.pid)

    def test_recover_orchestrator_state_does_not_resume_paused_rows_with_max_retry_at(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.workers.models import RETRY_AT_MAX

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.PAUSED,
            retry_at=RETRY_AT_MAX,
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        snapshot.refresh_from_db()

        assert recovered["crawls_started_with_due_snapshots"] == 0
        assert recovered["crawls_started_waiting_on_future_snapshots"] == 0
        assert recovered["crawls_started_without_active_snapshots"] == 0
        assert recovered["snapshots_started_without_running_results"] == 0
        assert crawl.status == Crawl.StatusChoices.PAUSED
        assert snapshot.status == Snapshot.StatusChoices.PAUSED
        assert crawl.retry_at == RETRY_AT_MAX
        assert snapshot.retry_at == RETRY_AT_MAX

    def test_recover_orchestrator_state_does_not_wake_sealed_snapshot_maintenance_rows(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            hook_name="on_Snapshot__50_singlefile.py",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="search_backend_sonic",
            hook_name="on_Snapshot__91_index_sonic",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert "snapshots_sealed_with_queued_results" not in recovered
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_run_due_snapshot_finalizes_completed_upload_result_left_queued(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=timezone.now(),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="dom",
            hook_name="on_Snapshot__archivebox_browser_extension_upload",
            status=ArchiveResult.StatusChoices.QUEUED,
            output_str="output.html",
            output_files={"output.html": {"extension": "html", "mimetype": "text/html", "size": 42}},
            output_size=42,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        result.refresh_from_db()
        snapshot.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert snapshot.retry_at is None

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_keeps_extension_upload_and_runs_server_hooks(self):

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

        crawl = Crawl.objects.create(
            urls="https://example.com/extension-upload",
            created_by_id=get_or_create_system_user_pk(),
            config={"PLUGINS": "parse_txt_urls"},
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/extension-upload",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        uploaded_result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="chrome_mhtml",
            hook_name="on_Snapshot__archivebox_browser_extension_upload",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="snapshot.mhtml",
            output_files={"snapshot.mhtml": {"extension": "mhtml", "mimetype": "multipart/related", "size": 42}},
            output_size=42,
        )

        recovered = recover_orchestrator_state()
        snapshot.refresh_from_db()
        crawl.refresh_from_db()
        assert recovered["snapshots_sealed_with_extension_uploads_only"] == 1
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at is not None
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        uploaded_result.refresh_from_db()
        server_results = snapshot.archiveresult_set.exclude(
            hook_name="on_Snapshot__archivebox_browser_extension_upload",
        )
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert uploaded_result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert server_results.filter(plugin="parse_txt_urls").exists()
        assert not server_results.filter(
            status__in=(ArchiveResult.StatusChoices.QUEUED, ArchiveResult.StatusChoices.STARTED),
        ).exists()

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_migrates_filesystem_before_returning_after_fast_finalize(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

        crawl = Crawl.objects.create(
            urls="https://example.com/legacy-fast-finalize",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/legacy-fast-finalize",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
            downloaded_at=timezone.now(),
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(fs_version="0.8.0")
        snapshot.refresh_from_db()
        legacy_dir = snapshot.output_dir
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "index.html").write_text("legacy archive", encoding="utf-8")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__06_wget",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="index.html",
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert snapshot.output_dir.joinpath("index.html").read_text(encoding="utf-8") == "legacy archive"
        assert not legacy_dir.exists()

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_migrates_filesystem_after_sealed_parent_reconciliation(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

        crawl = Crawl.objects.create(
            urls="https://example.com/legacy-parent-sealed",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/legacy-parent-sealed",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(fs_version="0.8.0")
        snapshot.refresh_from_db()
        legacy_dir = snapshot.output_dir
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "index.html").write_text("legacy archive", encoding="utf-8")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__06_wget",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="index.html",
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert snapshot.output_dir.joinpath("index.html").read_text(encoding="utf-8") == "legacy archive"
        assert not legacy_dir.exists()

    @pytest.mark.django_db(transaction=True)
    @pytest.mark.timeout(300)
    @pytest.mark.parametrize("chrome_isolation", ["crawl", "snapshot"])
    def test_resume_queued_chrome_navigate_reruns_background_prerequisites(
        self,
        initialized_archive,
        recursive_test_site,
        chrome_isolation,
    ):
        from archivebox.core.models import ArchiveResult
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        env = cli_env(disable_extractors=True)
        env.update(
            {
                "SAVE_TITLE": "false",
                "TIMEOUT": "60",
                "CHROME_TIMEOUT": "30",
            },
        )
        _install_real_chrome_for_test(initialized_archive, env, isolation=chrome_isolation)

        add_process = run_archivebox_cmd(
            [
                "add",
                "--depth=0",
                "--plugins=chrome",
                recursive_test_site["root_url"],
            ],
            cwd=initialized_archive,
            env=env,
            timeout=600,
        )
        assert add_process.returncode == 0, add_process.stderr or add_process.stdout

        list_process = run_archivebox_cmd(
            ["archiveresult", "list", "--plugin=chrome"],
            cwd=initialized_archive,
            env=env,
            timeout=60,
        )
        assert list_process.returncode == 0, list_process.stderr or list_process.stdout
        chrome_results = parse_jsonl_output(list_process.stdout)
        navigate_record = next(record for record in chrome_results if record["hook_name"] == "on_Snapshot__30_chrome_navigate")
        snapshot_id = navigate_record["snapshot_id"]

        with use_archivebox_db(initialized_archive):
            tab_result = ArchiveResult.objects.get(
                snapshot_id=snapshot_id,
                plugin="chrome",
                hook_name="on_Snapshot__01_chrome_tab.daemon.bg",
            )
            first_tab_process_id = tab_result.process_id
            assert first_tab_process_id is not None

        update_process = run_archivebox_cmd(
            ["archiveresult", "update", "--status=queued"],
            stdin=next(line for line in list_process.stdout.splitlines() if navigate_record["id"] in line) + "\n",
            cwd=initialized_archive,
            env=env,
            timeout=60,
        )
        assert update_process.returncode == 0, update_process.stderr or update_process.stdout

        run_process = run_archivebox_cmd(
            ["run"],
            cwd=initialized_archive,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            wait=False,
            start_new_session=True,
        )
        assert run_process.stdin is not None
        run_process.stdin.write(update_process.stdout)
        run_process.stdin.close()

        try:
            run_process.wait(timeout=120)
        finally:
            cleanup_process_group(run_process.pid)

        with use_archivebox_db(initialized_archive):
            navigate_result = ArchiveResult.objects.get(
                snapshot_id=snapshot_id,
                plugin="chrome",
                hook_name="on_Snapshot__30_chrome_navigate",
            )
            tab_result = ArchiveResult.objects.get(
                snapshot_id=snapshot_id,
                plugin="chrome",
                hook_name="on_Snapshot__01_chrome_tab.daemon.bg",
            )

        assert run_process.returncode == 0
        assert navigate_result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert tab_result.process_id is not None
        assert tab_result.process_id != first_tab_process_id

    def test_recover_orchestrator_state_ignores_sealed_downloaded_snapshot_without_results(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            downloaded_at=timezone.now(),
            retry_at=None,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert recovered["snapshots_started_without_running_results"] == 0
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    @pytest.mark.django_db(transaction=True)
    def test_recover_orchestrator_state_unlocks_started_snapshot_with_final_results_for_runner(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_snapshot

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            config={"PLUGINS": "__archivebox_test_no_plugins__"},
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        recovered = recover_orchestrator_state()

        snapshot.refresh_from_db()
        assert "sealed_snapshots" not in recovered
        assert recovered["snapshots_started_without_running_results"] == 1
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None

        assert run_due_snapshot(snapshot, lock_seconds=60) is True
        snapshot.refresh_from_db()

        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None


@pytest.mark.django_db
class TestRunDueCrawlState:
    def test_idle_maintenance_repairs_archive_result_delete_at(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_pending_crawls

        crawl = Crawl.objects.create(
            urls="https://example.com/retention-repair",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
            config={"DELETE_AFTER": "2h"},
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/retention-repair",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="search_backend_sqlite",
            hook_name="on_Snapshot__90_index_sqlite.py",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        # ArchiveResult saves are the plugin-event hot path. They intentionally
        # do not resolve parent Snapshot/Crawl config on every write; the real
        # runner's idle maintenance pass owns missing delete_at repair.
        assert result.delete_at is None
        assert run_pending_crawls(daemon=False, maintenance_only=True) == 0

        result.refresh_from_db()
        assert result.delete_at is not None

    def test_maintenance_only_runner_does_not_start_regular_queued_crawls(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_pending_crawls

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=now,
        )

        assert run_pending_crawls(daemon=False, maintenance_only=True) == 0

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == now
        assert crawl.snapshot_set.count() == 0

    def test_maintenance_only_runner_clears_snapshot_tick_without_scheduling_archive_results(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_pending_crawls

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://example.com/disabled-result",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com/disabled-result",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=now,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="disabled_plugin",
            hook_name="on_Snapshot__50_disabled",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        assert run_pending_crawls(daemon=False, maintenance_only=True) == 0

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert snapshot.retry_at is None
        assert result.status == ArchiveResult.StatusChoices.QUEUED

    def test_snapshot_start_writes_short_future_lease(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )

        snapshot.advance_lifecycle()
        snapshot.refresh_from_db()

        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at > timezone.now()

    def test_due_started_snapshot_with_live_child_extends_lease_without_reset(self):
        import os
        from datetime import datetime

        import psutil
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, NetworkInterface, Process
        from archivebox.services.runner import run_due_snapshot

        now = timezone.now()
        os_proc = psutil.Process(os.getpid())
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=now,
        )
        process = Process.objects.create(
            machine=Machine.current(),
            iface=NetworkInterface.current(),
            process_type=Process.TypeChoices.HOOK,
            status=Process.StatusChoices.RUNNING,
            pid=os.getpid(),
            started_at=datetime.fromtimestamp(os_proc.create_time(), tz=timezone.get_current_timezone()),
            cmd=os_proc.cmdline(),
            pwd=str(snapshot.output_dir / "title"),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            process=process,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
            output_str="live work should not be reset",
            output_files={"partial.txt": {"size": 12}},
            output_size=12,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at > now
        assert result.status == ArchiveResult.StatusChoices.STARTED
        assert result.output_str == "live work should not be reset"
        assert result.output_files == {"partial.txt": {"size": 12}}
        assert result.output_size == 12

    def test_run_due_crawl_seals_finished_started_crawl(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_run_due_crawl_preserves_next_future_snapshot_retry(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl

        future = timezone.now() + timedelta(hours=1)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=future,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at == future

    def test_run_due_crawl_preserves_next_future_started_snapshot_lease(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl

        future = timezone.now() + timedelta(minutes=5)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at == future

    def test_run_due_crawl_unlocks_null_retry_queued_snapshot(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=None,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        snapshot.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None
        assert snapshot.retry_at is not None


@pytest.mark.django_db
class TestRecoverOrchestratorStateRedFailureModes:
    def test_recovery_uses_newest_orphaned_process_for_exact_hook(self):
        import json
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, NetworkInterface, Process

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(url="https://example.com", crawl=crawl, status=Snapshot.StatusChoices.SEALED, retry_at=None)
        machine = Machine.current(refresh=True)
        iface = NetworkInterface.current(refresh=True)
        hook_name = "on_Snapshot__01_title.daemon.bg"
        older_start = timezone.now() - timedelta(minutes=2)
        newer_start = timezone.now() - timedelta(minutes=1)

        for started_at, output_str in ((older_start, "older title"), (newer_start, "newer title")):
            records = [
                {
                    "type": "ArchiveResult",
                    "plugin": "title",
                    "hook_name": hook_name,
                    "status": "succeeded",
                    "output_str": output_str,
                    "output_json": {"title": output_str},
                },
            ]
            if started_at == newer_start:
                records.append(
                    {
                        "type": "ArchiveResult",
                        "plugin": "title",
                        "hook_name": "on_Snapshot__02_other_title_hook",
                        "status": "failed",
                        "output_str": "wrong hook",
                    },
                )
            Process.objects.create(
                machine=machine,
                iface=iface,
                process_type=Process.TypeChoices.HOOK,
                worker_type="archiveresult",
                pwd=str(snapshot.output_dir / "title"),
                cmd=[f"{hook_name}.py"],
                status=Process.StatusChoices.EXITED,
                retry_at=None,
                exit_code=0,
                started_at=started_at,
                ended_at=started_at + timedelta(seconds=1),
                stdout="\n".join(json.dumps(record) for record in records),
            )

        recovered = recover_orchestrator_state()

        assert recovered["archiveresults_missing_for_orphaned_hook_processes"] == 1
        assert ArchiveResult.objects.filter(snapshot=snapshot, plugin="title", hook_name=hook_name).count() == 1
        result = ArchiveResult.objects.get(snapshot=snapshot, plugin="title", hook_name=hook_name)
        assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert result.output_str == "newer title"
        assert result.output_json == {"title": "newer title"}
        assert result.start_ts == newer_start
        assert result.end_ts == newer_start + timedelta(seconds=1)
        assert result.process.started_at == newer_start

    def test_recovery_does_not_seal_queued_snapshot_waiting_for_future_retry_even_with_final_results(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=future,
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=future,
        )
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )

        recover_orchestrator_state()

        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.QUEUED
        assert snapshot.retry_at == future

    def test_recovery_does_not_seal_queued_crawl_waiting_for_future_retry_even_with_finished_snapshots(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=future,
        )
        Snapshot.objects.create(url="https://example.com", crawl=crawl, status=Snapshot.StatusChoices.SEALED, retry_at=None)

        recover_orchestrator_state()

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == future

    def test_recovery_unlocks_started_parent_to_future_retry_child_not_now(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://www.mathjax.org/",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        Snapshot.objects.create(url="https://www.mathjax.org/", crawl=crawl, status=Snapshot.StatusChoices.QUEUED, retry_at=future)

        recover_orchestrator_state()

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at == future

    def test_recovery_closes_interrupted_result_and_requeues_parent_snapshot(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(
            urls="https://www.mathjax.org/",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://www.mathjax.org/",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
        )

        recover_orchestrator_state()

        result.refresh_from_db()
        snapshot.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.FAILED
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None

    def test_recovery_closes_started_archiveresult_with_exited_process(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, NetworkInterface, Process

        crawl = Crawl.objects.create(
            urls="https://revealjs.com/",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(url="https://revealjs.com/", crawl=crawl, status=Snapshot.StatusChoices.STARTED, retry_at=None)
        process = Process.objects.create(
            machine=Machine.current(refresh=True),
            iface=NetworkInterface.current(refresh=True),
            process_type=Process.TypeChoices.HOOK,
            worker_type="archiveresult",
            pwd=str(snapshot.output_dir / "title"),
            cmd=["python", "--version"],
            status=Process.StatusChoices.EXITED,
            retry_at=None,
            exit_code=0,
            ended_at=timezone.now(),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
            process=process,
        )

        recover_orchestrator_state()

        result.refresh_from_db()
        snapshot.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.FAILED
        assert snapshot.retry_at is not None

    def test_recovery_does_not_reopen_sealed_snapshot_for_interrupted_result_projection(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, NetworkInterface, Process

        crawl = Crawl.objects.create(
            urls="https://pdfobject.com/pdf/sample-3pp.pdf",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://pdfobject.com/pdf/sample-3pp.pdf",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        process = Process.objects.create(
            machine=Machine.current(refresh=True),
            iface=NetworkInterface.current(refresh=True),
            process_type=Process.TypeChoices.HOOK,
            worker_type="archiveresult",
            pwd=str(snapshot.output_dir / "pdf"),
            cmd=["python", "--version"],
            status=Process.StatusChoices.EXITED,
            retry_at=None,
            exit_code=0,
            ended_at=timezone.now(),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="pdf",
            hook_name="on_Snapshot__50_pdf",
            status=ArchiveResult.StatusChoices.STARTED,
            process=process,
        )

        recover_orchestrator_state()

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert result.status == ArchiveResult.StatusChoices.FAILED

    def test_recovery_closes_result_projection_before_unlocking_snapshot(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl

        crawl = Crawl.objects.create(
            urls="https://mermaid-js.github.io/mermaid/",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://mermaid-js.github.io/mermaid/",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=None,
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
        )

        recover_orchestrator_state()

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.FAILED
        assert snapshot.retry_at is not None

    def test_crawl_runner_load_run_state_does_not_return_future_retry_snapshots(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import CrawlRunner

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=future,
        )
        Snapshot.objects.create(url="https://example.com", crawl=crawl, status=Snapshot.StatusChoices.QUEUED, retry_at=future)

        runner = CrawlRunner(crawl, selected_plugins=[])

        assert runner.load_run_state() == []

    def test_crawl_runner_finalize_run_state_preserves_next_future_snapshot_retry(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import CrawlRunner

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=None,
        )
        Snapshot.objects.create(url="https://blog.sweeting.me", crawl=crawl, status=Snapshot.StatusChoices.QUEUED, retry_at=future)

        runner = CrawlRunner(crawl, selected_plugins=[])
        runner.finalize_run_state()

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at == future

    def test_due_started_crawl_yields_to_due_child_snapshot(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
        )
        snapshot = Snapshot.objects.create(
            url="https://blog.sweeting.me",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=now,
        )

        assert run_due_crawl(crawl, lock_seconds=10) is True

        crawl.refresh_from_db()
        snapshot.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.STARTED
        assert crawl.retry_at is not None
        assert crawl.retry_at > timezone.now()
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at == now

    def test_crawl_cancel_schedules_children_for_per_snapshot_sealing(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl, run_due_snapshot

        now = timezone.now()
        past = now - timedelta(minutes=5)
        future = now + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
        )
        queued = Snapshot.objects.create(
            url="https://blog.sweeting.me/queued",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=future,
        )
        started = Snapshot.objects.create(
            url="https://blog.sweeting.me/started",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )
        paused = Snapshot.objects.create(
            url="https://blog.sweeting.me/paused",
            crawl=crawl,
            status=Snapshot.StatusChoices.PAUSED,
            retry_at=future,
        )
        already_due = Snapshot.objects.create(
            url="https://blog.sweeting.me/already-due",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=past,
        )
        maintenance = Snapshot.objects.create(
            url="https://blog.sweeting.me/maintenance",
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=future,
        )
        ArchiveResult.objects.create(
            snapshot=maintenance,
            plugin="search_backend_sqlite",
            hook_name="on_Snapshot__90_index_sqlite",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        crawl.cancel()

        crawl.refresh_from_db()
        queued.refresh_from_db()
        started.refresh_from_db()
        paused.refresh_from_db()
        maintenance.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is not None
        assert crawl.retry_at <= timezone.now()
        for snapshot in (queued, started, paused, already_due):
            assert snapshot.status != Snapshot.StatusChoices.SEALED
            assert snapshot.retry_at is not None
            assert snapshot.retry_at <= timezone.now()
            assert run_due_snapshot(snapshot, lock_seconds=60) is True
            snapshot.refresh_from_db()
            assert snapshot.status == Snapshot.StatusChoices.SEALED
            assert snapshot.retry_at is None
        assert maintenance.status == Snapshot.StatusChoices.SEALED
        assert maintenance.retry_at == future
        assert run_due_crawl(crawl, lock_seconds=60) is True
        crawl.refresh_from_db()
        assert crawl.retry_at is None

    def test_crawl_cancel_reschedules_children_when_parent_was_already_sealed(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        future = timezone.now() + timedelta(days=1)
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://blog.sweeting.me/old-cancel",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=future,
        )

        crawl.cancel()

        crawl.refresh_from_db()
        snapshot.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None
        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at <= timezone.now()

        snapshot.status = Snapshot.StatusChoices.SEALED
        snapshot.retry_at = None
        snapshot.save(update_fields=["status", "retry_at", "modified_at"])
        crawl.refresh_from_db()
        sealed_modified_at = crawl.modified_at

        crawl.cancel()

        crawl.refresh_from_db()
        assert crawl.modified_at == sealed_modified_at

    def test_run_due_crawl_stale_started_object_cannot_resurrect_cancelled_crawl(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import run_due_crawl

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=now,
        )
        Snapshot.objects.create(
            url="https://blog.sweeting.me/queued",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=now,
        )
        stale_crawl = Crawl.objects.get(pk=crawl.pk)

        crawl.cancel()
        assert run_due_crawl(stale_crawl, lock_seconds=60) is True

        crawl.refresh_from_db()
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_snapshot_seal_uses_retry_at_ownership_not_modified_at(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl

        now = timezone.now()
        crawl = Crawl.objects.create(
            urls="https://blog.sweeting.me",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        snapshot = Snapshot.objects.create(
            url="https://blog.sweeting.me/owned-seal",
            crawl=crawl,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=now,
        )

        assert Snapshot.claim_for_worker(snapshot, lock_seconds=60) is True
        Snapshot.objects.filter(pk=snapshot.pk).update(
            downloaded_at=now,
            modified_at=now + timedelta(seconds=1),
        )

        snapshot.seal()
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert snapshot.downloaded_at == now

    def test_recovery_reschedules_stale_due_crawl_even_with_unrelated_process_path_containing_crawl_id(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, NetworkInterface, Process

        old = timezone.now() - timedelta(hours=13)
        crawl = Crawl.objects.create(
            urls="https://github.com/nodeca/pica",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.QUEUED,
            retry_at=old,
        )
        Crawl.objects.filter(id=crawl.id).update(modified_at=old, retry_at=old)
        Process.objects.create(
            machine=Machine.current(refresh=True),
            iface=NetworkInterface.current(refresh=True),
            process_type=Process.TypeChoices.HOOK,
            worker_type="archiveresult",
            pwd=f"/tmp/not-an-archivebox-child/{crawl.id}/title",
            cmd=["python", "--version"],
            status=Process.StatusChoices.EXITED,
            retry_at=None,
            exit_code=0,
            ended_at=timezone.now(),
        )

        recovered = recover_orchestrator_state()

        crawl.refresh_from_db()
        assert "stale_active_crawls_unlocked" not in recovered
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == old

    def test_recovery_does_not_crash_on_invalid_utf8_process_logs(self, tmp_path):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.machine.models import Machine, NetworkInterface, Process

        runtime_dir = tmp_path / "https_example_com" / ".hooks" / "on_Snapshot__01_title.py"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "stdout.log").write_bytes(b"\\xff\\xfe\\xfa")
        process = Process.objects.create(
            machine=Machine.current(refresh=True),
            iface=NetworkInterface.current(refresh=True),
            process_type=Process.TypeChoices.HOOK,
            worker_type="archiveresult",
            pwd=str(tmp_path / "https_example_com"),
            cmd=["on_Snapshot__01_title.py"],
            status=Process.StatusChoices.RUNNING,
            retry_at=None,
            pid=999999,
            started_at=timezone.now() - timedelta(hours=1),
            timeout=1,
        )

        recover_orchestrator_state()

        process.refresh_from_db()
        assert process.status == Process.StatusChoices.EXITED
