#!/usr/bin/env python3
"""Takeover utility tests and live command handoff flows."""

import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.tests.conftest import (
    assert_no_processes_for_data_dir,
    get_free_port,
    kill_processes_for_data_dir,
    cli_env,
    pid_is_alive,
    run_archivebox_cmd,
    start_archivebox_server,
    stop_archivebox_process,
    supervisor_pid_from_log,
    wait_for_http,
    wait_for_log,
    wait_for_log_count,
    wait_for_log_pattern,
    wait_for_pid_to_disappear,
    wait_for_snapshot_capture,
    wait_for_worker_pid_from_log,
    worker_pid_from_log,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def _require_sonic_binary() -> None:
    if shutil.which("sonic") is None:
        pytest.skip("sonic server binary is required for Sonic worker takeover tests")


def _archive_pages_for_sqlite_reindexing(data_dir: Path, env: dict[str, str], root_url: str) -> None:
    add_env = dict(env)
    add_env["SEARCH_BACKEND_ENGINE"] = "ripgrep"
    _cmd_result = run_archivebox_cmd(
        [
            "add",
            "--depth=2",
            "--max-urls=20",
            "--crawl-max-size=50mb",
            "--plugins=wget,parse_html_urls",
            root_url,
        ],
        cwd=data_dir,
        env=add_env,
        timeout=240,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout

    with use_archivebox_db(data_dir):
        assert Snapshot.objects.filter(status=Snapshot.StatusChoices.SEALED).count() >= 1
        assert not ArchiveResult.objects.filter(plugin="search_backend_sqlite").exists()


@pytest.mark.timeout(360)
def test_behavior_update_index_only_keeps_server_http_and_search_visible(tmp_path, initialized_archive, recursive_test_site):
    _require_sonic_binary()

    env = cli_env(
        live=True,
        SEARCH_BACKEND_ENGINE="sqlite",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
    )
    root_url = recursive_test_site["root_url"]
    _archive_pages_for_sqlite_reindexing(tmp_path, env, root_url)

    port = get_free_port()
    server = None
    try:
        server = start_archivebox_server(tmp_path, port=port, log_name="behavior-server-update.log", env=env)
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500

        update = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=1"],
            cwd=tmp_path,
            env=env,
            timeout=180,
        )

        assert update.returncode == 0, update.stderr or update.stdout
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500

        search = run_archivebox_cmd(
            ["list", "--search=contents", "--csv=url", "Root"],
            cwd=tmp_path,
            env=env,
            timeout=60,
        )

        assert search.returncode == 0, search.stderr or search.stdout
        assert root_url in search.stdout
    finally:
        if server is not None and server.poll() is None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(420)
def test_behavior_update_yields_to_server_then_finishes_visible_indexing(tmp_path, initialized_archive, recursive_test_site):
    _require_sonic_binary()

    env = cli_env(
        live=True,
        SEARCH_BACKEND_ENGINE="sqlite",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
    )
    root_url = recursive_test_site["root_url"]
    _archive_pages_for_sqlite_reindexing(tmp_path, env, root_url)

    port = get_free_port()
    update_proc = None
    server = None
    try:
        update_log = tmp_path / "behavior-update-yields.log"
        update_log_handle = update_log.open("w", encoding="utf-8")
        update_proc = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=1"],
            cwd=tmp_path,
            env=env,
            stdout=update_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            wait=False,
        )
        update_log_handle.close()
        wait_for_log(update_log, "[*] Reindexing", timeout=90)

        server = start_archivebox_server(tmp_path, port=port, log_name="behavior-server-takes-update.log", env=env)
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500
        wait_for_log(update_log, "A newer archivebox process took over the orchestrator, sonic", timeout=90)

        stop_archivebox_process(server, signal.SIGTERM)
        server = None
        update_proc.wait(timeout=180)
        update_text = update_log.read_text(encoding="utf-8", errors="replace")
        assert update_proc.returncode == 0, update_text

        search = run_archivebox_cmd(
            ["list", "--search=contents", "--csv=url", "Root"],
            cwd=tmp_path,
            env=env,
            timeout=60,
        )

        assert search.returncode == 0, search.stderr or search.stdout
        assert root_url in search.stdout
    finally:
        if update_proc is not None and update_proc.poll() is None:
            stop_archivebox_process(update_proc, signal.SIGTERM)
        if server is not None and server.poll() is None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(300)
