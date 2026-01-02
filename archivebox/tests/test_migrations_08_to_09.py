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

import json
import shutil
import sqlite3
import subprocess
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
    verify_process_migration,
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
        """Migration should preserve all Crawl records and create default crawl if needed."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        # Count snapshots with NULL crawl_id in original data
        snapshots_without_crawl = sum(1 for s in self.original_data['snapshots'] if s['crawl_id'] is None)

        # Expected count: original crawls + 1 default crawl if any snapshots had NULL crawl_id
        expected_count = len(self.original_data['crawls'])
        if snapshots_without_crawl > 0:
            expected_count += 1  # Migration 0024 creates a default crawl

        ok, msg = verify_crawl_count(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_preserves_snapshot_crawl_links(self):
        """Migration should preserve snapshot-to-crawl relationships and assign default crawl to orphans."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check EVERY snapshot has a crawl_id after migration
        for snapshot in self.original_data['snapshots']:
            cursor.execute("SELECT crawl_id FROM core_snapshot WHERE url = ?", (snapshot['url'],))
            row = cursor.fetchone()
            self.assertIsNotNone(row, f"Snapshot {snapshot['url']} not found after migration")

            if snapshot['crawl_id'] is not None:
                # Snapshots that had a crawl should keep it
                self.assertEqual(row[0], snapshot['crawl_id'],
                    f"Crawl ID changed for {snapshot['url']}: expected {snapshot['crawl_id']}, got {row[0]}")
            else:
                # Snapshots without a crawl should now have one (the default crawl)
                self.assertIsNotNone(row[0],
                    f"Snapshot {snapshot['url']} should have been assigned to default crawl but has NULL")

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

        result = run_archivebox(self.work_dir, ['snapshot', 'list'])
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
        """Migration should remove seed_id column from archivebox.crawls.crawl."""
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

    def test_migration_creates_process_records(self):
        """Migration should create Process records for all ArchiveResults."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        # Verify Process records created
        expected_count = len(self.original_data['archiveresults'])
        ok, msg = verify_process_migration(self.db_path, expected_count)
        self.assertTrue(ok, msg)

    def test_migration_creates_binary_records(self):
        """Migration should create Binary records from cmd_version data."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check Binary records exist
        cursor.execute("SELECT COUNT(*) FROM machine_binary")
        binary_count = cursor.fetchone()[0]

        # Should have at least one binary per unique extractor
        extractors = set(ar['extractor'] for ar in self.original_data['archiveresults'])
        self.assertGreaterEqual(binary_count, len(extractors),
                              f"Expected at least {len(extractors)} Binaries, got {binary_count}")

        conn.close()

    def test_migration_preserves_cmd_data(self):
        """Migration should preserve cmd data in Process.cmd field."""
        result = run_archivebox(self.work_dir, ['init'], timeout=45)
        self.assertEqual(result.returncode, 0, f"Init failed: {result.stderr}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Check that Process records have cmd arrays
        cursor.execute("SELECT cmd FROM machine_process WHERE cmd != '[]'")
        cmd_records = cursor.fetchall()

        # All Processes should have non-empty cmd (test data has json.dumps([extractor, '--version']))
        expected_count = len(self.original_data['archiveresults'])
        self.assertEqual(len(cmd_records), expected_count,
                        f"Expected {expected_count} Processes with cmd, got {len(cmd_records)}")

        conn.close()


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


class TestFilesystemMigration08to09(unittest.TestCase):
    """Test filesystem migration from 0.8.x flat structure to 0.9.x organized structure."""

    def setUp(self):
        """Create a temporary directory for testing."""
        self.work_dir = Path(tempfile.mkdtemp())
        self.db_path = self.work_dir / 'index.sqlite3'

    def tearDown(self):
        """Clean up temporary directory."""
        shutil.rmtree(self.work_dir, ignore_errors=True)

    def test_archiveresult_files_preserved_after_migration(self):
        """
        Test that ArchiveResult output files are reorganized into new structure.

        This test verifies that:
        1. Migration preserves ArchiveResult data in Process/Binary records
        2. Running `archivebox update` reorganizes files into new structure
        3. New structure: users/username/snapshots/YYYYMMDD/example.com/snap-uuid-here/output.ext
        4. All files are moved (no data loss)
        5. Old archive/timestamp/ directories are cleaned up
        """
        # Use the real 0.7.2 database which has actual ArchiveResults with files
        gold_db = Path('/Users/squash/Local/Code/archiveboxes/archivebox-migration-path/archivebox-v0.7.2/data')
        if not gold_db.exists():
            self.skipTest(f"Gold standard database not found at {gold_db}")

        # Copy gold database to test directory
        import shutil
        for item in gold_db.iterdir():
            if item.is_dir():
                shutil.copytree(item, self.work_dir / item.name, dirs_exist_ok=True)
            else:
                shutil.copy2(item, self.work_dir / item.name)

        # Count archive directories and files BEFORE migration
        archive_dir = self.work_dir / 'archive'
        dirs_before = list(archive_dir.glob('*')) if archive_dir.exists() else []
        dirs_before_count = len([d for d in dirs_before if d.is_dir()])

        # Count total files in all archive directories
        files_before = []
        for d in dirs_before:
            if d.is_dir():
                files_before.extend([f for f in d.rglob('*') if f.is_file()])
        files_before_count = len(files_before)

        # Sample some specific files to check they're preserved
        sample_files = [
            'favicon.ico',
            'screenshot.png',
            'singlefile.html',
            'headers.json',
        ]
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
        result = run_archivebox(self.work_dir, ['init'], timeout=60)
        self.assertEqual(result.returncode, 0, f"Init (migration) failed: {result.stderr}")

        # Count archive directories and files AFTER migration
        dirs_after = list(archive_dir.glob('*')) if archive_dir.exists() else []
        dirs_after_count = len([d for d in dirs_after if d.is_dir()])

        files_after = []
        for d in dirs_after:
            if d.is_dir():
                files_after.extend([f for f in d.rglob('*') if f.is_file()])
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
        self.assertEqual(dirs_before_count, dirs_after_count,
                        f"Archive directories lost during migration: {dirs_before_count} -> {dirs_after_count}")
        self.assertEqual(files_before_count, files_after_count,
                        f"Files lost during migration: {files_before_count} -> {files_after_count}")

        # Run update to trigger filesystem reorganization
        print(f"\n[*] Running archivebox update to reorganize filesystem...")
        result = run_archivebox(self.work_dir, ['update'], timeout=120)
        self.assertEqual(result.returncode, 0, f"Update failed: {result.stderr}")

        # Check new filesystem structure
        # New structure: users/username/snapshots/YYYYMMDD/example.com/snap-uuid-here/output.ext
        users_dir = self.work_dir / 'users'
        snapshots_base = None

        if users_dir.exists():
            # Find the snapshots directory
            for user_dir in users_dir.iterdir():
                if user_dir.is_dir():
                    user_snapshots = user_dir / 'snapshots'
                    if user_snapshots.exists():
                        snapshots_base = user_snapshots
                        break

        print(f"[*] New structure base: {snapshots_base}")

        # Count files in new structure
        # Structure: users/{username}/snapshots/YYYYMMDD/{domain}/{uuid}/files...
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
                                    for f in snap_dir.rglob('*'):
                                        if f.is_file():
                                            files_new_structure.append(f)
                                            # Track sample files
                                            if f.name in sample_files:
                                                new_sample_files[f"{snap_dir.name}/{f.name}"] = f

        files_new_count = len(files_new_structure)
        print(f"[*] Files in new structure: {files_new_count}")
        print(f"[*] Sample files in new structure: {len(new_sample_files)}")

        # Check old structure (should be gone or empty)
        old_archive_dir = self.work_dir / 'archive'
        old_files_remaining = []
        unmigrated_dirs = []
        if old_archive_dir.exists():
            for d in old_archive_dir.glob('*'):
                # Only count REAL directories, not symlinks (symlinks are the migrated ones)
                if d.is_dir(follow_symlinks=False) and d.name.replace('.', '').isdigit():
                    # This is a timestamp directory (old structure)
                    files_in_dir = [f for f in d.rglob('*') if f.is_file()]
                    if files_in_dir:
                        unmigrated_dirs.append((d.name, len(files_in_dir)))
                        old_files_remaining.extend(files_in_dir)

        old_files_count = len(old_files_remaining)
        print(f"[*] Files remaining in old structure: {old_files_count}")
        if unmigrated_dirs:
            print(f"[*] Unmigrated directories: {unmigrated_dirs}")

        # CRITICAL: Verify files were moved to new structure
        self.assertGreater(files_new_count, 0,
                          "No files found in new structure after update")

        # CRITICAL: Verify old structure is cleaned up
        self.assertEqual(old_files_count, 0,
                        f"Old structure not cleaned up: {old_files_count} files still in archive/timestamp/ directories")

        # CRITICAL: Verify all files were moved (total count should match)
        total_after_update = files_new_count + old_files_count
        self.assertEqual(files_before_count, total_after_update,
                        f"Files lost during reorganization: {files_before_count} before → {total_after_update} after")

        # CRITICAL: Verify sample files exist in new structure
        self.assertGreater(len(new_sample_files), 0,
                          f"Sample files not found in new structure")

        # Verify new path format
        for path_key, file_path in new_sample_files.items():
            # Path should contain: snapshots/YYYYMMDD/domain/snap-uuid/plugin/file
            path_parts = file_path.parts
            self.assertIn('snapshots', path_parts,
                         f"New path should contain 'snapshots': {file_path}")
            self.assertIn('users', path_parts,
                         f"New path should contain 'users': {file_path}")
            print(f"    ✓ {path_key} → {file_path.relative_to(self.work_dir)}")

        # Verify Process and Binary records were created
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM core_archiveresult")
        archiveresult_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM machine_process")
        process_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM machine_binary")
        binary_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM core_archiveresult WHERE process_id IS NOT NULL")
        linked_count = cursor.fetchone()[0]

        conn.close()

        print(f"[*] ArchiveResults: {archiveresult_count}")
        print(f"[*] Process records created: {process_count}")
        print(f"[*] Binary records created: {binary_count}")
        print(f"[*] ArchiveResults linked to Process: {linked_count}")

        # Verify data migration happened correctly
        # The 0.7.2 gold database has 44 ArchiveResults
        self.assertEqual(archiveresult_count, 44,
                        f"Expected 44 ArchiveResults from 0.7.2 database, got {archiveresult_count}")

        # Each ArchiveResult should create one Process record
        self.assertEqual(process_count, 44,
                        f"Expected 44 Process records (1 per ArchiveResult), got {process_count}")

        # The 44 ArchiveResults use 7 unique binaries (curl, wget, etc.)
        self.assertEqual(binary_count, 7,
                        f"Expected 7 unique Binary records, got {binary_count}")

        # ALL ArchiveResults should be linked to Process records
        self.assertEqual(linked_count, 44,
                        f"Expected all 44 ArchiveResults linked to Process, got {linked_count}")





if __name__ == '__main__':
    unittest.main()
