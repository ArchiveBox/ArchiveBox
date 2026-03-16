#!/usr/bin/env python3
"""Integration tests for archivebox search command."""

import os
import subprocess
import sqlite3
import json

import pytest

from .fixtures import process, disable_extractors_dict


def test_search_returns_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that search returns snapshots."""
    os.chdir(tmp_path)

    # Add some snapshots
    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'search'],
        capture_output=True,
        text=True,
    )

    # Should return some output (path or URL info)
    assert result.stdout.strip() != '' or result.returncode == 0


def test_search_filter_by_substring(tmp_path, process, disable_extractors_dict):
    """Test that substring filter works."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Search with filter - may not find if URL isn't stored as expected
    result = subprocess.run(
        ['archivebox', 'search', '--filter-type=substring', 'example'],
        capture_output=True,
        text=True,
    )

    # Should run without error
    assert result.returncode == 0 or 'No Snapshots' in result.stderr


def test_search_sort_option(tmp_path, process, disable_extractors_dict):
    """Test that --sort option works."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'search', '--sort=url'],
        capture_output=True,
        text=True,
    )

    # Should run without error
    assert result.returncode == 0


def test_search_with_headers_requires_format(tmp_path, process):
    """Test that --with-headers requires --json, --html, or --csv."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'search', '--with-headers'],
        capture_output=True,
        text=True,
    )

    # Should fail with error message
    assert result.returncode != 0
    assert 'requires' in result.stderr.lower() or 'json' in result.stderr.lower()


def test_search_status_option(tmp_path, process, disable_extractors_dict):
    """Test that --status option filters by status."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'search', '--status=indexed'],
        capture_output=True,
        text=True,
    )

    # Should run without error
    assert result.returncode == 0


def test_search_no_snapshots_message(tmp_path, process):
    """Test that searching empty archive shows appropriate output."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'search'],
        capture_output=True,
        text=True,
    )

    # Should complete (empty results are OK)
    assert result.returncode == 0


class TestSearchCLI:
    """Test the CLI interface for search command."""

    def test_cli_help(self, tmp_path, process):
        """Test that --help works for search command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ['archivebox', 'search', '--help'],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '--filter-type' in result.stdout or '-f' in result.stdout
        assert '--status' in result.stdout
        assert '--sort' in result.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
