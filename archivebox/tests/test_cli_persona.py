#!/usr/bin/env python3
"""
Tests for archivebox persona command.
"""

from archivebox.tests.conftest import run_archivebox_cmd


def test_persona_help_runs_successfully(tmp_path):
    """The persona command should be registered and expose help."""

    result = run_archivebox_cmd(["persona", "--help"])

    assert result.returncode == 0
    assert "persona" in result.stdout.lower()
    assert "list" in result.stdout