def test_behavior_foreground_add_keeps_existing_server_http_visible(tmp_path, initialized_archive, recursive_test_site):

    port = get_free_port()
    env = cli_env(live=True, server=True, port=port, SEARCH_BACKEND_ENGINE="ripgrep")
    server = None
    try:
        server = start_archivebox_server(tmp_path, port=port, log_name="behavior-server-add.log", env=env)
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500

        add = run_archivebox_cmd(
            [
                "add",
                "--depth=0",
                "--plugins=wget",
                recursive_test_site["root_url"],
            ],
            cwd=tmp_path,
            env=env,
            timeout=180,
        )

        assert add.returncode == 0, add.stderr or add.stdout
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500
        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=120)
        assert "Root" in captured_text
    finally:
        if server is not None and server.poll() is None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(300)
def test_behavior_background_add_returns_and_server_archives_visible_url(tmp_path, initialized_archive, recursive_test_site):

    port = get_free_port()
    env = cli_env(live=True, server=True, port=port, SEARCH_BACKEND_ENGINE="ripgrep")
    server = None
    try:
        server = start_archivebox_server(tmp_path, port=port, log_name="behavior-server-bg-add.log", env=env)
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500

        add = run_archivebox_cmd(
            [
                "add",
                "--bg",
                "--depth=0",
                "--plugins=wget",
                recursive_test_site["root_url"],
            ],
            cwd=tmp_path,
            env=env,
            timeout=60,
        )

        assert add.returncode == 0, add.stderr or add.stdout
        assert "background runner will process" in add.stdout
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500
        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=180)
        assert "Root" in captured_text
    finally:
        if server is not None and server.poll() is None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(300)
def test_behavior_daemonized_server_restarts_cleanly_after_forced_stop(tmp_path, initialized_archive):

    port = get_free_port()
    env = cli_env(live=True, server=True, port=port)
    try:
        first = start_archivebox_server(tmp_path, port=port, env=env, daemonize=True)
        assert first.returncode == 0, first.stderr or first.stdout
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500

        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)

        second = start_archivebox_server(tmp_path, port=port, env=env, daemonize=True)
        assert second.returncode == 0, second.stderr or second.stdout
        assert wait_for_http(port, host=f"archivebox.localhost:{port}").status_code < 500
    finally:
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(240)
def test_live_second_server_takes_over_existing_server_process(tmp_path, initialized_archive):

    env = cli_env(live=True)
    port = get_free_port()
    first = None
    second = None
    try:
        first = start_archivebox_server(tmp_path, port=port, log_name="server-first.log", env=env)
        first_log = first.log_path
        second = start_archivebox_server(tmp_path, port=port, log_name="server-second.log", env=env)
        second_log = second.log_path

        assert first.poll() is None
        first_text = first_log.read_text(encoding="utf-8", errors="replace")
        second_text = second_log.read_text(encoding="utf-8", errors="replace")
        assert "A newer archivebox process took over the orchestrator, server" in first_text
        assert "Starting orchestrator, server" in second_text

        _cmd_result = run_archivebox_cmd(
            ["status"],
            cwd=tmp_path,
            env=env,
            timeout=60,
        )
        stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert returncode == 0, stderr or stdout

        first_resumes = first_log.read_text(encoding="utf-8", errors="replace").count("Other newer archivebox process")
        stop_archivebox_process(second, signal.SIGTERM)
        second = None
        wait_for_log_count(first_log, "Other newer archivebox process", first_resumes + 1, timeout=35)
        assert first.poll() is None
    finally:
        if second is not None and second.poll() is None:
            stop_archivebox_process(second, signal.SIGTERM)
        if first is not None and first.poll() is None:
            stop_archivebox_process(first, signal.SIGKILL)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(180)
