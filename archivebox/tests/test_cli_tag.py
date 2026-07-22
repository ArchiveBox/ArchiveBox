#!/usr/bin/env python3
"""
Tests for archivebox tag command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_tag_help_runs_successfully(tmp_path):
    """The tag command should be registered and expose help."""

    result = run_archivebox_cmd(["tag", "--help"])

    assert result.returncode == 0
    assert "tag" in result.stdout.lower()
    assert "list" in result.stdout
