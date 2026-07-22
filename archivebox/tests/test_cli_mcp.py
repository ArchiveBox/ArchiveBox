#!/usr/bin/env python3
"""
Tests for archivebox mcp command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_mcp_help_runs_successfully(tmp_path):
    """The mcp command should be registered and expose help."""

    result = run_archivebox_cmd(["mcp", "--help"])

    assert result.returncode == 0
    assert "mcp" in result.stdout.lower()
