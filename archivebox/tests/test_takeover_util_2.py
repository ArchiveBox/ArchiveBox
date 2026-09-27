#!/usr/bin/env python3
"""Takeover utility tests and live command handoff flows."""

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import pty
import select
import termios
import time
from pathlib import Path

import pytest

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
    get_http_response,
    wait_for_snapshot_capture,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

from .test_takeover_util_1 import (
    pytestmark as pytestmark,
    _resolve_sonic_env as _resolve_sonic_env,
    _archive_pages_for_sqlite_reindexing as _archive_pages_for_sqlite_reindexing,
    _start_archivebox_shell as _start_archivebox_shell,
    _stop_archivebox_shells as _stop_archivebox_shells,
)


@pytest.mark.parametrize("force_abort", [None, "typed", "signal"], ids=["graceful", "force-after-choice", "force-after-ctrl-c"])
def test_interactive_add_borrowing_server_supervisor_can_abort(initialized_archive, force_abort):
    """A server-owned supervisor must not make an interactive add worker noninteractive."""
    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, 160))
    output = bytearray()
    server = None
    add = None
    port = get_free_port()
    env = cli_env(
        SEARCH_BACKEND_ENGINE="ripgrep",
        SEARCH_BACKEND_SONIC_ENABLED="False",
        CHROME_DELAY_AFTER_LOAD="60",
        CHROME_TIMEOUT="120",
        CHROME_HEADLESS="True",
    )
    installed = run_archivebox_cmd(["install", "chrome"], cwd=initialized_archive, env=env, timeout=600)
    assert installed.returncode == 0, installed.stderr or installed.stdout

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
            for hook in Process.objects.filter(
                process_type=Process.TypeChoices.HOOK,
                cmd__0__endswith="on_Snapshot__30_chrome_navigate.js",
                status="running",
            ):
                if hook.is_running:
                    return hook
        return None

    try:
        server = start_archivebox_server(initialized_archive, port=port, log_name="add-borrows-server.log", env=env)
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500
        add = run_archivebox_cmd(
            ["add", "--plugins=chrome", "https://example.com"],
            cwd=initialized_archive,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            wait=False,
            start_new_session=True,
        )
        read_until(lambda: active_hook() is not None)
        old_hook = active_hook()
        assert old_hook is not None
        add.send_signal(signal.SIGINT)
        read_until(lambda: b"Choice [skip]:" in output)
        read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
        assert add.poll() is None, output.decode(errors="replace")
        assert not pid_is_alive(old_hook.pid)

        if force_abort:
            # Both abort choices must become forceable before the worker has
            # time to write its marker or finish the normal hook grace phase.
            if force_abort == "typed":
                os.write(master, b"a")
            else:
                add.send_signal(signal.SIGINT)
            read_until(lambda: termios.tcgetattr(slave)[3] & termios.ICANON)
            forced_at = time.monotonic()
            add.send_signal(signal.SIGINT)
        else:
            add.send_signal(signal.SIGINT)
        read_until(lambda: add.poll() is not None)
        if force_abort:
            assert time.monotonic() - forced_at < 2.0, output.decode(errors="replace")
            assert b"Forcing aborted crawl to exit now" in output
        assert add.returncode == 130, output.decode(errors="replace")
        assert pid_is_alive(server.pid)
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500
        assert b"Traceback" not in output
    finally:
        for process in (add, server):
            if process is not None and process.poll() is None:
                stop_archivebox_process(process, signal.SIGTERM)
        os.close(slave)
        os.close(master)
        kill_processes_for_data_dir(initialized_archive)
        assert_no_processes_for_data_dir(initialized_archive, timeout=12)


def test_explicit_sonic_binary_is_used_by_real_search_worker(initialized_archive):
    sonic_port = get_free_port()
    lib_dir = initialized_archive / "lib"
    env = cli_env(
        live=True,
        ABXPKG_LIB_DIR=str(lib_dir),
        PLUGINS="search_backend_sonic",
        SEARCH_BACKEND_ENGINE="sonic",
        SEARCH_BACKEND_SONIC_PORT=str(sonic_port),
    )
    env.update(_resolve_sonic_env(env))
    env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), env["PATH"]))
    installed_binary = Path(env["SONIC_BINARY"]).resolve(strict=True)
    managed_sonic_dir = lib_dir / "bash" / "bin"
    managed_sonic_dir.mkdir(parents=True, exist_ok=True)
    managed_binary = managed_sonic_dir / "sonic"
    if installed_binary != managed_binary:
        shutil.copy2(installed_binary, managed_binary)
    config_result = run_archivebox_cmd(
        ["config", "--set", f"SONIC_BINARY={managed_binary}"],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    assert config_result.returncode == 0, config_result.stderr or config_result.stdout
    pinned_sonic_dir = initialized_archive / "pinned-sonic"
    pinned_sonic_dir.mkdir()
    sonic_binary = pinned_sonic_dir / "sonic"
    shutil.copy2(installed_binary, sonic_binary)
    env["SONIC_BINARY"] = str(sonic_binary)

    result = run_archivebox_cmd(
        ["list", "--search=contents", "--csv=url", "not-indexed"],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    config_match = re.search(r"Using supervisord config file: (\S+)", result.stderr)
    assert config_match, result.stderr
    worker_config = Path(config_match.group(1)).parent / "workers" / "worker_sonic.conf"
    worker_text = worker_config.read_text(encoding="utf-8")
    command = next(line.partition("=")[2] for line in worker_text.splitlines() if line.startswith("command="))
    assert shlex.split(command)[0] == str(sonic_binary), worker_text
    from archivebox.workers.supervisord_util import _sonic_worker_bind_target

    assert _sonic_worker_bind_target({"name": "worker_sonic", "command": command}) == ("127.0.0.1", sonic_port)
    renamed_binary = initialized_archive / "renamed-sonic-binary"
    shutil.copy2(sonic_binary, renamed_binary)
    renamed_command = shlex.join([str(renamed_binary), *shlex.split(command)[1:]])
    assert _sonic_worker_bind_target({"name": "worker_sonic", "command": renamed_command}) == ("127.0.0.1", sonic_port)

    relative_binary = pinned_sonic_dir / "sonic-alt"
    shutil.copy2(sonic_binary, relative_binary)
    relative_env = {
        **env,
        "SONIC_BINARY": relative_binary.name,
        "PATH": os.pathsep.join((str(pinned_sonic_dir), env["PATH"])),
        "SEARCH_BACKEND_SONIC_PORT": str(get_free_port()),
    }
    relative_result = run_archivebox_cmd(
        ["list", "--search=contents", "--csv=url", "not-indexed"],
        cwd=initialized_archive,
        env=relative_env,
        timeout=60,
    )
    assert relative_result.returncode == 0, relative_result.stderr or relative_result.stdout
    relative_worker_text = worker_config.read_text(encoding="utf-8")
    relative_command = next(line.partition("=")[2] for line in relative_worker_text.splitlines() if line.startswith("command="))
    assert Path(shlex.split(relative_command)[0]).name == relative_binary.name, relative_worker_text


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
