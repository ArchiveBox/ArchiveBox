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
    cli_env,
    create_test_url,
    parse_jsonl_output,
    run_archivebox_cmd,
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
@pytest.mark.parametrize(
    "choice,target",
    [(choice, "crawl") for choice in ["skip", "retry", "abort", "ctrl-c", "noninteractive"]]
    + [("skip", "snapshot"), ("skip", "global"), ("early-skip", "crawl")]
    + [(choice, "daemon") for choice in ["daemon-tty", "daemon-noninteractive"]]
    + [("daemon-term", "daemon")],
)
def test_run_crawl_interrupts_active_hook(initialized_archive, choice, target):
    """Foreground run uses the same terminal interrupt choices as add."""
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Process
    from archivebox.tests.test_orm_helpers import use_archivebox_db

    env = cli_env(CHROME_DELAY_AFTER_LOAD="60", CHROME_TIMEOUT="120", CHROME_HEADLESS="True", PLUGINS="chrome")
    # This test starts its 45-second observation at the active navigate hook.
    # Install Chrome through the real CLI first so a cold binary download is
    # not mistaken for a hook that never started.
    _install_real_chrome_for_test(initialized_archive, env, isolation="crawl")
    created = run_archivebox_cmd(["snapshot", "create", create_test_url()], cwd=initialized_archive, env=env)
    assert created.returncode == 0, created.stdout + created.stderr
    snapshot = next(record for record in parse_jsonl_output(created.stdout) if record.get("type") == "Snapshot")
    crawl_id = snapshot["crawl_id"]
    run_args = {
        "crawl": [f"--crawl-id={crawl_id}"],
        "snapshot": [f"--snapshot-id={snapshot['id']}"],
        "global": [],
        "daemon": ["--daemon", f"--crawl-id={crawl_id}"],
    }[target]

    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, 160))
    output = bytearray()
    result = None
    owned_processes = []

    def read_until(predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            if predicate():
                return
        raise AssertionError(output.decode(errors="replace"))

    def active_hook():
        with use_archivebox_db(initialized_archive):
            return Process.objects.filter(
                process_type=Process.TypeChoices.HOOK,
                cmd__0__endswith="on_Snapshot__30_chrome_navigate.js",
                status="running",
            ).first()

    try:
        result = run_archivebox_cmd(
            ["run", *run_args],
            cwd=initialized_archive,
            env=env,
            stdin=subprocess.DEVNULL if choice in {"noninteractive", "daemon-noninteractive"} else slave,
            stdout=slave,
            stderr=slave,
            wait=False,
            start_new_session=True,
        )
        read_until(lambda: active_hook() is not None)
        first_hook = active_hook()
        assert first_hook is not None
        with use_archivebox_db(initialized_archive):
            hook_pids = Process.objects.filter(status="running", process_type="hook").values_list("pid", flat=True)
            for pid in hook_pids:
                try:
                    process = psutil.Process(pid)
                    owned_processes.extend([process, *process.children(recursive=True)])
                except psutil.NoSuchProcess:
                    continue
        result.send_signal(signal.SIGTERM if choice == "daemon-term" else signal.SIGINT)
        if choice not in {"noninteractive", "daemon-tty", "daemon-noninteractive", "daemon-term"}:
            read_until(lambda: b"Choice [skip]:" in output, timeout=30)
            if choice != "early-skip":
                read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            if choice == "retry":
                os.write(master, b"r")
                read_until(lambda: (next_hook := active_hook()) is not None and next_hook.pid != first_hook.pid)
                before_prompt = len(output)
                result.send_signal(signal.SIGINT)
                read_until(lambda: b"Choice [skip]:" in output[before_prompt:], timeout=30)
                read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            if choice == "ctrl-c":
                result.send_signal(signal.SIGINT)
            else:
                os.write(master, b"a" if choice == "abort" else b"\r")
        read_until(lambda: result.poll() is not None, timeout=45)
        expected_exit = 143 if choice == "daemon-term" else (0 if choice in {"skip", "early-skip", "retry"} else 130)
        assert result.returncode == expected_exit, output.decode(errors="replace")
        assert not psutil.pid_exists(first_hook.pid)
        _, live_processes = psutil.wait_procs(owned_processes, timeout=5)
        assert not [process.pid for process in live_processes if process.is_running() and process.status() != psutil.STATUS_ZOMBIE]
        assert b"Traceback" not in output, output.decode(errors="replace")
        with use_archivebox_db(initialized_archive):
            crawl_after = Crawl.objects.get(id=crawl_id)
            snapshot_after = Snapshot.objects.get(id=snapshot["id"])
            if choice == "daemon-term":
                # A supervisor stop displaces this runner; the user's crawl
                # and snapshot remain resumable for the next owner.
                assert crawl_after.status == Crawl.StatusChoices.STARTED
                assert snapshot_after.status == Snapshot.StatusChoices.STARTED
                assert crawl_after.retry_at is not None and snapshot_after.retry_at is not None
            else:
                assert crawl_after.status == Crawl.StatusChoices.SEALED
                assert snapshot_after.status == Snapshot.StatusChoices.SEALED
            assert not Process.objects.filter(status="running", pid__isnull=False).exists()
        if choice in {"noninteractive", "daemon-tty", "daemon-noninteractive", "daemon-term"}:
            assert b"Choice [skip]:" not in output
    finally:
        if result is not None and result.poll() is None:
            result.terminate()
            try:
                result.wait(timeout=20)
            except subprocess.TimeoutExpired:
                result.send_signal(signal.SIGKILL)
                result.wait(timeout=5)
        for process in owned_processes:
            try:
                if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                    process.terminate()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(owned_processes, timeout=3)
        os.close(slave)
        os.close(master)
