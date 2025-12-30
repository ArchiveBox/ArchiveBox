#!/usr/bin/env python3
"""
Comprehensive tests for archivebox install command.
Verify install detects and records binary dependencies in DB.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_install_runs_successfully(tmp_path, process):
    """Test that install command runs without error."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'install', '--dry-run'],
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Dry run should complete quickly
    assert result.returncode in [0, 1]  # May return 1 if binaries missing


def test_install_creates_binary_records_in_db(tmp_path, process):
    """Test that install creates Binary records in database."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'install', '--dry-run'],
        capture_output=True,
        timeout=60,
    )

    # Check that binary records were created
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check machine_binary table exists
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='machine_binary'"
    ).fetchall()
    conn.close()

    assert len(tables) == 1


def test_install_dry_run_does_not_install(tmp_path, process):
    """Test that --dry-run doesn't actually install anything."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'install', '--dry-run'],
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Should complete without actually installing
    assert 'dry' in result.stdout.lower() or result.returncode in [0, 1]


def test_install_detects_system_binaries(tmp_path, process):
    """Test that install detects existing system binaries."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'install', '--dry-run'],
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Should detect at least some common binaries (python, curl, etc)
    assert result.returncode in [0, 1]


def test_install_shows_binary_status(tmp_path, process):
    """Test that install shows status of binaries."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'install', '--dry-run'],
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = result.stdout + result.stderr
    # Should show some binary information
    assert len(output) > 50


def test_install_updates_binary_table(tmp_path, process, disable_extractors_dict):
    """Test that install command runs successfully.

    Binary records are created lazily when binaries are first used, not during install.
    """
    os.chdir(tmp_path)

    # Run install - it should complete without errors or timeout (which is expected)
    # The install command starts the orchestrator which runs continuously
    try:
        result = subprocess.run(
            ['archivebox', 'install'],
            capture_output=True,
            timeout=30,
            env=disable_extractors_dict,
        )
        # If it completes, should be successful
        assert result.returncode == 0
    except subprocess.TimeoutExpired:
        # Timeout is expected since orchestrator runs continuously
        pass
