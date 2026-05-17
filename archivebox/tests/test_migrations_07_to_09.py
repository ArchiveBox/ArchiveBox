#!/usr/bin/env python3
"""
Migration tests from 0.7.x to 0.9.x.

0.7.x schema includes:
- Tag model with ManyToMany to Snapshot
- ArchiveResult model with ForeignKey to Snapshot
- AutoField primary keys
"""

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from .migrations_helpers import (
    SCHEMA_0_7,
    seed_0_7_data,
    run_archivebox,
    create_data_dir_structure,
    verify_snapshot_count,
    verify_snapshot_urls,
    verify_snapshot_titles,
    verify_tag_count,
    verify_archiveresult_count,
    verify_foreign_keys,
    verify_all_snapshots_in_output,
)


class TestMigrationFrom07x(unittest.TestCase):
    """Test migration from 0.7.x schema to latest."""

    def setUp(self):
        """Create a temporary directory with 0.7.x schema and data."""
        self.work_dir = Path(tempfile.mkdtemp())
        self.db_path = self.work_dir / "index.sqlite3"

        # Create directory structure
        create_data_dir_structure(self.work_dir)

        # Create database with 0.7.x schema
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA_0_7)
        conn.close()

        # Seed with test data
        self.original_data = seed_0_7_data(self.db_path)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_migration_preserves_snapshot_count(self):
        """Migration should preserve all snapshots."""
        expected_count = len(self.original_data["snapshots"])

        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_snapshot_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_urls(self):
        """Migration should preserve all snapshot URLs."""
        expected_urls = [s["url"] for s in self.original_data["snapshots"]]

        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_snapshot_urls(self.db_path, expected_urls)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_titles(self):
        """Migration should preserve all snapshot titles."""
        expected_titles = {s["url"]: s["title"] for s in self.original_data["snapshots"]}

        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_snapshot_titles(self.db_path, expected_titles)
        self.assertTrue(ok, msg)

    def test_migration_preserves_tags(self):
        """Migration should preserve all tags."""
        expected_count = len(self.original_data["tags"])

        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_tag_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_archiveresults(self):
        """Migration should preserve ArchiveResult rows and link each one to a Process."""
        expected_count = len(self.original_data["archiveresults"])
        expected_counts = {}
        for result in self.original_data["archiveresults"]:
            key = (result["extractor"], result["status"])
            expected_counts[key] = expected_counts.get(key, 0) + 1

        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_archiveresult_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT plugin, status, COUNT(*) FROM core_archiveresult GROUP BY plugin, status")
        migrated_counts = {(plugin, status): count for plugin, status, count in cursor.fetchall()}
        cursor.execute("SELECT COUNT(*) FROM core_archiveresult WHERE process_id IS NULL")
        missing_process_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM machine_process")
        process_count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(migrated_counts, expected_counts)
        self.assertEqual(missing_process_count, 0)
        self.assertEqual(process_count, expected_count)

    def test_migration_preserves_foreign_keys(self):
        """Migration should maintain foreign key relationships."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_foreign_keys(self.db_path)
        self.assertTrue(ok, msg)

    def test_migration_preserves_legacy_timestamp_meanings(self):
        """0.7.x timestamp is bookmark identity; added is row creation; updated is downloaded."""
        snapshot = self.original_data["snapshots"][0]
        legacy_bookmark_ts = "1609459200.123456"
        legacy_added = "2024-08-28 09:40:00"
        legacy_updated = "2024-08-29 10:41:00"

        conn = sqlite3.connect(str(self.db_path))
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

        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT timestamp, bookmarked_at, created_at, modified_at, downloaded_at FROM core_snapshot WHERE id = ?",
            (snapshot["id"],),
        )
        timestamp, bookmarked_at, created_at, modified_at, downloaded_at = cursor.fetchone()
        conn.close()

        self.assertEqual(timestamp, legacy_bookmark_ts)
        self.assertTrue(bookmarked_at.startswith("2021-01-01"), bookmarked_at)
        self.assertTrue(created_at.startswith("2024-08-28"), created_at)
        self.assertTrue(modified_at.startswith("2024-08-29"), modified_at)
        self.assertTrue(downloaded_at.startswith("2024-08-29"), downloaded_at)

    def test_update_saves_migrated_snapshots_without_foreign_key_errors(self):
        """Migrated 0.7.x snapshots should be writable through the current ORM."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ["update"], timeout=60)
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, f"Update failed after migration: {result.stderr}")
        self.assertNotIn("FOREIGN KEY constraint failed", output)
        self.assertNotIn("Skipping snapshot", output)

    def test_status_works_after_migration(self):
        """Status command should work after migration."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ["status"])
        self.assertEqual(result.returncode, 0, f"Status failed after migration: {result.stderr}")

    def test_search_works_after_migration(self):
        """Search command should find ALL migrated snapshots."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ["search"])
        self.assertEqual(result.returncode, 0, f"Search failed after migration: {result.stderr}")

        # Verify ALL snapshots appear in output
        output = result.stdout + result.stderr
        ok, msg = verify_all_snapshots_in_output(output, self.original_data["snapshots"])
        self.assertTrue(ok, msg)

    def test_list_works_after_migration(self):
        """List command should work and show ALL migrated data."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ["snapshot", "list"])
        self.assertEqual(result.returncode, 0, f"List failed after migration: {result.stderr}")

        # Verify ALL snapshots appear in output
        output = result.stdout + result.stderr
        ok, msg = verify_all_snapshots_in_output(output, self.original_data["snapshots"])
        self.assertTrue(ok, msg)

    def test_new_schema_elements_created_after_migration(self):
        """Migration should create new 0.9.x schema elements (crawls_crawl, etc.)."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check that new tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        # 0.9.x should have crawls_crawl table
        self.assertIn("crawls_crawl", tables, "crawls_crawl table not created during migration")

    def test_snapshots_have_new_fields_after_migration(self):
        """Migrated snapshots should have new 0.9.x fields (status, depth, etc.)."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check snapshot table has new columns
        cursor.execute("PRAGMA table_info(core_snapshot)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        # 0.9.x snapshots should have status, depth, created_at, modified_at
        required_new_columns = {"status", "depth", "created_at", "modified_at"}
        for col in required_new_columns:
            self.assertIn(col, columns, f"Snapshot missing new column: {col}")

    def test_add_works_after_migration(self):
        """Adding new URLs should work after migration from 0.7.x."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        # Verify that init created the crawls_crawl table before proceeding
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='crawls_crawl'")
        table_exists = cursor.fetchone() is not None
        conn.close()
        self.assertTrue(table_exists, f"Init failed to create crawls_crawl table. Init stderr: {result.stderr[-500:]}")

        # Try to add a new URL after migration (use --index-only for speed)
        result = run_archivebox(self.work_dir, ["add", "--index-only", "https://example.com/new-page"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Add failed after migration: {result.stderr}")

        # Verify a Crawl was created for the new URL
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
        crawl_count = cursor.fetchone()[0]
        conn.close()

        self.assertGreaterEqual(crawl_count, 1, f"No Crawl created when adding URL. Add stderr: {result.stderr[-500:]}")

    def test_archiveresult_status_preserved_after_migration(self):
        """Migration should preserve archive result status values."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Get status counts
        cursor.execute("SELECT status, COUNT(*) FROM core_archiveresult GROUP BY status")
        status_counts = dict(cursor.fetchall())
        conn.close()

        # Original data has known status distribution: succeeded, failed, skipped
        self.assertIn("succeeded", status_counts, "Should have succeeded results")
        self.assertIn("failed", status_counts, "Should have failed results")
        self.assertIn("skipped", status_counts, "Should have skipped results")

    def test_version_works_after_migration(self):
        """Version command should work after migration."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ["version"])
        self.assertEqual(result.returncode, 0, f"Version failed after migration: {result.stderr}")

        # Should show version info
        output = result.stdout + result.stderr
        self.assertTrue(
            "ArchiveBox" in output or "version" in output.lower(),
            f"Version output missing expected content: {output[:500]}",
        )

    def test_help_works_after_migration(self):
        """Help command should work after migration."""
        result = run_archivebox(self.work_dir, ["init"], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ["help"])
        self.assertEqual(result.returncode, 0, f"Help failed after migration: {result.stderr}")

        # Should show available commands
        output = result.stdout + result.stderr
        self.assertTrue(
            "add" in output.lower() and "status" in output.lower(),
            f"Help output missing expected commands: {output[:500]}",
        )


class TestMigrationDataIntegrity07x(unittest.TestCase):
    """Comprehensive data integrity tests for 0.7.x migrations."""

    def test_no_duplicate_snapshots_after_migration(self):
        """Migration should not create duplicate snapshots."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / "index.sqlite3"

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_7)
            conn.close()
            seed_0_7_data(db_path)

            result = run_archivebox(work_dir, ["init"], timeout=45)
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            # Check for duplicate URLs
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("""
                SELECT url, COUNT(*) as cnt FROM core_snapshot
                GROUP BY url HAVING cnt > 1
            """)
            duplicates = cursor.fetchall()
            conn.close()

            self.assertEqual(len(duplicates), 0, f"Found duplicate URLs: {duplicates}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_no_orphaned_archiveresults_after_migration(self):
        """Migration should not leave orphaned ArchiveResults."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / "index.sqlite3"

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_7)
            conn.close()
            seed_0_7_data(db_path)

            result = run_archivebox(work_dir, ["init"], timeout=45)
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            ok, msg = verify_foreign_keys(db_path)
            self.assertTrue(ok, msg)

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_timestamps_preserved_after_migration(self):
        """Migration should preserve original timestamps."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / "index.sqlite3"

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_7)
            conn.close()
            original_data = seed_0_7_data(db_path)

            original_timestamps = {s["url"]: s["timestamp"] for s in original_data["snapshots"]}

            result = run_archivebox(work_dir, ["init"], timeout=45)
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT url, timestamp FROM core_snapshot")
            migrated_timestamps = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()

            for url, original_ts in original_timestamps.items():
                self.assertEqual(
                    migrated_timestamps.get(url),
                    original_ts,
                    f"Timestamp changed for {url}: {original_ts} -> {migrated_timestamps.get(url)}",
                )

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_tag_associations_preserved_after_migration(self):
        """Migration should preserve snapshot-tag associations."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / "index.sqlite3"

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_7)
            conn.close()
            seed_0_7_data(db_path)

            # Count tag associations before migration
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM core_snapshot_tags")
            original_count = cursor.fetchone()[0]
            conn.close()

            result = run_archivebox(work_dir, ["init"], timeout=45)
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            # Count tag associations after migration
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM core_snapshot_tags")
            migrated_count = cursor.fetchone()[0]
            conn.close()

            self.assertEqual(
                migrated_count,
                original_count,
                f"Tag associations changed: {original_count} -> {migrated_count}",
            )

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
