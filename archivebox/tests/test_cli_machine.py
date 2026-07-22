#!/usr/bin/env python3
"""
Tests for archivebox machine command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_machine_help_runs_successfully(tmp_path):
    """The machine command should be registered and expose help."""

    result = run_archivebox_cmd(["machine", "--help"])

    assert result.returncode == 0
    assert "machine" in result.stdout.lower()
    assert "list" in result.stdout