def test_live_update_index_only_does_not_take_over_server_runtime(tmp_path, initialized_archive):

    env = cli_env(live=True)
    port = get_free_port()
    server = None
    try:
        server = start_archivebox_server(tmp_path, port=port, log_name="server-update-owner.log", env=env)
        server_log = server.log_path
        supervisor_pid_before = supervisor_pid_from_log(server_log)
        daphne_pid_before = worker_pid_from_log(server_log, "worker_daphne")

        _cmd_result = run_archivebox_cmd(
            ["update", "--index-only", "--before=0"],
            cwd=tmp_path,
            env=env,
            timeout=90,
        )
        update_stdout, update_stderr, update_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert update_returncode == 0, update_stderr or update_stdout
        assert server.poll() is None
        assert pid_is_alive(supervisor_pid_before)
        assert pid_is_alive(daphne_pid_before)
        assert supervisor_pid_from_log(server_log) == supervisor_pid_before
        assert worker_pid_from_log(server_log, "worker_daphne") == daphne_pid_before
        assert "A newer archivebox process took over the orchestrator, server" not in server_log.read_text(
            encoding="utf-8",
            errors="replace",
        )
    finally:
        if server is not None and server.poll() is None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(360)
def test_live_server_keeps_http_runtime_while_update_runs_real_sqlite_indexer(tmp_path, initialized_archive, recursive_test_site):
    _require_sonic_binary()

    env = cli_env(
        live=True,
        SEARCH_BACKEND_ENGINE="sqlite",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
    )
    _archive_pages_for_sqlite_reindexing(tmp_path, env, recursive_test_site["root_url"])

    port = get_free_port()
    server = None
    try:
        server = start_archivebox_server(tmp_path, port=port, log_name="server-real-sqlite-update.log", env=env)
        server_log = server.log_path
        supervisor_pid_before = supervisor_pid_from_log(server_log)
        daphne_pid_before = worker_pid_from_log(server_log, "worker_daphne")
        runner_pid_before = worker_pid_from_log(server_log, "worker_runner")
        sonic_pid_before = worker_pid_from_log(server_log, "worker_sonic")

        _cmd_result = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=1"],
            cwd=tmp_path,
            env=env,
            timeout=180,
        )
        update_stdout, update_stderr, update_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert update_returncode == 0, update_stderr or update_stdout
        assert server.poll() is None
        assert supervisor_pid_from_log(server_log) == supervisor_pid_before
        assert pid_is_alive(daphne_pid_before)
        assert pid_is_alive(sonic_pid_before)
        assert worker_pid_from_log(server_log, "worker_daphne") == daphne_pid_before
        assert worker_pid_from_log(server_log, "worker_sonic") == sonic_pid_before
        assert "A newer archivebox process took over the orchestrator, server" not in server_log.read_text(
            encoding="utf-8",
            errors="replace",
        )
        assert "Stopping older ArchiveBox runner process" in update_stdout

        deadline = time.time() + 180
        runner_pid_after = runner_pid_before
        while time.time() < deadline:
            with use_archivebox_db(tmp_path):
                rows = list(
                    Process.objects.filter(
                        process_type=Process.TypeChoices.ORCHESTRATOR,
                        worker_type="worker_runner",
                        status=Process.StatusChoices.RUNNING,
                    ).values("pid"),
                )
            for row in rows:
                pid = int(row["pid"])
                if pid != runner_pid_before and pid_is_alive(pid):
                    runner_pid_after = pid
                    break
            if runner_pid_after != runner_pid_before:
                break
            time.sleep(0.25)
        assert runner_pid_after != runner_pid_before

        deadline = time.time() + 180
        indexed_results: list[str] = []
        while time.time() < deadline:
            with use_archivebox_db(tmp_path):
                indexed_results = list(
                    ArchiveResult.objects.filter(plugin="search_backend_sqlite").values_list("status", flat=True),
                )
            if indexed_results and all(status in ArchiveResult.FINAL_STATES for status in indexed_results):
                break
            time.sleep(0.25)
        assert indexed_results
        assert all(status in ArchiveResult.FINAL_STATES for status in indexed_results)

        stop_archivebox_process(server, signal.SIGTERM)
        server = None
        wait_for_pid_to_disappear(daphne_pid_before, timeout=20)
        wait_for_pid_to_disappear(sonic_pid_before, timeout=20)
        wait_for_pid_to_disappear(runner_pid_after, timeout=20)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)
    finally:
        if server is not None and server.poll() is None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(420)
