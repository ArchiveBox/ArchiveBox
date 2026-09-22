#!/usr/bin/env python3
"""
Tests for archivebox help command.
Verify command runs successfully and produces output.
"""

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
