#!/usr/bin/env python3
"""Integration tests for archivebox version command."""

import os
import subprocess
import json

import pytest

from .fixtures import process, disable_extractors_dict


class TestVersionQuiet:
    """Test the quiet/minimal version output."""

    def test_version_prints_version_number(self, tmp_path):
        """Test that version prints the version number."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'version', '--quiet'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Should contain a version string like "0.8.0" or similar
        version = result.stdout.strip()
        assert version
        # Version should be a valid semver-ish format
        parts = version.split('.')
        assert len(parts) >= 2  # At least major.minor

    def test_version_flag_prints_version_number(self, tmp_path):
        """Test that --version flag prints the version number."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', '--version'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        version = result.stdout.strip()
        assert version
        parts = version.split('.')
        assert len(parts) >= 2


class TestVersionFull:
    """Test the full version output."""

    def test_version_shows_system_info(self, tmp_path, process):
        """Test that version shows system information."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'version'],
            capture_output=True,
            text=True,
        )

        output = result.stdout

        # Should show basic system info (exit code may be 1 if binaries missing)
        assert 'ArchiveBox' in output

    def test_version_shows_binary_section(self, tmp_path, process):
        """Test that version shows binary dependencies section."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'version'],
            capture_output=True,
            text=True,
        )

        output = result.stdout

        # Should show binary dependencies section
        assert 'Binary' in output or 'Dependenc' in output

    def test_version_shows_data_locations(self, tmp_path, process):
        """Test that version shows data locations."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'version'],
            capture_output=True,
            text=True,
        )

        output = result.stdout

        # Should show data/code locations
        assert 'Data' in output or 'location' in output.lower() or 'DIR' in output or 'Code' in output


class TestVersionWithBinaries:
    """Test version output after running install."""

    def test_version_shows_binary_status(self, tmp_path, process, disable_extractors_dict):
        """Test that version shows binary status (installed or not)."""
        os.chdir(tmp_path)

        # First run install (with dry-run to speed up)
        subprocess.run(
            ['archivebox', 'install', '--dry-run'],
            capture_output=True,
            text=True,
            env=disable_extractors_dict,
        )

        # Now check version
        result = subprocess.run(
            ['archivebox', 'version'],
            capture_output=True,
            text=True,
            env=disable_extractors_dict,
        )

        output = result.stdout

        # Should show binary status (either installed or not installed)
        assert 'installed' in output.lower() or 'Binary' in output


class TestVersionCLI:
    """Test the CLI interface for version command."""

    def test_cli_help(self, tmp_path):
        """Test that --help works for version command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'version', '--help'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '--quiet' in result.stdout or '-q' in result.stdout

    def test_cli_invalid_option(self, tmp_path):
        """Test that invalid options are handled."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'version', '--invalid-option'],
            capture_output=True,
            text=True,
        )

        # Should fail with non-zero exit code
        assert result.returncode != 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
