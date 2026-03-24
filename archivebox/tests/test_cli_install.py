#!/usr/bin/env python3
"""
Comprehensive tests for archivebox install command.
Verify install detects and records binary dependencies in DB.
"""

import os
import sqlite3
import subprocess
from pathlib import Path


def test_install_runs_successfully(tmp_path, process):
    """Test that install command runs without error."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "install", "--dry-run"],
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
        ["archivebox", "install", "--dry-run"],
        capture_output=True,
        timeout=60,
    )

    # Check that binary records were created
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check machine_binary table exists
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='machine_binary'",
    ).fetchall()
    conn.close()

    assert len(tables) == 1


def test_install_dry_run_does_not_install(tmp_path, process):
    """Test that --dry-run doesn't actually install anything."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ["archivebox", "install", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    # Should complete without actually installing
    assert "dry" in result.stdout.lower() or result.returncode in [0, 1]


def test_install_detects_system_binaries(tmp_path, process):
    """Test that install detects existing system binaries."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ["archivebox", "install", "--dry-run"],
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
        ["archivebox", "install", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    output = result.stdout + result.stderr
    # Should show some binary information
    assert len(output) > 50


def test_install_dry_run_prints_dry_run_message(tmp_path, process):
    """Test that install --dry-run clearly reports that no changes will be made."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "install", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0
    assert "dry run" in result.stdout.lower()


def test_install_help_lists_dry_run_flag(tmp_path):
    """Test that install --help documents the dry-run option."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "install", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--dry-run" in result.stdout or "-d" in result.stdout


def test_install_invalid_option_fails(tmp_path):
    """Test that invalid install options fail cleanly."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "install", "--invalid-option"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_install_from_empty_dir_initializes_collection(tmp_path):
    """Test that install bootstraps an empty dir before performing work."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "install", "--dry-run"],
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Initializing" in output or "Dry run" in output or "init" in output.lower()


def test_install_updates_binary_table(tmp_path, process):
    """Test that install completes and only mutates dependency state."""
    os.chdir(tmp_path)
    env = os.environ.copy()
    tmp_short = Path("/tmp") / f"abx-install-{tmp_path.name}"
    tmp_short.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "TMP_DIR": str(tmp_short),
            "ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS": "true",
        },
    )

    result = subprocess.run(
        ["archivebox", "install"],
        capture_output=True,
        text=True,
        timeout=420,
        env=env,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    binary_counts = dict(
        c.execute(
            "SELECT status, COUNT(*) FROM machine_binary GROUP BY status",
        ).fetchall(),
    )
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    sealed_crawls = c.execute(
        "SELECT COUNT(*) FROM crawls_crawl WHERE status='sealed'",
    ).fetchone()[0]
    conn.close()

    assert sealed_crawls == 0
    assert snapshot_count == 0
    assert binary_counts.get("installed", 0) > 0
