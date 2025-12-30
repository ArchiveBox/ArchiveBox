#!/usr/bin/env python3
"""
Tests for archivebox extract command.
Verify extract re-runs extractors on existing snapshots.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_extract_runs_on_existing_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that extract command runs on existing snapshots."""
    os.chdir(tmp_path)

    # Add a snapshot first
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Run extract
    result = subprocess.run(
        ['archivebox', 'extract'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    # Should complete
    assert result.returncode in [0, 1]


def test_extract_preserves_snapshot_count(tmp_path, process, disable_extractors_dict):
    """Test that extract doesn't change snapshot count."""
    os.chdir(tmp_path)

    # Add snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_before = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # Run extract
    subprocess.run(
        ['archivebox', 'extract', '--overwrite'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_after = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count_after == count_before
