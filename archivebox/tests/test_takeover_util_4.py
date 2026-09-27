#!/usr/bin/env python3
"""Takeover utility tests and live command handoff flows."""

import os
import signal
import subprocess

import pytest
import psutil

from archivebox.core.models import ArchiveResult
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
    wait_for_log_pattern,
    wait_for_pid_to_disappear,
    wait_for_worker_pid_from_log,
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

        result = run_archivebox_cmd(
            ["update", "--index-only", "--before=0"],
            cwd=tmp_path,
            env=env,
            timeout=90,
        )

        assert result.returncode == 0, result.stderr or result.stdout
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
        assert pid_is_alive(update_supervisor_pid_before)
        assert pid_is_alive(update_sonic_pid_before)
        assert "worker_runner_update_" not in update_log.read_text(encoding="utf-8", errors="replace")
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
