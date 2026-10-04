#!/usr/bin/env python3
"""
Comprehensive tests for archivebox config command.
Verify config reads/writes ArchiveBox.conf file correctly.
"""

from archivebox.tests.conftest import run_archivebox_cmd
from archivebox.config.configset import read_ini_config


def test_config_read_get_and_search_cover_core_plugin_alias_and_path_options(initialized_archive):
    """Exercise every read-only CLI branch against one unchanged collection."""
    result = run_archivebox_cmd(["config"], cwd=initialized_archive)
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert len(output) > 100
    assert "TIMEOUT" in output or "OUTPUT_PERMISSIONS" in output
    assert "DATA_DIR" in output
    assert output.count("\nDATA_DIR =") == 1
    assert str(initialized_archive) in output.replace("\n", "")
    assert "PERSONAS_DIR" in output
    assert output.count("\nPERSONAS_DIR =") == 1
    assert "SNAP_DIR" not in output
    assert "CRAWL_DIR" not in output

    data_dir = run_archivebox_cmd(["config", "--get", "DATA_DIR"], cwd=initialized_archive)
    snap_dir = run_archivebox_cmd(["config", "--get", "SNAP_DIR"], cwd=initialized_archive)

    assert data_dir.returncode == 0, data_dir.stderr
    assert "DATA_DIR" in data_dir.stdout
    assert str(initialized_archive) in data_dir.stdout.replace("\n", "")
    assert snap_dir.returncode != 0
    assert "SNAP_DIR =" not in snap_dir.stdout

    result = run_archivebox_cmd(
        ["config", "--get", "TIMEOUT"],
    )

    assert result.returncode == 0
    assert "TIMEOUT" in result.stdout

    for query, expected in (("TIMEOUT", "TIMEOUT"), ("wget", "WGET_BINARY"), ("URL_BLACK", "URL_DENYLIST")):
        result = run_archivebox_cmd(["config", "--search", query])
        assert result.returncode == 0, result.stderr
        assert expected in result.stdout, query


def test_config_rejects_readonly_runtime_unknown_and_malformed_keys(initialized_archive):
    """Each rejected input must fail through its own CLI validation branch."""
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

    result = run_archivebox_cmd(
        ["config", "--set", "TOTALLY_INVALID_KEY_XYZ=value"],
    )

    assert result.returncode != 0

    result = run_archivebox_cmd(
        ["config", "--set", "TIMEOUT"],
    )

    assert result.returncode != 0


def test_config_set_update_get_preserves_other_keys(initialized_archive):
    """Exercise each write path against one real config, checking each transition."""
    result = run_archivebox_cmd(["config", "--set", "TIMEOUT=120"])
    assert result.returncode == 0, result.stderr
    assert "TIMEOUT=120" in result.stdout
    config_file = initialized_archive / "ArchiveBox.conf"
    assert config_file.is_file()
    content = config_file.read_text()
    assert "TIMEOUT" in content and "120" in content
    assert "[" in content or "=" in content
    assert read_ini_config(config_file)["TIMEOUT"] == "120"

    result = run_archivebox_cmd(["config", "--set", "YTDLP_TIMEOUT=200"])
    assert result.returncode == 0, result.stderr
    content = config_file.read_text()
    assert "TIMEOUT" in content
    assert "YTDLP_TIMEOUT" in content
    assert read_ini_config(config_file)["TIMEOUT"] == "120"
    assert read_ini_config(config_file)["YTDLP_TIMEOUT"] == "200"

    updated = run_archivebox_cmd(["config", "--set", "TIMEOUT=654"])
    assert updated.returncode == 0, updated.stderr
    assert "TIMEOUT=654" in updated.stdout
    result = run_archivebox_cmd(["config", "--get", "TIMEOUT"])
    assert result.returncode == 0, result.stderr
    assert "654" in result.stdout
    assert read_ini_config(config_file)["TIMEOUT"] == "654"
    assert read_ini_config(config_file)["YTDLP_TIMEOUT"] == "200"


def test_config_set_multiple_values_in_fresh_sections(initialized_archive):
    """Keep first writes into new sections distinct from updating existing keys."""
    result = run_archivebox_cmd(["config", "--set", "TIMEOUT=111", "YTDLP_TIMEOUT=222"])
    assert result.returncode == 0, result.stderr
    config_file = initialized_archive / "ArchiveBox.conf"
    content = config_file.read_text()
    assert "111" in content
    assert "222" in content
    assert read_ini_config(config_file)["TIMEOUT"] == "111"
    assert read_ini_config(config_file)["YTDLP_TIMEOUT"] == "222"


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
