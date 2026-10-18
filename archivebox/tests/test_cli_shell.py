#!/usr/bin/env python3
"""
Tests for archivebox shell command.
Verify shell command starts Django shell (basic smoke tests only).
"""

import re

import pytest

from archivebox.tests.conftest import cli_env, run_archivebox_cmd


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
