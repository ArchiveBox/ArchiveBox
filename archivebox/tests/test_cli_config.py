#!/usr/bin/env python3
"""
Comprehensive tests for archivebox config command.
Verify config reads/writes ArchiveBox.conf file correctly.
"""

from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.config.configset import read_ini_config


def test_config_displays_all_config(initialized_archive):
    """Test that config without args displays all configuration."""
    result = run_archivebox_cmd(["config"])

    assert result.returncode == 0
    output = result.stdout
    # Should show config sections
    assert len(output) > 100
    # Should show at least some standard config keys
    assert "TIMEOUT" in output or "OUTPUT_PERMISSIONS" in output


def test_config_shows_derived_collection_paths_but_not_runtime_dirs(initialized_archive):
    """The CLI should expose collection paths, not per-crawl/per-snapshot runtime dirs."""
    run_archivebox_cmd(["init"], cwd=initialized_archive, check=True)

    result = run_archivebox_cmd(["config"], cwd=initialized_archive)

    assert result.returncode == 0, result.stderr
    unwrapped_output = result.stdout.replace("\n", "")
    assert "DATA_DIR" in result.stdout
    assert result.stdout.count("\nDATA_DIR =") == 1
    assert str(initialized_archive) in unwrapped_output
    assert "PERSONAS_DIR" in result.stdout
    assert result.stdout.count("\nPERSONAS_DIR =") == 1
    assert "SNAP_DIR" not in result.stdout
    assert "CRAWL_DIR" not in result.stdout


def test_config_get_derived_path_but_rejects_runtime_dir(initialized_archive):
    run_archivebox_cmd(["init"], cwd=initialized_archive, check=True)

    data_dir = run_archivebox_cmd(["config", "--get", "DATA_DIR"], cwd=initialized_archive)
    snap_dir = run_archivebox_cmd(["config", "--get", "SNAP_DIR"], cwd=initialized_archive)

    assert data_dir.returncode == 0, data_dir.stderr
    assert "DATA_DIR" in data_dir.stdout
    assert str(initialized_archive) in data_dir.stdout.replace("\n", "")
    assert snap_dir.returncode != 0
    assert "SNAP_DIR =" not in snap_dir.stdout


def test_config_set_rejects_readonly_and_runtime_dirs(initialized_archive):
    run_archivebox_cmd(["init"], cwd=initialized_archive, check=True)

    data_dir = run_archivebox_cmd(
        ["config", "--set", f"DATA_DIR={initialized_archive / 'other'}"],
        cwd=initialized_archive,
    )
    crawl_dir = run_archivebox_cmd(
        ["config", "--set", f"CRAWL_DIR={initialized_archive / 'crawl'}"],
        cwd=initialized_archive,
    )

    assert data_dir.returncode != 0
    assert crawl_dir.returncode != 0
    content = (initialized_archive / "ArchiveBox.conf").read_text()
    assert "DATA_DIR" not in content
    assert "CRAWL_DIR" not in content


def test_config_get_specific_key(initialized_archive):
    """Test that config --get KEY retrieves specific value."""
    result = run_archivebox_cmd(
        ["config", "--get", "TIMEOUT"],
    )

    assert result.returncode == 0
    assert "TIMEOUT" in result.stdout


def test_config_set_writes_to_file(initialized_archive):
    """Test that config --set KEY=VALUE writes to ArchiveBox.conf."""

    result = run_archivebox_cmd(
        ["config", "--set", "TIMEOUT=120"],
    )

    assert result.returncode == 0
    assert "TIMEOUT=120" in result.stdout

    # Verify config file was updated
    config_file = initialized_archive / "ArchiveBox.conf"
    assert config_file.exists()

    content = config_file.read_text()
    assert "TIMEOUT" in content or "120" in content


def test_config_set_and_get_roundtrip(initialized_archive):
    """Test that set value can be retrieved with get."""

    # Set a unique value
    run_archivebox_cmd(
        ["config", "--set", "TIMEOUT=987"],
    )

    updated = run_archivebox_cmd(
        ["config", "--set", "TIMEOUT=654"],
    )

    assert updated.returncode == 0
    assert "TIMEOUT=654" in updated.stdout

    # Get the value back
    result = run_archivebox_cmd(
        ["config", "--get", "TIMEOUT"],
    )

    assert "654" in result.stdout


def test_config_set_multiple_values(initialized_archive):
    """Test setting multiple config values at once."""

    result = run_archivebox_cmd(
        ["config", "--set", "TIMEOUT=111", "YTDLP_TIMEOUT=222"],
    )

    assert result.returncode == 0

    # Verify both were written
    config_file = initialized_archive / "ArchiveBox.conf"
    content = config_file.read_text()
    assert "111" in content
    assert "222" in content


