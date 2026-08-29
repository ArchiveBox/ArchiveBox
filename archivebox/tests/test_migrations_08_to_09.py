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
from datetime import datetime
from urllib.parse import urlparse

import pytest

from .migrations_helpers import (
    SCHEMA_0_7,
    SCHEMA_0_8,
    current_snapshot_dir,
    filesystem_manifest,
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
    verify_preserved_rows,
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


def convert_legacy_tags_to_uuid(conn: sqlite3.Connection) -> None:
    """Reproduce the alternate UUID-tag schema shipped by later 0.8 betas."""
    tags = conn.execute("SELECT id, name, slug, created_at, modified_at, created_by_id FROM core_tag ORDER BY id").fetchall()
    snapshot_tags = conn.execute("SELECT id, snapshot_id, tag_id FROM core_snapshot_tags ORDER BY id").fetchall()
    id_map = {tag[0]: uuid.uuid4().hex for tag in tags}
    conn.executescript(
        """
        ALTER TABLE core_tag RENAME TO core_tag_integer;
        ALTER TABLE core_snapshot_tags RENAME TO core_snapshot_tags_integer;
        CREATE TABLE core_tag (
            id CHAR(36) PRIMARY KEY, name VARCHAR(100) NOT NULL UNIQUE, slug VARCHAR(100) NOT NULL UNIQUE,
            created_at DATETIME, modified_at DATETIME, created_by_id INTEGER REFERENCES auth_user(id)
        );
        CREATE TABLE core_snapshot_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id CHAR(36) NOT NULL REFERENCES core_snapshot(id),
            tag_id CHAR(36) NOT NULL REFERENCES core_tag(id),
            UNIQUE(snapshot_id, tag_id)
        );
        """,
    )
    conn.executemany(
        "INSERT INTO core_tag (id, name, slug, created_at, modified_at, created_by_id) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (id_map[tag_id], name, slug, created_at, modified_at, created_by_id)
            for tag_id, name, slug, created_at, modified_at, created_by_id in tags
        ],
    )
    conn.executemany(
        "INSERT INTO core_snapshot_tags (id, snapshot_id, tag_id) VALUES (?, ?, ?)",
        [(row_id, snapshot_id, id_map[tag_id]) for row_id, snapshot_id, tag_id in snapshot_tags],
    )
    conn.executescript("DROP TABLE core_snapshot_tags_integer; DROP TABLE core_tag_integer;")


