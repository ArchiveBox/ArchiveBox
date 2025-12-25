#!/usr/bin/env python3
"""Integration tests for archivebox crawl command."""

import os
import subprocess
import sqlite3
import json

import pytest

from .fixtures import process, disable_extractors_dict


def test_crawl_creates_crawl_object(tmp_path, process, disable_extractors_dict):
    """Test that crawl command creates a Crawl object."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'crawl', '--no-wait', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    crawl = c.execute("SELECT id, max_depth FROM crawls_crawl ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()

    assert crawl is not None, "Crawl object should be created"


def test_crawl_depth_sets_max_depth_in_crawl(tmp_path, process, disable_extractors_dict):
    """Test that --depth option sets max_depth in the Crawl object."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'crawl', '--depth=2', '--no-wait', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    crawl = c.execute("SELECT max_depth FROM crawls_crawl ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()

    assert crawl is not None
    assert crawl[0] == 2, "Crawl max_depth should match --depth=2"


def test_crawl_creates_snapshot_for_url(tmp_path, process, disable_extractors_dict):
    """Test that crawl creates a Snapshot for the input URL."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'crawl', '--no-wait', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot = c.execute("SELECT url FROM core_snapshot WHERE url = ?",
                        ('https://example.com',)).fetchone()
    conn.close()

    assert snapshot is not None, "Snapshot should be created for input URL"


def test_crawl_links_snapshot_to_crawl(tmp_path, process, disable_extractors_dict):
    """Test that Snapshot is linked to Crawl via crawl_id."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'crawl', '--no-wait', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()

    # Get the crawl ID
    crawl = c.execute("SELECT id FROM crawls_crawl ORDER BY created_at DESC LIMIT 1").fetchone()
    assert crawl is not None
    crawl_id = crawl[0]

    # Check snapshot has correct crawl_id
    snapshot = c.execute("SELECT crawl_id FROM core_snapshot WHERE url = ?",
                        ('https://example.com',)).fetchone()
    conn.close()

    assert snapshot is not None
    assert snapshot[0] == crawl_id, "Snapshot should be linked to Crawl"


def test_crawl_multiple_urls_creates_multiple_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that crawling multiple URLs creates multiple snapshots."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'crawl', '--no-wait',
         'https://example.com',
         'https://iana.org'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    urls = c.execute("SELECT url FROM core_snapshot ORDER BY url").fetchall()
    conn.close()

    urls = [u[0] for u in urls]
    assert 'https://example.com' in urls
    assert 'https://iana.org' in urls


def test_crawl_from_file_creates_snapshot(tmp_path, process, disable_extractors_dict):
    """Test that crawl can create snapshots from a file of URLs."""
    os.chdir(tmp_path)

    # Write URLs to a file
    urls_file = tmp_path / 'urls.txt'
    urls_file.write_text('https://example.com\n')

    subprocess.run(
        ['archivebox', 'crawl', '--no-wait', str(urls_file)],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    snapshot = c.execute("SELECT url FROM core_snapshot").fetchone()
    conn.close()

    # Should create at least one snapshot (the source file or the URL)
    assert snapshot is not None, "Should create at least one snapshot"


def test_crawl_creates_seed_for_input(tmp_path, process, disable_extractors_dict):
    """Test that crawl creates a Seed object for input."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'crawl', '--no-wait', 'https://example.com'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect('index.sqlite3')
    c = conn.cursor()
    seed = c.execute("SELECT id FROM crawls_seed").fetchone()
    conn.close()

    assert seed is not None, "Seed should be created for crawl input"


class TestCrawlCLI:
    """Test the CLI interface for crawl command."""

    def test_cli_help(self, tmp_path, process):
        """Test that --help works for crawl command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'crawl', '--help'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '--depth' in result.stdout or '-d' in result.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
