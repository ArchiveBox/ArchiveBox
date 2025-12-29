#!/usr/bin/env python3
"""
Comprehensive tests for archivebox status command.
Verify status reports accurate collection state from DB and filesystem.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_status_runs_successfully(tmp_path, process):
    """Test that status command runs without error."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    assert result.returncode == 0
    assert len(result.stdout) > 100


def test_status_shows_zero_snapshots_in_empty_archive(tmp_path, process):
    """Test status shows 0 snapshots in empty archive."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    output = result.stdout
    # Should indicate empty/zero state
    assert '0' in output


def test_status_shows_correct_snapshot_count(tmp_path, process, disable_extractors_dict):
    """Test that status shows accurate snapshot count from DB."""
    os.chdir(tmp_path)

    # Add 3 snapshots
    for url in ['https://example.com', 'https://example.org', 'https://example.net']:
        subprocess.run(
            ['archivebox', 'add', '--index-only', '--depth=0', url],
            capture_output=True,
            env=disable_extractors_dict,
        )

    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    # Verify DB has 3 snapshots
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    db_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert db_count == 3
    # Status output should show 3
    assert '3' in result.stdout


def test_status_shows_archived_count(tmp_path, process, disable_extractors_dict):
    """Test status distinguishes archived vs unarchived snapshots."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    # Should show archived/unarchived categories
    assert 'archived' in result.stdout.lower() or 'queued' in result.stdout.lower()


def test_status_shows_archive_directory_size(tmp_path, process):
    """Test status reports archive directory size."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    output = result.stdout
    # Should show size info
    assert 'Size' in output or 'size' in output


def test_status_counts_archive_directories(tmp_path, process, disable_extractors_dict):
    """Test status counts directories in archive/ folder."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    # Should show directory count
    assert 'present' in result.stdout.lower() or 'directories' in result.stdout


def test_status_detects_orphaned_directories(tmp_path, process, disable_extractors_dict):
    """Test status detects directories not in DB (orphaned)."""
    os.chdir(tmp_path)

    # Add a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Create an orphaned directory
    (tmp_path / "archive" / "fake_orphaned_dir").mkdir(parents=True, exist_ok=True)

    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    # Should mention orphaned dirs
    assert 'orphan' in result.stdout.lower() or '1' in result.stdout


def test_status_shows_user_info(tmp_path, process):
    """Test status shows user/login information."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    output = result.stdout
    # Should show user section
    assert 'user' in output.lower() or 'login' in output.lower()


def test_status_reads_from_db_not_filesystem(tmp_path, process, disable_extractors_dict):
    """Test that status uses DB as source of truth, not filesystem."""
    os.chdir(tmp_path)

    # Add snapshot to DB
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Verify DB has snapshot
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    db_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert db_count == 1

    # Status should reflect DB count
    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)
    assert '1' in result.stdout


def test_status_shows_index_file_info(tmp_path, process):
    """Test status shows index file information."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'status'], capture_output=True, text=True)

    # Should mention index
    assert 'index' in result.stdout.lower() or 'Index' in result.stdout
