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

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from .test_migrations_helpers import (
    SCHEMA_0_8,
    seed_0_8_data,
    run_archivebox,
    create_data_dir_structure,
    verify_snapshot_count,
    verify_snapshot_urls,
    verify_snapshot_titles,
    verify_tag_count,
    verify_archiveresult_count,
    verify_foreign_keys,
    verify_all_snapshots_in_output,
    verify_crawl_count,
)


class TestMigrationFrom08x(unittest.TestCase):
    """Test migration from 0.8.x schema to latest."""

    def setUp(self):
        """Create a temporary directory with 0.8.x schema and data."""
        self.work_dir = Path(tempfile.mkdtemp())
        self.db_path = self.work_dir / 'index.sqlite3'

        # Create directory structure
        create_data_dir_structure(self.work_dir)

        # Create database with 0.8.x schema
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA_0_8)
        conn.close()

        # Seed with test data
        self.original_data = seed_0_8_data(self.db_path)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_migration_preserves_snapshot_count(self):
        """Migration should preserve all snapshots from 0.8.x."""
        expected_count = len(self.original_data['snapshots'])

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_snapshot_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_urls(self):
        """Migration should preserve all snapshot URLs from 0.8.x."""
        expected_urls = [s['url'] for s in self.original_data['snapshots']]

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_snapshot_urls(self.db_path, expected_urls)
        self.assertTrue(ok, msg)

    def test_migration_preserves_crawls(self):
        """Migration should preserve all Crawl records."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        expected_count = len(self.original_data['crawls'])
        ok, msg = verify_crawl_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_crawl_links(self):
        """Migration should preserve snapshot-to-crawl relationships."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check EVERY snapshot still has its crawl_id
        for snapshot in self.original_data['snapshots']:
            cursor.execute("SELECT crawl_id FROM core_snapshot WHERE url = ?", (snapshot['url'],))
            row = cursor.fetchone()
            self.assertIsNotNone(row, f"Snapshot {snapshot['url']} not found after migration")
            self.assertEqual(row[0], snapshot['crawl_id'],
                f"Crawl ID mismatch for {snapshot['url']}: expected {snapshot['crawl_id']}, got {row[0]}")

        conn.close()

    def test_migration_preserves_tags(self):
        """Migration should preserve all tags."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_tag_count(self.db_path, len(self.original_data['tags']))
        self.assertTrue(ok, msg)

    def test_migration_preserves_archiveresults(self):
        """Migration should preserve all archive results."""
        expected_count = len(self.original_data['archiveresults'])

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_archiveresult_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_archiveresult_status(self):
        """Migration should preserve archive result status values."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Get status counts
        cursor.execute("SELECT status, COUNT(*) FROM core_archiveresult GROUP BY status")
        status_counts = dict(cursor.fetchall())
        conn.close()

        # Original data has known status distribution: succeeded, failed, skipped
        self.assertIn('succeeded', status_counts, "Should have succeeded results")
        self.assertIn('failed', status_counts, "Should have failed results")
        self.assertIn('skipped', status_counts, "Should have skipped results")

    def test_status_works_after_migration(self):
        """Status command should work after migration."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ['status'])
        self.assertEqual(result.returncode, 0, f"Status failed after migration: {result.stderr}")

    def test_list_works_after_migration(self):
        """List command should work and show ALL migrated data."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ['list'])
        self.assertEqual(result.returncode, 0, f"List failed after migration: {result.stderr}")

        # Verify ALL snapshots appear in output
        output = result.stdout + result.stderr
        ok, msg = verify_all_snapshots_in_output(output, self.original_data['snapshots'])
        self.assertTrue(ok, msg)

    def test_search_works_after_migration(self):
        """Search command should find ALL migrated snapshots."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ['search'])
        self.assertEqual(result.returncode, 0, f"Search failed after migration: {result.stderr}")

        # Verify ALL snapshots appear in output
        output = result.stdout + result.stderr
        ok, msg = verify_all_snapshots_in_output(output, self.original_data['snapshots'])
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_titles(self):
        """Migration should preserve all snapshot titles."""
        expected_titles = {s['url']: s['title'] for s in self.original_data['snapshots']}

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_snapshot_titles(self.db_path, expected_titles)
        self.assertTrue(ok, msg)

    def test_migration_preserves_foreign_keys(self):
        """Migration should maintain foreign key relationships."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_foreign_keys(self.db_path)
        self.assertTrue(ok, msg)

    def test_migration_removes_seed_id_column(self):
        """Migration should remove seed_id column from crawls_crawl."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(crawls_crawl)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()

        self.assertNotIn('seed_id', columns,
            f"seed_id column should have been removed by migration. Columns: {columns}")

    def test_migration_removes_seed_table(self):
        """Migration should remove crawls_seed table."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='crawls_seed'")
        table_exists = cursor.fetchone() is not None
        conn.close()

        self.assertFalse(table_exists, "crawls_seed table should have been removed by migration")

    def test_add_works_after_migration(self):
        """Adding new URLs should work after migration from 0.8.x."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        # Check that init actually ran and applied migrations
        self.assertIn('Applying', result.stdout + result.stderr,
            f"Init did not apply migrations. stdout: {result.stdout[:500]}, stderr: {result.stderr[:500]}")
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        # Count existing crawls
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
        initial_crawl_count = cursor.fetchone()[0]
        conn.close()

        # Try to add a new URL after migration (use --index-only for speed)
        result = run_archivebox(self.work_dir, ['add', '--index-only', 'https://example.com/new-page'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Add failed after migration: {result.stderr}")

        # Verify a new Crawl was created
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM crawls_crawl")
        new_crawl_count = cursor.fetchone()[0]
        conn.close()

        self.assertGreater(new_crawl_count, initial_crawl_count,
                          f"No new Crawl created when adding URL. Add stderr: {result.stderr[-500:]}")

    def test_version_works_after_migration(self):
        """Version command should work after migration."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ['version'])
        self.assertEqual(result.returncode, 0, f"Version failed after migration: {result.stderr}")

        # Should show version info
        output = result.stdout + result.stderr
        self.assertTrue('ArchiveBox' in output or 'version' in output.lower(),
                       f"Version output missing expected content: {output[:500]}")


