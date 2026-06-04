#!/usr/bin/env python3
"""
Fresh install tests for ArchiveBox.

Tests that fresh installations work correctly with the current schema.
"""

import pytest
from django.db.migrations.recorder import MigrationRecorder

from archivebox.core.models import ArchiveResult, Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.tests.conftest import run_queued_crawls, cli_env

from .migrations_helpers import run_archivebox_migration_cmd

pytestmark = pytest.mark.django_db(transaction=True)


def test_init_creates_database(tmp_path):
    """Fresh init should create database and directories."""
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Verify database was created
    assert (tmp_path / "index.sqlite3").exists(), "Database not created"
    # Verify archive directory exists
    assert (tmp_path / "archive").is_dir(), "Archive dir not created"


def test_status_after_init(tmp_path):
    """Status command should work after init."""
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(tmp_path, ["status"])
    assert result.returncode == 0, f"Status failed: {result.stderr}"


def test_add_url_after_init(tmp_path):
    """Should be able to add URLs after init with --bg."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Add a URL with --bg for speed
    result = run_archivebox_migration_cmd(tmp_path, ["add", "--bg", "https://example.com"])
    assert result.returncode == 0, f"Add command failed: {result.stderr}"
    run_queued_crawls(tmp_path, env)

    with use_archivebox_db(tmp_path):
        assert Crawl.objects.count() >= 1, "No Crawl was created"
        assert Snapshot.objects.count() >= 1, "No Snapshot was created"


def test_list_after_add(tmp_path):
    """List command should show added snapshots."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(tmp_path, ["add", "--bg", "https://example.com"])
    assert result.returncode == 0, f"Add failed: {result.stderr}"
    run_queued_crawls(tmp_path, env)

    result = run_archivebox_migration_cmd(tmp_path, ["list"])
    assert result.returncode == 0, f"List failed: {result.stderr}"

    # Verify the URL appears in output
    output = result.stdout + result.stderr
    assert "example.com" in output, f"Added URL not in list output: {output[:500]}"


def test_migrations_table_populated(tmp_path):
    """Django migrations table should be populated after init."""
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    with use_archivebox_db(tmp_path):
        count = MigrationRecorder.Migration.objects.count()

    # Should have many migrations applied
    assert count > 10, f"Expected >10 migrations, got {count}"


def test_core_migrations_applied(tmp_path):
    """Core app migrations should be applied."""
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    with use_archivebox_db(tmp_path):
        migrations = list(
            MigrationRecorder.Migration.objects.filter(app="core").order_by("name").values_list("name", flat=True),
        )

    assert "0001_initial" in migrations


def test_snapshot_table_has_required_columns(tmp_path):
    """Snapshot table should have all required columns."""
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    columns = {field.column for field in Snapshot._meta.local_fields}

    required = {"id", "url", "timestamp", "title", "status", "created_at", "modified_at"}
    for col in required:
        assert col in columns, f"Missing column: {col}"


def test_archiveresult_table_has_required_columns(tmp_path):
    """ArchiveResult table should have all required columns."""
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    columns = {field.column for field in ArchiveResult._meta.local_fields}

    required = {"id", "snapshot_id", "plugin", "status", "created_at", "modified_at"}
    for col in required:
        assert col in columns, f"Missing column: {col}"


def test_tag_table_has_required_columns(tmp_path):
    """Tag table should have all required columns."""
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    columns = {field.column for field in Tag._meta.local_fields}

    required = {"id", "name"}
    for col in required:
        assert col in columns, f"Missing column: {col}"


def test_crawl_table_has_required_columns(tmp_path):
    """Crawl table should have all required columns."""
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    columns = {field.column for field in Crawl._meta.local_fields}

    required = {"id", "urls", "status", "created_at", "created_by_id"}
    for col in required:
        assert col in columns, f"Missing column: {col}"

    # seed_id should NOT exist (removed in 0.9.x)
    assert "seed_id" not in columns, "seed_id column should not exist in 0.9.x"


def test_add_urls_separately(tmp_path):
    """Should be able to add multiple URLs one at a time."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    # Add URLs one at a time
    result = run_archivebox_migration_cmd(tmp_path, ["add", "--bg", "https://example.com"])
    assert result.returncode == 0, f"Add 1 failed: {result.stderr}"

    result = run_archivebox_migration_cmd(tmp_path, ["add", "--bg", "https://example.org"])
    assert result.returncode == 0, f"Add 2 failed: {result.stderr}"
    run_queued_crawls(tmp_path, env)

    with use_archivebox_db(tmp_path):
        snapshot_count = Snapshot.objects.count()
        crawl_count = Crawl.objects.count()
    assert snapshot_count == 2, f"Expected 2 snapshots, got {snapshot_count}"
    assert crawl_count == 2, f"Expected 2 Crawls, got {crawl_count}"


def test_snapshots_linked_to_crawls(tmp_path):
    """Each snapshot should be linked to a crawl."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_migration_cmd(tmp_path, ["init"])
    assert result.returncode == 0, f"Init failed: {result.stderr}"

    result = run_archivebox_migration_cmd(tmp_path, ["add", "--bg", "https://example.com"])
    assert result.returncode == 0, f"Add failed: {result.stderr}"
    run_queued_crawls(tmp_path, env)

    with use_archivebox_db(tmp_path):
        row = Snapshot.objects.filter(url="https://example.com").values_list("crawl_id", flat=True).first()
    assert row is not None, "Snapshot not found"
    assert row is not None, "Snapshot should have a crawl_id"
