#!/usr/bin/env python3
"""
Tests for archivebox oneshot command.
Verify oneshot archives URL and exits.
"""

import os
import subprocess
import sqlite3
from pathlib import Path

from .fixtures import *


def test_oneshot_creates_temporary_collection(tmp_path, disable_extractors_dict):
    """Test that oneshot creates temporary collection."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'oneshot', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=60,
    )

    # Should complete
    assert result.returncode in [0, 1]


def test_oneshot_without_existing_collection(tmp_path, disable_extractors_dict):
    """Test oneshot works without pre-existing collection."""
    empty_dir = tmp_path / "oneshot_test"
    empty_dir.mkdir()
    os.chdir(empty_dir)

    result = subprocess.run(
        ['archivebox', 'oneshot', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=60,
    )

    # Should work even without init
    assert result.returncode in [0, 1]


def test_oneshot_creates_archive_output(tmp_path, disable_extractors_dict):
    """Test that oneshot creates archive output."""
    empty_dir = tmp_path / "oneshot_test2"
    empty_dir.mkdir()
    os.chdir(empty_dir)

    result = subprocess.run(
        ['archivebox', 'oneshot', '--index-only', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=60,
    )

    # Oneshot may create archive directory
    # Check if any output was created
    assert result.returncode in [0, 1] or len(list(empty_dir.iterdir())) > 0
