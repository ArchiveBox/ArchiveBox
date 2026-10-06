#!/usr/bin/env python3
"""
Comprehensive tests for archivebox status command.
Verify status reports accurate collection state from DB and filesystem.
"""

import pytest

from archivebox.core.models import Snapshot
from archivebox.tests.conftest import find_snapshot_dir, run_archivebox_cmd, cli_env

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def _create_snapshot_rows(initialized_archive, env, *urls):
    result = run_archivebox_cmd(
        ["snapshot", "create", *urls],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    return result


def test_status_reports_empty_collection_size_user_index_and_path(initialized_archive):
    """All empty-collection fields come from the same real status response."""
    result = run_archivebox_cmd(["status"], cwd=initialized_archive)
    assert result.returncode == 0
    output = result.stdout
    assert len(output) > 100
    assert "0" in output
    assert "Size" in output or "size" in output
    assert "user" in output.lower() or "login" in output.lower()
    assert "index" in output.lower() or "Index" in output
    assert "archive" in output.lower() or str(initialized_archive) in output


def test_status_shows_correct_snapshot_count(initialized_archive):
    """Test that status shows accurate snapshot count from DB."""
    env = cli_env(disable_extractors=True)

    _create_snapshot_rows(initialized_archive, env, "https://example.com", "https://example.org", "https://example.net")

    result = run_archivebox_cmd(["status"], cwd=initialized_archive)

    # Verify DB has 3 snapshots
    with use_archivebox_db(initialized_archive):
        db_count = Snapshot.objects.count()

    assert db_count == 3
    # Status output should show 3
    assert "3" in result.stdout


def test_status_reports_database_snapshot_count_and_archive_categories(initialized_archive):
    """One uncaptured snapshot exercises the DB count and filesystem categories."""
    env = cli_env(disable_extractors=True)
    _create_snapshot_rows(initialized_archive, env, "https://example.com")
    with use_archivebox_db(initialized_archive):
        assert Snapshot.objects.count() == 1
    result = run_archivebox_cmd(["status"], cwd=initialized_archive)
    assert result.returncode == 0, result.stderr
    assert "1" in result.stdout
    assert "archived" in result.stdout.lower() or "queued" in result.stdout.lower()
    assert "present" in result.stdout.lower() or "directories" in result.stdout


def test_status_detects_orphaned_directories(initialized_archive):
    """Test status detects directories not in DB (orphaned)."""
    env = cli_env(disable_extractors=True)

    _create_snapshot_rows(initialized_archive, env, "https://example.com")

    # Create an orphaned directory
    (initialized_archive / "archive" / "1234567890").mkdir(parents=True, exist_ok=True)

    result = run_archivebox_cmd(["status"], cwd=initialized_archive)

    # Should mention orphaned dirs
    assert "orphan" in result.stdout.lower()
    assert "archivebox update" in result.stdout


def test_status_counts_new_snapshot_output_dirs_as_archived(initialized_archive, recursive_test_site):
    """Test status reads archived/present counts from the current snapshot output layout."""
    env = cli_env(disable_extractors=True)
    env = env.copy()
    env["ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS"] = "true"

    url = recursive_test_site["root_url"]
    captured = run_archivebox_cmd(["add", "--plugins=wget", url], cwd=initialized_archive, env=env, timeout=120)
    assert captured.returncode == 0, captured.stdout + captured.stderr

    with use_archivebox_db(initialized_archive):
        snapshot_id = Snapshot.objects.values_list("id", flat=True).get(url=url)

    snapshot_dir = find_snapshot_dir(initialized_archive, str(snapshot_id))
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"
    assert any("Root" in path.read_text(errors="ignore") for path in (snapshot_dir / "wget").rglob("*.html"))

    result = run_archivebox_cmd(["status"], cwd=initialized_archive, env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "archived: 1" in result.stdout
    assert "present: 1" in result.stdout


def test_status_help_lists_available_options(initialized_archive):
    """Test that status --help works and documents the command."""
    result = run_archivebox_cmd(
        ["status", "--help"],
        cwd=initialized_archive,
    )

    assert result.returncode == 0
    assert "status" in result.stdout.lower() or "statistic" in result.stdout.lower()