def test_live_update_yields_to_server_then_reclaims_real_sqlite_indexing(tmp_path, initialized_archive, recursive_test_site):
    _require_sonic_binary()

    env = cli_env(
        live=True,
        SEARCH_BACKEND_ENGINE="sqlite",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
    )
    _archive_pages_for_sqlite_reindexing(tmp_path, env, recursive_test_site["root_url"])

    port = get_free_port()
    update_proc = None
    server = None
    try:
        update_log = tmp_path / "update-real-sqlite-owner.log"
        update_log_handle = update_log.open("w", encoding="utf-8")
        update_proc = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=1"],
            cwd=tmp_path,
            env=env,
            stdout=update_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            wait=False,
        )
        update_log_handle.close()
        wait_for_log(update_log, "[*] Reindexing", timeout=90)
        update_supervisor_match = wait_for_log_pattern(update_log, r"Supervisord connected \(pid=(\d+)\)", timeout=90)
        update_supervisor_pid_before = int(update_supervisor_match.group(1))
        update_sonic_pid_before = wait_for_worker_pid_from_log(update_log, "worker_sonic", timeout=90)
        update_runner_pid_before = wait_for_worker_pid_from_log(update_log, f"worker_runner_update_{update_proc.pid}", timeout=90)
        assert pid_is_alive(update_supervisor_pid_before)
        assert pid_is_alive(update_sonic_pid_before)
        assert pid_is_alive(update_runner_pid_before)
        assert "worker_daphne" not in update_log.read_text(encoding="utf-8", errors="replace")

        server = start_archivebox_server(tmp_path, port=port, log_name="server-takes-real-sqlite-update.log", env=env)
        server_log = server.log_path
        wait_for_log(update_log, "A newer archivebox process took over the orchestrator, sonic", timeout=90)
        assert update_proc.poll() is None
        assert server.poll() is None
        server_text = server_log.read_text(encoding="utf-8", errors="replace")
        assert "Taking over orchestrator, sonic from older existing archivebox process" in server_text
        assert "Starting orchestrator, server, sonic" in server_text
        server_daphne_pid = worker_pid_from_log(server_log, "worker_daphne")
        server_runner_pid = worker_pid_from_log(server_log, "worker_runner")
        server_sonic_pid = worker_pid_from_log(server_log, "worker_sonic")
        assert pid_is_alive(server_daphne_pid)
        assert pid_is_alive(server_runner_pid)
        assert pid_is_alive(server_sonic_pid)
        wait_for_pid_to_disappear(update_supervisor_pid_before, timeout=30)
        wait_for_pid_to_disappear(update_sonic_pid_before, timeout=30)
        wait_for_pid_to_disappear(update_runner_pid_before, timeout=30)

        stop_archivebox_process(server, signal.SIGTERM)
        server = None
        update_proc.wait(timeout=180)
        update_text = update_log.read_text(encoding="utf-8", errors="replace")
        assert update_proc.returncode == 0, update_text
        wait_for_pid_to_disappear(server_daphne_pid, timeout=20)
        wait_for_pid_to_disappear(server_runner_pid, timeout=20)
        wait_for_pid_to_disappear(server_sonic_pid, timeout=20)

        deadline = time.time() + 30
        indexed_results: list[str] = []
        while time.time() < deadline:
            with use_archivebox_db(tmp_path):
                indexed_results = list(
                    ArchiveResult.objects.filter(plugin="search_backend_sqlite").values_list("status", flat=True),
                )
            if indexed_results and all(status in ArchiveResult.FINAL_STATES for status in indexed_results):
                break
            time.sleep(0.25)
        assert indexed_results
        assert all(status in ArchiveResult.FINAL_STATES for status in indexed_results)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)
    finally:
        if update_proc is not None and update_proc.poll() is None:
            stop_archivebox_process(update_proc, signal.SIGTERM)
        if server is not None and server.poll() is None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(420)
