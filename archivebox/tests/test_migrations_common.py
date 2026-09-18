"""The same migration invariants must hold for both supported legacy schemas."""

import sqlite3

import pytest

from .migrations_helpers import (
    create_legacy_archive,
    run_archivebox_migration_cmd,
    verify_all_snapshots_in_output,
    verify_foreign_keys,
    verify_snapshot_count,
    verify_snapshot_titles,
    verify_snapshot_urls,
)


@pytest.fixture(params=("0.7", "0.8"), ids=("from-0.7", "from-0.8"))
def legacy_archive(tmp_path, request):
    return create_legacy_archive(tmp_path, request.param)


def test_migration_preserves_snapshot_count(legacy_archive):
    """Migration should preserve all snapshots."""
    work_dir, db_path, original_data = legacy_archive
    expected_count = len(original_data["snapshots"])

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_count(db_path, expected_count)
    assert ok, msg


def test_migration_preserves_snapshot_urls(legacy_archive):
    """Migration should preserve all snapshot URLs."""
    work_dir, db_path, original_data = legacy_archive
    expected_urls = [s["url"] for s in original_data["snapshots"]]

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_urls(db_path, expected_urls)
    assert ok, msg


def test_migration_preserves_snapshot_titles(legacy_archive):
    """Migration should preserve all snapshot titles."""
    work_dir, db_path, original_data = legacy_archive
    expected_titles = {s["url"]: s["title"] for s in original_data["snapshots"]}

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_snapshot_titles(db_path, expected_titles)
    assert ok, msg


def test_migration_preserves_foreign_keys(legacy_archive):
    """Migration should maintain foreign key relationships."""
    work_dir, db_path, _original_data = legacy_archive

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_foreign_keys(db_path)
    assert ok, msg


def test_status_works_after_migration(legacy_archive):
    """Status command should work after migration."""
    work_dir, _db_path, _original_data = legacy_archive

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["status"])
    assert result.returncode == 0, f"Status failed after migration: {result.stderr}"


def test_search_works_after_migration(legacy_archive):
    """Search command should find ALL migrated snapshots."""
    work_dir, _db_path, original_data = legacy_archive

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["search"])
    assert result.returncode == 0, f"Search failed after migration: {result.stderr}"

    # Verify ALL snapshots appear in output
    output = result.stdout + result.stderr
    ok, msg = verify_all_snapshots_in_output(output, original_data["snapshots"])
    assert ok, msg


def test_list_works_after_migration(legacy_archive):
    """List command should work and show ALL migrated data."""
    work_dir, _db_path, original_data = legacy_archive

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["snapshot", "list"])
    assert result.returncode == 0, f"List failed after migration: {result.stderr}"

    # Verify ALL snapshots appear in output
    output = result.stdout + result.stderr
    ok, msg = verify_all_snapshots_in_output(output, original_data["snapshots"])
    assert ok, msg


def test_version_works_after_migration(legacy_archive):
    """Version command should work after migration."""
    work_dir, _db_path, _original_data = legacy_archive

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(work_dir, ["version"])
    assert result.returncode == 0, f"Version failed after migration: {result.stderr}"

    # Should show version info
    output = result.stdout + result.stderr
    assert "ArchiveBox" in output or "version" in output.lower(), f"Version output missing expected content: {output[:500]}"


def test_no_duplicate_snapshots_after_migration(legacy_archive):
    """Migration should not create duplicate snapshots."""
    work_dir, db_path, _original_data = legacy_archive

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


def test_no_orphaned_archiveresults_after_migration(legacy_archive):
    """Migration should not leave orphaned ArchiveResults."""
    work_dir, db_path, _original_data = legacy_archive

    result = run_archivebox_migration_cmd(work_dir, ["init"], timeout=45)
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    ok, msg = verify_foreign_keys(db_path)
    assert ok, msg


def test_timestamps_preserved_after_migration(legacy_archive):
    """Migration should preserve original timestamps."""
    work_dir, db_path, original_data = legacy_archive
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


def test_tag_associations_preserved_after_migration(legacy_archive):
    """Migration should preserve snapshot-tag associations."""
    work_dir, db_path, _original_data = legacy_archive

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
