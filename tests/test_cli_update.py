#!/usr/bin/env python3
"""
Comprehensive tests for archivebox update command.
Verify update drains old dirs, reconciles DB, and queues snapshots.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_update_runs_successfully_on_empty_archive(tmp_path, process):
    """Test that update runs without error on empty archive."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'update'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should complete successfully even with no snapshots
    assert result.returncode == 0


def test_update_reconciles_existing_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that update command reconciles existing snapshots."""
    os.chdir(tmp_path)

    # Add a snapshot (index-only for faster test)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Run update - should reconcile and queue
    result = subprocess.run(
        ['archivebox', 'update'],
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
        ['archivebox', 'add', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=90,
    )
    subprocess.run(
        ['archivebox', 'add', '--depth=0', 'https://example.org'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=90,
    )

    # Update with filter pattern (uses filter_patterns argument)
    result = subprocess.run(
        ['archivebox', 'update', '--filter-type=substring', 'example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    # Should complete successfully
    assert result.returncode == 0


def test_update_preserves_snapshot_count(tmp_path, process, disable_extractors_dict):
    """Test that update doesn't change snapshot count."""
    os.chdir(tmp_path)

    # Add snapshots
    subprocess.run(
        ['archivebox', 'add', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=90,
    )

    # Count before update
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_before = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count_before == 1

    # Run update (should reconcile + queue, not create new snapshots)
    subprocess.run(
        ['archivebox', 'update'],
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


def test_update_queues_snapshots_for_archiving(tmp_path, process, disable_extractors_dict):
    """Test that update queues snapshots for archiving."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=90,
    )

    # Run update
    result = subprocess.run(
        ['archivebox', 'update'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode == 0

    # Check that snapshot is queued
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    status = c.execute("SELECT status FROM core_snapshot").fetchone()[0]
    conn.close()

    assert status == 'queued'
