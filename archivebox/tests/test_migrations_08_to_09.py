#!/usr/bin/env python3
"""
Migration tests from 0.8.x to 0.9.x.

0.8.x introduced:
- Crawl model for grouping URLs
- Seed model (removed in 0.9.x)
- UUID primary keys for Snapshot
- Status fields for state machine
- New fields like depth, retry_at, etc.
"""

import sqlite3
import json
import uuid

import pytest

from .migrations_helpers import (
    SCHEMA_0_7,
    SCHEMA_0_8,
    seed_0_8_data,
    seed_0_7_data,
    run_archivebox_migration_cmd,
    create_data_dir_structure,
    verify_snapshot_count,
    verify_snapshot_urls,
    verify_snapshot_titles,
    verify_tag_count,
    verify_archiveresult_count,
    verify_foreign_keys,
    verify_all_snapshots_in_output,
    verify_crawl_count,
    verify_process_migration,
)


@pytest.fixture
def migration_08_data(tmp_path):
    """Create a temporary directory with 0.8.x schema and data."""
    work_dir = tmp_path
    db_path = work_dir / "index.sqlite3"

    create_data_dir_structure(work_dir)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_0_8)
    conn.close()

    original_data = seed_0_8_data(db_path)
    return work_dir, db_path, original_data


def test_migration_preserves_snapshot_count(migration_08_data):
    """Migration should preserve all snapshots from 0.8.x."""
    work_dir, db_path, original_data = migration_08_data
    expected_count = len(original_data["snapshots"])

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_count(db_path, expected_count)
    assert ok, msg


def test_migration_preserves_snapshot_urls(migration_08_data):
    """Migration should preserve all snapshot URLs from 0.8.x."""
    work_dir, db_path, original_data = migration_08_data
    expected_urls = [s["url"] for s in original_data["snapshots"]]

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_urls(db_path, expected_urls)
    assert ok, msg


def test_migration_preserves_crawls(migration_08_data):
    """Migration should preserve all Crawl records and create default crawl if needed."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Count snapshots with NULL crawl_id in original data
    snapshots_without_crawl = sum(1 for s in original_data["snapshots"] if s["crawl_id"] is None)

    # Expected count: original crawls + 1 default crawl if any snapshots had NULL crawl_id
    expected_count = len(original_data["crawls"])
    if snapshots_without_crawl > 0:
        expected_count += 1  # Migration 0024 creates a default crawl

    ok, msg = verify_crawl_count(db_path, expected_count)
    assert ok, msg


def test_migration_preserves_snapshot_crawl_links(migration_08_data):
    """Migration should preserve snapshot-to-crawl relationships and assign default crawl to orphans."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check EVERY snapshot has a crawl_id after migration
    for snapshot in original_data["snapshots"]:
        cursor.execute("SELECT crawl_id FROM core_snapshot WHERE url = ?", (snapshot["url"],))
        row = cursor.fetchone()
        assert row is not None, f"Snapshot {snapshot['url']} not found after migration"

        if snapshot["crawl_id"] is not None:
            # Snapshots that had a crawl should keep it
            assert row[0] == snapshot["crawl_id"], f"Crawl ID changed for {snapshot['url']}: expected {snapshot['crawl_id']}, got {row[0]}"
        else:
            # Snapshots without a crawl should now have one (the default crawl)
            assert row[0] is not None, f"Snapshot {snapshot['url']} should have been assigned to default crawl but has NULL"

    conn.close()


def test_migration_preserves_tags(migration_08_data):
    """Migration should preserve all tags."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_tag_count(db_path, len(original_data["tags"]))
    assert ok, msg


def test_migration_preserves_archiveresults(migration_08_data):
    """Migration should preserve ArchiveResult rows and link each one to a Process."""
    work_dir, db_path, original_data = migration_08_data
    expected_count = len(original_data["archiveresults"])
    expected_counts = {}
    for result in original_data["archiveresults"]:
        status = "succeeded" if result["status"] == "success" else result["status"]
        key = (result["extractor"], status)
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


def test_migration_preserves_archiveresult_status(migration_08_data):
    """Migration should preserve archive result status values."""
    work_dir, db_path, original_data = migration_08_data
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


def test_status_works_after_migration(migration_08_data):
    """Status command should work after migration."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["status"])
    assert result.returncode == 0, f"Status failed after migration: {result.stderr}"