def test_live_repeated_server_startups_take_over_cleanly(tmp_path, initialized_archive):

    env = cli_env(live=True)
    port = get_free_port()
    servers: list[subprocess.Popen[str]] = []
    server_pids: list[int] = []
    daphne_pids: list[int] = []
    runner_pids: list[int] = []
    try:
        for index in range(5):
            server = start_archivebox_server(tmp_path, port=port, log_name=f"server-chaos-{index}.log", env=env)
            log_path = server.log_path
            servers.append(server)
            server_pids.append(server.pid)
            daphne_pids.append(worker_pid_from_log(log_path, "worker_daphne"))
            runner_pids.append(worker_pid_from_log(log_path, "worker_runner"))

            if index > 0:
                previous_server = servers[index - 1]
                previous_log = (tmp_path / f"server-chaos-{index - 1}.log").read_text(encoding="utf-8", errors="replace")
                current_log = log_path.read_text(encoding="utf-8", errors="replace")
                assert previous_server.poll() is None
                assert pid_is_alive(server_pids[index - 1])
                assert "A newer archivebox process took over the orchestrator, server" in previous_log
                assert "Starting orchestrator, server" in current_log
                wait_for_pid_to_disappear(daphne_pids[index - 1], timeout=15)
                wait_for_pid_to_disappear(runner_pids[index - 1], timeout=15)

            _cmd_result = run_archivebox_cmd(
                ["status"],
                cwd=tmp_path,
                env=env,
                timeout=60,
            )
            stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
            assert returncode == 0, stderr or stdout
            time.sleep(5)

        assert servers[-1].poll() is None
        assert all(server.poll() is None for server in servers)
        listener = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert listener.returncode == 0, listener.stderr or listener.stdout
        assert listener.stdout.count(f":{port} (LISTEN)") == 1

        previous_log_path = tmp_path / "server-chaos-3.log"
        previous_takeovers = previous_log_path.read_text(encoding="utf-8", errors="replace").count(
            "Other newer archivebox process",
        )
        stop_archivebox_process(servers[-1], signal.SIGTERM)
        wait_for_log_count(previous_log_path, "Other newer archivebox process", previous_takeovers + 1, timeout=35)
        assert servers[3].poll() is None
    finally:
        for server in reversed(servers):
            if server.poll() is None:
                stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(420)
