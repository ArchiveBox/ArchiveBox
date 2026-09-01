#!/usr/bin/env python3
"""Takeover utility tests and live command handoff flows."""

import os
import json
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import psutil

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
    get_http_response,
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


def test_pid_is_alive_treats_unreaped_archivebox_cli_as_exited(tmp_path, initialized_archive):
    proc = run_archivebox_cmd(
        ["version"],
        cwd=tmp_path,
        default_cli_env=True,
        disable_extractors=True,
        wait=False,
    )
    try:
        os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOWAIT)
        assert psutil.Process(proc.pid).status() == psutil.STATUS_ZOMBIE
        assert not pid_is_alive(proc.pid)
    finally:
        proc.wait(timeout=5)


def _resolve_sonic_env(env: dict[str, str]) -> dict[str, str]:
    from abx_plugins import get_plugins_dir

    config = Path(get_plugins_dir()) / "search_backend_sonic" / "config.json"
    result = subprocess.run(
        [
            str(Path(sys.executable).with_name("abxpkg")),
            "env",
            "--install",
            "--json",
            f"--lib={env['ABXPKG_LIB_DIR']}",
            f"--deps-from={config}:required_binaries",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = {str(key): str(value) for key, value in json.loads(result.stdout).items()}
    assert Path(payload["SONIC_BINARY"]).is_file()
    return payload


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
    env = cli_env(
        live=True,
        PLUGINS="wget,parse_html_urls,search_backend_sqlite",
        SEARCH_BACKEND_ENGINE="sqlite",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
    )
    env.update(_resolve_sonic_env(env))
    root_url = recursive_test_site["root_url"]
    _archive_pages_for_sqlite_reindexing(tmp_path, env, root_url)

    port = get_free_port()
    server = None
    try:
        server = start_archivebox_server(tmp_path, port=port, log_name="behavior-server-update.log", env=env)
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500

        update = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=1"],
            cwd=tmp_path,
            env=env,
            timeout=180,
        )

        assert update.returncode == 0, update.stderr or update.stdout
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500

        search = run_archivebox_cmd(
            ["list", "--search=contents", "--csv=url", "Root"],
            cwd=tmp_path,
            env=env,
            timeout=60,
        )

        assert search.returncode == 0, search.stderr or search.stdout
        assert root_url in search.stdout
    finally:
        if server is not None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(420)
def test_behavior_update_yields_to_server_then_finishes_visible_indexing(tmp_path, initialized_archive, recursive_test_site):
    env = cli_env(
        live=True,
        PLUGINS="wget,parse_html_urls,search_backend_sqlite",
        SEARCH_BACKEND_ENGINE="sqlite",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
    )
    env.update(_resolve_sonic_env(env))
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
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500
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
        if update_proc is not None:
            stop_archivebox_process(update_proc, signal.SIGTERM)
        if server is not None:
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
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500

        add = run_archivebox_cmd(
            [
                "add",
                "--depth=2",
                "--max-urls=10",
                "--plugins=wget,parse_html_urls",
                recursive_test_site["root_url"],
            ],
            cwd=tmp_path,
            env=env,
            timeout=180,
        )

        assert add.returncode == 0, add.stderr or add.stdout
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500
        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=120)
        assert "Root" in captured_text
    finally:
        if server is not None:
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
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500

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
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500
        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=180)
        assert "Root" in captured_text
    finally:
        if server is not None:
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
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500

        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)

        second = start_archivebox_server(tmp_path, port=port, env=env, daemonize=True)
        assert second.returncode == 0, second.stderr or second.stdout
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500
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

        assert pid_is_alive(first.pid)
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
        assert pid_is_alive(first.pid)
    finally:
        if second is not None:
            stop_archivebox_process(second, signal.SIGTERM)
        if first is not None:
            stop_archivebox_process(first, signal.SIGTERM)
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
        assert pid_is_alive(server.pid)
        assert pid_is_alive(supervisor_pid_before)
        assert pid_is_alive(daphne_pid_before)
        assert supervisor_pid_from_log(server_log) == supervisor_pid_before
        assert worker_pid_from_log(server_log, "worker_daphne") == daphne_pid_before
        assert "A newer archivebox process took over the orchestrator, server" not in server_log.read_text(
            encoding="utf-8",
            errors="replace",
        )
    finally:
        if server is not None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(360)
