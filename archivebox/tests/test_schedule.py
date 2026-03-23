#!/usr/bin/env python3
"""Integration tests for the database-backed archivebox schedule command."""

import os
import sqlite3
import subprocess

import pytest


def _fetchone(tmp_path, query):
    conn = sqlite3.connect(tmp_path / "index.sqlite3")
    try:
        return conn.execute(query).fetchone()
    finally:
        conn.close()


def test_schedule_creates_enabled_db_schedule(tmp_path, process):
    os.chdir(tmp_path)

    result = subprocess.run(
        ["archivebox", "schedule", "--every=daily", "--depth=1", "https://example.com/feed.xml"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    schedule_row = _fetchone(
        tmp_path,
        "SELECT schedule, is_enabled, label FROM crawls_crawlschedule ORDER BY created_at DESC LIMIT 1",
    )
    crawl_row = _fetchone(
        tmp_path,
        "SELECT urls, status, max_depth FROM crawls_crawl ORDER BY created_at DESC LIMIT 1",
    )

    assert schedule_row == ("daily", 1, "Scheduled import: https://example.com/feed.xml")
    assert crawl_row == ("https://example.com/feed.xml", "sealed", 1)


def test_schedule_show_lists_enabled_schedules(tmp_path, process):
    os.chdir(tmp_path)

    subprocess.run(
        ["archivebox", "schedule", "--every=weekly", "https://example.com/feed.xml"],
        capture_output=True,
        text=True,
        check=True,
    )

    result = subprocess.run(
        ["archivebox", "schedule", "--show"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Active scheduled crawls" in result.stdout
    assert "https://example.com/feed.xml" in result.stdout
    assert "weekly" in result.stdout


def test_schedule_clear_disables_existing_schedules(tmp_path, process):
    os.chdir(tmp_path)

    subprocess.run(
        ["archivebox", "schedule", "--every=daily", "https://example.com/feed.xml"],
        capture_output=True,
        text=True,
        check=True,
    )

    result = subprocess.run(
        ["archivebox", "schedule", "--clear"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Disabled 1 scheduled crawl" in result.stdout

    disabled_count = _fetchone(
        tmp_path,
        "SELECT COUNT(*) FROM crawls_crawlschedule WHERE is_enabled = 0",
    )[0]
    enabled_count = _fetchone(
        tmp_path,
        "SELECT COUNT(*) FROM crawls_crawlschedule WHERE is_enabled = 1",
    )[0]

    assert disabled_count == 1
    assert enabled_count == 0


def test_schedule_every_requires_valid_period(tmp_path, process):
    os.chdir(tmp_path)

    result = subprocess.run(
        ["archivebox", "schedule", "--every=invalid_period", "https://example.com/feed.xml"],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Invalid schedule" in result.stderr or "Invalid schedule" in result.stdout


class TestScheduleCLI:
    def test_cli_help(self, tmp_path, process):
        os.chdir(tmp_path)

        result = subprocess.run(
            ["archivebox", "schedule", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "--every" in result.stdout
        assert "--show" in result.stdout
        assert "--clear" in result.stdout
        assert "--run-all" in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