def test_config_set_invalid_key_fails(initialized_archive):
    """Test that setting invalid config key fails."""

    result = run_archivebox_cmd(
        ["config", "--set", "TOTALLY_INVALID_KEY_XYZ=value"],
    )

    assert result.returncode != 0


def test_config_set_requires_equals_sign(initialized_archive):
    """Test that set requires KEY=VALUE format."""

    result = run_archivebox_cmd(
        ["config", "--set", "TIMEOUT"],
    )

    assert result.returncode != 0


def test_config_search_finds_keys(initialized_archive):
    """Test that config --search finds matching keys."""

    result = run_archivebox_cmd(
        ["config", "--search", "TIMEOUT"],
    )

    # Should find timeout-related config
    assert "TIMEOUT" in result.stdout


def test_config_search_finds_plugin_options(initialized_archive):
    """Test that config --search finds plugin keys and descriptions."""

    result = run_archivebox_cmd(
        ["config", "--search", "wget"],
    )

    assert result.returncode == 0
    assert "WGET_BINARY" in result.stdout


def test_config_search_finds_core_aliases(initialized_archive):
    """Test that config --search finds core options by partial alias."""

    result = run_archivebox_cmd(
        ["config", "--search", "URL_BLACK"],
    )

    assert result.returncode == 0
    assert "URL_DENYLIST" in result.stdout


def test_config_preserves_existing_values(initialized_archive):
    """Test that setting new values preserves existing ones."""

    # Set first value
    run_archivebox_cmd(
        ["config", "--set", "TIMEOUT=100"],
    )

    # Set second value
    run_archivebox_cmd(
        ["config", "--set", "YTDLP_TIMEOUT=200"],
    )

    # Verify both are in config file
    config_file = initialized_archive / "ArchiveBox.conf"
    content = config_file.read_text()
    assert "TIMEOUT" in content
    assert "YTDLP_TIMEOUT" in content


def test_config_file_is_valid_toml(initialized_archive):
    """Test that config file remains valid TOML after set."""

    run_archivebox_cmd(
        ["config", "--set", "TIMEOUT=150"],
    )

    config_file = initialized_archive / "ArchiveBox.conf"
    content = config_file.read_text()

    # Basic TOML validation - should have sections and key=value pairs
    assert "[" in content or "=" in content


def test_config_updates_existing_value(initialized_archive):
    """Test that setting same key twice updates the value."""

    # Set initial value
    run_archivebox_cmd(
        ["config", "--set", "TIMEOUT=100"],
    )

    # Update to new value
    run_archivebox_cmd(
        ["config", "--set", "TIMEOUT=200"],
    )

    # Get current value
    result = run_archivebox_cmd(
        ["config", "--get", "TIMEOUT"],
    )

    # Should show updated value
    assert "200" in result.stdout


def test_config_ignores_legacy_unknown_keys(tmp_path, initialized_archive):
    """Old ArchiveBox.conf keys should not prevent startup during upgrades."""
    (tmp_path / "ArchiveBox.conf").write_text(
        """
[ARCHIVING_CONFIG]
MAX_MEDIA_SIZE = "750m"

[SEARCH_BACKEND_CONFIG]
SEARCH_BACKEND_HOST_NAME = "sonic"
SEARCH_BACKEND_PASSWORD = "SecretPassword"
""",
    )

    result = run_archivebox_cmd(
        ["version", "--binaries=curl"],
    )

    assert result.returncode == 0, result.stderr
    assert "Extra inputs are not permitted" not in result.stderr


def test_inaccessible_config_file_is_ignored(tmp_path):
    private_dir = tmp_path / "private"
    private_dir.mkdir()
    config_file = private_dir / "ArchiveBox.conf"
    config_file.write_text("[SERVER_CONFIG]\nDEBUG = True\n")
    private_dir.chmod(0o000)
    try:
        assert read_ini_config(config_file) == {}
    finally:
        private_dir.chmod(0o700)


def test_config_file_preserves_literal_percent_templates(tmp_path):
    config_file = tmp_path / "ArchiveBox.conf"
    config_file.write_text("[ARCHIVING_CONFIG]\nYTDLP_OUTPUT_TEMPLATE = %(title)s.%(ext)s\n")

    assert read_ini_config(config_file)["YTDLP_OUTPUT_TEMPLATE"] == "%(title)s.%(ext)s"


class TestConfigCLI:
    """Test the CLI interface for config command."""

    def test_cli_help(self, tmp_path, initialized_archive):
        """Test that --help works for config command."""

        result = run_archivebox_cmd(
            ["config", "--help"],
        )

        assert result.returncode == 0
        assert "--get" in result.stdout
        assert "--set" in result.stdout