def test_live_server_keeps_http_runtime_while_update_runs_real_sqlite_indexer(tmp_path, initialized_archive, recursive_test_site):
    env = cli_env(
        live=True,
        PLUGINS="wget,parse_html_urls,search_backend_sqlite,search_backend_sonic",
        SEARCH_BACKEND_ENGINE="sqlite",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
    )
    env.update(_resolve_sonic_env(env))
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
        supervisord_log = tmp_path / "logs" / "supervisord.log"
        runner_spawn_text = "spawned: 'worker_runner' with pid"
        runner_spawn_count = supervisord_log.read_text(encoding="utf-8", errors="replace").count(runner_spawn_text)

        _cmd_result = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=1"],
            cwd=tmp_path,
            env=env,
            timeout=180,
        )
        update_stdout, update_stderr, update_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert update_returncode == 0, update_stderr or update_stdout
        assert pid_is_alive(server.pid)
        assert supervisor_pid_from_log(server_log) == supervisor_pid_before
        assert pid_is_alive(daphne_pid_before)
        assert pid_is_alive(sonic_pid_before)
        assert worker_pid_from_log(server_log, "worker_daphne") == daphne_pid_before
        assert worker_pid_from_log(server_log, "worker_sonic") == sonic_pid_before
        assert "A newer archivebox process took over the orchestrator, server" not in server_log.read_text(
            encoding="utf-8",
            errors="replace",
        )
        worker_name_match = re.search(r"Worker (worker_runner_update_\d+):", update_stdout)
        assert worker_name_match, update_stdout
        wait_for_log(
            tmp_path / "logs" / f"{worker_name_match.group(1)}.log",
            "Stopping older ArchiveBox runner process",
        )

        supervisord_text = wait_for_log_count(supervisord_log, runner_spawn_text, runner_spawn_count + 1, timeout=30)
        runner_pid_after = int(re.findall(r"spawned: 'worker_runner' with pid (\d+)", supervisord_text)[-1])
        assert runner_pid_after != runner_pid_before
        assert pid_is_alive(runner_pid_after)

        with use_archivebox_db(tmp_path):
            indexed_results = list(
                ArchiveResult.objects.filter(plugin="search_backend_sqlite").values_list("status", flat=True),
            )
        assert indexed_results
        assert all(status in ArchiveResult.FINAL_STATES for status in indexed_results)

        stop_archivebox_process(server, signal.SIGTERM)
        server = None
        wait_for_pid_to_disappear(daphne_pid_before, timeout=20)
        wait_for_pid_to_disappear(sonic_pid_before, timeout=20)
        wait_for_pid_to_disappear(runner_pid_after, timeout=20)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)
    finally:
        if server is not None:
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(420)
def test_live_update_yields_to_server_then_reclaims_real_sqlite_indexing(tmp_path, initialized_archive, recursive_test_site):
    env = cli_env(
        live=True,
        PLUGINS="wget,parse_html_urls,search_backend_sqlite,search_backend_sonic",
        SEARCH_BACKEND_ENGINE="sqlite",
        SEARCH_BACKEND_SONIC_PORT=str(get_free_port()),
    )
    env.update(_resolve_sonic_env(env))
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
        assert pid_is_alive(update_proc.pid)
        assert pid_is_alive(server.pid)
        server_text = server_log.read_text(encoding="utf-8", errors="replace")
        # The older update process can yield orchestrator ownership just before
        # the server logs its takeover, but sonic must always move to the server.
        assert (
            "Taking over orchestrator, sonic from older existing archivebox process" in server_text
            or "Taking over sonic from older existing archivebox process" in server_text
        )
        assert "worker_daphne" in server_text
        assert "worker_sonic" in server_text
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

        with use_archivebox_db(tmp_path):
            indexed_results = list(
                ArchiveResult.objects.filter(plugin="search_backend_sqlite").values_list("status", flat=True),
            )
        assert indexed_results
        assert all(status in ArchiveResult.FINAL_STATES for status in indexed_results)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)
    finally:
        if update_proc is not None:
            stop_archivebox_process(update_proc, signal.SIGTERM)
        if server is not None:
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
                assert pid_is_alive(previous_server.pid)
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

        assert pid_is_alive(servers[-1].pid)
        assert all(pid_is_alive(server.pid) for server in servers)
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
        assert pid_is_alive(servers[3].pid)
    finally:
        for server in reversed(servers):
            stop_archivebox_process(server, signal.SIGTERM)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


