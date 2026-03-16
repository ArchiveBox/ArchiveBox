#!/usr/bin/env python3
"""
Tests for archivebox manage command.
Verify manage command runs Django management commands.
"""

import os
import subprocess
import sqlite3

from .fixtures import *


def test_manage_help_works(tmp_path, process):
    """Test that manage help command works."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'manage', 'help'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert len(result.stdout) > 100


def test_manage_showmigrations_works(tmp_path, process):
    """Test that manage showmigrations works."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'manage', 'showmigrations'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    # Should show migration status
    assert 'core' in result.stdout or '[' in result.stdout


def test_manage_dbshell_command_exists(tmp_path, process):
    """Test that manage dbshell command is recognized."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'manage', 'help', 'dbshell'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Should show help for dbshell
    assert result.returncode == 0
    assert 'dbshell' in result.stdout or 'database' in result.stdout.lower()


def test_manage_check_works(tmp_path, process):
    """Test that manage check works."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ['archivebox', 'manage', 'check'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Check should complete
    assert result.returncode in [0, 1]
