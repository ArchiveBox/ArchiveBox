#!/usr/bin/env python3
"""
Migration tests from 0.4.x to 0.9.x.

0.4.x was the first Django-powered version with a simpler schema:
- No Tag model (tags stored as comma-separated string in Snapshot)
- No ArchiveResult model (results stored in JSON files)
"""

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from .test_migrations_helpers import (
    SCHEMA_0_4,
    seed_0_4_data,
    run_archivebox,
    create_data_dir_structure,
    verify_snapshot_count,
    verify_snapshot_urls,
    verify_tag_count,
)


class TestMigrationFrom04x(unittest.TestCase):
    """Test migration from 0.4.x schema to latest."""

    def setUp(self):
        """Create a temporary directory with 0.4.x schema and data."""
        self.work_dir = Path(tempfile.mkdtemp())
        self.db_path = self.work_dir / 'index.sqlite3'

        # Create directory structure
        create_data_dir_structure(self.work_dir)

        # Create database with 0.4.x schema
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript(SCHEMA_0_4)
        conn.close()

        # Seed with test data
        self.original_data = seed_0_4_data(self.db_path)

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_migration_preserves_snapshot_count(self):
        """Migration should preserve all snapshots from 0.4.x."""
        expected_count = len(self.original_data['snapshots'])

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_snapshot_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_urls(self):
        """Migration should preserve all snapshot URLs from 0.4.x."""
        expected_urls = [s['url'] for s in self.original_data['snapshots']]

        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        ok, msg = verify_snapshot_urls(self.db_path, expected_urls)
        self.assertTrue(ok, msg)

    def test_migration_converts_string_tags_to_model(self):
        """Migration should convert comma-separated tags to Tag model instances."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        # Collect unique tags from original data
        original_tags = set()
        for tags_str in self.original_data['tags_str']:
            if tags_str:
                for tag in tags_str.split(','):
                    original_tags.add(tag.strip())

        # Tags should have been created
        ok, msg = verify_tag_count(self.db_path, len(original_tags))
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_titles(self):
        """Migration should preserve all snapshot titles."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT url, title FROM core_snapshot")
        actual = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        for snapshot in self.original_data['snapshots']:
            self.assertEqual(
                actual.get(snapshot['url']),
                snapshot['title'],
                f"Title mismatch for {snapshot['url']}"
            )

    def test_status_works_after_migration(self):
        """Status command should work after migration."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ['status'])
        self.assertEqual(result.returncode, 0, f"Status failed after migration: {result.stderr}")

    def test_list_works_after_migration(self):
        """List command should work and show ALL migrated snapshots."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        result = run_archivebox(self.work_dir, ['list'])
        self.assertEqual(result.returncode, 0, f"List failed after migration: {result.stderr}")

        # Verify ALL snapshots appear in output
        output = result.stdout + result.stderr
        for snapshot in self.original_data['snapshots']:
            url_fragment = snapshot['url'][:30]
            self.assertIn(url_fragment, output,
                         f"Snapshot {snapshot['url']} not found in list output")

    def test_add_works_after_migration(self):
        """Adding new URLs should work after migration from 0.4.x."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        # Try to add a new URL after migration
        result = run_archivebox(self.work_dir, ['add', '--index-only', 'https://example.com/new-page'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Add failed after migration: {result.stderr}")

        # Verify snapshot was added
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM core_snapshot WHERE url = 'https://example.com/new-page'")
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 1, "New snapshot was not created after migration")

    def test_new_schema_elements_created(self):
        """Migration should create new 0.9.x schema elements."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        # New tables should exist
        self.assertIn('crawls_crawl', tables, "crawls_crawl table not created")
        self.assertIn('core_tag', tables, "core_tag table not created")
        self.assertIn('core_archiveresult', tables, "core_archiveresult table not created")

    def test_snapshots_have_new_fields(self):
        """Migrated snapshots should have new 0.9.x fields."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute('PRAGMA table_info(core_snapshot)')
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        required_columns = {'status', 'depth', 'created_at', 'modified_at'}
        for col in required_columns:
            self.assertIn(col, columns, f"Snapshot missing new column: {col}")


if __name__ == '__main__':
    unittest.main()
