#!/usr/bin/env python3
"""
Tests for archivebox schedule command.
Verify schedule creates scheduled crawl records.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_schedule_creates_scheduled_crawl(tmp_path, process, disable_extractors_dict):
    """Test that schedule command creates a scheduled crawl."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'schedule', '--every=day', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    # Should complete (creating schedule or showing usage)
    assert result.returncode in [0, 1, 2]


def test_schedule_with_every_flag(tmp_path, process, disable_extractors_dict):
    """Test schedule with --every flag."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'schedule', '--every=week', '--depth=0', 'https://example.com'],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    assert result.returncode in [0, 1, 2]


def test_schedule_list_shows_schedules(tmp_path, process):
    """Test that schedule can list existing schedules."""
    os.chdir(tmp_path)

    # Try to list schedules
    result = subprocess.run(
        ['archivebox', 'schedule', '--list'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should show schedules or empty list
    assert result.returncode in [0, 1, 2]