def test_live_add_update_jobs_survive_server_and_cli_owner_exits(tmp_path, initialized_archive, recursive_test_site):
    plugins_root = tmp_path / "runtime_plugins"
    marker_dir = tmp_path / "slow-plugin-markers"
    plugin_dir = plugins_root / "slow_exit"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    counter_hook = plugin_dir / "on_Snapshot__08_counter.sh"
    counter_hook.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"marker_dir={str(marker_dir)!r}",
                'mkdir -p "$marker_dir/counter-seen"',
                'snapshot_key="${SNAPSHOT_ID:-$(basename "${SNAP_DIR:-unknown}")}"',
                'seen_file="$marker_dir/counter-seen/$snapshot_key"',
                'if [[ -e "$seen_file" ]]; then',
                '  echo "$snapshot_key" >> "$marker_dir/counter-duplicates.txt"',
                "  exit 42",
                "fi",
                'touch "$seen_file"',
                'echo "$snapshot_key" >> "$marker_dir/counter-runs.txt"',
                "",
            ],
        ),
        encoding="utf-8",
    )
    counter_hook.chmod(0o755)
    hook = plugin_dir / "on_Snapshot__09_slow_exit.sh"
    hook.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f"marker_dir={str(marker_dir)!r}",
                'mkdir -p "$marker_dir"',
                'echo $$ >> "$marker_dir/hook-pids.txt"',
                'touch "$marker_dir/hook-started"',
                "trap 'touch \"$marker_dir/hook-stopped\"; exit 143' TERM INT HUP",
                'while [[ ! -f "$marker_dir/allow-finish" ]]; do sleep 0.1; done',
                'touch "$marker_dir/hook-finished"',
                "",
            ],
        ),
        encoding="utf-8",
    )
    hook.chmod(0o755)

    env = cli_env(live=True, plugins_root=plugins_root)
    port = get_free_port()
    server = None
    server2 = None
    server3 = None
    add_proc = None
    add_proc2 = None
    try:
        server = start_archivebox_server(tmp_path, port=port, log_name="server-add-owner-1.log", env=env)
        server_log = server.log_path
        supervisor_pid_before = supervisor_pid_from_log(server_log)

        _cmd_result = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=10"],
            cwd=tmp_path,
            env=env,
            timeout=90,
        )
        update_stdout, update_stderr, update_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        assert update_returncode == 0, update_stderr or update_stdout
        assert server.poll() is None
        assert pid_is_alive(supervisor_pid_before)
        assert supervisor_pid_from_log(server_log) == supervisor_pid_before

        add_log = tmp_path / "archivebox-add-1.log"
        add_log_handle = add_log.open("w", encoding="utf-8")
        add_proc = run_archivebox_cmd(
            [
                "add",
                "--depth=1",
                "--max-urls=2",
                "--crawl-max-size=50mb",
                "--plugins=wget,parse_html_urls,slow_exit",
                recursive_test_site["root_url"],
                recursive_test_site["child_urls"][0],
            ],
            cwd=tmp_path,
            env=env,
            stdout=add_log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            wait=False,
        )
        add_log_handle.close()

        pid_file = marker_dir / "hook-pids.txt"
        deadline = time.time() + 45
        hook_pids: list[int] = []
        while time.time() < deadline:
            if pid_file.exists():
                hook_pids = [int(line.strip()) for line in pid_file.read_text().splitlines() if line.strip()]
                if len(hook_pids) >= 1:
                    break
            time.sleep(0.25)
        assert len(hook_pids) >= 1

        deadline = time.time() + 30
        snapshot_started = False
        while time.time() < deadline:
            with use_archivebox_db(tmp_path):
                snapshot_started = Snapshot.objects.filter(status=Snapshot.StatusChoices.STARTED).exists()
            if snapshot_started:
                break
            time.sleep(0.25)
        assert snapshot_started

        os.kill(server.pid, signal.SIGTERM)
        server.wait(timeout=20)
        assert add_proc.poll() is None, "foreground add should keep owning its crawl after the server exits"
        assert "Got SIGTERM" in server_log.read_text(encoding="utf-8", errors="replace")

        stop_archivebox_process(add_proc, signal.SIGKILL, timeout=30)
        add_output = add_log.read_text(encoding="utf-8", errors="replace")
        assert "Runner error" not in add_output
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)

        server2 = start_archivebox_server(tmp_path, port=port, log_name="server-add-owner-2.log", env=env)
        _server2_log = server2.log_path
        (marker_dir / "allow-finish").touch()

        deadline = time.time() + 90
        crawls = []
        snapshots = []
        bad_results = []
        while time.time() < deadline:
            with use_archivebox_db(tmp_path):
                crawls = list(Crawl.objects.order_by("created_at").values_list("status", "retry_at"))
                snapshots = list(Snapshot.objects.order_by("created_at").values_list("url", "status", "retry_at"))
                bad_results = list(
                    ArchiveResult.objects.filter(
                        status__in=[
                            ArchiveResult.StatusChoices.FAILED,
                            ArchiveResult.StatusChoices.SKIPPED,
                        ],
                    ).values_list("plugin", "status", "output_str"),
                )
            if (
                crawls
                and snapshots
                and all(status == Crawl.StatusChoices.SEALED for status, _retry_at in crawls)
                and all(status == Snapshot.StatusChoices.SEALED for _url, status, _retry_at in snapshots)
                and not bad_results
            ):
                break
            time.sleep(0.25)

        os.kill(server2.pid, signal.SIGTERM)
        server2.wait(timeout=20)
        with use_archivebox_db(tmp_path):
            crawls = list(Crawl.objects.order_by("created_at").values_list("status", "retry_at"))
            snapshots = list(Snapshot.objects.order_by("created_at").values_list("url", "status", "retry_at"))
            bad_results = list(
                ArchiveResult.objects.filter(
                    status__in=[
                        ArchiveResult.StatusChoices.FAILED,
                        ArchiveResult.StatusChoices.SKIPPED,
                    ],
                ).values_list("plugin", "status", "output_str"),
            )
        assert crawls
        assert snapshots
        assert all(status == Crawl.StatusChoices.SEALED for status, _retry_at in crawls)
        assert all(status == Snapshot.StatusChoices.SEALED for _url, status, _retry_at in snapshots)
        counter_runs = (marker_dir / "counter-runs.txt").read_text(encoding="utf-8").splitlines()
        assert counter_runs
        assert len(counter_runs) == len(set(counter_runs))
        assert not (marker_dir / "counter-duplicates.txt").exists()

        # The interrupted hook should be retried directly without rerunning the
        # previous hook in the same plugin. That keeps plugin-level shell hooks
        # idempotent across runner takeover instead of depending on each hook to
        # detect partial prior work itself.
        assert not bad_results
        assert (marker_dir / "hook-finished").exists()
    finally:
        for proc in (add_proc, add_proc2, server, server2, server3):
            if proc is not None and proc.poll() is None:
                stop_archivebox_process(proc, signal.SIGTERM, timeout=10)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


