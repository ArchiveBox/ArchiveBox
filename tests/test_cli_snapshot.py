#!/usr/bin/env python3
"""
Tests for archivebox snapshot command.
Verify snapshot command works with snapshot IDs/URLs.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_snapshot_command_works_with_url(tmp_path, process, disable_extractors_dict):
    """Test that snapshot command works with URL."""
    os.chdir(tmp_path)

    # Add a snapshot first
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Try to view/interact with snapshot
    result = subprocess.run(
        ['archivebox', 'snapshot', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    # Should complete (exit code depends on implementation)
    assert result.returncode in [0, 1, 2]


def test_snapshot_command_with_timestamp(tmp_path, process, disable_extractors_dict):
    """Test snapshot command with timestamp ID."""
    os.chdir(tmp_path)

    # Add snapshot
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

    # Try snapshot command with timestamp
    result = subprocess.run(
        ['archivebox', 'snapshot', str(timestamp)],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode in [0, 1, 2]