@pytest.mark.parametrize("uuid_tags", (False, True), ids=("integer-tags", "uuid-tags"))
def test_migration_preserves_extended_08_metadata(migration_08_data, uuid_tags):
    work_dir, db_path, original_data = migration_08_data
    snapshot = original_data["snapshots"][1]
    parent = original_data["snapshots"][0]
    archiveresult = next(row for row in original_data["archiveresults"] if row["snapshot_id"] == snapshot["id"])
    tag = original_data["tags"][0]
    user_id = original_data["users"][0]["id"]
    metadata = {
        "depth": 7,
        "config": {"USER_AGENT": "legacy-agent", "SAVE_SCREENSHOT": False},
        "notes": "legacy snapshot notes",
        "num_uses_failed": 11,
        "num_uses_succeeded": 23,
        "current_step": 6,
        "fs_version": "0.8.5",
    }
    tag_metadata = ("2020-01-02 03:04:05", "2021-06-07 08:09:10", user_id)

    with sqlite3.connect(db_path) as conn:
        conn.execute("ALTER TABLE core_snapshot ADD COLUMN parent_snapshot_id CHAR(36) REFERENCES core_snapshot(id)")
        conn.execute("ALTER TABLE core_snapshot ADD COLUMN current_step INTEGER NOT NULL DEFAULT 0")
        conn.execute("ALTER TABLE core_snapshot ADD COLUMN fs_version VARCHAR(10) NOT NULL DEFAULT '0.8.0'")
        conn.execute(
            """
            UPDATE core_snapshot
            SET depth = ?, config = ?, notes = ?, num_uses_failed = ?, num_uses_succeeded = ?,
                parent_snapshot_id = ?, current_step = ?, fs_version = ?
            WHERE id = ?
            """,
            (
                metadata["depth"],
                json.dumps(metadata["config"]),
                metadata["notes"],
                metadata["num_uses_failed"],
                metadata["num_uses_succeeded"],
                parent["id"],
                metadata["current_step"],
                metadata["fs_version"],
                snapshot["id"],
            ),
        )
        conn.execute("UPDATE core_archiveresult SET notes = 'legacy archive result notes' WHERE uuid = ?", (archiveresult["uuid"],))
        conn.execute(
            "UPDATE core_tag SET created_at = ?, modified_at = ?, created_by_id = ? WHERE id = ?",
            (*tag_metadata, tag["id"]),
        )
        if uuid_tags:
            convert_legacy_tags_to_uuid(conn)
        expected_counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("core_snapshot", "core_archiveresult", "core_tag", "core_snapshot_tags")
        }

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=90)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    with sqlite3.connect(db_path) as conn:
        snapshot_row = conn.execute(
            """
            SELECT depth, config, notes, num_uses_failed, num_uses_succeeded,
                   parent_snapshot_id, current_step, fs_version
            FROM core_snapshot WHERE id = ?
            """,
            (snapshot["id"],),
        ).fetchone()
        result_notes = conn.execute(
            "SELECT notes FROM core_archiveresult WHERE id = REPLACE(?, '-', '')",
            (archiveresult["uuid"],),
        ).fetchone()
        migrated_tag = conn.execute(
            "SELECT created_at, modified_at, created_by_id FROM core_tag WHERE name = ?",
            (tag["name"],),
        ).fetchone()
        migrated_counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in expected_counts}

    assert json.loads(snapshot_row[1]) | metadata["config"] == json.loads(snapshot_row[1])
    assert (snapshot_row[0], *snapshot_row[2:]) == (
        metadata["depth"],
        metadata["notes"],
        metadata["num_uses_failed"],
        metadata["num_uses_succeeded"],
        parent["id"],
        metadata["current_step"],
        metadata["fs_version"],
    )
    assert result_notes == ("legacy archive result notes",)
    assert migrated_tag == tag_metadata
    assert migrated_counts == expected_counts


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


def test_migration_preserves_users_groups_permissions_api_secrets_and_repeated_init(migration_08_data):
    work_dir, db_path, original_data = migration_08_data

    for init_number in (1, 2):
        result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=90)
        assert result.returncode == 0, f"Init {init_number} failed: {result.stderr}"
        verify_preserved_rows(db_path, original_data["preserved_rows"])


def test_process_metadata_migration_rolls_back_completely_on_malformed_row(migration_08_data):
    work_dir, db_path, original_data = migration_08_data
    malformed_uuid = original_data["archiveresults"][0]["uuid"]

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE core_archiveresult SET cmd = '[]', cmd_version = 'broken-version' WHERE uuid = ?",
            (malformed_uuid,),
        )
        source_rows = conn.execute(
            "SELECT uuid, cmd, pwd, cmd_version FROM core_archiveresult ORDER BY uuid",
        ).fetchall()

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=90)
    assert result.returncode != 0
    assert "has cmd_version metadata but no command" in result.stdout + result.stderr

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(core_archiveresult)")}
        current_rows = conn.execute(
            "SELECT uuid, cmd, pwd, cmd_version FROM core_archiveresult ORDER BY uuid",
        ).fetchall()
        assert {"cmd", "pwd", "cmd_version"} <= columns
        assert current_rows == source_rows
        assert conn.execute("SELECT COUNT(*) FROM machine_process").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM machine_binary").fetchone()[0] == 0


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


