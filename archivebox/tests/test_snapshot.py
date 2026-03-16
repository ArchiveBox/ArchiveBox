#!/usr/bin/env python3
"""Integration tests for archivebox snapshot command."""

import os
import subprocess
import sqlite3
from archivebox.machine.models import Process
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import uuid

import pytest

from .fixtures import process, disable_extractors_dict


def test_snapshot_creates_snapshot_with_correct_url(tmp_path, process, disable_extractors_dict):
    """Test that snapshot stores the exact URL in the database."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'snapshot', 'create', 'https://example.com'],
        capture_output=True,
        env={**disable_extractors_dict, 'DATA_DIR': str(tmp_path)},
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot_row = c.execute(
        "SELECT id, created_at, url, crawl_id FROM core_snapshot WHERE url = ?",
        ('https://example.com',)
    ).fetchone()
    assert snapshot_row is not None
    crawl_row = c.execute(
        "SELECT id, created_at, urls, created_by_id FROM crawls_crawl WHERE id = ?",
        (snapshot_row[3],)
    ).fetchone()
    assert crawl_row is not None
    user_row = c.execute(
        "SELECT username FROM auth_user WHERE id = ?",
        (crawl_row[3],)
    ).fetchone()
    assert user_row is not None
    conn.close()

    snapshot_id_raw, snapshot_created_at, snapshot_url, crawl_id = snapshot_row
    snapshot_id = str(uuid.UUID(snapshot_id_raw))
    crawl_id, crawl_created_at, crawl_urls, crawl_created_by_id = crawl_row
    username = user_row[0]
    crawl_date_str = datetime.fromisoformat(crawl_created_at).strftime('%Y%m%d')
    snapshot_date_str = datetime.fromisoformat(snapshot_created_at).strftime('%Y%m%d')
    domain = urlparse(snapshot_url).hostname or 'unknown'

    # Verify crawl symlink exists and is relative
    target_path = tmp_path / 'users' / username / 'snapshots' / snapshot_date_str / domain / snapshot_id
    symlinks = [
        p for p in tmp_path.rglob(str(snapshot_id))
        if p.is_symlink()
    ]
    assert symlinks, "Snapshot symlink should exist under crawl dir"
    link_path = symlinks[0]

    assert link_path.is_symlink(), "Snapshot symlink should exist under crawl dir"
    link_target = os.readlink(link_path)
    assert not os.path.isabs(link_target), "Symlink should be relative"
    assert link_path.resolve() == target_path.resolve()


def test_snapshot_multiple_urls_creates_multiple_records(tmp_path, process, disable_extractors_dict):
    """Test that multiple URLs each get their own snapshot record."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'snapshot', 'create',
         'https://example.com',
         'https://iana.org'],
        capture_output=True,
        env={**disable_extractors_dict, 'DATA_DIR': str(tmp_path)},
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    urls = c.execute("SELECT url FROM core_snapshot ORDER BY url").fetchall()
    conn.close()

    urls = [u[0] for u in urls]
    assert 'https://example.com' in urls
    assert 'https://iana.org' in urls
    assert len(urls) >= 2


def test_snapshot_tag_creates_tag_and_links_to_snapshot(tmp_path, process, disable_extractors_dict):
    """Test that --tag creates tag record and links it to the snapshot."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'snapshot', 'create', '--tag=mytesttag',
         'https://example.com'],
        capture_output=True,
        env={**disable_extractors_dict, 'DATA_DIR': str(tmp_path)},
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Verify tag was created
    tag = c.execute("SELECT id, name FROM core_tag WHERE name = ?", ('mytesttag',)).fetchone()
    assert tag is not None, "Tag 'mytesttag' should exist in core_tag"
    tag_id = tag[0]

    # Verify snapshot exists
    snapshot = c.execute("SELECT id FROM core_snapshot WHERE url = ?",
                        ('https://example.com',)).fetchone()
    assert snapshot is not None
    snapshot_id = snapshot[0]

    # Verify tag is linked to snapshot via join table
    link = c.execute("""
        SELECT * FROM core_snapshot_tags
        WHERE snapshot_id = ? AND tag_id = ?
    """, (snapshot_id, tag_id)).fetchone()
    conn.close()

    assert link is not None, "Tag should be linked to snapshot via core_snapshot_tags"


def test_snapshot_jsonl_output_has_correct_structure(tmp_path, process, disable_extractors_dict):
    """Test that JSONL output contains required fields with correct types."""
    os.chdir(tmp_path)

    # Pass URL as argument instead of stdin for more reliable behavior
    result = subprocess.run(
        ['archivebox', 'snapshot', 'create', 'https://example.com'],
        capture_output=True,
        text=True,
        env={**disable_extractors_dict, 'DATA_DIR': str(tmp_path)},
    )

    # Parse JSONL output lines
    records = Process.parse_records_from_text(result.stdout)
    snapshot_records = [r for r in records if r.get('type') == 'Snapshot']

    assert len(snapshot_records) >= 1, "Should output at least one Snapshot JSONL record"

    record = snapshot_records[0]
    assert record.get('type') == 'Snapshot'
    assert 'id' in record, "Snapshot record should have 'id' field"
    assert 'url' in record, "Snapshot record should have 'url' field"
    assert record['url'] == 'https://example.com'


def test_snapshot_with_tag_stores_tag_name(tmp_path, process, disable_extractors_dict):
    """Test that title is stored when provided via tag option."""
    os.chdir(tmp_path)

    # Use command line args instead of stdin
    subprocess.run(
        ['archivebox', 'snapshot', 'create', '--tag=customtag', 'https://example.com'],
        capture_output=True,
        text=True,
        env={**disable_extractors_dict, 'DATA_DIR': str(tmp_path)},
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Verify tag was created with correct name
    tag = c.execute("SELECT name FROM core_tag WHERE name = ?",
                   ('customtag',)).fetchone()
    conn.close()

    assert tag is not None
    assert tag[0] == 'customtag'


def test_snapshot_with_depth_sets_snapshot_depth(tmp_path, process, disable_extractors_dict):
    """Test that --depth sets snapshot depth when creating snapshots."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'snapshot', 'create', '--depth=1',
         'https://example.com'],
        capture_output=True,
        env={**disable_extractors_dict, 'DATA_DIR': str(tmp_path)},
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot = c.execute("SELECT depth FROM core_snapshot ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()

    assert snapshot is not None, "Snapshot should be created when depth is provided"
    assert snapshot[0] == 1, "Snapshot depth should match --depth value"


def test_snapshot_allows_duplicate_urls_across_crawls(tmp_path, process, disable_extractors_dict):
    """Snapshot create auto-creates a crawl per run; same URL can appear multiple times."""
    os.chdir(tmp_path)

    # Add same URL twice
    subprocess.run(
        ['archivebox', 'snapshot', 'create', 'https://example.com'],
        capture_output=True,
        env={**disable_extractors_dict, 'DATA_DIR': str(tmp_path)},
    )
    subprocess.run(
        ['archivebox', 'snapshot', 'create', 'https://example.com'],
        capture_output=True,
        env={**disable_extractors_dict, 'DATA_DIR': str(tmp_path)},
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_snapshot WHERE url = ?",
                     ('https://example.com',)).fetchone()[0]
    conn.close()

    assert count == 2, "Same URL should create separate snapshots across different crawls"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
