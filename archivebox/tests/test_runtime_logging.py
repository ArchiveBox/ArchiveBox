"""Real foreground runner logs use stderr, with Rich only on a terminal."""

import errno
import json
import os
import pty
import re
import select
import sqlite3
import subprocess
import termios
import time

import pytest

from archivebox.tests.conftest import cli_env, run_archivebox_cmd, stop_archivebox_process


@pytest.mark.parametrize("terminal", [False, True])
def test_runner_lifecycle_uses_terminal_aware_logging(initialized_archive, terminal):
    url = "https://example.com/" + "complete-unwrapped-path-" * 18
    env = cli_env(live=True, PLUGINS="hashes", USE_COLOR="True", TERM="xterm-256color")
    created = run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, env=env)
    assert created.returncode == 0, created.stdout + created.stderr
    master = slave = None
    process = None
    output = bytearray()
    try:
        if terminal:
            master, slave = pty.openpty()
            termios.tcsetwinsize(slave, (40, 100))
        with (initialized_archive / "runner-stdout.txt").open("w+") as stdout:
            process = run_archivebox_cmd(
                ["run", "--no-stdin"],
                cwd=initialized_archive,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=slave if terminal else subprocess.PIPE,
                wait=False,
            )
            if terminal:
                os.close(slave)
                slave = None
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError as error:
                            if error.errno == errno.EIO:
                                break
                            raise
                        if not chunk:
                            break
                        output.extend(chunk)
                    elif process.poll() is not None:
                        break
                process.wait(timeout=5)
                stderr = output.decode()
            else:
                _, stderr = process.communicate(timeout=60)
            assert process.returncode == 0, stderr
            stdout.seek(0)
            assert "[Crawl#" not in stdout.read()
        assert "archivebox.workers.runner" in stderr
        assert "[Crawl#" in re.sub(r"\x1b\[[0-9;]*m", "", stderr)
        if terminal:
            assert "\x1b[" in stderr
        else:
            assert "\x1b[" not in stderr
            assert any(url in line for line in stderr.splitlines()), stderr
            assert sum("[Crawl#" in line and "[STARTED]" in line for line in stderr.splitlines()) == 1
        persisted = (initialized_archive / "logs" / "errors.log").read_text()
        assert url in persisted
        assert "[STARTED]" in persisted
        with sqlite3.connect(initialized_archive / "index.sqlite3") as database:
            assert database.execute("SELECT status, downloaded_at IS NOT NULL FROM core_snapshot").fetchall() == [("sealed", 1)]
            assert database.execute("SELECT status FROM core_archiveresult WHERE plugin = 'hashes'").fetchall() == [("succeeded",)]
        assert "\x1b[" not in persisted
    finally:
        if process is not None:
            stop_archivebox_process(process)
        for fd in (master, slave):
            if fd is not None:
                os.close(fd)


def test_outbound_http_logs_leave_json_stdout_and_full_plain_stderr(initialized_archive, recursive_test_site):
    url = recursive_test_site["root_url"] + "?trace=" + "complete-unwrapped-path-" * 18
    result = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "--no-imports",
            "-c",
            f"import httpx, json; response = httpx.get({url!r}); print(json.dumps({{'status': response.status_code}}))",
        ],
        cwd=initialized_archive,
        env=cli_env(live=True, USE_COLOR="True"),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"status": 404}
    assert "\x1b[" not in result.stderr
    assert sum(url in line for line in result.stderr.splitlines()) == 1, result.stderr
    assert "OutboundWebhook:" in result.stderr
