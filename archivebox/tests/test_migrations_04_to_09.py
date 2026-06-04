#!/usr/bin/env python3
"""
Migration tests from 0.4.x to 0.9.x.

0.4.x was the first Django-powered version with a simpler schema:
- No Tag model (tags stored as comma-separated string in Snapshot)
- No ArchiveResult model (results stored in JSON files)
"""

import sqlite3

import pytest

from .migrations_helpers import (
    SCHEMA_0_4,
    create_data_dir_structure,
    run_archivebox_migration_cmd,
    seed_0_4_data,
    verify_snapshot_count,
    verify_snapshot_urls,
    verify_tag_count,
)


@pytest.fixture
def archive_04(tmp_path):
    """Create a temporary directory with 0.4.x schema and data."""
    db_path = tmp_path / "index.sqlite3"

    # Create directory structure
    create_data_dir_structure(tmp_path)

    # Create database with 0.4.x schema
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_0_4)
    conn.close()

    # Seed with test data
    original_data = seed_0_4_data(db_path)

    return tmp_path, db_path, original_data


def test_migration_preserves_snapshot_count(archive_04):
    """Migration should preserve all snapshots from 0.4.x."""
    work_dir, db_path, original_data = archive_04
    expected_count = len(original_data["snapshots"])

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_count(db_path, expected_count)
    assert ok, msg


def test_migration_preserves_snapshot_urls(archive_04):
    """Migration should preserve all snapshot URLs from 0.4.x."""
    work_dir, db_path, original_data = archive_04
    expected_urls = [s["url"] for s in original_data["snapshots"]]

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_urls(db_path, expected_urls)
    assert ok, msg


def test_migration_converts_string_tags_to_model(archive_04):
    """Migration should convert comma-separated tags to Tag model instances."""
    work_dir, db_path, original_data = archive_04

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Collect unique tags from original data
    original_tags = set()
    for tags_str in original_data["tags_str"]:
        if tags_str:
            for tag in tags_str.split(","):
                original_tags.add(tag.strip())

    # Tags should have been created
    ok, msg = verify_tag_count(db_path, len(original_tags))
    assert ok, msg


def test_migration_preserves_snapshot_titles(archive_04):
    """Migration should preserve all snapshot titles."""
    work_dir, db_path, original_data = archive_04

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT url, title FROM core_snapshot")
    actual = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    for snapshot in original_data["snapshots"]:
        assert actual.get(snapshot["url"]) == snapshot["title"], f"Title mismatch for {snapshot['url']}"


def test_status_works_after_migration(archive_04):
    """Status command should work after migration."""
    work_dir, _db_path, _original_data = archive_04

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["status"])
    assert result.returncode == 0, f"Status failed after migration: {result.stderr}"


def test_list_works_after_migration(archive_04):
    """List command should work and show ALL migrated snapshots."""
    work_dir, _db_path, original_data = archive_04

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["list"])
    assert result.returncode == 0, f"List failed after migration: {result.stderr}"

    # Verify ALL snapshots appear in output
    output = result.stdout + result.stderr
    for snapshot in original_data["snapshots"]:
        url_fragment = snapshot["url"][:30]
        assert url_fragment in output, f"Snapshot {snapshot['url']} not found in list output"


def test_add_works_after_migration(archive_04):
    """Adding new URLs should work after migration from 0.4.x."""
    work_dir, db_path, _original_data = archive_04

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Try to add a new URL after migration
    result = run_archivebox_migration_cmd(work_dir, ["add", "--bg", "https://example.com/new-page"], timeout=45)
    assert result.returncode == 0, f"Add failed after migration: {result.stderr}"
    result = run_archivebox_migration_cmd(work_dir, ["run"], timeout=90)
    assert result.returncode == 0, f"Run failed after migration: {result.stderr}"

    # Verify add queued the new crawl after migration.
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM crawls_crawl WHERE urls LIKE '%example.com/new-page%'")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1, "New crawl was not created after migration"


def test_new_schema_elements_created(archive_04):
    """Migration should create new 0.9.x schema elements."""
    work_dir, db_path, _original_data = archive_04

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    # New tables should exist
    assert "crawls_crawl" in tables, "crawls_crawl table not created"
    assert "core_tag" in tables, "core_tag table not created"
    assert "core_archiveresult" in tables, "core_archiveresult table not created"


def test_snapshots_have_new_fields(archive_04):
    """Migrated snapshots should have new 0.9.x fields."""
    work_dir, db_path, _original_data = archive_04

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(core_snapshot)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    required_columns = {"status", "depth", "created_at", "modified_at"}
    for col in required_columns:
        assert col in columns, f"Snapshot missing new column: {col}"