# Utility-level takeover selection tests.


def test_runtime_stack_owner_prefers_newer_server_over_older_update(tmp_path):
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type in (Process.TypeChoices.UPDATE, Process.TypeChoices.SERVER):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            procs.append(proc)
            Process.objects.create(
                machine=Machine.current(),
                process_type=process_type,
                worker_type=process_type,
                pwd=str(tmp_path),
                cmd=[],
                pid=proc.pid,
                status=Process.StatusChoices.RUNNING,
            )
            time.sleep(0.05)

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is not None
        assert owner.process_type == Process.TypeChoices.SERVER
        assert owner.pid == procs[-1].pid
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)


def test_runtime_stack_owner_keeps_server_over_newer_update(tmp_path):
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type in (Process.TypeChoices.SERVER, Process.TypeChoices.UPDATE):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            procs.append(proc)
            Process.objects.create(
                machine=Machine.current(),
                process_type=process_type,
                worker_type=process_type,
                pwd=str(tmp_path),
                cmd=[],
                pid=proc.pid,
                status=Process.StatusChoices.RUNNING,
            )
            time.sleep(0.05)

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is not None
        assert owner.process_type == Process.TypeChoices.SERVER
        assert owner.pid == procs[0].pid
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)


def test_foreground_runner_owner_prefers_newer_update_over_server(tmp_path):
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import foreground_runner_owner, runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type in (Process.TypeChoices.SERVER, Process.TypeChoices.UPDATE):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            procs.append(proc)
            Process.objects.create(
                machine=Machine.current(),
                process_type=process_type,
                worker_type=process_type,
                pwd=str(tmp_path),
                cmd=[],
                pid=proc.pid,
                status=Process.StatusChoices.RUNNING,
            )
            time.sleep(0.05)

        runtime_owner = runtime_stack_owner(data_dir=tmp_path)
        runner_owner = foreground_runner_owner(data_dir=tmp_path)

        assert runtime_owner is not None
        assert runtime_owner.process_type == Process.TypeChoices.SERVER
        assert runner_owner is not None
        assert runner_owner.process_type == Process.TypeChoices.UPDATE
        assert runner_owner.pid == procs[-1].pid
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)


