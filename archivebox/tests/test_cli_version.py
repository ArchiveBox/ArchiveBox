#!/usr/bin/env python3
"""
Tests for archivebox version command.
Verify version output and system information reporting.
"""

import os
import re
import sys
import tempfile
import subprocess
from pathlib import Path

from .fixtures import process

FIXTURES = (process,)


def _archivebox_cli() -> str:
    cli = Path(sys.executable).with_name("archivebox")
    return str(cli if cli.exists() else "archivebox")


def _run_real_cli(
    args: list[str],
    cwd: Path,
    *,
    home_dir: Path,
    timeout: int = 180,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("DATA_DIR", None)
    env["HOME"] = str(home_dir)
    env["USE_COLOR"] = "False"
    env["SHOW_PROGRESS"] = "False"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [_archivebox_cli(), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=timeout,
    )


def _make_deep_collection_dir(tmp_path: Path) -> Path:
    deep_dir = tmp_path / "deep-collection"
    for idx in range(6):
        deep_dir /= f"segment-{idx}-1234567890abcdef"
    deep_dir.mkdir(parents=True)
    return deep_dir


def _extract_location_path(output: str, key: str) -> Path:
    for line in output.splitlines():
        if key not in line:
            continue
        columns = [column for column in re.split(r"\s{2,}", line.strip()) if column]
        if len(columns) >= 5 and columns[1] == key:
            return Path(os.path.expanduser(columns[-1]))
    raise AssertionError(f"Did not find a {key} location line in output:\n{output}")


def test_version_quiet_outputs_version_number(tmp_path):
    """Test that version --quiet outputs just the version number."""
    os.chdir(tmp_path)
    result = subprocess.run(["archivebox", "version", "--quiet"], capture_output=True, text=True)

    assert result.returncode == 0
    version = result.stdout.strip()
    assert version
    # Version should be semver-ish format (e.g., 0.8.0)
    parts = version.split(".")
    assert len(parts) >= 2


def test_version_flag_outputs_version_number(tmp_path):
    """Test that top-level --version reports the package version."""
    os.chdir(tmp_path)
    result = subprocess.run(["archivebox", "--version"], capture_output=True, text=True)

    assert result.returncode == 0
    version = result.stdout.strip()
    assert version
    assert len(version.split(".")) >= 2


def test_version_shows_system_info_in_initialized_dir(tmp_path, process):
    """Test that version shows system metadata in initialized directory."""
    os.chdir(tmp_path)
    result = subprocess.run(["archivebox", "version"], capture_output=True, text=True)

    output = result.stdout
    assert "ArchiveBox" in output
    # Should show system info
    assert any(x in output for x in ["ARCH=", "OS=", "PYTHON="])


def test_version_shows_binaries_after_init(tmp_path, process):
    """Test that version shows binary dependencies in initialized directory."""
    os.chdir(tmp_path)
    result = subprocess.run(["archivebox", "version"], capture_output=True, text=True)

    output = result.stdout
    # Should show binary section
    assert "Binary" in output or "Dependencies" in output


def test_version_shows_data_locations(tmp_path, process):
    """Test that version shows data directory locations."""
    os.chdir(tmp_path)
    result = subprocess.run(["archivebox", "version"], capture_output=True, text=True)

    output = result.stdout
    # Should show paths
    assert any(x in output for x in ["Data", "Code", "location"])


def test_version_in_uninitialized_dir_still_works(tmp_path):
    """Test that version command works even without initialized data dir."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    os.chdir(empty_dir)

    result = subprocess.run(["archivebox", "version", "--quiet"], capture_output=True, text=True)

    # Should still output version
    assert result.returncode == 0
    assert len(result.stdout.strip()) > 0


def test_version_auto_selects_short_tmp_dir_for_deep_collection_path(tmp_path):
    """Test the real CLI init/version flow auto-selects a short TMP_DIR outside deep collections."""
    data_dir = _make_deep_collection_dir(tmp_path)
    default_tmp_dir = data_dir / "tmp"
    extra_env = {"ARCHIVEBOX_ALLOW_NO_UNIX_SOCKETS": "true"}

    with tempfile.TemporaryDirectory(prefix="abx-home-") as home_tmp:
        home_dir = Path(home_tmp)

        init_result = _run_real_cli(["init", "--quick"], cwd=data_dir, home_dir=home_dir, extra_env=extra_env)
        assert init_result.returncode == 0, init_result.stdout + init_result.stderr

        version_result = _run_real_cli(["version"], cwd=data_dir, home_dir=home_dir, extra_env=extra_env)
        output = version_result.stdout + version_result.stderr

    assert version_result.returncode == 0, output
    assert "ArchiveBox" in output
    assert "TMP_DIR" in output
    assert "Error with configured TMP_DIR" not in output

    reported_tmp_dir = _extract_location_path(output, "TMP_DIR")
    if not reported_tmp_dir.is_absolute():
        reported_tmp_dir = (data_dir / reported_tmp_dir).resolve()

    assert reported_tmp_dir.exists()
    assert not reported_tmp_dir.is_relative_to(default_tmp_dir)
    assert len(f"file://{reported_tmp_dir / 'supervisord.sock'}") <= 96


def test_version_help_lists_quiet_flag(tmp_path):
    """Test that version --help documents the quiet output mode."""
    os.chdir(tmp_path)
    result = subprocess.run(["archivebox", "version", "--help"], capture_output=True, text=True)

    assert result.returncode == 0
    assert "--quiet" in result.stdout or "-q" in result.stdout


def test_version_invalid_option_fails(tmp_path):
    """Test that invalid version options fail cleanly."""
    os.chdir(tmp_path)
    result = subprocess.run(["archivebox", "version", "--invalid-option"], capture_output=True, text=True)

    assert result.returncode != 0
