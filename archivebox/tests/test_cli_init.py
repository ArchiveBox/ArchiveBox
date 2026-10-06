#!/usr/bin/env python3
"""
Comprehensive tests for archivebox init command.
Verify init creates correct database schema, filesystem structure, and config.
"""

import pytest
import subprocess
import sys
from pathlib import Path
from django.utils import timezone
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder

from archivebox.config.common import get_config
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Machine
from archivebox.tests.conftest import run_queued_crawls, run_archivebox_cmd, cli_env
from archivebox.tests.conftest import _set_test_source_pythonpath

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


DIR_PERMISSIONS = get_config().OUTPUT_PERMISSIONS.replace("6", "7").replace("4", "5")


def _runtime_artifact_state(source_root: Path) -> dict[str, tuple[int, int] | None]:
    artifact_paths = (
        "index.sqlite3",
        ".archivebox_id",
        "ArchiveBox.conf",
        "archive.log",
        "logs",
        "cache",
        "tmp",
        "lib",
    )
    state = {}
    for relative_path in artifact_paths:
        path = source_root / relative_path
        state[relative_path] = (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None
    return state


def test_cli_refuses_source_root_without_side_effects_and_allows_separate_data_dir(tmp_path):
    source_root = Path(__file__).resolve().parents[2]
    archivebox = Path(sys.executable).with_name("archivebox")
    assert archivebox.is_file()

    env = cli_env(disable_extractors=True)
    _set_test_source_pythonpath(env)
    before = _runtime_artifact_state(source_root)

    def run_from_source_root(*args: str):
        return subprocess.run(
            [
                sys.executable,
                "-c",
                "import os, sys; os.chdir(sys.argv[1]); os.execv(sys.argv[2], sys.argv[2:])",
                source_root,
                archivebox,
                *args,
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    for metadata_args in (("--help",), ("--version",)):
        result = run_from_source_root(*metadata_args)
        assert result.returncode == 0, result.stderr or result.stdout

    refused = run_from_source_root("init", "--quick")
    assert refused.returncode != 0
    assert "source checkout as a DATA_DIR" in refused.stderr
    assert _runtime_artifact_state(source_root) == before

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    initialized = subprocess.run(
        [archivebox, "init", "--quick"],
        cwd=data_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert initialized.returncode == 0, initialized.stderr or initialized.stdout
    assert (data_dir / "index.sqlite3").is_file()
    assert (data_dir / "logs").is_dir()


def test_init_creates_collection_schema_directories_config_and_permissions(tmp_path):
    """Inspect all outputs of one real fresh init; upgrade cases stay separate."""
    result = run_archivebox_cmd(["init"])
    assert result.returncode == 0, result.stderr

    db_path = tmp_path / "index.sqlite3"
    assert db_path.is_file()
    config_file = tmp_path / "ArchiveBox.conf"
    assert config_file.is_file()
    for relative_path in ("archive", "archive/users", "sources", "logs"):
        assert (tmp_path / relative_path).is_dir(), relative_path

    with use_archivebox_db(tmp_path):
        assert MigrationRecorder.Migration.objects.count() > 0
        assert Snapshot._meta.db_table == "core_snapshot"
        assert Snapshot.objects.count() == 0
        assert Crawl._meta.db_table == "crawls_crawl"
        assert Crawl.objects.count() == 0
        assert ArchiveResult._meta.db_table == "core_archiveresult"
        assert ArchiveResult.objects.count() == 0
        assert Machine._meta.db_table == "machine_machine"
        Machine.objects.count()

    assert oct(db_path.stat().st_mode)[-3:] in (get_config().OUTPUT_PERMISSIONS, DIR_PERMISSIONS)
    assert oct((tmp_path / "archive").stat().st_mode)[-3:] in (get_config().OUTPUT_PERMISSIONS, DIR_PERMISSIONS)
    output = result.stdout
    assert "ArchiveBox" in output or "collection" in output.lower() or "Initializing" in output


def test_init_creates_database_with_archivebox_permissions_despite_permissive_umask(tmp_path):
    """SQLite must create index.sqlite3 with ArchiveBox's restrictive mode from first open."""
    env = cli_env(disable_extractors=True)
    _set_test_source_pythonpath(env)
    result = subprocess.run(
        ["bash", "-lc", "umask 000; archivebox init"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert oct((tmp_path / "index.sqlite3").stat().st_mode)[-3:] == get_config().OUTPUT_PERMISSIONS


def test_init_is_idempotent(tmp_path):
    """Test that running init multiple times is safe (idempotent)."""

    # First init
    result1 = run_archivebox_cmd(["init"])
    assert result1.returncode == 0
    assert "Initializing a new ArchiveBox" in result1.stdout

    # Second init should update, not fail
    result2 = run_archivebox_cmd(["init"])
    assert result2.returncode == 0
    assert "updating existing ArchiveBox" in result2.stdout or "up-to-date" in result2.stdout.lower()

    # Database should still be valid
    with use_archivebox_db(tmp_path):
        count = MigrationRecorder.Migration.objects.count()
    assert count > 0


def test_init_refuses_database_migrated_by_newer_code(tmp_path):
    """A downgraded ArchiveBox build must fail before serving a newer DB schema."""
    result = run_archivebox_cmd(["init"])
    assert result.returncode == 0

    with use_archivebox_db(tmp_path):
        MigrationRecorder.Migration.objects.create(app="crawls", name="9999_future_test", applied=timezone.now())
        connections["default"].commit()

    result = run_archivebox_cmd(["init"])
    assert result.returncode == 3
    assert "migrated by a newer version of ArchiveBox" in result.stderr
    assert "crawls.9999_future_test" in result.stderr
    assert "archivebox manage migrate crawls " in result.stderr


def test_init_recovers_from_pre_squash_dev_history(tmp_path):
    """Known historical migration rows must not trip the newer-DB guard."""
    result = run_archivebox_cmd(["init"])
    assert result.returncode == 0

    # Sampling across affected apps, including v0.6.2 runtime-generated names
    # absent from Git. These older collections must still pass init.
    historical_pre_squash_rows = [
        ("api", "0002_alter_apitoken_options"),
        ("api", "0009_rename_created_apitoken_created_at_and_more"),
        # v0.6.2 ran makemigrations at init, so these reported 0021 names were
        # created in the installed package and never appeared in Git.
        ("core", "0021_auto_20220510_0644"),
        ("core", "0021_auto_20220724_1254"),
        ("core", "0021_auto_20221128_1116"),
        ("core", "0023_alter_archiveresult_options_archiveresult_abid_and_more"),
        ("core", "0056_progress_covering_indexes"),
        ("core", "0074_alter_snapshot_downloaded_at"),
        ("core", "0075_crawl"),
        ("core", "0075_archiveresult_retry_at"),
        ("core", "0076_snapshot_crawl_snapshot_retry_at_snapshot_status_and_more"),
        ("machine", "0002_alter_machine_stats_installedbinary"),
        ("machine", "0004_alter_installedbinary_abspath_and_more"),
    ]
    with use_archivebox_db(tmp_path):
        for app, name in historical_pre_squash_rows:
            MigrationRecorder.Migration.objects.create(app=app, name=name, applied=timezone.now())
        connections["default"].commit()

    result = run_archivebox_cmd(["init"])
    assert result.returncode == 0, f"init refused to recover pre-squash dev DB.\nstdout={result.stdout}\nstderr={result.stderr}"
    assert "migrated by a newer version of ArchiveBox" not in result.stderr


def test_init_with_existing_data_preserves_snapshots(initialized_archive):
    """Test that re-running init preserves existing snapshot data."""
    env = cli_env(disable_extractors=True)

    # Add a snapshot
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )
    run_queued_crawls(initialized_archive, env, timeout=300)

    # Check snapshot was created
    with use_archivebox_db(initialized_archive):
        count_before = Snapshot.objects.count()
    assert count_before == 1

    # Run init again
    result = run_archivebox_cmd(["init"], cwd=initialized_archive)
    assert result.returncode == 0

    # Snapshot should still exist
    with use_archivebox_db(initialized_archive):
        count_after = Snapshot.objects.count()
    assert count_after == count_before


def test_init_quick_flag_skips_checks(tmp_path):
    """Test that init --quick runs faster by skipping some checks."""

    result = run_archivebox_cmd(["init", "--quick"])

    assert result.returncode == 0
    # Database should still be created
    db_path = tmp_path / "index.sqlite3"
    assert db_path.exists()


def test_init_ignores_unrecognized_archive_directories(initialized_archive):
    """Test that init upgrades existing dirs without choking on extra folders."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)
    (initialized_archive / "archive" / "some_random_folder").mkdir(parents=True, exist_ok=True)

    result = run_archivebox_cmd(
        ["init"],
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
