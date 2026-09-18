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
    install_real_chrome,
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(660)
def test_cli_run_signal_cleans_real_chrome_hook_process_group(initialized_archive, recursive_test_site):
    from archivebox.core.models import Snapshot
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(live=True, PLUGINS="chrome", CHROME_ISOLATION="crawl", CHROME_HEADLESS="true", CHROME_SANDBOX="false")
    install_real_chrome(initialized_archive, env, isolation="crawl")

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


class TestRunInput:
    """Run new records, run their persisted IDs again, and accept plain URLs."""

    @pytest.mark.parametrize("source", ["crawl", "snapshot"])
    @pytest.mark.parametrize("runs", [1, 2], ids=["new-record", "existing-record"])
    def test_run_created_record(self, initialized_archive, source, runs):
        created = run_archivebox_cmd(
            [source, "create", create_test_url()],
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert created.returncode == 0, created.stderr
        created_record = next(record for record in parse_jsonl_output(created.stdout) if record.get("type") == source.title())
        stdin = created.stdout
        for _ in range(runs):
            result = run_archivebox_cmd(
                ["run"],
                stdin=stdin,
                timeout=120,
                env=RUN_TEST_ENV,
                cwd=initialized_archive,
                default_cli_env=True,
                disable_extractors=True,
            )
            assert result.returncode == 0, result.stderr
            records = parse_jsonl_output(result.stdout)
            assert len(records) >= 1
            matching = [record for record in records if record.get("type") == source.title()]
            assert len(matching) >= 1
            assert matching[0].get("id")
            assert matching[0]["id"] == created_record["id"]
            stdin = result.stdout

    def test_run_with_plain_url(self, initialized_archive):
        """Run accepts plain URL records (no type field)."""
        url = create_test_url()
        result = run_archivebox_cmd(
            ["run"],
            stdin=url + "\n",
            timeout=120,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0
        records = parse_jsonl_output(result.stdout)
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
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
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
            timeout=120,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
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
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        _cmd_result = run_archivebox_cmd(
            ["archiveresult", "create", "--plugin=favicon"],
            stdin=stdout1,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert any(record.get("type") == "ArchiveResult" for record in parse_jsonl_output(stdout2))

        initial_run = run_archivebox_cmd(
            ["run"],
            stdin=stdout2,
            timeout=120,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert initial_run.returncode == 0, initial_run.stderr
        persisted_result = run_archivebox_cmd(
            ["archiveresult", "list", "--plugin=favicon"],
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert persisted_result.returncode == 0, persisted_result.stderr
        assert any(record.get("type") == "ArchiveResult" for record in parse_jsonl_output(persisted_result.stdout))

        # Update to failed
        update_result = run_archivebox_cmd(
            ["archiveresult", "update", "--status=failed"],
            stdin=persisted_result.stdout,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert update_result.returncode == 0, update_result.stderr
        failed_result = run_archivebox_cmd(
            ["archiveresult", "list", "--plugin=favicon"],
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
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
            timeout=120,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
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

        result = run_archivebox_cmd(
            ["run", "--maintenance-only"],
            timeout=90,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Repairing" in result.stderr
        assert "Resuming 1 Crawl(s) with pending URLs ready to archive" in result.stderr
        assert "interrupted before" in result.stderr
        assert "remaining URLs" in result.stderr

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

        result = run_archivebox_cmd(
            ["run"],
            stdin=tag_result.stdout,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0
        records = parse_jsonl_output(result.stdout)
        tag_records = [record for record in records if record.get("type") == "Tag"]
        assert len(tag_records) == 1
        assert tag_records[0]["id"] == tag_record["id"]

    def test_run_outputs_all_processed_records(self, initialized_archive):
        """Run outputs all processed records for chaining."""
        url = create_test_url()
        create_result = run_archivebox_cmd(
            ["crawl", "create", url],
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert create_result.returncode == 0, create_result.stderr

        result = run_archivebox_cmd(
            ["run"],
            stdin=create_result.stdout,
            timeout=120,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0
        records = parse_jsonl_output(result.stdout)
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

        result = run_archivebox_cmd(
            ["run"],
            stdin=tag_result.stdout + snapshot_result.stdout,
            timeout=120,
            env=RUN_TEST_ENV,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0
        records = parse_jsonl_output(result.stdout)

        types = {record.get("type") for record in records}
        assert {"Crawl", "Snapshot", "Tag"}.issubset(types)


class TestRunEmpty:
    """Tests for `archivebox run` edge cases."""

    def test_run_empty_stdin(self, initialized_archive):
        """Run with empty stdin returns success."""
        result = run_archivebox_cmd(["run"], stdin="", cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

        assert result.returncode == 0

    def test_run_no_runnable_records_to_process(self, initialized_archive):
        """Run with only a real non-runnable Tag reports no work."""
        tag_result = run_archivebox_cmd(
            ["tag", "create", "non-runnable-tag"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert tag_result.returncode == 0, tag_result.stderr

        result = run_archivebox_cmd(
            ["run"],
            stdin=tag_result.stdout,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )

        assert result.returncode == 0
        assert "No records to process" in result.stderr


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