@pytest.mark.parametrize("has_snapshot_status", (True, False), ids=("with-status", "without-status"))
def test_migration_preserves_08_timestamp_meanings(migration_08_data, has_snapshot_status):
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
    if not has_snapshot_status:
        cursor.execute("ALTER TABLE core_snapshot DROP COLUMN status")
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
        "SELECT timestamp, bookmarked_at, created_at, modified_at, downloaded_at, status FROM core_snapshot WHERE id = ?",
        (snapshot["id"],),
    )
    migrated = cursor.fetchone()
    conn.close()

    assert migrated[0] == legacy_timestamp
    assert migrated[1].startswith("2021-01-01"), migrated[1]
    assert migrated[2].startswith("2024-08-28"), migrated[2]
    assert migrated[3].startswith("2024-08-29"), migrated[3]
    assert migrated[4].startswith("2024-08-30"), migrated[4]
    assert migrated[5] == "sealed"


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
        cursor.execute("SELECT urls, label, status FROM crawls_crawl WHERE id = ?", (crawl["id"],))
        row = cursor.fetchone()
        assert row is not None, f"Crawl {crawl['id']} not found after migration"
        assert row[0] == crawl["urls"], f"URLs mismatch for crawl {crawl['id']}"
        assert row[1] == crawl["label"], f"Label mismatch for crawl {crawl['id']}"
        assert row[2] == crawl["status"], f"Status mismatch for crawl {crawl['id']}"

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
    for pass_number in (1, 2):
        result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=120)
        assert result.returncode == 0, f"Update pass {pass_number} failed: {result.stderr}"

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
    assert not (work_dir / "archive" / timestamp).exists()
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
    assert not (work_dir / "archive" / "1508259732").exists()
    assert not (work_dir / "archive" / "1508259732.0").exists()
    assert not (work_dir / "invalid").exists()


def test_update_preserves_legacy_plugin_directory_without_output_files(migration_08_data):
    """Duplicate empty rows must not delete shared log-only plugin outputs."""
    work_dir, db_path, original_data = migration_08_data
    snapshot = original_data["snapshots"][0]
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE core_archiveresult SET extractor = 'media', output = '' WHERE snapshot_id = ? AND extractor = 'singlefile'",
        (snapshot["id"],),
    )
    conn.execute(
        """
        INSERT INTO core_archiveresult (
            uuid, created_by_id, created_at, modified_at, snapshot_id, extractor,
            pwd, cmd, cmd_version, output, start_ts, end_ts, status, retry_at,
            notes, output_dir, iface_id, config, num_uses_failed, num_uses_succeeded
        )
        SELECT lower(hex(randomblob(16))), created_by_id, created_at, modified_at,
            snapshot_id, extractor, pwd, cmd, cmd_version, output, start_ts,
            end_ts, status, retry_at, notes, output_dir, iface_id, config,
            num_uses_failed, num_uses_succeeded
        FROM core_archiveresult
        WHERE snapshot_id = ? AND extractor = 'media'
        """,
        (snapshot["id"],),
    )
    conn.commit()
    conn.close()

    legacy_output = work_dir / "archive" / snapshot["timestamp"] / "media" / "stderr.log"
    legacy_output.parent.mkdir(parents=True, exist_ok=True)
    legacy_output.write_text("legacy diagnostic output")
    (legacy_output.parent / "empty" / "nested").mkdir(parents=True)

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=60)
    assert result.returncode == 0, f"Init failed: {result.stderr}"
    for pass_number in (1, 2):
        result = run_archivebox_migration_cmd(work_dir, ["update"], timeout=120)
        assert result.returncode == 0, f"Update pass {pass_number} failed: {result.stderr}"

    migrated_outputs = list((work_dir / "archive" / "users").glob("*/snapshots/*/*/*/media/stderr.log"))
    assert len(migrated_outputs) == 1
    assert migrated_outputs[0].read_text() == "legacy diagnostic output"
    assert (migrated_outputs[0].parent / "empty" / "nested").is_dir()

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT output_str, output_files, hook_name FROM core_archiveresult WHERE snapshot_id = ? AND plugin = 'media'",
        (snapshot["id"],),
    ).fetchall()
    conn.close()
    assert rows == [("", "{}", "")]


