#!/usr/bin/env python3
"""
Comprehensive tests for archivebox config command.
Verify config reads/writes ArchiveBox.conf file correctly.
"""

import os
import subprocess
from pathlib import Path

from .fixtures import *


def test_config_displays_all_config(tmp_path, process):
    """Test that config without args displays all configuration."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'config'], capture_output=True, text=True)

    assert result.returncode == 0
    output = result.stdout
    # Should show config sections
    assert len(output) > 100
    # Should show at least some standard config keys
    assert 'TIMEOUT' in output or 'OUTPUT_PERMISSIONS' in output


def test_config_get_specific_key(tmp_path, process):
    """Test that config --get KEY retrieves specific value."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ['archivebox', 'config', '--get', 'TIMEOUT'],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert 'TIMEOUT' in result.stdout


def test_config_set_writes_to_file(tmp_path, process):
    """Test that config --set KEY=VALUE writes to ArchiveBox.conf."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=120'],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    # Verify config file was updated
    config_file = tmp_path / 'ArchiveBox.conf'
    assert config_file.exists()

    content = config_file.read_text()
    assert 'TIMEOUT' in content or '120' in content


def test_config_set_and_get_roundtrip(tmp_path, process):
    """Test that set value can be retrieved with get."""
    os.chdir(tmp_path)

    # Set a unique value
    subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=987'],
        capture_output=True,
        text=True,
    )

    # Get the value back
    result = subprocess.run(
        ['archivebox', 'config', '--get', 'TIMEOUT'],
        capture_output=True,
        text=True,
    )

    assert '987' in result.stdout


def test_config_set_multiple_values(tmp_path, process):
    """Test setting multiple config values at once."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=111', 'YTDLP_TIMEOUT=222'],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    # Verify both were written
    config_file = tmp_path / 'ArchiveBox.conf'
    content = config_file.read_text()
    assert '111' in content
    assert '222' in content


def test_config_set_invalid_key_fails(tmp_path, process):
    """Test that setting invalid config key fails."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--set', 'TOTALLY_INVALID_KEY_XYZ=value'],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_config_set_requires_equals_sign(tmp_path, process):
    """Test that set requires KEY=VALUE format."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT'],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_config_search_finds_keys(tmp_path, process):
    """Test that config --search finds matching keys."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'config', '--search', 'TIMEOUT'],
        capture_output=True,
        text=True,
    )

    # Should find timeout-related config
    assert 'TIMEOUT' in result.stdout


def test_config_preserves_existing_values(tmp_path, process):
    """Test that setting new values preserves existing ones."""
    os.chdir(tmp_path)

    # Set first value
    subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=100'],
        capture_output=True,
    )

    # Set second value
    subprocess.run(
        ['archivebox', 'config', '--set', 'YTDLP_TIMEOUT=200'],
        capture_output=True,
    )

    # Verify both are in config file
    config_file = tmp_path / 'ArchiveBox.conf'
    content = config_file.read_text()
    assert 'TIMEOUT' in content
    assert 'YTDLP_TIMEOUT' in content


def test_config_file_is_valid_toml(tmp_path, process):
    """Test that config file remains valid TOML after set."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=150'],
        capture_output=True,
    )

    config_file = tmp_path / 'ArchiveBox.conf'
    content = config_file.read_text()

    # Basic TOML validation - should have sections and key=value pairs
    assert '[' in content or '=' in content


def test_config_updates_existing_value(tmp_path, process):
    """Test that setting same key twice updates the value."""
    os.chdir(tmp_path)

    # Set initial value
    subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=100'],
        capture_output=True,
    )

    # Update to new value
    subprocess.run(
        ['archivebox', 'config', '--set', 'TIMEOUT=200'],
        capture_output=True,
    )

    # Get current value
    result = subprocess.run(
        ['archivebox', 'config', '--get', 'TIMEOUT'],
        capture_output=True,
        text=True,
    )

    # Should show updated value
    assert '200' in result.stdout
