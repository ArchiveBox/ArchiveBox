#!/usr/bin/env python3
"""Takeover utility tests and live command handoff flows."""

import signal
import subprocess

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
    wait_for_log_count,
    wait_for_pid_to_disappear,
    wait_for_snapshot_capture,
    worker_pid_from_log,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

from .test_takeover_util_1 import (
    pytestmark as pytestmark,
    _resolve_sonic_env as _resolve_sonic_env,
    _archive_pages_for_sqlite_reindexing as _archive_pages_for_sqlite_reindexing,
    _start_archivebox_shell as _start_archivebox_shell,
    _stop_archivebox_shells as _stop_archivebox_shells,
)


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

        result = run_archivebox_cmd(
            ["status"],
            cwd=tmp_path,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr or result.stdout

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

        result = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=1"],
            cwd=tmp_path,
            env=env,
            timeout=180,
        )

        assert result.returncode == 0, result.stderr or result.stdout
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
        supervisord_text = supervisord_log.read_text(encoding="utf-8", errors="replace")
        assert supervisord_text.count(runner_spawn_text) == runner_spawn_count
        assert worker_pid_from_log(server_log, "worker_runner") == runner_pid_before
        assert pid_is_alive(runner_pid_before)

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
        wait_for_pid_to_disappear(runner_pid_before, timeout=20)
        assert_no_processes_for_data_dir(tmp_path, timeout=12)
    finally:
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

            result = run_archivebox_cmd(
                ["status"],
                cwd=tmp_path,
                env=env,
                timeout=60,
            )
            assert result.returncode == 0, result.stderr or result.stdout

        assert pid_is_alive(servers[-1].pid)
        assert all(pid_is_alive(server.pid) for server in servers)
        # Inspect the actual server worker rather than requiring a host lsof
        # installation. Previous workers must be gone, and the newest worker
        # must own exactly one listening socket on our assigned port.
        assert all(not pid_is_alive(pid) for pid in daphne_pids[:-1])
        listeners = [
            connection
            for connection in psutil.Process(daphne_pids[-1]).net_connections(kind="tcp")
            if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port
        ]
        assert len(listeners) == 1, listeners

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

        result = run_archivebox_cmd(
            ["update", "--index-only", "--batch-size=10"],
            cwd=tmp_path,
            env=env,
            timeout=90,
        )
        assert result.returncode == 0, result.stderr or result.stdout
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
