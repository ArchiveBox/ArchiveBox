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
    """Test that crawl command creates snapshots."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'crawl', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode == 0

    # Check snapshot was created
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert count == 1


def test_crawl_with_depth_0(tmp_path, process, disable_extractors_dict):
    """Test crawl with depth=0 creates single snapshot."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'crawl', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # Depth 0 should create at least 1 snapshot
    assert count >= 1


def test_crawl_creates_crawl_record(tmp_path, process, disable_extractors_dict):
    """Test that crawl creates a Crawl record."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'crawl', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    assert crawl_count >= 1
