#!/usr/bin/env python3
"""Integration tests for archivebox install command."""

import os
import subprocess
import sqlite3

import pytest

from .fixtures import process, disable_extractors_dict


class TestInstallDryRun:
    """Test the dry-run mode of install command."""

    def test_dry_run_prints_message(self, tmp_path, process):
        """Test that dry-run mode prints appropriate message."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'install', '--dry-run'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert 'Dry run' in result.stdout

    def test_dry_run_does_not_create_crawl(self, tmp_path, process):
        """Test that dry-run mode doesn't create a crawl."""
        os.chdir(tmp_path)

        # Get initial crawl count
        conn = sqlite3.connect('index.sqlite3')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM crawls_crawl")
        initial_count = c.fetchone()[0]
        conn.close()

        # Run install with dry-run
        result = subprocess.run(
            ['archivebox', 'install', '--dry-run'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0

        # Check crawl count unchanged
        conn = sqlite3.connect('index.sqlite3')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM crawls_crawl")
        final_count = c.fetchone()[0]
        conn.close()

        assert final_count == initial_count


class TestInstallOutput:
    """Test the output/messages from install command."""

    def test_install_prints_detecting_message(self, tmp_path, process, disable_extractors_dict):
        """Test that install prints detecting dependencies message."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'install', '--dry-run'],
            capture_output=True,
            text=True,
            env=disable_extractors_dict,
        )

        assert result.returncode == 0
        # Should mention detecting or dependencies
        output = result.stdout.lower()
        assert 'detect' in output or 'dependenc' in output or 'dry run' in output


class TestInstallCLI:
    """Test the CLI interface for install command."""

    def test_cli_help(self, tmp_path):
        """Test that --help works for install command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'install', '--help'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '--dry-run' in result.stdout or '-d' in result.stdout

    def test_cli_invalid_option(self, tmp_path):
        """Test that invalid options are handled."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'install', '--invalid-option'],
            capture_output=True,
            text=True,
        )

        # Should fail with non-zero exit code
        assert result.returncode != 0


class TestInstallInitialization:
    """Test that install initializes the data directory if needed."""

    def test_install_from_empty_dir(self, tmp_path):
        """Test that install from empty dir initializes first."""
        os.chdir(tmp_path)

        # Don't use process fixture - start from empty dir
        result = subprocess.run(
            ['archivebox', 'install', '--dry-run'],
            capture_output=True,
            text=True,
        )

        # Should either initialize or show dry run message
        output = result.stdout
        assert 'Initializing' in output or 'Dry run' in output or 'init' in output.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
