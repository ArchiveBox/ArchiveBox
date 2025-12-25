#!/usr/bin/env python3
"""Integration tests for archivebox snapshot command."""

import os
import subprocess
import sqlite3
import json

import pytest

from .fixtures import process, disable_extractors_dict


def test_snapshot_creates_snapshot_with_correct_url(tmp_path, process, disable_extractors_dict):
    """Test that snapshot stores the exact URL in the database."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'snapshot', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    result = c.execute("SELECT url FROM core_snapshot WHERE url = ?",
                       ('https://example.com',)).fetchone()
    conn.close()

    assert result is not None
    assert result[0] == 'https://example.com'


def test_snapshot_multiple_urls_creates_multiple_records(tmp_path, process, disable_extractors_dict):
    """Test that multiple URLs each get their own snapshot record."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'snapshot',
         'https://example.com',
         'https://iana.org'],
        capture_output=True,
        env=disable_extractors_dict,
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
        ['archivebox', 'snapshot', '--tag=mytesttag',
         'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
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
        ['archivebox', 'snapshot', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    # Parse JSONL output lines
    snapshot_records = []
    for line in result.stdout.strip().split('\n'):
        if line:
            try:
                record = json.loads(line)
                if record.get('type') == 'Snapshot':
                    snapshot_records.append(record)
            except json.JSONDecodeError:
                continue

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
        ['archivebox', 'snapshot', '--tag=customtag', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Verify tag was created with correct name
    tag = c.execute("SELECT name FROM core_tag WHERE name = ?",
                   ('customtag',)).fetchone()
    conn.close()

    assert tag is not None
    assert tag[0] == 'customtag'


def test_snapshot_with_depth_creates_crawl_object(tmp_path, process, disable_extractors_dict):
    """Test that --depth > 0 creates a Crawl object with correct max_depth."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'snapshot', '--depth=1',
         'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    crawl = c.execute("SELECT max_depth FROM crawls_crawl ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()

    assert crawl is not None, "Crawl object should be created when depth > 0"
    assert crawl[0] == 1, "Crawl max_depth should match --depth value"


def test_snapshot_deduplicates_urls(tmp_path, process, disable_extractors_dict):
    """Test that adding the same URL twice doesn't create duplicate snapshots."""
    os.chdir(tmp_path)

    # Add same URL twice
    subprocess.run(
        ['archivebox', 'snapshot', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )
    subprocess.run(
        ['archivebox', 'snapshot', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM core_snapshot WHERE url = ?",
                     ('https://example.com',)).fetchone()[0]
    conn.close()

    assert count == 1, "Same URL should not create duplicate snapshots"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