@pytest.mark.timeout(420)
def test_live_background_add_survives_server_exit_and_foreground_run_reclaims(tmp_path, initialized_archive, recursive_test_site):
    env = cli_env(live=True, SEARCH_BACKEND_ENGINE="ripgrep")
    port = get_free_port()
    server = None
    server2 = None
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
        assert pid_is_alive(server.pid)
        assert pid_is_alive(supervisor_pid_before)
        assert supervisor_pid_from_log(server_log) == supervisor_pid_before

        add = run_archivebox_cmd(
            [
                "add",
                "--bg",
                "--depth=1",
                "--max-urls=20",
                "--crawl-max-size=50mb",
                "--plugins=wget,parse_html_urls",
                recursive_test_site["root_url"],
            ],
            cwd=tmp_path,
            env=env,
            timeout=60,
        )
        assert add.returncode == 0, add.stderr or add.stdout
        assert "background runner will process" in add.stdout

        stop_archivebox_process(server, signal.SIGTERM)
        server = None
        assert "Got SIGTERM" in server_log.read_text(encoding="utf-8", errors="replace")
        assert_no_processes_for_data_dir(tmp_path, timeout=12)

        with use_archivebox_db(tmp_path):
            crawl_id = str(Crawl.objects.get().id)
        run = run_archivebox_cmd(
            ["run", f"--crawl-id={crawl_id}"],
            cwd=tmp_path,
            env=env,
            timeout=180,
        )
        assert run.returncode == 0, run.stderr or run.stdout

        server2 = start_archivebox_server(tmp_path, port=port, log_name="server-add-owner-2.log", env=env)
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500
        captured_text = wait_for_snapshot_capture(tmp_path, recursive_test_site["root_url"], timeout=180)
        assert "Root" in captured_text
        stop_archivebox_process(server2, signal.SIGTERM)
        server2 = None
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
        assert not bad_results
    finally:
        for proc in (server, server2):
            if proc is not None:
                stop_archivebox_process(proc, signal.SIGTERM, timeout=10)
        kill_processes_for_data_dir(tmp_path)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)


# Utility-level takeover selection tests.


def _start_archivebox_shell(tmp_path: Path):
    process = run_archivebox_cmd(
        ["manage", "shell"],
        cwd=tmp_path,
        env=cli_env(live=True),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        capture_output=False,
        start_new_session=True,
        wait=False,
    )
    assert process.pid is not None
    assert process.stdin is not None
    assert pid_is_alive(process.pid)
    return process


def _stop_archivebox_shells(processes) -> None:
    for process in processes:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
    for process in processes:
        process.wait(timeout=20)
        assert not pid_is_alive(process.pid)


