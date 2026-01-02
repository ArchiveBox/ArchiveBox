#!/usr/bin/env python3
"""
Tests for archivebox version command.
Verify version output and system information reporting.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_version_quiet_outputs_version_number(tmp_path):
    """Test that version --quiet outputs just the version number."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'version', '--quiet'], capture_output=True, text=True)

    assert result.returncode == 0
    version = result.stdout.strip()
    assert version
    # Version should be semver-ish format (e.g., 0.8.0)
    parts = version.split('.')
    assert len(parts) >= 2


def test_version_shows_system_info_in_initialized_dir(tmp_path, process):
    """Test that version shows system metadata in initialized directory."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'version'], capture_output=True, text=True)

    output = result.stdout
    assert 'ArchiveBox' in output
    # Should show system info
    assert any(x in output for x in ['ARCH=', 'OS=', 'PYTHON='])


def test_version_shows_binaries_after_init(tmp_path, process):
    """Test that version shows binary dependencies in initialized directory."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'version'], capture_output=True, text=True)

    output = result.stdout
    # Should show binary section
    assert 'Binary' in output or 'Dependencies' in output


def test_version_shows_data_locations(tmp_path, process):
    """Test that version shows data directory locations."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'version'], capture_output=True, text=True)

    output = result.stdout
    # Should show paths
    assert any(x in output for x in ['Data', 'Code', 'location'])


def test_version_in_uninitialized_dir_still_works(tmp_path):
    """Test that version command works even without initialized data dir."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    os.chdir(empty_dir)

    result = subprocess.run(['archivebox', 'version', '--quiet'], capture_output=True, text=True)

    # Should still output version
    assert result.returncode == 0
    assert len(result.stdout.strip()) > 0
