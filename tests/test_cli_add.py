#!/usr/bin/env python3
"""
Comprehensive tests for archivebox add command.
Verify add creates snapshots in DB, crawls, source files, and archive directories.
"""

import os
import subprocess
import sqlite3
from pathlib import Path

from .fixtures import *


def test_add_single_url_creates_snapshot_in_db(tmp_path, process, disable_extractors_dict):
    """Test that adding a single URL creates a snapshot in the database."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshots = c.execute("SELECT url FROM core_snapshot").fetchall()
    conn.close()

    assert len(snapshots) == 1
    assert snapshots[0][0] == 'https://example.com'


def test_add_creates_crawl_record(tmp_path, process, disable_extractors_dict):
    """Test that add command creates a Crawl record in the database."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    assert crawl_count == 1


def test_add_creates_source_file(tmp_path, process, disable_extractors_dict):
    """Test that add creates a source file with the URL."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    sources_dir = tmp_path / "sources"
    assert sources_dir.exists()

    source_files = list(sources_dir.glob("*cli_add.txt"))
    assert len(source_files) >= 1

    source_content = source_files[0].read_text()
    assert "https://example.com" in source_content


def test_add_multiple_urls_single_command(tmp_path, process, disable_extractors_dict):
    """Test adding multiple URLs in a single command."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com', 'https://example.org'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    urls = c.execute("SELECT url FROM core_snapshot ORDER BY url").fetchall()
    conn.close()

    assert snapshot_count == 2
    assert urls[0][0] == 'https://example.com'
    assert urls[1][0] == 'https://example.org'


def test_add_from_file(tmp_path, process, disable_extractors_dict):
    """Test adding URLs from a file.

    With --index-only, this creates a snapshot for the file itself, not the URLs inside.
    To get snapshots for the URLs inside, you need to run without --index-only so parsers run.
    """
    os.chdir(tmp_path)

    # Create a file with URLs
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.com\nhttps://example.org\n")

    result = subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', str(urls_file)],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # With --index-only, creates 1 snapshot for the file itself
    assert crawl_count == 1
    assert snapshot_count == 1


def test_add_with_depth_0_flag(tmp_path, process, disable_extractors_dict):
    """Test that --depth=0 flag is accepted and works."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0
    assert 'unrecognized arguments: --depth' not in result.stderr.decode('utf-8')


def test_add_with_depth_1_flag(tmp_path, process, disable_extractors_dict):
    """Test that --depth=1 flag is accepted."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=1', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0
    assert 'unrecognized arguments: --depth' not in result.stderr.decode('utf-8')


def test_add_with_tags(tmp_path, process, disable_extractors_dict):
    """Test adding URL with tags stores tags_str in crawl.

    With --index-only, Tag objects are not created until archiving happens.
    Tags are stored as a string in the Crawl.tags_str field.
    """
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', '--tag=test,example', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    tags_str = c.execute("SELECT tags_str FROM crawls_crawl").fetchone()[0]
    conn.close()

    # Tags are stored as a comma-separated string in crawl
    assert 'test' in tags_str or 'example' in tags_str


def test_add_duplicate_url_creates_separate_crawls(tmp_path, process, disable_extractors_dict):
    """Test that adding the same URL twice creates separate crawls and snapshots.

    Each 'add' command creates a new Crawl. Multiple crawls can archive the same URL.
    This allows re-archiving URLs at different times.
    """
    os.chdir(tmp_path)

    # Add URL first time
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Add same URL second time
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot WHERE url='https://example.com'").fetchone()[0]
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    # Each add creates a new crawl with its own snapshot
    assert crawl_count == 2
    assert snapshot_count == 2


def test_add_with_overwrite_flag(tmp_path, process, disable_extractors_dict):
    """Test that --overwrite flag forces re-archiving."""
    os.chdir(tmp_path)

    # Add URL first time
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Add with overwrite
    result = subprocess.run(
        ['archivebox', 'add', '--index-only', '--overwrite', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0
    assert 'unrecognized arguments: --overwrite' not in result.stderr.decode('utf-8')


def test_add_creates_archive_subdirectory(tmp_path, process, disable_extractors_dict):
    """Test that add creates archive subdirectory for the snapshot.

    Archive subdirectories are named by timestamp, not by snapshot ID.
    """
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Get the snapshot timestamp from the database
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    timestamp = c.execute("SELECT timestamp FROM core_snapshot").fetchone()[0]
    conn.close()

    # Check that archive subdirectory was created using timestamp
    archive_dir = tmp_path / "archive" / str(timestamp)
    assert archive_dir.exists()
    assert archive_dir.is_dir()


def test_add_index_only_skips_extraction(tmp_path, process, disable_extractors_dict):
    """Test that --index-only flag skips extraction (fast)."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,  # Should be fast
    )

    assert result.returncode == 0

    # Snapshot should exist but archive results should be minimal
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert snapshot_count == 1


def test_add_links_snapshot_to_crawl(tmp_path, process, disable_extractors_dict):
    """Test that add links the snapshot to the crawl via crawl_id."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Get crawl id
    crawl_id = c.execute("SELECT id FROM crawls_crawl").fetchone()[0]

    # Get snapshot's crawl_id
    snapshot_crawl = c.execute("SELECT crawl_id FROM core_snapshot").fetchone()[0]

    conn.close()

    assert snapshot_crawl == crawl_id


def test_add_sets_snapshot_timestamp(tmp_path, process, disable_extractors_dict):
    """Test that add sets a timestamp on the snapshot."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    timestamp = c.execute("SELECT timestamp FROM core_snapshot").fetchone()[0]
    conn.close()

    assert timestamp is not None
    assert len(str(timestamp)) > 0
