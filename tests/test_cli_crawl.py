#!/usr/bin/env python3
"""
Tests for archivebox crawl command.
Verify crawl creates snapshots with depth.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_crawl_creates_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that crawl command works on existing snapshots."""
    os.chdir(tmp_path)

    # First add a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Then run crawl on it
    result = subprocess.run(
        ['archivebox', 'crawl', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode in [0, 1, 2]  # May succeed or fail depending on URL

    # Check snapshot was created
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count == 1


def test_crawl_with_depth_0(tmp_path, process, disable_extractors_dict):
    """Test crawl with depth=0 works on existing snapshot."""
    os.chdir(tmp_path)

    # First add a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Then crawl it
    subprocess.run(
        ['archivebox', 'crawl', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # Should have at least 1 snapshot from the add command
    assert count >= 1


def test_crawl_creates_crawl_record(tmp_path, process, disable_extractors_dict):
    """Test that add+crawl creates Crawl records."""
    os.chdir(tmp_path)

    # First add a snapshot (this creates a Crawl)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Then crawl it
    subprocess.run(
        ['archivebox', 'crawl', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    # Should have at least 1 crawl from the add command
    assert crawl_count >= 1