def test_07_filesystem_hop_preserves_complete_output_tree(tmp_path):
    """Validate the public init/update path, including the merge fallback and retry."""
    db_path = tmp_path / "index.sqlite3"
    create_data_dir_structure(tmp_path)
    loose_archive_file = tmp_path / "archive" / ".DS_Store"
    loose_archive_file.write_bytes(b"legacy archive root metadata\x00\xff")
    loose_archive_file_manifest = filesystem_manifest(tmp_path / "archive")[".DS_Store"]
    with sqlite3.connect(db_path) as connection:
        connection.executescript(SCHEMA_0_7)
    original = seed_0_7_data(db_path)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE core_archiveresult SET output = 'Legacy Title Only' WHERE snapshot_id = ? AND extractor = 'title'",
            (original["snapshots"][0]["id"],),
        )
        original_results = connection.execute(
            """
            SELECT snapshot_id, extractor, status, output, start_ts, end_ts
            FROM core_archiveresult
            ORDER BY snapshot_id, extractor, start_ts
            """,
        ).fetchall()

    output_payloads = {
        "favicon.ico": b"\x00\x00\x01\x00legacy icon",
        "screenshot.png": b"\x89PNG\r\n\x1a\nlegacy screenshot",
        "singlefile.html": b"<html><body>legacy singlefile</body></html>",
        "wget/example.com/index.html": b"<html><body>legacy wget</body></html>",
    }
    original_trees = {}
    for index, snapshot in enumerate(original["snapshots"]):
        snapshot_dir = tmp_path / "archive" / snapshot["timestamp"]
        snapshot_dir.mkdir(parents=True)
        for relative_path, payload in output_payloads.items():
            output_path = snapshot_dir / relative_path
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(payload + snapshot["url"].encode())
        legacy_index = {
            "url": snapshot["url"],
            "timestamp": snapshot["timestamp"],
            "title": snapshot["title"],
            "sources": ["sources/legacy-import.txt"],
            "history": {},
            "custom_legacy_metadata": {"must": "survive"},
        }
        (snapshot_dir / "index.json").write_text(json.dumps(legacy_index, indent=2, sort_keys=True))
        if index == 0:
            unknown_dir = snapshot_dir / "unknown-plugin" / "duplicate-output"
            unknown_dir.mkdir(parents=True)
            (unknown_dir / "payload.bin").write_bytes(b"unknown payload\x00\xff")
            (unknown_dir / "payload-link").symlink_to("payload.bin")
            (snapshot_dir / "unknown-empty-dir" / "nested").mkdir(parents=True)
        original_trees[snapshot["timestamp"]] = filesystem_manifest(snapshot_dir)

    result = run_archivebox_migration_cmd(tmp_path, ["init"], timeout=90)
    assert result.returncode == 0, result.stderr

    first_snapshot = original["snapshots"][0]
    with sqlite3.connect(db_path) as connection:
        username, bookmarked_at, snapshot_id, url = connection.execute(
            """
            SELECT u.username, s.bookmarked_at, s.id, s.url
            FROM core_snapshot s
            JOIN crawls_crawl c ON c.id = s.crawl_id
            JOIN auth_user u ON u.id = c.created_by_id
            WHERE s.id = ?
            """,
            (first_snapshot["id"],),
        ).fetchone()

    date_bucket = datetime.fromisoformat(bookmarked_at).strftime("%Y%m%d")
    destination = tmp_path / "archive" / "users" / username / "snapshots" / date_bucket / urlparse(url).hostname / snapshot_id
    partial_unknown = destination / "unknown-plugin" / "duplicate-output"
    partial_unknown.mkdir(parents=True)
    (partial_unknown / "payload.bin").write_bytes(b"unknown payload\x00\xff")
    (partial_unknown / "payload-link").symlink_to("payload.bin")
    (destination / "preexisting-output.bin").write_bytes(b"destination-only output")

    for pass_number in (1, 2):
        result = run_archivebox_migration_cmd(tmp_path, ["update", "--migrate-only"], timeout=180)
        assert result.returncode == 0, f"Update pass {pass_number} failed: {result.stderr}"

    assert loose_archive_file.is_file()
    assert filesystem_manifest(tmp_path / "archive")[".DS_Store"] == loose_archive_file_manifest

    for timestamp, expected_tree in original_trees.items():
        legacy_dir = tmp_path / "archive" / timestamp
        assert not legacy_dir.exists()
        migrated_tree = filesystem_manifest(current_snapshot_dir(tmp_path, db_path, timestamp))
        assert {path: migrated_tree.get(path) for path in expected_tree} == expected_tree
    assert (destination / "preexisting-output.bin").read_bytes() == b"destination-only output"

    with sqlite3.connect(db_path) as connection:
        migrated_results = connection.execute(
            """
            SELECT snapshot_id, plugin, status, output_str, start_ts, end_ts
            FROM core_archiveresult
            WHERE hook_name = ''
            ORDER BY snapshot_id, plugin, start_ts
            """,
        ).fetchall()
        assert migrated_results == original_results
        assert connection.execute(
            "SELECT COUNT(*) FROM core_archiveresult WHERE hook_name = '' AND process_id IS NOT NULL",
        ).fetchone()[0] == len(original_results)
        assert connection.execute(
            "SELECT output_str FROM core_archiveresult WHERE plugin = 'title' AND hook_name = '' ORDER BY start_ts LIMIT 1",
        ).fetchone() == ("Legacy Title Only",)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    crawl_snapshot_links = list((tmp_path / "archive" / "users").glob("*/crawls/*/*/*/snapshots/*/*"))
    assert crawl_snapshot_links
    assert all(path.is_symlink() for path in crawl_snapshot_links)


