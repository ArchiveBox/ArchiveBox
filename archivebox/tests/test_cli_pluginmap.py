#!/usr/bin/env python3
"""
Tests for archivebox pluginmap command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_pluginmap_help_runs_successfully(tmp_path):
    """The pluginmap command should be registered and expose help."""

    result = run_archivebox_cmd(["pluginmap", "--help"])

    assert result.returncode == 0
    assert "pluginmap" in result.stdout.lower()
    assert "--event" in result.stdout