def test_runtime_stack_owner_prefers_newer_server_over_older_update(tmp_path, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.core.takeover_util import runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type in (Process.TypeChoices.UPDATE, Process.TypeChoices.SERVER):
            proc = _start_archivebox_shell(tmp_path)
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

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is not None
        assert owner.process_type == Process.TypeChoices.SERVER
        assert owner.pid == procs[-1].pid
    finally:
        _stop_archivebox_shells(procs)


def test_runtime_stack_owner_keeps_server_over_newer_update(tmp_path, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.core.takeover_util import runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type in (Process.TypeChoices.SERVER, Process.TypeChoices.UPDATE):
            proc = _start_archivebox_shell(tmp_path)
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

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is not None
        assert owner.process_type == Process.TypeChoices.SERVER
        assert owner.pid == procs[0].pid
    finally:
        _stop_archivebox_shells(procs)


def test_foreground_runner_owner_prefers_newer_update_over_server(tmp_path, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.core.takeover_util import foreground_runner_owner, runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type in (Process.TypeChoices.SERVER, Process.TypeChoices.UPDATE):
            proc = _start_archivebox_shell(tmp_path)
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

        runtime_owner = runtime_stack_owner(data_dir=tmp_path)
        runner_owner = foreground_runner_owner(data_dir=tmp_path)

        assert runtime_owner is not None
        assert runtime_owner.process_type == Process.TypeChoices.SERVER
        assert runner_owner is not None
        assert runner_owner.process_type == Process.TypeChoices.UPDATE
        assert runner_owner.pid == procs[-1].pid
    finally:
        _stop_archivebox_shells(procs)


def test_foreground_runner_owner_prefers_newer_server_over_update(tmp_path, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.core.takeover_util import foreground_runner_owner, runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type in (Process.TypeChoices.UPDATE, Process.TypeChoices.SERVER):
            proc = _start_archivebox_shell(tmp_path)
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

        runtime_owner = runtime_stack_owner(data_dir=tmp_path)
        runner_owner = foreground_runner_owner(data_dir=tmp_path)

        assert runtime_owner is not None
        assert runtime_owner.process_type == Process.TypeChoices.SERVER
        assert runner_owner is not None
        assert runner_owner.process_type == Process.TypeChoices.SERVER
        assert runner_owner.pid == procs[-1].pid
    finally:
        _stop_archivebox_shells(procs)


def test_runtime_stack_owner_keeps_server_over_newer_supervised_runner(tmp_path, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE, runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for process_type, worker_type in (
            (Process.TypeChoices.SERVER, ""),
            (Process.TypeChoices.ORCHESTRATOR, RUNNER_ACTIVE_WORKER_TYPE),
        ):
            proc = _start_archivebox_shell(tmp_path)
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

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is not None
        assert owner.process_type == Process.TypeChoices.SERVER
        assert owner.pid == procs[0].pid
    finally:
        _stop_archivebox_shells(procs)


def test_runtime_stack_owner_reaps_dead_server_without_promoting_update(tmp_path, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.core.takeover_util import runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    older_row = None
    newer_row = None
    try:
        for process_type in (Process.TypeChoices.UPDATE, Process.TypeChoices.SERVER):
            proc = _start_archivebox_shell(tmp_path)
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

        assert older_row is not None
        assert newer_row is not None

        os.kill(procs[-1].pid, signal.SIGTERM)
        procs[-1].wait(timeout=20)

        owner = runtime_stack_owner(data_dir=tmp_path)

        assert owner is None
        newer_row.refresh_from_db()
        assert newer_row.status == Process.StatusChoices.EXITED
        older_row.refresh_from_db()
        assert older_row.status == Process.StatusChoices.RUNNING
    finally:
        _stop_archivebox_shells(procs)


def test_runtime_stack_owner_ignores_supervised_orphan_runner(tmp_path, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE, runtime_stack_owner

    procs: list[subprocess.Popen[str]] = []
    try:
        for _ in range(2):
            proc = _start_archivebox_shell(tmp_path)
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
        _stop_archivebox_shells(procs)


def test_runtime_stack_owner_allows_top_level_runner_when_no_parent_command_exists(tmp_path, initialized_archive):
    from archivebox.machine.models import Machine
    from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE, runtime_stack_owner

    proc = _start_archivebox_shell(tmp_path)
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
        _stop_archivebox_shells([proc])


def test_foreign_machine_runner_only_warns(tmp_path, initialized_archive, capsys):
    from archivebox.core.takeover_util import RUNNER_ACTIVE_WORKER_TYPE, live_runner_processes
    from archivebox.machine.models import Machine

    foreign_machine = Machine.objects.create(
        guid="foreign-machine",
        hostname="foreign-host",
        hw_manufacturer="Test",
        hw_product="Test",
        hw_uuid="foreign-hardware",
        os_arch="x86_64",
        os_family="linux",
        os_platform="linux",
        os_release="test",
        os_kernel="test",
    )
    foreign_runner = Process.objects.create(
        machine=foreign_machine,
        process_type=Process.TypeChoices.ORCHESTRATOR,
        worker_type=RUNNER_ACTIVE_WORKER_TYPE,
        pwd=str(tmp_path),
        pid=1,
        status=Process.StatusChoices.RUNNING,
    )

    assert live_runner_processes(data_dir=tmp_path) == []
    foreign_runner.refresh_from_db()
    assert foreign_runner.status == Process.StatusChoices.RUNNING
    assert "Multiple orchestrators sharing a single collection is not officially supported" in capsys.readouterr().err
