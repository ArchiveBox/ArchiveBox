#!/usr/bin/env python3
"""
Tests for archivebox list command.
Verify list emits snapshot JSONL and applies the documented filters.
"""

import json
import os
import sqlite3
import subprocess


def _parse_jsonl(stdout: str) -> list[dict]:
    return [
        json.loads(line)
        for line in stdout.splitlines()
        if line.strip().startswith('{')
    ]


def test_list_outputs_existing_snapshots_as_jsonl(tmp_path, process, disable_extractors_dict):
    """Test that list prints one JSON object per stored snapshot."""
    os.chdir(tmp_path)
    for url in ['https://example.com', 'https://iana.org']:
        subprocess.run(
            ['archivebox', 'add', '--index-only', '--depth=0', url],
            capture_output=True,
            env=disable_extractors_dict,
            check=True,
        )

    result = subprocess.run(
        ['archivebox', 'list'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    rows = _parse_jsonl(result.stdout)
    urls = {row['url'] for row in rows}

    assert result.returncode == 0, result.stderr
    assert 'https://example.com' in urls
    assert 'https://iana.org' in urls


def test_list_filters_by_url_icontains(tmp_path, process, disable_extractors_dict):
    """Test that list --url__icontains returns only matching snapshots."""
    os.chdir(tmp_path)
    for url in ['https://example.com', 'https://iana.org']:
        subprocess.run(
            ['archivebox', 'add', '--index-only', '--depth=0', url],
            capture_output=True,
            env=disable_extractors_dict,
            check=True,
        )

    result = subprocess.run(
        ['archivebox', 'list', '--url__icontains', 'example.com'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    rows = _parse_jsonl(result.stdout)
    assert result.returncode == 0, result.stderr
    assert len(rows) == 1
    assert rows[0]['url'] == 'https://example.com'


def test_list_filters_by_crawl_id_and_limit(tmp_path, process, disable_extractors_dict):
    """Test that crawl-id and limit filters constrain the result set."""
    os.chdir(tmp_path)
    for url in ['https://example.com', 'https://iana.org']:
        subprocess.run(
            ['archivebox', 'add', '--index-only', '--depth=0', url],
            capture_output=True,
            env=disable_extractors_dict,
            check=True,
        )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    crawl_id = str(c.execute(
        "SELECT crawl_id FROM core_snapshot WHERE url = ?",
        ('https://example.com',),
    ).fetchone()[0])
    conn.close()

    result = subprocess.run(
        ['archivebox', 'list', '--crawl-id', crawl_id, '--limit', '1'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    rows = _parse_jsonl(result.stdout)
    assert result.returncode == 0, result.stderr
    assert len(rows) == 1
    assert rows[0]['crawl_id'].replace('-', '') == crawl_id.replace('-', '')
    assert rows[0]['url'] == 'https://example.com'


def test_list_filters_by_status(tmp_path, process, disable_extractors_dict):
    """Test that list can filter using the current snapshot status."""
    os.chdir(tmp_path)
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        check=True,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    status = c.execute("SELECT status FROM core_snapshot LIMIT 1").fetchone()[0]
    conn.close()

    result = subprocess.run(
        ['archivebox', 'list', '--status', status],
        capture_output=True,
        text=True,
        timeout=30,
    )

    rows = _parse_jsonl(result.stdout)
    assert result.returncode == 0, result.stderr
    assert len(rows) == 1
    assert rows[0]['status'] == status


def test_list_help_lists_filter_options(tmp_path, process):
    """Test that list --help documents the supported filter flags."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'list', '--help'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert '--url__icontains' in result.stdout
    assert '--crawl-id' in result.stdout
    assert '--limit' in result.stdout
