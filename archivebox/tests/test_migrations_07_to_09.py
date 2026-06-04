#!/usr/bin/env python3
"""
Migration tests from 0.7.x to 0.9.x.

0.7.x schema includes:
- Tag model with ManyToMany to Snapshot
- ArchiveResult model with ForeignKey to Snapshot
- AutoField primary keys
"""

import sqlite3

import pytest

from .migrations_helpers import (
    SCHEMA_0_7,
    create_data_dir_structure,
    run_archivebox_migration_cmd,
    seed_0_7_data,
    verify_all_snapshots_in_output,
    verify_archiveresult_count,
    verify_foreign_keys,
    verify_snapshot_count,
    verify_snapshot_titles,
    verify_snapshot_urls,
    verify_tag_count,
)


@pytest.fixture
def archive_07(tmp_path):
    """Create a temporary directory with 0.7.x schema and data."""
    db_path = tmp_path / "index.sqlite3"

    # Create directory structure
    create_data_dir_structure(tmp_path)

    # Create database with 0.7.x schema
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_0_7)
    conn.close()

    # Seed with test data
    original_data = seed_0_7_data(db_path)

    return tmp_path, db_path, original_data


def test_migration_preserves_snapshot_count(archive_07):
    """Migration should preserve all snapshots."""
    work_dir, db_path, original_data = archive_07
    expected_count = len(original_data["snapshots"])

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_count(db_path, expected_count)
    assert ok, msg


def test_migration_preserves_snapshot_urls(archive_07):
    """Migration should preserve all snapshot URLs."""
    work_dir, db_path, original_data = archive_07
    expected_urls = [s["url"] for s in original_data["snapshots"]]

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_urls(db_path, expected_urls)
    assert ok, msg


def test_migration_preserves_snapshot_titles(archive_07):
    """Migration should preserve all snapshot titles."""
    work_dir, db_path, original_data = archive_07
    expected_titles = {s["url"]: s["title"] for s in original_data["snapshots"]}

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_titles(db_path, expected_titles)
    assert ok, msg


def test_migration_preserves_tags(archive_07):
    """Migration should preserve all tags."""
    work_dir, db_path, original_data = archive_07
    expected_count = len(original_data["tags"])

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_tag_count(db_path, expected_count)
    assert ok, msg


def test_migration_preserves_archiveresults(archive_07):
    """Migration should preserve ArchiveResult rows and link each one to a Process."""
    work_dir, db_path, original_data = archive_07
    expected_count = len(original_data["archiveresults"])
    expected_counts = {}
    for result in original_data["archiveresults"]:
        key = (result["extractor"], result["status"])
        expected_counts[key] = expected_counts.get(key, 0) + 1

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_archiveresult_count(db_path, expected_count)
    assert ok, msg

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT plugin, status, COUNT(*) FROM core_archiveresult GROUP BY plugin, status")
    migrated_counts = {(plugin, status): count for plugin, status, count in cursor.fetchall()}
    cursor.execute("SELECT COUNT(*) FROM core_archiveresult WHERE process_id IS NULL")
    missing_process_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM machine_process")
    process_count = cursor.fetchone()[0]
    conn.close()

    assert migrated_counts == expected_counts
    assert missing_process_count == 0
    assert process_count == expected_count


def test_migration_preserves_foreign_keys(archive_07):
    """Migration should maintain foreign key relationships."""
    work_dir, db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_foreign_keys(db_path)
    assert ok, msg


