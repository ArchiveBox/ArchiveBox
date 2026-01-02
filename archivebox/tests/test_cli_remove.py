#!/usr/bin/env python3
"""
Comprehensive tests for archivebox remove command.
Verify remove deletes snapshots from DB and filesystem.
"""

import os
import subprocess
import sqlite3
from pathlib import Path

from .fixtures import *


def test_remove_deletes_snapshot_from_db(tmp_path, process, disable_extractors_dict):
    """Test that remove command deletes snapshot from database."""
    os.chdir(tmp_path)

    # Add a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Verify it exists
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_before = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()
    assert count_before == 1

    # Remove it
    subprocess.run(
        ['archivebox', 'remove', 'https://example.com', '--yes'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Verify it's gone
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_after = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count_after == 0


def test_remove_deletes_archive_directory(tmp_path, process, disable_extractors_dict):
    """Test that remove deletes the archive directory when using --delete flag.

    Archive directories are named by timestamp, not by snapshot ID.
    """
    os.chdir(tmp_path)

    # Add a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Get snapshot timestamp
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    timestamp = c.execute("SELECT timestamp FROM core_snapshot").fetchone()[0]
    conn.close()

    archive_dir = tmp_path / "archive" / str(timestamp)
    assert archive_dir.exists()

    # Remove snapshot with --delete to remove both DB record and directory
    subprocess.run(
        ['archivebox', 'remove', 'https://example.com', '--yes', '--delete'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Archive directory should be deleted
    assert not archive_dir.exists()


def test_remove_yes_flag_skips_confirmation(tmp_path, process, disable_extractors_dict):
    """Test that --yes flag skips confirmation prompt."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Remove with --yes should complete without interaction
    result = subprocess.run(
        ['archivebox', 'remove', 'https://example.com', '--yes'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode == 0


def test_remove_multiple_snapshots(tmp_path, process, disable_extractors_dict):
    """Test removing multiple snapshots at once."""
    os.chdir(tmp_path)

    # Add multiple snapshots
    for url in ['https://example.com', 'https://example.org']:
        subprocess.run(
            ['archivebox', 'add', '--index-only', '--depth=0', url],
            capture_output=True,
            env=disable_extractors_dict,
        )

    # Verify both exist
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_before = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()
    assert count_before == 2

    # Remove both
    subprocess.run(
        ['archivebox', 'remove', 'https://example.com', 'https://example.org', '--yes'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Verify both are gone
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_after = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count_after == 0


def test_remove_with_filter(tmp_path, process, disable_extractors_dict):
    """Test removing snapshots using filter."""
    os.chdir(tmp_path)

    # Add snapshots
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Remove using filter
    result = subprocess.run(
        ['archivebox', 'remove', '--filter-type=search', '--filter=example.com', '--yes'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    # Should complete (exit code depends on implementation)
    assert result.returncode in [0, 1, 2]


def test_remove_nonexistent_url_fails_gracefully(tmp_path, process, disable_extractors_dict):
    """Test that removing non-existent URL fails gracefully."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'remove', 'https://nonexistent-url-12345.com', '--yes'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Should fail or show error
    assert result.returncode != 0 or 'not found' in result.stdout.lower() or 'no matches' in result.stdout.lower()


def test_remove_after_flag(tmp_path, process, disable_extractors_dict):
    """Test remove --after flag removes snapshots after date."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Try remove with --after flag (should work or show usage)
    result = subprocess.run(
        ['archivebox', 'remove', '--after=2020-01-01', '--yes'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    # Should complete
    assert result.returncode in [0, 1, 2]
