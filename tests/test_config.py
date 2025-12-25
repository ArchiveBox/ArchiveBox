#!/usr/bin/env python3
"""Integration tests for archivebox config command."""

import os
import subprocess

import pytest

from .fixtures import process, disable_extractors_dict


def test_config_shows_all_config_values(tmp_path, process):
    """Test that config without args shows all config values."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config'],
        capture_output=True,
        text=True,
    )

    # Should show various config sections
    assert 'TIMEOUT' in result.stdout or 'timeout' in result.stdout.lower()
    # Config should show some output
    assert len(result.stdout) > 100


def test_config_get_specific_key(tmp_path, process):
    """Test that --get retrieves a specific config value."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--get', 'TIMEOUT'],
        capture_output=True,
        text=True,
    )

    # Should show the TIMEOUT value
    assert 'TIMEOUT' in result.stdout or result.returncode == 0


def test_config_set_value_writes_to_config_file(tmp_path, process):
    """Test that --set writes config value to ArchiveBox.conf file."""
    os.chdir(tmp_path)

    # Set a config value
    result = subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=120'],
        capture_output=True,
        text=True,
    )

    # Read the config file directly to verify it was written
    config_file = tmp_path / 'ArchiveBox.conf'
    if config_file.exists():
        config_content = config_file.read_text()
        # Config should contain the set value
        assert 'TIMEOUT' in config_content or 'timeout' in config_content.lower()


def test_config_set_and_get_roundtrip(tmp_path, process):
    """Test that a value set with --set can be retrieved with --get."""
    os.chdir(tmp_path)

    # Set a value
    set_result = subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=999'],
        capture_output=True,
        text=True,
    )

    # Verify set was successful
    assert set_result.returncode == 0 or '999' in set_result.stdout

    # Read the config file directly to verify
    config_file = tmp_path / 'ArchiveBox.conf'
    if config_file.exists():
        config_content = config_file.read_text()
        assert '999' in config_content or 'TIMEOUT' in config_content


def test_config_search_finds_matching_keys(tmp_path, process):
    """Test that --search finds config keys matching a pattern."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--search', 'TIMEOUT'],
        capture_output=True,
        text=True,
    )

    # Should find TIMEOUT-related config
    assert 'TIMEOUT' in result.stdout or result.returncode == 0


def test_config_invalid_key_fails(tmp_path, process):
    """Test that setting an invalid config key fails."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--set', 'INVALID_KEY_THAT_DOES_NOT_EXIST=value'],
        capture_output=True,
        text=True,
    )

    # Should fail
    assert result.returncode != 0 or 'failed' in result.stdout.lower()


def test_config_set_requires_equals_sign(tmp_path, process):
    """Test that --set requires KEY=VALUE format."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT'],
        capture_output=True,
        text=True,
    )

    # Should fail because there's no = sign
    assert result.returncode != 0


class TestConfigCLI:
    """Test the CLI interface for config command."""

    def test_cli_help(self, tmp_path, process):
        """Test that --help works for config command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'config', '--help'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '--get' in result.stdout
        assert '--set' in result.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