def test_list_works_after_migration(migration_08_data):
    """List command should work and show ALL migrated data."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["snapshot", "list"])
    assert result.returncode == 0, f"List failed after migration: {result.stderr}"

    # Verify ALL snapshots appear in output
    output = result.stdout + result.stderr
    ok, msg = verify_all_snapshots_in_output(output, original_data["snapshots"])
    assert ok, msg


def test_search_works_after_migration(migration_08_data):
    """Search command should find ALL migrated snapshots."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["search"])
    assert result.returncode == 0, f"Search failed after migration: {result.stderr}"

    # Verify ALL snapshots appear in output
    output = result.stdout + result.stderr
    ok, msg = verify_all_snapshots_in_output(output, original_data["snapshots"])
    assert ok, msg


def test_migration_preserves_snapshot_titles(migration_08_data):
    """Migration should preserve all snapshot titles."""
    work_dir, db_path, original_data = migration_08_data
    expected_titles = {s["url"]: s["title"] for s in original_data["snapshots"]}

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_titles(db_path, expected_titles)
    assert ok, msg


def test_migration_preserves_foreign_keys(migration_08_data):
    """Migration should maintain foreign key relationships."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_foreign_keys(db_path)
    assert ok, msg


def test_migration_preserves_08_timestamp_meanings(migration_08_data):
    """0.8.x already has separated timestamp/bookmarked_at/created_at/downloaded_at fields."""
    work_dir, db_path, original_data = migration_08_data
    snapshot = original_data["snapshots"][0]
    legacy_timestamp = "1609459200.123456"
    bookmarked_at = "2021-01-01 00:00:00"
    created_at = "2024-08-28 09:40:00"
    modified_at = "2024-08-29 10:41:00"
    downloaded_at = "2024-08-30 11:42:00"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE core_snapshot
        SET timestamp = ?, bookmarked_at = ?, created_at = ?, modified_at = ?, downloaded_at = ?
        WHERE id = ?
        """,
        (legacy_timestamp, bookmarked_at, created_at, modified_at, downloaded_at, snapshot["id"]),
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
    migrated = cursor.fetchone()
    conn.close()

    assert migrated[0] == legacy_timestamp
    assert migrated[1].startswith("2021-01-01"), migrated[1]
    assert migrated[2].startswith("2024-08-28"), migrated[2]
    assert migrated[3].startswith("2024-08-29"), migrated[3]
    assert migrated[4].startswith("2024-08-30"), migrated[4]


def test_hyphenated_crawl_ids_are_normalized_before_snapshot_saves(migration_08_data):
    """0.8.x crawl UUIDs with dashes should migrate to Django's SQLite UUID format."""
    work_dir, db_path, original_data = migration_08_data
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    for crawl in original_data["crawls"]:
        hyphenated = str(uuid.UUID(hex=crawl["id"]))
        cursor.execute("UPDATE crawls_crawl SET id = ? WHERE id = ?", (hyphenated, crawl["id"]))
        cursor.execute("UPDATE core_snapshot SET crawl_id = ? WHERE crawl_id = ?", (hyphenated, crawl["id"]))
        crawl["id"] = hyphenated
    conn.commit()
    conn.close()

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM crawls_crawl WHERE id LIKE '%-%'")
    hyphenated_crawls = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM core_snapshot WHERE crawl_id LIKE '%-%'")
    hyphenated_snapshot_refs = cursor.fetchone()[0]
    conn.close()

    assert hyphenated_crawls == 0
    assert hyphenated_snapshot_refs == 0

    result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=60)
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"Update failed after migration: {result.stderr}"
    assert "FOREIGN KEY constraint failed" not in output


