#!/usr/bin/env python3
"""
Comprehensive tests for archivebox init command.
Verify init creates correct database schema, filesystem structure, and config.
"""

import os
import subprocess
import sqlite3
from pathlib import Path

from archivebox.config.common import STORAGE_CONFIG

from .fixtures import *


DIR_PERMISSIONS = STORAGE_CONFIG.OUTPUT_PERMISSIONS.replace('6', '7').replace('4', '5')


def test_init_creates_database_file(tmp_path):
    """Test that init creates index.sqlite3 database file."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'init'], capture_output=True)

    assert result.returncode == 0
    db_path = tmp_path / "index.sqlite3"
    assert db_path.exists()
    assert db_path.is_file()


def test_init_creates_archive_directory(tmp_path):
    """Test that init creates archive directory."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    archive_dir = tmp_path / "archive"
    assert archive_dir.exists()
    assert archive_dir.is_dir()


def test_init_creates_sources_directory(tmp_path):
    """Test that init creates sources directory."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    sources_dir = tmp_path / "sources"
    assert sources_dir.exists()
    assert sources_dir.is_dir()


def test_init_creates_logs_directory(tmp_path):
    """Test that init creates logs directory."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    logs_dir = tmp_path / "logs"
    assert logs_dir.exists()
    assert logs_dir.is_dir()


def test_init_creates_config_file(tmp_path):
    """Test that init creates ArchiveBox.conf config file."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    config_file = tmp_path / "ArchiveBox.conf"
    assert config_file.exists()
    assert config_file.is_file()


def test_init_runs_migrations(tmp_path):
    """Test that init runs Django migrations and creates core tables."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    # Check that migrations were applied
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check django_migrations table exists
    migrations = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='django_migrations'"
    ).fetchall()
    assert len(migrations) == 1

    # Check that some migrations were applied
    migration_count = c.execute("SELECT COUNT(*) FROM django_migrations").fetchone()[0]
    assert migration_count > 0

    conn.close()


def test_init_creates_core_snapshot_table(tmp_path):
    """Test that init creates core_snapshot table."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check core_snapshot table exists
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='core_snapshot'"
    ).fetchall()
    assert len(tables) == 1

    conn.close()


def test_init_creates_crawls_crawl_table(tmp_path):
    """Test that init creates crawls_crawl table."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check crawls_crawl table exists
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='crawls_crawl'"
    ).fetchall()
    assert len(tables) == 1

    conn.close()


def test_init_creates_core_archiveresult_table(tmp_path):
    """Test that init creates core_archiveresult table."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check core_archiveresult table exists
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='core_archiveresult'"
    ).fetchall()
    assert len(tables) == 1

    conn.close()


def test_init_sets_correct_file_permissions(tmp_path):
    """Test that init sets correct permissions on created files."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    # Check database permissions
    db_path = tmp_path / "index.sqlite3"
    assert oct(db_path.stat().st_mode)[-3:] in (STORAGE_CONFIG.OUTPUT_PERMISSIONS, DIR_PERMISSIONS)

    # Check directory permissions
    archive_dir = tmp_path / "archive"
    assert oct(archive_dir.stat().st_mode)[-3:] in (STORAGE_CONFIG.OUTPUT_PERMISSIONS, DIR_PERMISSIONS)


def test_init_is_idempotent(tmp_path):
    """Test that running init multiple times is safe (idempotent)."""
    os.chdir(tmp_path)

    # First init
    result1 = subprocess.run(['archivebox', 'init'], capture_output=True, text=True)
    assert result1.returncode == 0
    assert "Initializing a new ArchiveBox" in result1.stdout

    # Second init should update, not fail
    result2 = subprocess.run(['archivebox', 'init'], capture_output=True, text=True)
    assert result2.returncode == 0
    assert "updating existing ArchiveBox" in result2.stdout or "up-to-date" in result2.stdout.lower()

    # Database should still be valid
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM django_migrations").fetchone()[0]
    assert count > 0
    conn.close()


def test_init_with_existing_data_preserves_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that re-running init preserves existing snapshot data."""
    os.chdir(tmp_path)

    # Add a snapshot
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Check snapshot was created
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_before = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    assert count_before == 1
    conn.close()

    # Run init again
    result = subprocess.run(['archivebox', 'init'], capture_output=True)
    assert result.returncode == 0

    # Snapshot should still exist
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count_after = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    assert count_after == count_before
    conn.close()


def test_init_quick_flag_skips_checks(tmp_path):
    """Test that init --quick runs faster by skipping some checks."""
    os.chdir(tmp_path)

    result = subprocess.run(['archivebox', 'init', '--quick'], capture_output=True, text=True)

    assert result.returncode == 0
    # Database should still be created
    db_path = tmp_path / "index.sqlite3"
    assert db_path.exists()


def test_init_creates_machine_table(tmp_path):
    """Test that init creates the machine_machine table."""
    os.chdir(tmp_path)
    subprocess.run(['archivebox', 'init'], capture_output=True)

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Check machine_machine table exists
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='machine_machine'"
    ).fetchall()
    conn.close()

    assert len(tables) == 1


def test_init_output_shows_collection_info(tmp_path):
    """Test that init output shows helpful collection information."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'init'], capture_output=True, text=True)

    output = result.stdout
    # Should show some helpful info about the collection
    assert 'ArchiveBox' in output or 'collection' in output.lower() or 'Initializing' in output