class TestMigrationDataIntegrity08x(unittest.TestCase):
    """Comprehensive data integrity tests for 0.8.x migrations."""

    def test_no_duplicate_snapshots_after_migration(self):
        """Migration should not create duplicate snapshots."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / 'index.sqlite3'

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_8)
            conn.close()
            seed_0_8_data(db_path)

            result = run_archivebox(work_dir, ['init'], timeout=45)
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
        db_path = work_dir / 'index.sqlite3'

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_8)
            conn.close()
            seed_0_8_data(db_path)

            result = run_archivebox(work_dir, ['init'], timeout=45)
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            ok, msg = verify_foreign_keys(db_path)
            self.assertTrue(ok, msg)

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_timestamps_preserved_after_migration(self):
        """Migration should preserve original timestamps."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / 'index.sqlite3'

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_8)
            conn.close()
            original_data = seed_0_8_data(db_path)

            original_timestamps = {s['url']: s['timestamp'] for s in original_data['snapshots']}

            result = run_archivebox(work_dir, ['init'], timeout=45)
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT url, timestamp FROM core_snapshot")
            migrated_timestamps = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()

            for url, original_ts in original_timestamps.items():
                self.assertEqual(
                    migrated_timestamps.get(url), original_ts,
                    f"Timestamp changed for {url}: {original_ts} -> {migrated_timestamps.get(url)}"
                )

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_crawl_data_preserved_after_migration(self):
        """Migration should preserve crawl metadata (urls, label, status)."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / 'index.sqlite3'

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_8)
            conn.close()
            original_data = seed_0_8_data(db_path)

            result = run_archivebox(work_dir, ['init'], timeout=45)
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Check each crawl's data is preserved
            for crawl in original_data['crawls']:
                cursor.execute("SELECT urls, label FROM crawls_crawl WHERE id = ?", (crawl['id'],))
                row = cursor.fetchone()
                self.assertIsNotNone(row, f"Crawl {crawl['id']} not found after migration")
                self.assertEqual(row[0], crawl['urls'], f"URLs mismatch for crawl {crawl['id']}")
                self.assertEqual(row[1], crawl['label'], f"Label mismatch for crawl {crawl['id']}")

            conn.close()

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def test_tag_associations_preserved_after_migration(self):
        """Migration should preserve snapshot-tag associations."""
        work_dir = Path(tempfile.mkdtemp())
        db_path = work_dir / 'index.sqlite3'

        try:
            create_data_dir_structure(work_dir)
            conn = sqlite3.connect(str(db_path))
            conn.executescript(SCHEMA_0_8)
            conn.close()
            seed_0_8_data(db_path)

            # Count tag associations before migration
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM core_snapshot_tags")
            original_count = cursor.fetchone()[0]
            conn.close()

            result = run_archivebox(work_dir, ['init'], timeout=45)
            self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

            # Count tag associations after migration
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM core_snapshot_tags")
            migrated_count = cursor.fetchone()[0]
            conn.close()

            self.assertEqual(migrated_count, original_count,
                           f"Tag associations changed: {original_count} -> {migrated_count}")

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