def test_foreground_runner_owner_prefers_newer_server_over_update(tmp_path):
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import foreground_runner_owner, runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type in (Process.TypeChoices.UPDATE, Process.TypeChoices.SERVER):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            procs.append(proc)
            Process.objects.create(
                machine=Machine.current(),
                process_type=process_type,
                worker_type=process_type,
                pwd=str(tmp_path),
                cmd=[],
                pid=proc.pid,
                status=Process.StatusChoices.RUNNING,
            )
            time.sleep(0.05)

        runtime_owner = runtime_stack_owner(data_dir=tmp_path)
        runner_owner = foreground_runner_owner(data_dir=tmp_path)

        assert runtime_owner is not None
        assert runtime_owner.process_type == Process.TypeChoices.SERVER
        assert runner_owner is not None
        assert runner_owner.process_type == Process.TypeChoices.SERVER
        assert runner_owner.pid == procs[-1].pid
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)


def test_runtime_stack_owner_keeps_server_over_newer_supervised_runner(tmp_path):
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE, runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type, worker_type in (
            (Process.TypeChoices.SERVER, ""),
            (Process.TypeChoices.ORCHESTRATOR, RUNNER_ACTIVE_WORKER_TYPE),
        ):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            procs.append(proc)
            Process.objects.create(
                machine=Machine.current(),
                process_type=process_type,
                worker_type=worker_type,
                pwd=str(tmp_path),
                cmd=[],
                pid=proc.pid,
                status=Process.StatusChoices.RUNNING,
            )
            time.sleep(0.05)

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is not None
        assert owner.process_type == Process.TypeChoices.SERVER
        assert owner.pid == procs[0].pid
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)


def test_runtime_stack_owner_reaps_dead_server_without_promoting_update(tmp_path):
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    older_row = None
    newer_row = None
    try:
        for process_type in (Process.TypeChoices.UPDATE, Process.TypeChoices.SERVER):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            procs.append(proc)
            row = Process.objects.create(
                machine=Machine.current(),
                process_type=process_type,
                worker_type=process_type,
                pwd=str(tmp_path),
                cmd=[],
                pid=proc.pid,
                status=Process.StatusChoices.RUNNING,
            )
            if process_type == Process.TypeChoices.UPDATE:
                older_row = row
            else:
                newer_row = row
            time.sleep(0.05)

        assert older_row is not None
        assert newer_row is not None

        os.killpg(procs[-1].pid, signal.SIGTERM)
        procs[-1].wait(timeout=5)

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is None
        newer_row.refresh_from_db()
        assert newer_row.status == Process.StatusChoices.EXITED
        older_row.refresh_from_db()
        assert older_row.status == Process.StatusChoices.RUNNING
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)


def test_runtime_stack_owner_ignores_supervised_orphan_runner(tmp_path):
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE, runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for _ in range(2):
            proc = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            procs.append(proc)

        supervisor_row = Process.objects.create(
            machine=Machine.current(),
            process_type=Process.TypeChoices.SUPERVISORD,
            worker_type="supervisord",
            pwd=str(tmp_path),
            cmd=[],
            pid=procs[0].pid,
            status=Process.StatusChoices.RUNNING,
        )
        Process.objects.create(
            machine=Machine.current(),
            parent=supervisor_row,
            process_type=Process.TypeChoices.ORCHESTRATOR,
            worker_type=RUNNER_ACTIVE_WORKER_TYPE,
            pwd=str(tmp_path),
            cmd=[],
            pid=procs[1].pid,
            status=Process.StatusChoices.RUNNING,
        )

        assert runtime_stack_owner(data_dir=tmp_path) is None
    finally:
        for proc in procs:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)


def test_runtime_stack_owner_allows_top_level_runner_when_no_parent_command_exists(tmp_path):
    from archivebox.machine.models import Machine, Process
    from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE, runtime_stack_owner

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    try:
        runner_row = Process.objects.create(
            machine=Machine.current(),
            process_type=Process.TypeChoices.ORCHESTRATOR,
            worker_type=RUNNER_ACTIVE_WORKER_TYPE,
            pwd=str(tmp_path),
            cmd=[],
            pid=proc.pid,
            status=Process.StatusChoices.RUNNING,
        )

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is not None
        assert owner.id == runner_row.id
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
