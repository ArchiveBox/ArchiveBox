#!/usr/bin/env python3
"""
Comprehensive tests for archivebox update command.
Verify update drains old dirs, reconciles DB, and queues snapshots.
"""

import pytest

from archivebox.core.models import Snapshot
from archivebox.tests.conftest import run_queued_crawls, run_archivebox_cmd, cli_env

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_update_runs_successfully_on_empty_archive(initialized_archive):
    """Test that update runs without error on empty archive."""
    result = run_archivebox_cmd(
        ["update"],
        timeout=120,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "Phase 1: Draining old archive/ directories" in output
    assert "Phase 2: Processing all database snapshots" in output
    assert "Updated DB rows:  0" in output
    assert "Sealed crawls:    0" in output

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
    assert "Phase 2: Processing all database snapshots" in output
    assert "Updated DB rows:" in output

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
    """Test that full update reconciles migrated snapshots without re-queuing them."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        timeout=90,
    )
    run_queued_crawls(initialized_archive, env)

    # Run update
    result = run_archivebox_cmd(
        ["update"],
        env=env,
        timeout=120,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "No queued/interrupted crawl work found" in output

    # Check that snapshot remains archived instead of being queued for a full re-crawl.
    with use_archivebox_db(initialized_archive):
        status = Snapshot.objects.values_list("status", flat=True).get()

    assert status == "sealed"