def test_migration_preserves_legacy_timestamp_meanings(archive_07):
    """0.7.x timestamp is bookmark identity; added is row creation; updated is downloaded."""
    work_dir, db_path, original_data = archive_07
    snapshot = original_data["snapshots"][0]
    legacy_bookmark_ts = "1609459200.123456"
    legacy_added = "2024-08-28 09:40:00"
    legacy_updated = "2024-08-29 10:41:00"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE core_snapshot
        SET timestamp = ?, added = ?, updated = ?
        WHERE id = ?
        """,
        (legacy_bookmark_ts, legacy_added, legacy_updated, snapshot["id"]),
    )
    conn.commit()
    conn.close()

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timestamp, bookmarked_at, created_at, modified_at, downloaded_at FROM core_snapshot WHERE id = ?",
        (snapshot["id"],),
    )
    timestamp, bookmarked_at, created_at, modified_at, downloaded_at = cursor.fetchone()
    conn.close()

    assert timestamp == legacy_bookmark_ts
    assert bookmarked_at.startswith("2021-01-01"), bookmarked_at
    assert created_at.startswith("2024-08-28"), created_at
    assert modified_at.startswith("2024-08-29"), modified_at
    assert downloaded_at.startswith("2024-08-29"), downloaded_at


def test_update_saves_migrated_snapshots_without_foreign_key_errors(archive_07):
    """Migrated 0.7.x snapshots should be writable through the current ORM."""
    work_dir, _db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=60)
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"Update failed after migration: {result.stderr}"
    assert "FOREIGN KEY constraint failed" not in output
    assert "Skipping snapshot" not in output


def test_status_works_after_migration(archive_07):
    """Status command should work after migration."""
    work_dir, _db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["status"])
    assert result.returncode == 0, f"Status failed after migration: {result.stderr}"


def test_search_works_after_migration(archive_07):
    """Search command should find ALL migrated snapshots."""
    work_dir, _db_path, original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["search"])
    assert result.returncode == 0, f"Search failed after migration: {result.stderr}"

    # Verify ALL snapshots appear in output
    output = result.stdout + result.stderr
    ok, msg = verify_all_snapshots_in_output(output, original_data["snapshots"])
    assert ok, msg


def test_list_works_after_migration(archive_07):
    """List command should work and show ALL migrated data."""
    work_dir, _db_path, original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["snapshot", "list"])
    assert result.returncode == 0, f"List failed after migration: {result.stderr}"

    # Verify ALL snapshots appear in output
    output = result.stdout + result.stderr
    ok, msg = verify_all_snapshots_in_output(output, original_data["snapshots"])
    assert ok, msg


def test_new_schema_elements_created_after_migration(archive_07):
    """Migration should create new 0.9.x schema elements (crawls_crawl, etc.)."""
    work_dir, db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check that new tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    conn.close()

    # 0.9.x should have crawls_crawl table
    assert "crawls_crawl" in tables, "crawls_crawl table not created during migration"


def test_snapshots_have_new_fields_after_migration(archive_07):
    """Migrated snapshots should have new 0.9.x fields (status, depth, etc.)."""
    work_dir, db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check snapshot table has new columns
    cursor.execute("PRAGMA table_info(core_snapshot)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()

    # 0.9.x snapshots should have status, depth, created_at, modified_at
    required_new_columns = {"status", "depth", "created_at", "modified_at"}
    for col in required_new_columns:
        assert col in columns, f"Snapshot missing new column: {col}"


def test_add_works_after_migration(archive_07):
    """Adding new URLs should work after migration from 0.7.x."""
    work_dir, db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Verify that init created the crawls_crawl table before proceeding
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='crawls_crawl'")
    table_exists = cursor.fetchone() is not None
    conn.close()
    assert table_exists, f"Init failed to create crawls_crawl table. Init stderr: {result.stderr[-500:]}"

    # Try to add a new URL after migration (use --bg for speed)
    result = run_archivebox_migration_cmd(work_dir, ["add", "--bg", "https://example.com/new-page"], timeout=45)
    assert result.returncode == 0, f"Add failed after migration: {result.stderr}"

    # Verify a Crawl was created for the new URL
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
    crawl_count = cursor.fetchone()[0]
    conn.close()

    assert crawl_count >= 1, f"No Crawl created when adding URL. Add stderr: {result.stderr[-500:]}"


def test_archiveresult_status_preserved_after_migration(archive_07):
    """Migration should preserve archive result status values."""
    work_dir, db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Get status counts
    cursor.execute("SELECT status, COUNT(*) FROM core_archiveresult GROUP BY status")
    status_counts = dict(cursor.fetchall())
    conn.close()

    # Original data has known status distribution: succeeded, failed, skipped
    assert "succeeded" in status_counts, "Should have succeeded results"
    assert "failed" in status_counts, "Should have failed results"
    assert "skipped" in status_counts, "Should have skipped results"


def test_version_works_after_migration(archive_07):
    """Version command should work after migration."""
    work_dir, _db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["version"])
    assert result.returncode == 0, f"Version failed after migration: {result.stderr}"

    # Should show version info
    output = result.stdout + result.stderr
    assert "ArchiveBox" in output or "version" in output.lower(), f"Version output missing expected content: {output[:500]}"


def test_help_works_after_migration(archive_07):
    """Help command should work after migration."""
    work_dir, _db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["help"])
    assert result.returncode == 0, f"Help failed after migration: {result.stderr}"

    # Should show available commands
    output = result.stdout + result.stderr
    assert "add" in output.lower() and "status" in output.lower(), f"Help output missing expected commands: {output[:500]}"


def test_no_duplicate_snapshots_after_migration(archive_07):
    """Migration should not create duplicate snapshots."""
    work_dir, db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Check for duplicate URLs
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("""
        SELECT url, COUNT(*) as cnt FROM core_snapshot
        GROUP BY url HAVING cnt > 1
    """)
    duplicates = cursor.fetchall()
    conn.close()

    assert len(duplicates) == 0, f"Found duplicate URLs: {duplicates}"


def test_no_orphaned_archiveresults_after_migration(archive_07):
    """Migration should not leave orphaned ArchiveResults."""
    work_dir, db_path, _original_data = archive_07

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_foreign_keys(db_path)
    assert ok, msg


def test_timestamps_preserved_after_migration(archive_07):
    """Migration should preserve original timestamps."""
    work_dir, db_path, original_data = archive_07
    original_timestamps = {s["url"]: s["timestamp"] for s in original_data["snapshots"]}

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT url, timestamp FROM core_snapshot")
    migrated_timestamps = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    for url, original_ts in original_timestamps.items():
        assert migrated_timestamps.get(url) == original_ts, f"Timestamp changed for {url}: {original_ts} -> {migrated_timestamps.get(url)}"


def test_tag_associations_preserved_after_migration(archive_07):
    """Migration should preserve snapshot-tag associations."""
    work_dir, db_path, _original_data = archive_07

    # Count tag associations before migration
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM core_snapshot_tags")
    original_count = cursor.fetchone()[0]
    conn.close()

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Count tag associations after migration
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM core_snapshot_tags")
    migrated_count = cursor.fetchone()[0]
    conn.close()

    assert migrated_count == original_count, f"Tag associations changed: {original_count} -> {migrated_count}"
