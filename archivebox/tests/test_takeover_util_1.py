#!/usr/bin/env python3
"""Takeover utility tests and live command handoff flows."""

import os
import json
import signal
import subprocess
import sys
import pty
import select
import termios
import time
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
    get_http_response,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


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


@pytest.mark.parametrize("interrupt_before_takeover", [False, True], ids=["running", "prompt"])
@pytest.mark.parametrize("after_takeover", ["resume", "cancel-standby"])
def test_interactive_add_takeover(initialized_archive, interrupt_before_takeover, after_takeover):
    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, 160))
    output = bytearray()
    add = None
    server = None
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

    def active_hook_for(parent_pid):
        with use_archivebox_db(initialized_archive):
            for hook in Process.objects.filter(
                process_type=Process.TypeChoices.HOOK,
                cmd__0__endswith="on_Snapshot__30_chrome_navigate.js",
                status="running",
            ):
                if hook.is_running and parent_pid in {parent.pid for parent in psutil.Process(hook.pid).parents()}:
                    return hook
        return None

    try:
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
        read_until(lambda: active_hook_for(add.pid) is not None)
        old_hook = active_hook_for(add.pid)
        assert old_hook is not None
        if interrupt_before_takeover:
            add.send_signal(signal.SIGINT)
            read_until(lambda: b"Choice [skip]:" in output)
            read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            assert not pid_is_alive(old_hook.pid)

        server = start_archivebox_server(initialized_archive, port=port, log_name="interrupt-takeover-server.log", env=env)
        read_until(lambda: b"A newer archivebox process took over" in output)
        assert add.poll() is None, output.decode(errors="replace")
        assert termios.tcgetattr(slave)[3] & termios.ICANON
        assert not pid_is_alive(old_hook.pid)
        assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500

        if after_takeover == "cancel-standby":
            add.send_signal(signal.SIGINT)
            read_until(lambda: add.poll() is not None)
            assert add.returncode == 130, output.decode(errors="replace")
            assert pid_is_alive(server.pid)
            assert get_http_response(port, host=f"archivebox.localhost:{port}").status_code < 500
        else:
            read_until(lambda: active_hook_for(server.pid) is not None)
            stop_archivebox_process(server, signal.SIGTERM)
            server = None
            read_until(lambda: active_hook_for(add.pid) is not None)
            resumed_hook = active_hook_for(add.pid)
            assert resumed_hook is not None and resumed_hook.pid != old_hook.pid
            prompt_offset = len(output)
            add.send_signal(signal.SIGINT)
            read_until(lambda: b"Choice [skip]:" in output[prompt_offset:])
            read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            os.write(master, b"\r")
            read_until(lambda: add.poll() is not None)
            assert add.returncode == 0, output.decode(errors="replace")
            with use_archivebox_db(initialized_archive):
                assert Crawl.objects.get().status == Crawl.StatusChoices.SEALED
        assert b"Traceback" not in output
    finally:
        for process in (server, add):
            if process is not None and process.poll() is None:
                stop_archivebox_process(process, signal.SIGTERM)
        os.close(slave)
        os.close(master)
        kill_processes_for_data_dir(initialized_archive)
        assert_no_processes_for_data_dir(initialized_archive, timeout=12)
