#!/usr/bin/env python3
"""
Tests for archivebox shell command.
Verify shell command starts Django shell (basic smoke tests only).
"""

import re
import json
import subprocess

import psutil

import pytest

from archivebox.tests.conftest import cli_env, run_archivebox_cmd


@pytest.mark.parametrize("shutdown", ["flush", "ignore"])
def test_cli_timeout_preserves_failure_output_and_reaps_children(initialized_archive, shutdown):
    pid_file = initialized_archive / "timeout-pids.json"
    script = f"""
import json, os, signal, subprocess, sys, time
from pathlib import Path
def shutdown(signum, frame):
    sys.stderr.write('cleanup-output:' + 'x' * 262144 + ':cleanup-finished\\n')
    sys.stderr.flush()
    raise SystemExit(0)
signal.signal(signal.SIGTERM, {"shutdown" if shutdown == "flush" else "signal.SIG_IGN"})
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
Path({str(pid_file)!r}).write_text(json.dumps([os.getpid(), child.pid]))
print('command-started', flush=True)
time.sleep(120)
"""
    try:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            run_archivebox_cmd(["shell", "-c", script], cwd=initialized_archive, timeout=4)
        assert pid_file.exists(), "the real CLI must start before testing its timeout"
        assert caught.value.timeout == 4
        assert caught.value.cmd[:2] == ["archivebox", "shell"]
        stdout = caught.value.output
        stderr = caught.value.stderr
        assert "command-started" in (stdout.decode() if isinstance(stdout, bytes) else stdout)
        if shutdown == "flush":
            assert ":cleanup-finished" in (stderr.decode() if isinstance(stderr, bytes) else stderr)
        pids = json.loads(pid_file.read_text())
        assert all(not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE for pid in pids)
        for stream, output in (("stdout", stdout), ("stderr", stderr)):
            saved = initialized_archive / "logs" / f"cli-timeout-{pids[0]}.{stream}.log"
            assert saved.read_bytes() == (output.encode() if isinstance(output, str) else output)
    finally:
        if pid_file.exists():
            for pid in json.loads(pid_file.read_text()):
                try:
                    psutil.Process(pid).kill()
                except psutil.NoSuchProcess:
                    pass


def test_shell_command_exists(initialized_archive):
    """Test that shell command is recognized."""

    result = run_archivebox_cmd(
        ["shell", "--help"],
        timeout=10,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "usage:" in result.stdout
    assert "shell" in result.stdout


def test_shell_c_executes_python(initialized_archive):
    """shell -c should fully initialize Django and run the provided command."""

    result = run_archivebox_cmd(
        ["shell", "-c", 'print("shell-ok")'],
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "shell-ok" in result.stdout


def test_cli_logs_do_not_pad_to_an_artificial_terminal_width(initialized_archive):
    long_url = "https://archivebox.io/tests/" + "saved-resource/" * 30
    result = run_archivebox_cmd(
        [
            "shell",
            "-c",
            "import logging; from archivebox.misc.logging import STDERR; "
            "logging.getLogger('archivebox.services.runner').warning('Capture admission deferred: io stalls'); "
            "logging.getLogger('archivebox.services.runner').info('Snapshot admission complete'); "
            f"STDERR.print({long_url!r})",
        ],
        cwd=initialized_archive,
        env=cli_env(COLUMNS="160", TERM="xterm-256color", USE_COLOR="True", SHOW_PROGRESS="True"),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    stderr = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stderr)
    assert "Capture admission deferred: io stalls" in stderr
    assert "Snapshot admission complete" in stderr
    assert max(len(line) for line in stderr.splitlines() if long_url not in line) <= 160
    # Soft wrapping must still preserve copyable long URLs without hard breaks.
    assert long_url in stderr


@pytest.mark.parametrize("width", [80, 160])
def test_piped_logs_keep_error_messages_and_tracebacks_copyable(initialized_archive, width):
    long_url = "https://archivebox.io/tests/" + "saved-resource/" * 30
    script = (
        "import logging; from pathlib import Path\n"
        "try:\n"
        "    Path.cwd().mkdir()\n"
        "except FileExistsError:\n"
        f"    logging.getLogger('archivebox.services.runner').exception('Cannot save capture output: %s', {long_url!r})\n"
    )
    result = run_archivebox_cmd(
        ["shell", "-c", script],
        cwd=initialized_archive,
        env=cli_env(COLUMNS=str(width), TERM="xterm-256color", USE_COLOR="True"),
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    stderr = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stderr)
    assert f"Cannot save capture output: {long_url}" in stderr
    assert "Traceback (most recent call last):" in stderr
    assert "FileExistsError: [Errno 17]" in stderr
