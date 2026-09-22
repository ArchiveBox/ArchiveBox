#!/usr/bin/env python3
"""
Tests for archivebox binary command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_binary_help_runs_successfully(tmp_path):
    """The binary command should be registered and expose help."""

    result = run_archivebox_cmd(["binary", "--help"])

    assert result.returncode == 0
    assert "binary" in result.stdout.lower()
    assert "list" in result.stdout
