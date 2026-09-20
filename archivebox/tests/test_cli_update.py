#!/usr/bin/env python3
"""
Comprehensive tests for archivebox update command.
Verify update drains old dirs, reconciles DB, and queues snapshots.
"""

import pytest
import shutil
import signal
import json
import uuid

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.config import CONSTANTS
from archivebox.tests.conftest import run_queued_crawls, run_archivebox_cmd, cli_env

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_rescan_imports_current_layout_and_is_idempotent(initialized_archive, tmp_path):
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(["add", "--index-only", "https://example.com/rescan"], cwd=initialized_archive, env=env, check=True)
    run_queued_crawls(initialized_archive, env)
    run_archivebox_cmd(["update", "--migrate-only"], cwd=initialized_archive, env=env, check=True)
    with use_archivebox_db(initialized_archive):
        original = Snapshot.objects.get(url="https://example.com/rescan")
        original.title = "Imported snapshot"
        original.save()
        output = original.output_dir / "singlefile" / "singlefile.html"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("<html><title>Portable archive fixture</title></html>")
        result = ArchiveResult.objects.create(
            snapshot=original,
            plugin="singlefile",
            hook_name="on_Snapshot__singlefile",
            status="succeeded",
            output_str="singlefile/singlefile.html",
        )
        result.update_output_metadata_from_filesystem(full_scan=True)
        result.refresh_from_db()
        expected_result = (result.pk, result.created_at, result.modified_at, result.output_files, result.output_size)
        original.refresh_from_db()
        original.write_index_jsonl()
        index = original.output_dir / "index.jsonl"
        historical = {**result.to_json(), "id": uuid.uuid4().hex}
        index.write_text(json.dumps(historical) + "\n" + index.read_text())
        snapshot_id = original.pk
        original_fields = (original.crawl_id, original.created_at, original.modified_at, original.bookmarked_at, original.timestamp)
        original.crawl.refresh_from_db()
        crawl_dates = (original.crawl.created_at, original.crawl.modified_at)
        relative_path = original.output_dir.relative_to(initialized_archive)

    destination = tmp_path / "destination"
    destination.mkdir()
    run_archivebox_cmd(["init", "--quick"], cwd=destination, env=env, check=True)
    shutil.copytree(initialized_archive / "archive", destination / "archive", dirs_exist_ok=True, symlinks=True)
    result = run_archivebox_cmd(["update", "--migrate-only", "--index-only"], cwd=destination, env=env, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    with use_archivebox_db(destination):
        assert not Snapshot.objects.filter(pk=snapshot_id).exists()

    for expected in ("Imported: 1", "Unchanged: 1"):
        result = run_archivebox_cmd(["update", "--rescan", "--migrate-only"], cwd=destination, env=env, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        assert expected in result.stdout
        with use_archivebox_db(destination):
            imported = Snapshot.objects.get(pk=snapshot_id)
            assert imported.title == "Imported snapshot"
            assert imported.status == "sealed"
            assert imported.output_dir.relative_to(CONSTANTS.DATA_DIR) == relative_path
            assert (destination / relative_path / "index.jsonl").is_file()
            assert (
                imported.crawl_id,
                imported.created_at,
                imported.modified_at,
                imported.bookmarked_at,
                imported.timestamp,
            ) == original_fields
            assert (imported.crawl.created_at, imported.crawl.modified_at) == crawl_dates
            assert Snapshot.objects.count() == 1
            imported_result = imported.archiveresult_set.get()
            assert (
                imported_result.pk,
                imported_result.created_at,
                imported_result.modified_at,
                imported_result.output_files,
                imported_result.output_size,
            ) == expected_result
            assert (destination / relative_path / "singlefile" / "singlefile.html").read_text() == output.read_text()

    copied_index = destination / relative_path / "index.jsonl"
    records = [json.loads(line) for line in copied_index.read_text().splitlines()]
    for record in records:
        if record.get("type") == "Snapshot":
            record["url"] = "https://example.com/conflicting-identity"
    conflicting_bytes = "\n".join(json.dumps(record) for record in records) + "\n"
    copied_index.write_text(conflicting_bytes)
    result = run_archivebox_cmd(["update", "--rescan"], cwd=destination, env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "conflicting identity" in result.stdout
    assert copied_index.read_text() == conflicting_bytes
    with use_archivebox_db(destination):
        assert Snapshot.objects.get(pk=snapshot_id).url == "https://example.com/rescan"


@pytest.mark.parametrize("reverse", [False, True])
def test_rescan_resumes_after_real_interrupt_in_requested_order(initialized_archive, tmp_path, reverse):
    env = cli_env(disable_extractors=True)
    urls = [f"https://example.com/rescan-interrupt/{number}" for number in range(30)]
    run_archivebox_cmd(["add", "--index-only", *urls], cwd=initialized_archive, env=env, check=True)
    run_queued_crawls(initialized_archive, env)
    run_archivebox_cmd(["update", "--migrate-only"], cwd=initialized_archive, env=env, check=True)
    with use_archivebox_db(initialized_archive):
        originals = list(Snapshot.objects.order_by("id" if reverse else "-id"))
        expected = [(snapshot.pk, snapshot.created_at, snapshot.crawl_id) for snapshot in originals]
        for snapshot in originals:
            snapshot.write_index_jsonl()
    destination = tmp_path / "destination"
    destination.mkdir()
    run_archivebox_cmd(["init", "--quick"], cwd=destination, env=env, check=True)
    shutil.copytree(initialized_archive / "archive", destination / "archive", dirs_exist_ok=True, symlinks=True)
    args = ["update", "--rescan", *(["--reverse"] if reverse else [])]
    process = run_archivebox_cmd(args, cwd=destination, env=env, wait=False)
    try:
        for line in process.stdout:
            if "Imported:" in line:
                process.send_signal(signal.SIGINT)
                break
        stdout, stderr = process.communicate(timeout=60)
        assert process.returncode == 130, stdout + stderr
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=60)
    with use_archivebox_db(destination):
        partial = list(Snapshot.objects.order_by("id" if reverse else "-id").values_list("pk", "created_at", "crawl_id"))
        assert 0 < len(partial) < len(expected)
        assert partial == expected[: len(partial)]
    result = run_archivebox_cmd(args, cwd=destination, env=env, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    with use_archivebox_db(destination):
        assert list(Snapshot.objects.order_by("id" if reverse else "-id").values_list("pk", "created_at", "crawl_id")) == expected


def test_update_runs_successfully_on_empty_archive(initialized_archive):
    """Test that update runs without error on empty archive."""
    result = run_archivebox_cmd(
        ["update"],
        timeout=120,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "Filesystem migrations remain lazy" in output
    assert "Phase 1" not in output
    assert "Phase 2" not in output

    with use_archivebox_db(initialized_archive):
        assert Snapshot.objects.count() == 0


def test_update_reconciles_existing_snapshots(initialized_archive):
    """Test that update command reconciles existing snapshots."""
    env = cli_env(disable_extractors=True)

    # Add a snapshot (index-only for faster test)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    # Run update - should reconcile and queue
    result = run_archivebox_cmd(
        ["update"],
        env=env,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Filesystem migrations remain lazy" in output
    assert "Updated DB rows:" not in output

    with use_archivebox_db(initialized_archive):
        assert Snapshot.objects.filter(url="https://example.com", status="sealed").count() == 1


def test_update_specific_snapshot_by_filter(initialized_archive):
    """Test updating specific snapshot using filter."""
    env = cli_env(disable_extractors=True)

    # Add multiple snapshots
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        timeout=90,
    )
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.org"],
        env=env,
        timeout=90,
    )
    run_queued_crawls(initialized_archive, env)

    # Update with filter pattern (uses filter_patterns argument)
    result = run_archivebox_cmd(
        ["update", "--filter-type=substring", "example.com"],
        env=env,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Processing filtered snapshots from database" in output
    assert "Found 1 matching snapshots" in output

    with use_archivebox_db(initialized_archive):
        assert Snapshot.objects.filter(url="https://example.com", status="sealed").count() == 1
        assert Snapshot.objects.filter(url="https://example.org", status="sealed").count() == 1


def test_update_preserves_snapshot_count(initialized_archive):
    """Test that update doesn't change snapshot count."""
    env = cli_env(disable_extractors=True)

    # Add snapshots
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        timeout=90,
    )
    run_queued_crawls(initialized_archive, env)

    # Count before update
    with use_archivebox_db(initialized_archive):
        count_before = Snapshot.objects.count()

    assert count_before == 1

    # Run update (should reconcile + queue, not create new snapshots)
    run_archivebox_cmd(
        ["update"],
        env=env,
        timeout=120,
        check=True,
    )

    # Count after update
    with use_archivebox_db(initialized_archive):
        count_after = Snapshot.objects.count()

    # Snapshot count should remain the same
    assert count_after == count_before


def test_update_seals_migrated_snapshots(initialized_archive):
    """Test that migrate-only update reconciles snapshots without search backfill."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        timeout=90,
    )
    run_queued_crawls(initialized_archive, env)

    # Run the documented upgrade path without scheduling normal maintenance jobs.
    result = run_archivebox_cmd(
        ["update", "--migrate-only"],
        env=env,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Phase 2: Selecting database snapshots with stale filesystem versions" in output
    assert "Reindexing" not in output

    # Check that snapshot remains archived instead of being queued for a full re-crawl.
    with use_archivebox_db(initialized_archive):
        status = Snapshot.objects.values_list("status", flat=True).get()

    assert status == "sealed"
