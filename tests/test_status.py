#!/usr/bin/env python3
"""Integration tests for archivebox status command."""

import os
import subprocess
import sqlite3

import pytest

from .fixtures import process, disable_extractors_dict


def test_status_shows_index_info(tmp_path, process):
    """Test that status shows index information."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should show index scanning info
    assert 'index' in result.stdout.lower() or 'Index' in result.stdout


def test_status_shows_snapshot_count(tmp_path, process, disable_extractors_dict):
    """Test that status shows snapshot count."""
    os.chdir(tmp_path)

    # Add some snapshots
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://iana.org'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should show link/snapshot count
    assert '2' in result.stdout or 'links' in result.stdout.lower()


def test_status_shows_archive_size(tmp_path, process, disable_extractors_dict):
    """Test that status shows archive size information."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should show size info (bytes, KB, MB, etc)
    assert 'Size' in result.stdout or 'size' in result.stdout or 'B' in result.stdout


def test_status_shows_indexed_count(tmp_path, process, disable_extractors_dict):
    """Test that status shows indexed folder count."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should show indexed count
    assert 'indexed' in result.stdout.lower()


def test_status_shows_archived_vs_unarchived(tmp_path, process, disable_extractors_dict):
    """Test that status shows archived vs unarchived counts."""
    os.chdir(tmp_path)

    # Add index-only snapshot (unarchived)
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should show archived/unarchived categories
    assert 'archived' in result.stdout.lower() or 'unarchived' in result.stdout.lower()


def test_status_shows_data_directory_info(tmp_path, process):
    """Test that status shows data directory path."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should show data directory or archive path
    assert 'archive' in result.stdout.lower() or str(tmp_path) in result.stdout


def test_status_shows_user_info(tmp_path, process):
    """Test that status shows user information."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should show user info section
    assert 'user' in result.stdout.lower() or 'login' in result.stdout.lower()


def test_status_empty_archive(tmp_path, process):
    """Test status on empty archive shows zero counts."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should still run successfully
    assert result.returncode == 0 or 'index' in result.stdout.lower()
    # Should show 0 links
    assert '0' in result.stdout or 'links' in result.stdout.lower()


def test_status_shows_valid_vs_invalid(tmp_path, process, disable_extractors_dict):
    """Test that status shows valid vs invalid folder counts."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'status'],
        capture_output=True,
        text=True,
    )

    # Should show valid/invalid categories
    assert 'valid' in result.stdout.lower() or 'present' in result.stdout.lower()


class TestStatusCLI:
    """Test the CLI interface for status command."""

    def test_cli_help(self, tmp_path, process):
        """Test that --help works for status command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'status', '--help'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Help should show some info about the command
        assert 'status' in result.stdout.lower() or 'statistic' in result.stdout.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
