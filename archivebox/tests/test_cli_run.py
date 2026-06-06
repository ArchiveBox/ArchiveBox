"""
Tests for archivebox run CLI command.

Tests cover:
- run with stdin JSONL (Crawl, Snapshot, ArchiveResult)
- create-or-update behavior (records with/without id)
- pass-through output (for chaining)
"""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from archivebox.tests.conftest import (
    cleanup_process_group,
    cli_env,
    run_archivebox_cmd,
    parse_jsonl_output,
    create_test_url,
    create_test_crawl_json,
    create_test_snapshot_json,
    pid_is_alive,
    wait_for_pid_to_disappear,
)

RUN_TEST_ENV = {
    "PLUGINS": "favicon",
    "SAVE_FAVICON": "True",
}


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(90)
def test_cli_run_signal_cleans_background_hook_process_group(initialized_archive):

    plugins_root = initialized_archive / "runtime_plugins"
    plugin_dir = plugins_root / "cancel_group"
    plugin_dir.mkdir(parents=True)
    daemon_hook = plugin_dir / "on_CrawlSetup__10_daemon.daemon.bg.sh"
    foreground_hook = plugin_dir / "on_CrawlSetup__20_foreground.sh"
    daemon_hook.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'test_dir="${LEAK_TEST_DIR:?}"',
                "sleep 600 &",
                'echo $$ > "$test_dir/daemon.pid"',
                'echo $! > "$test_dir/daemon-child.pid"',
                'echo ready > "$test_dir/daemon.ready"',
                "trap 'echo cleaned > \"$test_dir/daemon.cleaned\"; exit 0' TERM INT",
                "wait",
                "",
            ],
        ),
    )
    foreground_hook.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                'test_dir="${LEAK_TEST_DIR:?}"',
                'echo $$ > "$test_dir/foreground.pid"',
                'echo ready > "$test_dir/foreground.ready"',
                "trap 'echo cleaned > \"$test_dir/foreground.cleaned\"; exit 0' TERM INT",
                "while true; do sleep 1; done",
                "",
            ],
        ),
    )
    daemon_hook.chmod(0o755)
    foreground_hook.chmod(0o755)

    leak_test_dir = initialized_archive / "leak-check"
    leak_test_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "ABX_PLUGINS_DIR": str(plugins_root),
            "LEAK_TEST_DIR": str(leak_test_dir),
            "PLUGINS": "cancel_group",
            "TIMEOUT": "30",
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
        },
    )

    _cmd_result = run_archivebox_cmd(
        ["crawl", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout
    crawl_records = [json.loads(line) for line in stdout.splitlines() if line.strip().startswith("{")]
    crawl_id = next(record["id"] for record in crawl_records if record.get("type") == "Crawl")

    daemon_pid: int | None = None
    daemon_child_pid: int | None = None
    foreground_pid: int | None = None
    run_process = run_archivebox_cmd(
        ["run", f"--crawl-id={crawl_id}"],
        cwd=initialized_archive,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        wait=False,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            if (leak_test_dir / "daemon.ready").exists() and (leak_test_dir / "foreground.ready").exists():
                break
            if run_process.poll() is not None:
                output = run_process.communicate(timeout=1)[0]
                raise AssertionError(f"archivebox run exited before hooks were ready:\n{output}")
            time.sleep(0.05)
        assert (leak_test_dir / "daemon.ready").exists()
        assert (leak_test_dir / "foreground.ready").exists()

        daemon_pid = int((leak_test_dir / "daemon.pid").read_text().strip())
        daemon_child_pid = int((leak_test_dir / "daemon-child.pid").read_text().strip())
        foreground_pid = int((leak_test_dir / "foreground.pid").read_text().strip())
        assert pid_is_alive(daemon_pid)
        assert pid_is_alive(daemon_child_pid)
        assert pid_is_alive(foreground_pid)

        run_process.send_signal(signal.SIGTERM)
        output = run_process.communicate(timeout=20)[0]
        assert "Runner error" not in output

        wait_for_pid_to_disappear(daemon_pid, timeout=5)
        wait_for_pid_to_disappear(daemon_child_pid, timeout=5)
        wait_for_pid_to_disappear(foreground_pid, timeout=5)
        assert (leak_test_dir / "daemon.cleaned").read_text().strip() == "cleaned"
        assert (leak_test_dir / "foreground.cleaned").read_text().strip() == "cleaned"
    finally:
        if run_process.poll() is None:
            try:
                os.killpg(run_process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            run_process.communicate(timeout=5)
        cleanup_process_group(daemon_pid, daemon_child_pid)
        cleanup_process_group(foreground_pid)


class TestRunWithCrawl:
    """Tests for `archivebox run` with Crawl input."""

    def test_run_with_new_crawl(self, initialized_archive):
        """Run creates and processes a new Crawl (no id)."""
        crawl_record = create_test_crawl_json()

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(crawl_record),
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
        crawl = parse_jsonl_output(stdout1)[0]

        # Run with the existing crawl
        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(crawl),
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
        """Run creates and processes a new Snapshot (no id, just url)."""
        snapshot_record = create_test_snapshot_json()

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(snapshot_record),
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
        snapshot = parse_jsonl_output(stdout1)[0]

        # Run with the existing snapshot
        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(snapshot),
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
        url_record = {"url": url}

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(url_record),
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

    def test_run_requeues_failed_archiveresult(self, initialized_archive):
        """Run re-queues a failed ArchiveResult."""
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
        snapshot = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["archiveresult", "create", "--plugin=favicon"],
            stdin=json.dumps(snapshot),
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        ar = next(r for r in parse_jsonl_output(stdout2) if r.get("type") == "ArchiveResult")

        # Update to failed
        ar["status"] = "failed"
        run_archivebox_cmd(
            ["archiveresult", "update", "--status=failed"],
            stdin=json.dumps(ar),
            cwd=initialized_archive,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )

        # Now run should re-queue it
        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(ar),
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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

    def test_run_passes_through_unknown_types(self, initialized_archive):
        """Run passes through records with unknown types."""
        unknown_record = {"type": "Unknown", "id": "fake-id", "data": "test"}

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(unknown_record),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        unknown_records = [r for r in records if r.get("type") == "Unknown"]
        assert len(unknown_records) == 1
        assert unknown_records[0]["data"] == "test"

    def test_run_outputs_all_processed_records(self, initialized_archive):
        """Run outputs all processed records for chaining."""
        url = create_test_url()
        crawl_record = create_test_crawl_json(urls=[url])

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(crawl_record),
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

    def test_run_handles_mixed_types(self, initialized_archive):
        """Run handles mixed Crawl/Snapshot/ArchiveResult input."""
        crawl = create_test_crawl_json()
        snapshot = create_test_snapshot_json()
        unknown = {"type": "Tag", "id": "fake", "name": "test"}

        stdin = "\n".join(
            [
                json.dumps(crawl),
                json.dumps(snapshot),
                json.dumps(unknown),
            ],
        )

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=stdin,
            cwd=initialized_archive,
            timeout=120,
            env=RUN_TEST_ENV,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)

        types = {r.get("type") for r in records}
        # Should have processed Crawl and Snapshot, passed through Tag
        assert "Crawl" in types or "Snapshot" in types or "Tag" in types


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

    def test_run_no_records_to_process(self, initialized_archive):
        """Run with only pass-through records shows message."""
        unknown = {"type": "Unknown", "id": "fake"}

        _cmd_result = run_archivebox_cmd(
            ["run"],
            stdin=json.dumps(unknown),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "No records to process" in stderr


class TestRunDaemonMode:
    @pytest.mark.parametrize("stdin_kind", ["malformed", "valid-snapshot"])
    def test_run_daemon_ignores_piped_stdin_and_starts_real_runner(self, initialized_archive, db, stdin_kind):
        from archivebox.machine.models import Process
        from archivebox.core.models import Snapshot
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        snapshot_url = None
        if stdin_kind == "valid-snapshot":
            snapshot_url = create_test_url()
            piped_stdin = json.dumps(create_test_snapshot_json(url=snapshot_url)) + "\n"
        else:
            piped_stdin = "{this is not jsonl}\n"

        env = cli_env()
        proc = run_archivebox_cmd(
            ["run", "--daemon"],
            cwd=initialized_archive,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            wait=False,
        )
        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None

        try:
            proc.stdin.write(piped_stdin)
            proc.stdin.close()

            deadline = time.monotonic() + 20
            started = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    stdout = proc.stdout.read()
                    stderr = proc.stderr.read()
                    pytest.fail(f"daemon exited before starting runner: code={proc.returncode}\nstdout={stdout}\nstderr={stderr}")
                with use_archivebox_db(initialized_archive):
                    started = Process.objects.filter(
                        process_type=Process.TypeChoices.ORCHESTRATOR,
                        status=Process.StatusChoices.RUNNING,
                        pid=proc.pid,
                    ).exists()
                if started:
                    break
                time.sleep(0.25)

            assert started is True
            if snapshot_url is not None:
                with use_archivebox_db(initialized_archive):
                    assert not Snapshot.objects.filter(url=snapshot_url).exists()
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)

        stdout = proc.stdout.read()
        stderr = proc.stderr.read()
        assert proc.returncode == 143, stdout + stderr
        assert "No records to process" not in stderr

    def test_run_daemon_takeover_has_single_active_runner_gate(self, initialized_archive, db):
        from archivebox.machine.models import Process
        from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE
        from archivebox.tests.test_orm_helpers import use_archivebox_db

        env = cli_env()
        procs = [
            run_archivebox_cmd(
                ["run", "--daemon"],
                cwd=initialized_archive,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                wait=False,
            )
            for _ in range(2)
        ]
        try:
            deadline = time.monotonic() + 30
            active_pid = None
            while time.monotonic() < deadline:
                with use_archivebox_db(initialized_archive):
                    active = [
                        proc
                        for proc in Process.objects.filter(
                            process_type=Process.TypeChoices.ORCHESTRATOR,
                            worker_type=RUNNER_ACTIVE_WORKER_TYPE,
                            status=Process.StatusChoices.RUNNING,
                            pwd=str(initialized_archive),
                        )
                        if proc.is_running
                    ]
                    assert len(active) <= 1
                    if len(active) == 1:
                        active_pid = active[0].pid
                        break
                time.sleep(0.25)

            assert active_pid is not None
            time.sleep(1)
            with use_archivebox_db(initialized_archive):
                active = [
                    proc
                    for proc in Process.objects.filter(
                        process_type=Process.TypeChoices.ORCHESTRATOR,
                        worker_type=RUNNER_ACTIVE_WORKER_TYPE,
                        status=Process.StatusChoices.RUNNING,
                        pwd=str(initialized_archive),
                    )
                    if proc.is_running
                ]
                assert len(active) == 1

            os.killpg(active_pid, signal.SIGKILL)
            replacement = run_archivebox_cmd(
                ["run", "--daemon"],
                cwd=initialized_archive,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                wait=False,
            )
            procs.append(replacement)
            deadline = time.monotonic() + 30
            recovered_pid = None
            while time.monotonic() < deadline:
                with use_archivebox_db(initialized_archive):
                    active = [
                        proc
                        for proc in Process.objects.filter(
                            process_type=Process.TypeChoices.ORCHESTRATOR,
                            worker_type=RUNNER_ACTIVE_WORKER_TYPE,
                            status=Process.StatusChoices.RUNNING,
                            pwd=str(initialized_archive),
                        )
                        if proc.is_running
                    ]
                    assert len(active) <= 1
                    if len(active) == 1 and active[0].pid != active_pid:
                        recovered_pid = active[0].pid
                        break
                time.sleep(0.25)

            assert recovered_pid is not None
        finally:
            for proc in procs:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
            for proc in procs:
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)


@pytest.mark.django_db
class TestRecoverOrchestratorState:
    def test_recover_orchestrator_state_unlocks_started_crawl_with_pending_snapshot(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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

    def test_recover_orchestrator_state_requeues_backoff_archiveresults(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="search_backend_sqlite",
            hook_name="on_Snapshot__90_index_sqlite",
            status=ArchiveResult.StatusChoices.BACKOFF,
        )

        recovered = recover_orchestrator_state()

        result.refresh_from_db()
        snapshot.refresh_from_db()
        crawl.refresh_from_db()

        assert recovered["archiveresults_backoff"] == 1
        assert result.status == ArchiveResult.StatusChoices.QUEUED
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is not None
        assert crawl.status == Crawl.StatusChoices.SEALED

    def test_recover_orchestrator_state_leaves_due_queued_snapshot_for_runner_even_with_final_results(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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

    def test_recover_orchestrator_state_leaves_stale_queued_final_rows_for_runner(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.services.runner import run_due_crawl, run_due_snapshot

        old = timezone.now() - timedelta(hours=13)
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
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
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at == old

        assert run_due_crawl(crawl, lock_seconds=60) is True
        crawl.refresh_from_db()

        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None

    def test_run_due_snapshot_seals_queued_snapshot_with_final_results(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.services.runner import run_due_snapshot

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
        assert snapshot.downloaded_at is None

    def test_create_pending_archiveresults_uses_canonical_hook_names(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot

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

        snapshot.create_pending_archiveresults()

        hook_names = list(ArchiveResult.objects.filter(snapshot=snapshot).values_list("hook_name", flat=True))
        assert hook_names
        assert all(not hook_name.endswith((".py", ".js", ".sh")) for hook_name in hook_names)

    def test_run_due_snapshot_pauses_child_when_parent_is_paused(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
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
        assert result.status == ArchiveResult.StatusChoices.PAUSED
        assert snapshot.archiveresult_set.count() == 1

    def test_parent_status_transitions_schedule_children_to_follow_parent_status(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
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
        sealed_child.refresh_from_db()
        sealed_started_child.refresh_from_db()
        assert paused_child.status == Snapshot.StatusChoices.STARTED
        assert paused_child.retry_at is not None
        assert paused_child.retry_at <= timezone.now()
        assert sealed_child.status == Snapshot.StatusChoices.PAUSED
        assert sealed_child.retry_at is not None
        assert sealed_child.retry_at <= timezone.now()
        assert sealed_started_child.status == Snapshot.StatusChoices.STARTED
        assert sealed_started_child.retry_at is not None
        assert sealed_started_child.retry_at <= timezone.now()

        assert run_due_snapshot(paused_child, lock_seconds=60) is True
        paused_child.refresh_from_db()
        paused_result.refresh_from_db()
        assert paused_child.status == Snapshot.StatusChoices.PAUSED
        assert paused_child.retry_at == RETRY_AT_MAX
        assert paused_result.status == ArchiveResult.StatusChoices.PAUSED

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
        from archivebox.crawls.models import Crawl
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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

    def test_recover_orchestrator_state_preserves_future_started_snapshot_with_live_result_process(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.machine.models import Machine, NetworkInterface, Process
        from archivebox.core.recovery_util import recover_orchestrator_state

        worker = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
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
            if worker.poll() is None:
                os.killpg(worker.pid, signal.SIGTERM)
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(worker.pid, signal.SIGKILL)
                worker.wait(timeout=5)

    def test_recover_orchestrator_state_does_not_resume_paused_rows_with_max_retry_at(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
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
    def test_run_due_snapshot_runs_queued_plugin_after_fs_migration(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
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
        Snapshot.objects.filter(pk=snapshot.pk).update(fs_version="0.9.0")
        snapshot.refresh_from_db()
        snapshot.output_dir.mkdir(parents=True, exist_ok=True)
        title_dir = snapshot.output_dir / "title"
        title_dir.mkdir(parents=True, exist_ok=True)
        (title_dir / "title.txt").write_text("Example Domain\n", encoding="utf-8")
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="search_backend_sqlite",
            hook_name="on_Snapshot__90_index_sqlite",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        snapshot.refresh_from_db()
        result.refresh_from_db()
        assert snapshot.fs_version == Snapshot._fs_current_version()
        assert result.status in ArchiveResult.FINAL_STATES
        assert result.status != ArchiveResult.StatusChoices.QUEUED
        assert result.start_ts is not None
        assert result.end_ts is not None

    @pytest.mark.django_db(transaction=True)
    def test_run_due_snapshot_fails_obsolete_queued_hook_name(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
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
            plugin="singlefile",
            hook_name="on_Snapshot__50_singlefile.py",
            status=ArchiveResult.StatusChoices.QUEUED,
        )

        assert run_due_snapshot(snapshot, lock_seconds=60) is True

        result.refresh_from_db()
        snapshot.refresh_from_db()
        assert result.status == ArchiveResult.StatusChoices.FAILED
        assert snapshot.retry_at is None

    def test_recover_orchestrator_state_ignores_sealed_downloaded_snapshot_without_results(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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

    def test_recover_orchestrator_state_unlocks_started_snapshot_with_final_results_for_runner(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state
        from archivebox.services.runner import run_due_snapshot

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
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

    def test_snapshot_start_writes_short_future_lease(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

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

        snapshot.sm.tick()
        snapshot.refresh_from_db()

        assert snapshot.status == Snapshot.StatusChoices.STARTED
        assert snapshot.retry_at is not None
        assert snapshot.retry_at > timezone.now()

    def test_abandoned_started_snapshot_results_are_reset_locally_for_resume(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot

        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by_id=get_or_create_system_user_pk(),
            status=Crawl.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        snapshot = Snapshot.objects.create(
            url="https://example.com",
            crawl=crawl,
            status=Snapshot.StatusChoices.STARTED,
            retry_at=timezone.now(),
        )
        abandoned = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="title",
            hook_name="on_Snapshot__01_title",
            status=ArchiveResult.StatusChoices.STARTED,
            output_str="partial output should be cleared",
            output_files={"partial.txt": {"size": 12}},
            output_size=12,
            start_ts=timezone.now(),
        )
        queued = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="wget",
            hook_name="on_Snapshot__40_wget",
            status=ArchiveResult.StatusChoices.QUEUED,
        )
        finished = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="favicon",
            hook_name="on_Snapshot__01_favicon",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            output_str="keep me",
            output_files={"favicon.ico": {"size": 1}},
            output_size=1,
        )

        snapshot.reset_abandoned_results()

        abandoned.refresh_from_db()
        queued.refresh_from_db()
        finished.refresh_from_db()

        assert abandoned.status == ArchiveResult.StatusChoices.QUEUED
        assert abandoned.output_str == ""
        assert abandoned.output_files == {}
        assert abandoned.output_size == 0
        assert queued.status == ArchiveResult.StatusChoices.QUEUED
        assert finished.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert finished.output_str == "keep me"
        assert finished.output_files == {"favicon.ico": {"size": 1}}

    def test_due_started_snapshot_with_live_child_extends_lease_without_reset(self):
        import os
        from datetime import datetime

        import psutil
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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
    def test_recovery_does_not_seal_queued_snapshot_waiting_for_future_retry_even_with_final_results(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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

    def test_recovery_requeues_started_archiveresult_without_process(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        assert result.status == ArchiveResult.StatusChoices.QUEUED

    def test_recovery_requeues_started_archiveresult_with_exited_process(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.machine.models import Machine, NetworkInterface, Process
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        assert result.status == ArchiveResult.StatusChoices.QUEUED

    def test_recovery_requeues_sealed_snapshot_started_result_with_exited_process_result_too(self):
        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.machine.models import Machine, NetworkInterface, Process
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        assert snapshot.retry_at is not None
        assert result.status == ArchiveResult.StatusChoices.QUEUED

    def test_recovery_requeues_started_snapshot_result_before_unlocking_snapshot(self):
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.core.recovery_util import recover_orchestrator_state

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
        assert result.status == ArchiveResult.StatusChoices.QUEUED
        assert snapshot.retry_at is not None

    def test_crawl_runner_load_run_state_does_not_return_future_retry_snapshots(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import ArchiveResult, Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot
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
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot

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

        snapshot.sm.seal()
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        assert snapshot.retry_at is None
        assert snapshot.downloaded_at == now

    def test_recovery_reschedules_stale_due_crawl_even_with_unrelated_process_path_containing_crawl_id(self):
        from datetime import timedelta

        from django.utils import timezone

        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, NetworkInterface, Process
        from archivebox.core.recovery_util import recover_orchestrator_state

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

        from archivebox.machine.models import Machine, NetworkInterface, Process
        from archivebox.core.recovery_util import recover_orchestrator_state

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
