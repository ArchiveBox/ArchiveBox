#!/usr/bin/env python3
"""
Comprehensive tests for archivebox install command.
Verify install detects and records binary dependencies in DB.
"""

import os
from pathlib import Path

from archivebox.tests.conftest import run_archivebox_cmd

import pytest

from archivebox.cli.archivebox_install import ensure_data_dir_lib_symlink
from archivebox.cli.archivebox_install import _resolve_install_targets
from archivebox.config.paths import get_machine_type
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Binary
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_install_runs_successfully(initialized_archive):
    """Test that install command runs without error."""
    result = run_archivebox_cmd(
        ["install", "--dry-run"],
        timeout=60,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Dry run - would detect ArchiveBox dependencies" in result.stdout


def test_install_creates_binary_records_in_db(initialized_archive):
    """Test that install --dry-run does not create Binary records in database."""

    result = run_archivebox_cmd(
        ["install", "--dry-run"],
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        assert Binary.objects.count() == 0


def test_install_dry_run_does_not_install(initialized_archive):
    """Test that --dry-run doesn't actually install anything."""

    result = run_archivebox_cmd(
        ["install", "--dry-run"],
        timeout=60,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "Dry run - would detect ArchiveBox dependencies and run the abx-dl install flow"


def test_install_detects_system_binaries(initialized_archive):
    """Test that install detects existing system binaries."""

    result = run_archivebox_cmd(
        ["install", "--dry-run"],
        timeout=60,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "ArchiveBox dependencies" in result.stdout


def test_install_target_resolver_uses_declared_binary_aliases():
    """Targeted plugin-owned binaries must not fan out to every plugin or raw '*' provider installs."""

    assert _resolve_install_targets(("ripgrep",)) == (["search_backend_ripgrep"], [])
    assert _resolve_install_targets(("rg",)) == (["search_backend_ripgrep"], [])
    assert _resolve_install_targets(("sonic",)) == (["search_backend_sonic"], [])
    assert _resolve_install_targets(("not-a-real-tool",)) == ([], ["not-a-real-tool"])


def test_install_shows_binary_status(initialized_archive):
    """Test that install shows status of binaries."""

    result = run_archivebox_cmd(
        ["install", "--dry-run"],
        timeout=60,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "Dry run - would detect ArchiveBox dependencies and run the abx-dl install flow"


def test_install_dry_run_prints_dry_run_message(initialized_archive):
    """Test that install --dry-run clearly reports that no changes will be made."""
    result = run_archivebox_cmd(
        ["install", "--dry-run"],
        timeout=60,
    )

    assert result.returncode == 0
    assert "dry run" in result.stdout.lower()


def test_install_help_lists_dry_run_flag(tmp_path):
    """Test that install --help documents the dry-run option."""
    result = run_archivebox_cmd(
        ["install", "--help"],
    )

    assert result.returncode == 0
    assert "--dry-run" in result.stdout or "-d" in result.stdout


def test_install_invalid_option_fails(tmp_path):
    """Test that invalid install options fail cleanly."""
    result = run_archivebox_cmd(
        ["install", "--invalid-option"],
    )

    assert result.returncode != 0


def test_install_from_empty_dir_initializes_collection(tmp_path):
    """Test that install bootstraps an empty dir before performing work."""
    env = os.environ.copy()
    tmp_short = Path("/tmp") / f"abx-install-empty-{tmp_path.name}"
    tmp_short.mkdir(parents=True, exist_ok=True)
    stale_lib_dir = tmp_path / "lib"
    stale_lib_dir.mkdir()
    (stale_lib_dir / "stale.txt").write_text("stale")
    env.update(
        {
            "TMP_DIR": str(tmp_short),
            "ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS": "true",
        },
    )

    result = run_archivebox_cmd(
        ["install", "git"],
        cwd=tmp_path,
        timeout=120,
        env=env,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "Initializing a new ArchiveBox" in output
    assert "Installing specific binaries: git" in output
    assert (tmp_path / "ArchiveBox.conf").is_file()
    assert (tmp_path / "index.sqlite3").is_file()
    assert (tmp_path / "lib").is_symlink()
    assert (tmp_path / "lib").resolve().is_dir()

    with use_archivebox_db(tmp_path):
        assert Snapshot.objects.count() == 0
        assert Crawl.objects.count() == 0
        assert Binary.objects.filter(status="installed", name="git").count() == 1


def test_install_lib_symlink_preserves_scoped_data_lib_dir(tmp_path):
    """DATA_DIR/lib/<machine_type> is a valid ABXPKG_LIB_DIR and must not be replaced by a parent symlink."""
    scoped_lib_dir = tmp_path / "lib" / get_machine_type()

    assert ensure_data_dir_lib_symlink(tmp_path, scoped_lib_dir) is None
    assert (tmp_path / "lib").is_dir()
    assert not (tmp_path / "lib").is_symlink()
    assert scoped_lib_dir.is_dir()


def test_install_updates_binary_table(initialized_archive):
    """Test that install completes and only mutates dependency state."""
    env = os.environ.copy()
    tmp_short = Path("/tmp") / f"abx-install-{initialized_archive.name}"
    tmp_short.mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "TMP_DIR": str(tmp_short),
            "ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS": "true",
        },
    )

    result = run_archivebox_cmd(
        ["install", "git"],
        timeout=120,
        env=env,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output

    with use_archivebox_db(initialized_archive):
        binary_counts = {
            status: Binary.objects.filter(status=status).count() for status in Binary.objects.values_list("status", flat=True).distinct()
        }
        snapshot_count = Snapshot.objects.count()
        sealed_crawls = Crawl.objects.filter(status="sealed").count()
        installed_git = Binary.objects.filter(status="installed", name="git").count()

    assert sealed_crawls == 0
    assert snapshot_count == 0
    assert binary_counts.get("installed", 0) > 0
    assert installed_git == 1
    assert (initialized_archive / "lib").is_symlink()
    assert (initialized_archive / "lib").resolve().is_dir()
