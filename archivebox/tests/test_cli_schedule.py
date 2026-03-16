#!/usr/bin/env python3
"""CLI-specific tests for archivebox schedule."""

import os
import sqlite3
import subprocess

from .fixtures import process, disable_extractors_dict


def test_schedule_run_all_enqueues_scheduled_crawl(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'schedule', '--every=daily', '--depth=0', 'https://example.com'],
        capture_output=True,
        text=True,
        check=True,
    )

    result = subprocess.run(
        ['archivebox', 'schedule', '--run-all'],
        capture_output=True,
        text=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0
    assert 'Enqueued 1 scheduled crawl' in result.stdout

    conn = sqlite3.connect(tmp_path / "index.sqlite3")
    try:
        crawl_count = conn.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
        queued_count = conn.execute("SELECT COUNT(*) FROM crawls_crawl WHERE status = 'queued'").fetchone()[0]
    finally:
        conn.close()

    assert crawl_count >= 2
    assert queued_count >= 1


def test_schedule_without_import_path_creates_maintenance_schedule(tmp_path, process):
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'schedule', '--every=day'],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert 'Created scheduled maintenance update' in result.stdout

    conn = sqlite3.connect(tmp_path / "index.sqlite3")
    try:
        row = conn.execute(
            "SELECT urls, status FROM crawls_crawl ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row == ('archivebox://update', 'sealed')