def test_add_works_after_migration(migration_08_data):
    """Adding new URLs should work after migration from 0.8.x."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    # Check that init actually ran and applied migrations
    assert "Applying" in result.stdout + result.stderr, (
        f"Init did not apply migrations. stdout: {result.stdout[:500]}, stderr: {result.stderr[:500]}"
    )
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Count existing crawls
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
    initial_crawl_count = cursor.fetchone()[0]
    conn.close()

    # Try to add a new URL after migration (use --index-only for speed)
    result = run_archivebox_migration_cmd(work_dir, ["add", "--index-only", "https://example.com/new-page"], timeout=45)
    assert result.returncode == 0, f"Add failed after migration: {result.stderr}"

    # Verify a new Crawl was created
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
    new_crawl_count = cursor.fetchone()[0]
    conn.close()

    assert new_crawl_count > initial_crawl_count, f"No new Crawl created when adding URL. Add stderr: {result.stderr[-500:]}"


def test_version_works_after_migration(migration_08_data):
    """Version command should work after migration."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["version"])
    assert result.returncode == 0, f"Version failed after migration: {result.stderr}"

    # Should show version info
    output = result.stdout + result.stderr
    assert "ArchiveBox" in output or "version" in output.lower(), f"Version output missing expected content: {output[:500]}"


def test_migration_creates_process_records(migration_08_data):
    """Migration should create Process records for all ArchiveResults."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Verify Process records created
    expected_count = len(original_data["archiveresults"])
    ok, msg = verify_process_migration(db_path, expected_count)
    assert ok, msg


def test_migration_creates_binary_records(migration_08_data):
    """Migration should create and link Binary/NetworkInterface records from migrated Process data."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check Binary records exist
    cursor.execute("SELECT COUNT(*) FROM machine_binary")
    binary_count = cursor.fetchone()[0]

    # Should have at least one binary per unique extractor
    extractors = {ar["extractor"] for ar in original_data["archiveresults"]}
    assert binary_count >= len(extractors), f"Expected at least {len(extractors)} Binaries, got {binary_count}"

    cursor.execute("""
        SELECT COUNT(*)
        FROM machine_process
        WHERE cmd != '[]' AND binary_id IS NULL
    """)
    missing_binary_count = cursor.fetchone()[0]
    assert missing_binary_count == 0

    cursor.execute("""
        SELECT p.cmd, b.name, b.abspath
        FROM machine_process p
        JOIN machine_binary b ON p.binary_id = b.id
        WHERE p.cmd != '[]'
    """)
    rows = cursor.fetchall()
    assert rows
    for cmd_raw, binary_name, binary_abspath in rows:
        cmd = json.loads(cmd_raw)
        assert binary_name == cmd[0]
        assert binary_abspath == cmd[0]

    cursor.execute("SELECT COUNT(*) FROM machine_process WHERE iface_id IS NULL")
    missing_iface_count = cursor.fetchone()[0]
    assert missing_iface_count == 0

    conn.close()


def test_migration_preserves_cmd_data(migration_08_data):
    """Migration should preserve cmd data in Process.cmd field."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check that Process records have cmd arrays
    cursor.execute("SELECT cmd FROM machine_process WHERE cmd != '[]'")
    cmd_records = cursor.fetchall()

    # All Processes should have non-empty cmd (test data has json.dumps([extractor, '--version']))
    expected_count = len(original_data["archiveresults"])
    assert len(cmd_records) == expected_count, f"Expected {expected_count} Processes with cmd, got {len(cmd_records)}"

    conn.close()


def test_no_duplicate_snapshots_after_migration(migration_08_data):
    """Migration should not create duplicate snapshots."""
    work_dir, db_path, original_data = migration_08_data
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


def test_no_orphaned_archiveresults_after_migration(migration_08_data):
    """Migration should not leave orphaned ArchiveResults."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_foreign_keys(db_path)
    assert ok, msg


