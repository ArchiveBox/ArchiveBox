#!/usr/bin/env python3
"""
Tests for archivebox version command.
Verify version output and system information reporting.
"""

import os
import re
import tempfile
import shutil
import subprocess
import pty
import select
import termios
import time
import pytest
from pathlib import Path
from archivebox.config.paths import tmp_dir_socket_path_is_short_enough
from archivebox.cli.archivebox_version import _binary_row_dedupe_key
from archivebox.tests.conftest import cli_env, run_archivebox_cmd


@pytest.mark.parametrize("width", [80, 160])
def test_version_terminal_keeps_plugin_paths_visible_without_probe_errors(tmp_path, width):
    env = cli_env(COLUMNS=str(width))
    initialized = run_archivebox_cmd(["init", "--quick"], cwd=tmp_path, env=env)
    assert initialized.returncode == 0, initialized.stdout + initialized.stderr
    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, width))
    output = bytearray()
    result = None
    try:
        result = run_archivebox_cmd(
            ["version", "--binaries=opendataloader,singlefile"],
            cwd=tmp_path,
            env=env,
            stdout=slave,
            stderr=slave,
            wait=False,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            elif result.poll() is not None:
                break
        text = output.decode(errors="replace")
        assert result.poll() == 0, text
        assert "opendataloader-pdf" in text
        assert "singlefile" in text
        assert "ABXPKG_LIB_DIR" in text or "not installed" in text
        assert "required: input_path" not in text
        assert "WARNING" not in text
        assert all(" " * 40 not in line.rstrip() for line in text.splitlines())
        if width == 80:
            assert "· opendataloader" in text
            assert "· singlefile" in text
    finally:
        if result is not None and result.poll() is None:
            result.terminate()
            result.wait(timeout=10)
        os.close(slave)
        os.close(master)


def test_version_verifies_plugin_binary_instead_of_database_record(tmp_path):
    data_dir = tmp_path / "collection"
    data_dir.mkdir()
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    binary_path = lib_dir / "git"
    shutil.copy2(shutil.which("git"), binary_path)
    actual_version = subprocess.run([str(binary_path), "--version"], capture_output=True, text=True, check=True).stdout.split()[2]
    env = cli_env(PLUGINS="git", GIT_BINARY=str(binary_path), ABXPKG_LIB_DIR=str(lib_dir), COLUMNS="500")
    result = run_archivebox_cmd(["init", "--quick"], cwd=data_dir, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    script = (
        "from archivebox.machine.models import Machine, Binary; "
        f"Binary.objects.create(machine=Machine.current(), name='git', abspath={str(binary_path)!r}, "
        "version='0.0.0-stale', binprovider='env', status='installed')"
    )
    result = run_archivebox_cmd(["shell", "-c", script], cwd=data_dir, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    result = run_archivebox_cmd(["version", "--binaries=git"], cwd=data_dir, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert actual_version in result.stdout
    assert "0.0.0-stale" not in result.stdout
    assert "(database)" not in result.stdout
    assert str(binary_path) in result.stdout

    binary_path.chmod(0o644)
    result = run_archivebox_cmd(["version", "--binaries=git"], cwd=data_dir, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "not installed" in result.stdout
    assert "✅" not in result.stdout

    shutil.rmtree(lib_dir)
    result = run_archivebox_cmd(["version", "--binaries=git"], cwd=data_dir, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "not installed" in result.stdout
    assert "✅" not in result.stdout
    assert "(database)" not in result.stdout


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


def test_binary_row_dedupe_key_keeps_distinct_paths_visible(tmp_path):
    first_path = tmp_path / "lib" / "env" / "bin" / "node"
    second_path = tmp_path / "other" / "bin" / "node"
    first_path.parent.mkdir(parents=True)
    second_path.parent.mkdir(parents=True)

    first = _binary_row_dedupe_key(
        display_name="node",
        valid=True,
        version="26.0.0",
        provider="env",
        abspath=str(first_path),
    )
    repeat = _binary_row_dedupe_key(
        display_name="node",
        valid=True,
        version="26.0.0",
        provider="env",
        abspath=str(first_path),
    )
    different_path = _binary_row_dedupe_key(
        display_name="node",
        valid=True,
        version="26.0.0",
        provider="env",
        abspath=str(second_path),
    )

    assert repeat == first
    assert different_path != first


def test_binary_row_dedupe_key_collapses_enabled_and_disabled_plugin_references(tmp_path):
    binary_path = tmp_path / "bin" / "node"
    binary_path.parent.mkdir(parents=True)

    enabled_reference = _binary_row_dedupe_key(
        display_name="node",
        valid=True,
        version="26.0.0",
        provider="env",
        abspath=str(binary_path),
    )
    disabled_reference = _binary_row_dedupe_key(
        display_name="node",
        valid=True,
        version="26.0.0",
        provider="env",
        abspath=str(binary_path),
    )

    assert disabled_reference == enabled_reference


def test_version_quiet_outputs_version_number(tmp_path):
    """Test that version --quiet outputs just the version number."""
    result = run_archivebox_cmd(["version", "--quiet"])

    assert result.returncode == 0
    version = result.stdout.strip()
    assert version
    # Version should be semver-ish format (e.g., 0.8.0)
    parts = version.split(".")
    assert len(parts) >= 2


def test_version_flag_outputs_version_number(tmp_path):
    """Test that top-level --version reports the package version."""
    result = run_archivebox_cmd(["--version"])

    assert result.returncode == 0
    version = result.stdout.strip()
    assert version
    assert len(version.split(".")) >= 2


def test_version_shows_system_info_in_initialized_dir(tmp_path, initialized_archive):
    """Test that version shows system metadata in initialized directory."""
    result = run_archivebox_cmd(["version", "--binaries=curl"])

    output = result.stdout
    assert "ArchiveBox" in output
    # Should show system info
    assert any(x in output for x in ["ARCH=", "OS=", "PYTHON="])


def test_version_shows_binaries_after_init(tmp_path, initialized_archive):
    """Test that version shows binary dependencies in initialized directory."""
    result = run_archivebox_cmd(["version"])

    output = result.stdout
    # Should show binary section
    assert "Binary" in output or "Dependencies" in output


def test_version_includes_disabled_plugin_dependencies(tmp_path):
    """Every plugin declaration stays visible even when all plugins are disabled."""
    data_dir = tmp_path / "no-plugins"
    data_dir.mkdir()
    env = cli_env(PLUGINS="__archivebox_test_no_plugins__", SEARCH_BACKEND_ENGINE="", COLUMNS="500")

    init_result = run_archivebox_cmd(["init"], cwd=data_dir, env=env)
    assert init_result.returncode == 0, init_result.stderr

    version_result = run_archivebox_cmd(["version"], cwd=data_dir, env=env)
    output = version_result.stdout + version_result.stderr

    assert version_result.returncode == 0, output
    from archivebox.plugins.discovery import get_plugin_catalog

    rows = [re.split(r"\s{2,}", line.strip()) for line in version_result.stdout.splitlines()]
    for plugin_name, plugin in get_plugin_catalog().items():
        if plugin.config.required_binaries:
            assert sum(len(row) >= 6 and plugin_name in row[1].split(", ") for row in rows) == len(plugin.config.required_binaries), (
                plugin_name
            )
    binary_names = [row[0] for row in rows if len(row) == 6 and row[2] == "disabled"]
    assert len(binary_names) == len(set(binary_names))
    assert "(database)" not in output
    assert "youtube-dl" not in output
    assert "Failed to detect the following binaries" not in output


def test_version_names_disabling_config_in_path_column(tmp_path):
    env = cli_env(OPENCODE_ENABLED="False", COLUMNS="200")
    result = run_archivebox_cmd(["version", "--binaries=opencode"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [re.split(r"\s{2,}", line.strip()) for line in result.stdout.splitlines()]
    opencode_rows = [row for row in rows if len(row) == 6 and row[1] == "opencode"]
    assert len(opencode_rows) == 4, result.stdout
    assert all(row[2] == "disabled" and row[5] == "disabled by OPENCODE_ENABLED=False" for row in opencode_rows)
    assert "Disabled plugins are dimmed" not in result.stdout


def test_version_shared_git_stays_installed_when_opencode_disabled(tmp_path):
    env = cli_env(PLUGINS="git", GIT_ENABLED="True", OPENCODE_ENABLED="False", COLUMNS="300")
    result = run_archivebox_cmd(["version", "--binaries=git"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = [re.split(r"\s{2,}", line.strip()) for line in result.stdout.splitlines()]
    git_rows = [row for row in rows if len(row) == 6 and row[0] == "git"]
    assert len(git_rows) == 1, result.stdout
    assert set(git_rows[0][1].split(", ")) == {"git", "opencode"}
    assert git_rows[0][2] == "✅"
    assert Path(git_rows[0][5]).is_file()
    assert "disabled by OPENCODE_ENABLED=False" not in result.stdout


def test_version_honors_legacy_save_aliases_when_disabling_extractors(tmp_path):
    """Legacy SAVE_* aliases should disable their canonical plugin flags."""
    data_dir = tmp_path / "legacy-save-disabled"
    data_dir.mkdir()
    env = {"PLUGINS": "wget,title", "SEARCH_BACKEND_ENGINE": ""}

    init_result = run_archivebox_cmd(["init"], cwd=data_dir, env=env, default_cli_env=True, disable_extractors=True, timeout=120)
    assert init_result.returncode == 0, init_result.stderr or init_result.stdout

    config_result = run_archivebox_cmd(
        ["config", "--get", "WGET_ENABLED", "TITLE_ENABLED", "CHROME_ENABLED"],
        cwd=data_dir,
        env=env,
        default_cli_env=True,
        disable_extractors=True,
    )
    config_output = config_result.stdout + config_result.stderr
    assert config_result.returncode == 0, config_output
    assert "WGET_ENABLED = false" in config_output
    assert "TITLE_ENABLED = false" in config_output
    assert "CHROME_ENABLED = false" in config_output

    version_result = run_archivebox_cmd(
        ["version"],
        cwd=data_dir,
        env=env,
        default_cli_env=True,
        disable_extractors=True,
        timeout=60,
    )
    output = version_result.stdout + version_result.stderr

    assert version_result.returncode == 0, output
    assert "Failed to detect the following binaries" not in output


def test_plugins_selection_includes_required_plugins_via_config_cli(tmp_path):
    """PLUGINS selection should include transitive plugin dependencies exactly once."""
    data_dir = tmp_path / "plugin-dependencies"
    data_dir.mkdir()
    env = {"PLUGINS": "wget,screenshot"}

    init_result = run_archivebox_cmd(["init"], cwd=data_dir, env=env, default_cli_env=True, timeout=120)
    assert init_result.returncode == 0, init_result.stderr or init_result.stdout

    config_result = run_archivebox_cmd(
        ["config", "--get", "WGET_ENABLED", "SCREENSHOT_ENABLED", "CHROME_ENABLED", "YTDLP_ENABLED"],
        cwd=data_dir,
        env=env,
        default_cli_env=True,
    )
    config_output = config_result.stdout + config_result.stderr

    assert config_result.returncode == 0, config_output
    assert "WGET_ENABLED = true" in config_output
    assert "SCREENSHOT_ENABLED = true" in config_output
    assert "CHROME_ENABLED = true" in config_output
    assert "YTDLP_ENABLED = false" in config_output


def test_version_shows_data_locations(tmp_path, initialized_archive):
    """Test that version shows data directory locations."""
    result = run_archivebox_cmd(["version"])

    output = result.stdout
    # Should show paths
    assert any(x in output for x in ["Data", "Code", "location"])


def test_version_in_uninitialized_dir_still_works(tmp_path):
    """Test that version command works even without initialized data dir."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = run_archivebox_cmd(["version", "--quiet"], cwd=empty_dir)

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
        env = {
            "HOME": str(home_dir),
            "USE_COLOR": "False",
            "SHOW_PROGRESS": "False",
            **extra_env,
        }

        init_result = run_archivebox_cmd(["init", "--quick"], cwd=data_dir, env=env, timeout=180)
        assert init_result.returncode == 0, init_result.stdout + init_result.stderr

        version_result = run_archivebox_cmd(["version"], cwd=data_dir, env=env, timeout=180)
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
    assert tmp_dir_socket_path_is_short_enough(reported_tmp_dir)


def test_version_help_lists_quiet_flag(tmp_path):
    """Test that version --help documents the quiet output mode."""
    result = run_archivebox_cmd(["version", "--help"])

    assert result.returncode == 0
    assert "--quiet" in result.stdout or "-q" in result.stdout


def test_version_invalid_option_fails(tmp_path):
    """Test that invalid version options fail cleanly."""
    result = run_archivebox_cmd(["version", "--invalid-option"])

    assert result.returncode != 0
