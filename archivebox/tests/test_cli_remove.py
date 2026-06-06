#!/usr/bin/env python3
"""
Comprehensive tests for archivebox remove command.
Verify remove deletes snapshots from DB and filesystem.
"""

import json
from pathlib import Path

from archivebox.tests.conftest import find_snapshot_dir, run_archivebox_cmd, run_queued_crawls, cli_env


def _snapshot_rows(data_dir: Path, env: dict) -> list[dict]:
    script = """
import json
from archivebox.core.models import Snapshot
print(json.dumps([
    {"id": str(snapshot.id), "url": snapshot.url}
    for snapshot in Snapshot.objects.order_by("url")
]))
"""
    result = run_archivebox_cmd(
        ["manage", "shell", "-c", script],
        cwd=data_dir,
        env=env,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_remove_deletes_snapshot_from_db(initialized_archive):
    """Test that remove command deletes snapshot from database."""
    env = cli_env(disable_extractors=True)

    # Add a snapshot
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    rows = _snapshot_rows(initialized_archive, env)
    assert len(rows) == 1
    snapshot_id = rows[0]["id"]
    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot_id)
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"

    # Remove it
    run_archivebox_cmd(
        ["remove", "https://example.com", "--yes"],
        env=env,
    )

    assert len(_snapshot_rows(initialized_archive, env)) == 0
    assert not snapshot_dir.exists()


def test_remove_deletes_archive_directory(initialized_archive):
    """Test that remove --yes removes the current snapshot output directory."""
    env = cli_env(disable_extractors=True)

    # Add a snapshot
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    rows = _snapshot_rows(initialized_archive, env)
    assert len(rows) == 1
    snapshot_id = rows[0]["id"]

    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot_id)
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"

    run_archivebox_cmd(
        ["remove", "https://example.com", "--yes"],
        env=env,
    )

    assert not snapshot_dir.exists()


def test_remove_yes_flag_skips_confirmation(initialized_archive):
    """Test that --yes flag skips confirmation prompt."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    # Remove with --yes should complete without interaction
    result = run_archivebox_cmd(
        ["remove", "https://example.com", "--yes"],
        env=env,
        timeout=30,
    )

    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "Index now contains 0 links." in output


def test_remove_without_yes_prompts_and_keeps_snapshot(initialized_archive):
    """Test that omitting --yes prompts for confirmation and keeps data when declined."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)

    rows = _snapshot_rows(initialized_archive, env)
    assert len(rows) == 1
    snapshot_dir = find_snapshot_dir(initialized_archive, rows[0]["id"])
    assert snapshot_dir is not None

    result = run_archivebox_cmd(
        ["remove", "https://example.com"],
        input="n\n",
        env=env,
        timeout=30,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Do you want to proceed" in output or "y/[n]" in output
    assert len(_snapshot_rows(initialized_archive, env)) == 1
    assert snapshot_dir.exists()


def test_remove_multiple_snapshots(initialized_archive):
    """Test removing multiple snapshots at once."""
    env = cli_env(disable_extractors=True)

    # Add multiple snapshots
    for url in ["https://example.com", "https://example.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
        )
    run_queued_crawls(initialized_archive, env)

    assert len(_snapshot_rows(initialized_archive, env)) == 2

    # Remove both
    run_archivebox_cmd(
        ["remove", "https://example.com", "https://example.org", "--yes"],
        env=env,
    )

    assert len(_snapshot_rows(initialized_archive, env)) == 0


def test_remove_with_regex_filter_deletes_all_matches(initialized_archive):
    """Test regex filters remove every matching snapshot."""
    env = cli_env(disable_extractors=True)

    for url in ["https://example.com", "https://iana.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
            check=True,
        )
    run_queued_crawls(initialized_archive, env)

    result = run_archivebox_cmd(
        ["remove", "--filter-type=regex", ".*", "--yes"],
        env=env,
        check=True,
    )

    output = result.stdout + result.stderr
    assert len(_snapshot_rows(initialized_archive, env)) == 0
    assert "Removed" in output or "Found" in output


def test_remove_nonexistent_url_fails_gracefully(initialized_archive):
    """Test that removing non-existent URL fails gracefully."""
    env = cli_env(disable_extractors=True)

    result = run_archivebox_cmd(
        ["remove", "https://nonexistent-url-12345.com", "--yes"],
        env=env,
    )

    # Should fail or show error
    stdout_text = result.stdout.lower()
    assert result.returncode != 0 or "not found" in stdout_text or "no matches" in stdout_text


def test_remove_reports_remaining_link_count_correctly(initialized_archive):
    """Test remove reports the remaining snapshot count after deletion."""
    env = cli_env(disable_extractors=True)

    for url in ["https://example.com", "https://example.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
            check=True,
        )
    run_queued_crawls(initialized_archive, env)

    result = run_archivebox_cmd(
        ["remove", "https://example.org", "--yes"],
        env=env,
        check=True,
    )

    output = result.stdout + result.stderr
    assert "Removed 1 out of 2 links" in output
    assert "Index now contains 1 links." in output


def test_remove_after_flag(initialized_archive):
    """Test remove --after flag removes snapshots after date."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)

    rows = _snapshot_rows(initialized_archive, env)
    assert len(rows) == 1
    snapshot_dir = find_snapshot_dir(initialized_archive, rows[0]["id"])
    assert snapshot_dir is not None, f"Snapshot output directory not found for {rows[0]['id']}"

    result = run_archivebox_cmd(
        ["remove", "--after=1577836800", "--yes"],
        env=env,
        timeout=30,
        check=True,
    )

    output = result.stdout + result.stderr
    assert "Removed 1 out of 1 links" in output
    assert "Index now contains 0 links." in output
    assert len(_snapshot_rows(initialized_archive, env)) == 0
    assert not snapshot_dir.exists()