def test_timestamps_preserved_after_migration(migration_08_data):
    """Migration should preserve original timestamps."""
    work_dir, db_path, original_data = migration_08_data
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


def test_crawl_data_preserved_after_migration(migration_08_data):
    """Migration should preserve crawl metadata (urls, label, status)."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check each crawl's data is preserved
    for crawl in original_data["crawls"]:
        cursor.execute("SELECT urls, label FROM crawls_crawl WHERE id = ?", (crawl["id"],))
        row = cursor.fetchone()
        assert row is not None, f"Crawl {crawl['id']} not found after migration"
        assert row[0] == crawl["urls"], f"URLs mismatch for crawl {crawl['id']}"
        assert row[1] == crawl["label"], f"Label mismatch for crawl {crawl['id']}"

    conn.close()


def test_tag_associations_preserved_after_migration(migration_08_data):
    """Migration should preserve snapshot-tag associations."""
    work_dir, db_path, original_data = migration_08_data
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


def test_update_migrates_db_snapshot_when_legacy_index_missing(tmp_path):
    """A legacy folder with no index file should still migrate if its timestamp exists in DB."""
    work_dir = tmp_path
    db_path = work_dir / "index.sqlite3"
    create_data_dir_structure(work_dir)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_0_7)
    conn.close()
    original_data = seed_0_7_data(db_path)
    snapshot = original_data["snapshots"][0]

    snapshot_dir = work_dir / "archive" / snapshot["timestamp"]
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "screenshot.png").write_text("existing-db-snapshot")

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=60)
    assert result.returncode == 0, f"Init failed: {result.stderr}"
    result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=120)
    assert result.returncode == 0, f"Update failed: {result.stderr}"

    migrated_files = list((work_dir / "archive" / "users").glob("*/snapshots/*/*/*/screenshot.png"))
    assert len(migrated_files) == 1
    assert migrated_files[0].read_text() == "existing-db-snapshot"
    assert not (work_dir / "invalid").exists()


def test_update_recovers_orphan_with_corrupt_index_from_archive_org_url(tmp_path):
    """A corrupt legacy index can be imported when archive.org.txt has the original URL."""
    work_dir = tmp_path
    db_path = work_dir / "index.sqlite3"
    create_data_dir_structure(work_dir)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_0_7)
    conn.close()
    seed_0_7_data(db_path)

    timestamp = "1339747993"
    original_url = "http://www.wired.com/wiredenterprise/2012/01/seamicro-and-google/all/1"
    snapshot_dir = work_dir / "archive" / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.json").write_text("")
    (snapshot_dir / "archive.org.txt").write_text(f"https://web.archive.org/web/20170531210128/{original_url}\n")
    (snapshot_dir / "output.pdf").write_text("orphan-output")

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=60)
    assert result.returncode == 0, f"Init failed: {result.stderr}"
    result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=120)
    assert result.returncode == 0, f"Update failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT url, timestamp FROM core_snapshot WHERE timestamp = ?", (timestamp,))
    row = cursor.fetchone()
    conn.close()

    assert row == (original_url, timestamp)
    migrated_files = list((work_dir / "archive" / "users").glob("*/snapshots/*/*/*/output.pdf"))
    assert len(migrated_files) == 1
    assert migrated_files[0].read_text() == "orphan-output"
    assert not (work_dir / "invalid").exists()


def test_update_preserves_legacy_folder_timestamp_over_index_float_variant(tmp_path):
    """Legacy folder timestamp is the on-disk identity even if index.json has a .0 variant."""
    work_dir = tmp_path
    db_path = work_dir / "index.sqlite3"
    create_data_dir_structure(work_dir)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_0_7)
    conn.close()
    seed_0_7_data(db_path)

    timestamp = "1508259732"
    url = "https://example.com/folder-timestamp"
    snapshot_dir = work_dir / "archive" / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / "index.json").write_text(
        json.dumps(
            {
                "url": url,
                "timestamp": "1508259732.0",
                "title": "Folder Timestamp",
            },
        ),
    )
    (snapshot_dir / "output.html").write_text("folder timestamp output")

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=60)
    assert result.returncode == 0, f"Init failed: {result.stderr}"
    result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=120)
    assert result.returncode == 0, f"Update failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM core_snapshot WHERE url = ?", (url,))
    row = cursor.fetchone()
    conn.close()

    assert row == (timestamp,)
    assert (work_dir / "archive" / timestamp).is_symlink()
    assert not (work_dir / "archive" / f"{timestamp}.0").exists()
    assert not (work_dir / "invalid").exists()


def test_update_preserves_distinct_legacy_dirs_with_integer_and_float_timestamps(tmp_path):
    """Sibling legacy dirs like 1508259732 and 1508259732.0 must not fuzzy-merge."""
    work_dir = tmp_path
    db_path = work_dir / "index.sqlite3"
    create_data_dir_structure(work_dir)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_0_7)
    conn.close()
    seed_0_7_data(db_path)

    url = "https://example.com/duplicate-timestamp"
    for timestamp, payload in [("1508259732.0", "float-dir"), ("1508259732", "int-dir")]:
        snapshot_dir = work_dir / "archive" / timestamp
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / "index.json").write_text(
            json.dumps(
                {
                    "url": url,
                    "timestamp": timestamp,
                    "title": payload,
                },
            ),
        )
        (snapshot_dir / f"{payload}.txt").write_text(payload)

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=60)
    assert result.returncode == 0, f"Init failed: {result.stderr}"
    result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=120)
    assert result.returncode == 0, f"Update failed: {result.stderr}"

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp FROM core_snapshot WHERE url = ? ORDER BY timestamp", (url,))
    rows = cursor.fetchall()
    conn.close()

    assert rows == [("1508259732",), ("1508259732.0",)]
    assert (work_dir / "archive" / "1508259732").is_symlink()
    assert (work_dir / "archive" / "1508259732.0").is_symlink()
    assert not (work_dir / "invalid").exists()


def test_update_preserves_legacy_plugin_directory_without_output_files(migration_08_data):
    """Legacy plugin files must survive while empty output_files metadata is hydrated."""
    work_dir, db_path, original_data = migration_08_data
    snapshot = original_data["snapshots"][0]
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE core_archiveresult SET extractor = 'media', output = 'media/' WHERE snapshot_id = ? AND extractor = 'singlefile'",
        (snapshot["id"],),
    )
    conn.commit()
    conn.close()

    legacy_output = work_dir / "archive" / snapshot["timestamp"] / "media" / "track.info.json"
    legacy_output.parent.mkdir(parents=True, exist_ok=True)
    legacy_output.write_text('{"title": "legacy media payload"}')

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=60)
    assert result.returncode == 0, f"Init failed: {result.stderr}"
    result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=120)
    assert result.returncode == 0, f"Update failed: {result.stderr}"

    migrated_outputs = list((work_dir / "archive" / "users").glob("*/snapshots/*/*/*/media/track.info.json"))
    assert len(migrated_outputs) == 1
    assert migrated_outputs[0].read_text() == '{"title": "legacy media payload"}'

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT output_files FROM core_archiveresult WHERE snapshot_id = ? AND plugin = 'media'",
        (snapshot["id"],),
    ).fetchone()
    conn.close()
    assert row is not None
    assert "track.info.json" in json.loads(row[0])


def test_archiveresult_files_preserved_after_migration(tmp_path):
    """
    Test that ArchiveResult output files are reorganized into new structure.

    This test verifies that:
    1. Migration preserves ArchiveResult data in Process/Binary records
    2. Running `archivebox update` reorganizes files into new structure
    3. New structure: archive/users/username/snapshots/YYYYMMDD/example.com/snap-uuid-here/output.ext
    4. All files are moved (no data loss)
    5. Old archive/timestamp/ directories are cleaned up
    """
    work_dir = tmp_path
    db_path = work_dir / "index.sqlite3"
    create_data_dir_structure(work_dir)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_0_7)
    conn.close()
    original_data = seed_0_7_data(db_path)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    for i, snapshot in enumerate(original_data["snapshots"]):
        legacy_timestamp = "1609459200.123456" if i == 0 else str(1704110400 + (i * 86400))
        cursor.execute(
            "UPDATE core_snapshot SET timestamp = ? WHERE id = ?",
            (legacy_timestamp, snapshot["id"]),
        )
        cursor.execute(
            "UPDATE core_archiveresult SET pwd = ? WHERE snapshot_id = ?",
            (f"/data/archive/{legacy_timestamp}", snapshot["id"]),
        )
        snapshot["timestamp"] = legacy_timestamp
    conn.commit()
    conn.close()

    sample_files = [
        "favicon.ico",
        "screenshot.png",
        "singlefile.html",
        "headers.json",
    ]
    for snapshot in original_data["snapshots"]:
        snapshot_dir = work_dir / "archive" / snapshot["timestamp"]
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / "index.json").write_text(
            json.dumps(
                {
                    "url": snapshot["url"],
                    "timestamp": snapshot["timestamp"],
                    "title": snapshot["title"],
                },
            ),
        )
        for sample_file in sample_files:
            (snapshot_dir / sample_file).write_text(f"{snapshot['url']}::{sample_file}")

    # Count archive directories and files BEFORE migration
    archive_dir = work_dir / "archive"
    dirs_before = [d for d in archive_dir.glob("*") if d.name.replace(".", "").isdigit()] if archive_dir.exists() else []
    dirs_before_count = len([d for d in dirs_before if d.is_dir()])

    # Count total files in all archive directories
    files_before = []
    for d in dirs_before:
        if d.is_dir():
            files_before.extend([f for f in d.rglob("*") if f.is_file()])
    files_before_count = len(files_before)
    generated_metadata_names = {"index.html", "index.json", "index.jsonl"}
    generated_search_backends = {"search_backend_sqlite", "search_backend_sonic"}

    def is_generated_file(path) -> bool:
        return path.name in generated_metadata_names or any(part in generated_search_backends for part in path.parts)

    original_payloads = sorted(path.read_text() for path in files_before if not is_generated_file(path))

    # Sample some specific files to check they're preserved
    sample_paths_before = {}
    for d in dirs_before:
        if d.is_dir():
            for sample_file in sample_files:
                matching = list(d.glob(sample_file))
                if matching:
                    sample_paths_before[f"{d.name}/{sample_file}"] = matching[0]

    print(f"\n[*] Archive directories before migration: {dirs_before_count}")
    print(f"[*] Total files before migration: {files_before_count}")
    print(f"[*] Sample files found: {len(sample_paths_before)}")

    # Run init to trigger migration
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=60)
    assert result.returncode == 0, f"Init (migration) failed: {result.stderr}"

    # Count archive directories and files AFTER migration
    dirs_after = [d for d in archive_dir.glob("*") if d.name.replace(".", "").isdigit()] if archive_dir.exists() else []
    dirs_after_count = len([d for d in dirs_after if d.is_dir()])

    files_after = []
    for d in dirs_after:
        if d.is_dir():
            files_after.extend([f for f in d.rglob("*") if f.is_file()])
    files_after_count = len(files_after)

    # Verify sample files still exist
    sample_paths_after = {}
    for d in dirs_after:
        if d.is_dir():
            for sample_file in sample_files:
                matching = list(d.glob(sample_file))
                if matching:
                    sample_paths_after[f"{d.name}/{sample_file}"] = matching[0]

    print(f"[*] Archive directories after migration: {dirs_after_count}")
    print(f"[*] Total files after migration: {files_after_count}")
    print(f"[*] Sample files found: {len(sample_paths_after)}")

    # Verify files still in old structure after migration (not moved yet)
    assert dirs_before_count == dirs_after_count, f"Archive directories lost during migration: {dirs_before_count} -> {dirs_after_count}"
    assert files_before_count == files_after_count, f"Files lost during migration: {files_before_count} -> {files_after_count}"

    # Run update to trigger filesystem reorganization
    print("\n[*] Running archivebox update to reorganize filesystem...")
    result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=120)
    assert result.returncode == 0, f"Update failed: {result.stderr}"

    # Check new filesystem structure
    # New structure: archive/users/username/snapshots/YYYYMMDD/example.com/snap-uuid-here/output.ext
    users_dir = work_dir / "archive" / "users"
    snapshots_base = None

    if users_dir.exists():
        # Find the snapshots directory
        for user_dir in users_dir.iterdir():
            if user_dir.is_dir():
                user_snapshots = user_dir / "snapshots"
                if user_snapshots.exists():
                    snapshots_base = user_snapshots
                    break

    print(f"[*] New structure base: {snapshots_base}")

    # Count files in new structure
    # Structure: archive/users/{username}/snapshots/YYYYMMDD/{domain}/{uuid}/files...
    files_new_structure = []
    new_sample_files = {}

    if snapshots_base and snapshots_base.exists():
        for date_dir in snapshots_base.iterdir():
            if date_dir.is_dir():
                for domain_dir in date_dir.iterdir():
                    if domain_dir.is_dir():
                        for snap_dir in domain_dir.iterdir():
                            if snap_dir.is_dir():
                                # Files are directly in snap-uuid/ directory (no plugin subdirs)
                                for f in snap_dir.rglob("*"):
                                    if f.is_file():
                                        files_new_structure.append(f)
                                        # Track sample files
                                        if f.name in sample_files:
                                            new_sample_files[f"{snap_dir.name}/{f.name}"] = f

    files_new_count = len(files_new_structure)
    print(f"[*] Files in new structure: {files_new_count}")
    print(f"[*] Sample files in new structure: {len(new_sample_files)}")

    migrated_2021_files = list(users_dir.glob("*/snapshots/20210101/*/*/favicon.ico"))
    assert len(migrated_2021_files) > 0, "Legacy snapshot should be bucketed by normalized bookmarked_at, not created_at/import time"

    crawl_snapshot_links = list(users_dir.glob("*/crawls/*/*/*/snapshots/*/*"))
    crawl_snapshot_symlinks = [path for path in crawl_snapshot_links if path.is_symlink()]
    crawl_dirs = list(users_dir.glob("*/crawls/*/*/*"))
    print(f"[*] Crawl snapshot symlinks: {len(crawl_snapshot_symlinks)}")

    # Check old structure (should be gone or empty)
    old_archive_dir = work_dir / "archive"
    old_files_remaining = []
    unmigrated_dirs = []
    if old_archive_dir.exists():
        for d in old_archive_dir.glob("*"):
            # Only count REAL directories, not symlinks (symlinks are the migrated ones)
            if d.is_dir(follow_symlinks=False) and d.name.replace(".", "").isdigit():
                # This is a timestamp directory (old structure)
                files_in_dir = [f for f in d.rglob("*") if f.is_file()]
                if files_in_dir:
                    unmigrated_dirs.append((d.name, len(files_in_dir)))
                    old_files_remaining.extend(files_in_dir)

    old_files_count = len(old_files_remaining)
    print(f"[*] Files remaining in old structure: {old_files_count}")
    if unmigrated_dirs:
        print(f"[*] Unmigrated directories: {unmigrated_dirs}")

    # CRITICAL: Verify files were moved to new structure
    assert files_new_count > 0, "No files found in new structure after update"

    assert len(crawl_snapshot_symlinks) > 0, "No crawl snapshot symlinks created for migrated snapshots"

    assert not any((crawl_dir / "index.jsonl").exists() for crawl_dir in crawl_dirs), (
        "Migrated crawl dirs should match normal 0.9 crawl dirs and not add crawl index.jsonl files"
    )

    # CRITICAL: Verify old structure is cleaned up
    assert old_files_count == 0, f"Old structure not cleaned up: {old_files_count} files still in archive/timestamp/ directories"

    # CRITICAL: Verify all original payload files were moved. The 0.9 lazy
    # maintenance pass also writes fresh index.jsonl/index.html metadata from
    # the hydrated DB row, so raw file counts are allowed to increase; compare
    # the legacy payload contents after excluding those generated metadata
    # files to keep the no-data-loss assertion strict.
    migrated_payloads = sorted(path.read_text() for path in [*files_new_structure, *old_files_remaining] if not is_generated_file(path))
    assert original_payloads == migrated_payloads, "Legacy payload files changed or were lost during reorganization"
    assert files_new_count >= files_before_count, "New 0.9 metadata should not replace legacy payload files"

    # CRITICAL: Verify sample files exist in new structure
    assert len(new_sample_files) > 0, "Sample files not found in new structure"

    # Verify new path format
    for path_key, file_path in new_sample_files.items():
        # Path should contain: snapshots/YYYYMMDD/domain/snap-uuid/plugin/file
        path_parts = file_path.parts
        assert "snapshots" in path_parts, f"New path should contain 'snapshots': {file_path}"
        assert "users" in path_parts, f"New path should contain 'users': {file_path}"
        print(f"    ✓ {path_key} → {file_path.relative_to(work_dir)}")

    # Verify Process and Binary records were created
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM core_archiveresult")
    archiveresult_count = cursor.fetchone()[0]

    original_plugins = sorted({row["extractor"] for row in original_data["archiveresults"]})
    cursor.execute(
        f"SELECT COUNT(*) FROM core_archiveresult WHERE plugin IN ({','.join('?' for _ in original_plugins)})",
        original_plugins,
    )
    legacy_archiveresult_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM machine_process")
    process_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM machine_binary")
    binary_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM core_archiveresult WHERE process_id IS NOT NULL")
    linked_count = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM core_archiveresult WHERE plugin IN ({','.join('?' for _ in original_plugins)}) AND process_id IS NOT NULL",
        original_plugins,
    )
    legacy_linked_count = cursor.fetchone()[0]

    conn.close()

    print(f"[*] ArchiveResults: {archiveresult_count}")
    print(f"[*] Process records created: {process_count}")
    print(f"[*] Binary records created: {binary_count}")
    print(f"[*] ArchiveResults linked to Process: {linked_count}")

    # Verify data migration happened correctly. A full `archivebox update` may
    # add new maintenance ArchiveResults (e.g. search index backfills), so keep
    # the strict preservation assertion scoped to the legacy extractor plugins
    # that came from the old DB rows.
    assert archiveresult_count >= len(original_data["archiveresults"]), "Full update should not delete ArchiveResult rows"
    assert legacy_archiveresult_count == len(original_data["archiveresults"]), (
        f"Expected {len(original_data['archiveresults'])} migrated legacy ArchiveResults, got {legacy_archiveresult_count}"
    )

    # Each legacy ArchiveResult should create one linked Process record. The
    # command/worker rows created by `archivebox update` itself can increase the
    # total process count, but they must not replace or orphan migrated process
    # metadata.
    assert process_count >= len(original_data["archiveresults"]), (
        f"Expected at least {len(original_data['archiveresults'])} Process records, got {process_count}"
    )

    assert binary_count == 5, f"Expected 5 unique Binary records, got {binary_count}"

    # ALL legacy ArchiveResults should be linked to Process records
    assert linked_count >= len(original_data["archiveresults"]), "Full update should not unlink migrated ArchiveResult processes"
    assert legacy_linked_count == len(original_data["archiveresults"]), (
        f"Expected all {len(original_data['archiveresults'])} legacy ArchiveResults linked to Process, got {legacy_linked_count}"
    )
