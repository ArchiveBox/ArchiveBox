#!/usr/bin/env python3
"""
Tests for archivebox process command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_process_help_runs_successfully(tmp_path):
    """The process command should be registered and expose help."""

    result = run_archivebox_cmd(["process", "--help"])

    assert result.returncode == 0
    assert "process" in result.stdout.lower()
    assert "list" in result.stdout