@pytest.mark.parametrize("fs_version", ("0.7.0", "0.8.0", "0.8.5", "0.9.0", "0.9.1", "0.9.2", "0.9.3"))
def test_each_declared_filesystem_hop_preserves_outputs(migration_08_data, fs_version):
    """Every declared source version must migrate through the public update command."""
    work_dir, db_path, original_data = migration_08_data
    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=90)
    assert result.returncode == 0, result.stderr

    snapshot = original_data["snapshots"][0]
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE core_snapshot SET fs_version = ? WHERE id = ?", (fs_version, snapshot["id"]))
        username, bookmarked_at = connection.execute(
            """
            SELECT u.username, s.bookmarked_at
            FROM core_snapshot s
            JOIN crawls_crawl c ON c.id = s.crawl_id
            JOIN auth_user u ON u.id = c.created_by_id
            WHERE s.id = ?
            """,
            (snapshot["id"],),
        ).fetchone()

    if fs_version in ("0.7.0", "0.8.0", "0.8.5"):
        source_dir = work_dir / "archive" / snapshot["timestamp"]
    else:
        source_dir = (
            work_dir
            / "archive"
            / "users"
            / username
            / "snapshots"
            / datetime.fromisoformat(bookmarked_at).strftime("%Y%m%d")
            / urlparse(snapshot["url"]).hostname
            / snapshot["id"]
        )

    output = source_dir / "unknown-plugin" / "payload.bin"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"migration payload\x00\xff")
    (output.parent / "payload-link").symlink_to("payload.bin")
    (source_dir / "unknown-empty-dir" / "nested").mkdir(parents=True)
    expected_tree = filesystem_manifest(source_dir)

    result = run_archivebox_migration_cmd(work_dir, ["update", "--migrate-only"], timeout=180)
    assert result.returncode == 0, result.stderr

    migrated_dir = current_snapshot_dir(work_dir, db_path, snapshot["timestamp"])
    assert {path: filesystem_manifest(migrated_dir).get(path) for path in expected_tree} == expected_tree
    if fs_version in ("0.7.0", "0.8.0", "0.8.5"):
        assert not source_dir.exists()
        assert not source_dir.is_symlink()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT fs_version FROM core_snapshot WHERE id = ?", (snapshot["id"],)).fetchone() == ("0.9.4",)
