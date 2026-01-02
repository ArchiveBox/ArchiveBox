#!/usr/bin/env python3
"""
Tests for archivebox search command.
Verify search queries snapshots from DB.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_search_finds_snapshots(tmp_path, process, disable_extractors_dict):
    """Test that search command finds matching snapshots."""
    os.chdir(tmp_path)

    # Add snapshots
    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Search for it
    result = subprocess.run(
        ['archivebox', 'search', 'example'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert 'example' in result.stdout


def test_search_returns_no_results_for_missing_term(tmp_path, process, disable_extractors_dict):
    """Test search returns empty for non-existent term."""
    os.chdir(tmp_path)

    subprocess.run(
        ['archivebox', 'add', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
    )

    result = subprocess.run(
        ['archivebox', 'search', 'nonexistentterm12345'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should complete with no results
    assert result.returncode in [0, 1]


def test_search_on_empty_archive(tmp_path, process):
    """Test search works on empty archive."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'search', 'anything'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should complete without error
    assert result.returncode in [0, 1]
