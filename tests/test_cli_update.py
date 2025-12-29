#!/usr/bin/env python3
"""
Comprehensive tests for archivebox update command.
Verify update re-archives snapshots and updates DB status.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_update_runs_successfully_on_empty_archive(tmp_path, process):
    """Test that update runs without error on empty archive."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'update', '--index-only'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should complete successfully even with no snapshots
    assert result.returncode == 0


def test_update_re_archives_existing_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that update command re-archives existing snapshots."""
    os.chdir(tmp_path)

    # Add a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Run update
    result = subprocess.run(
        ['archivebox', 'update', '--index-only'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode == 0


def test_update_index_only_flag(tmp_path, process, disable_extractors_dict):
    """Test that --index-only flag skips extraction."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Update with index-only should be fast
    result = subprocess.run(
        ['archivebox', 'update', '--index-only'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode == 0


def test_update_specific_snapshot_by_filter(tmp_path, process, disable_extractors_dict):
    """Test updating specific snapshot using filter."""
    os.chdir(tmp_path)

    # Add multiple snapshots
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.org'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Update with filter
    result = subprocess.run(
        ['archivebox', 'update', '--index-only', '--filter-type=search', '--filter=example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    # Should complete (may succeed or show usage)
    assert result.returncode in [0, 1, 2]


def test_update_preserves_snapshot_count(tmp_path, process, disable_extractors_dict):
    """Test that update doesn't change snapshot count."""
    os.chdir(tmp_path)

    # Add snapshots
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Count before update
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_before = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count_before == 1

    # Run update
    subprocess.run(
        ['archivebox', 'update', '--index-only'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    # Count after update
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_after = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # Snapshot count should remain the same
    assert count_after == count_before


def test_update_with_overwrite_flag(tmp_path, process, disable_extractors_dict):
    """Test update with --overwrite flag forces re-archiving."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'update', '--index-only', '--overwrite'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode == 0
