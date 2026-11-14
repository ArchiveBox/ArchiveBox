#!/usr/bin/env python3
"""
Tests for archivebox help command.
Verify command runs successfully and produces output.
"""

import pytest

from archivebox.tests.conftest import run_archivebox_cmd


def test_help_runs_successfully(tmp_path):
    """Test that help command runs and produces output."""
    result = run_archivebox_cmd(["help"])

    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert len(combined) > 100
    assert "archivebox" in combined.lower()


def test_help_in_initialized_dir(initialized_archive):
    """Test help command in initialized data directory."""
    result = run_archivebox_cmd(["help"])

    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "init" in combined
    assert "add" in combined


@pytest.mark.parametrize("command", ["linkhealth", "storageaudit", "storage"])
def test_management_commands_exclude_removed_apps(initialized_archive, command):
    check = run_archivebox_cmd(["manage", "check"])
    assert check.returncode == 0, check.stderr
    result = run_archivebox_cmd(["manage", command, "--help"])
    assert result.returncode != 0
    assert f"Unknown command: '{command}'" in result.stderr
