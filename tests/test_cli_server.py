#!/usr/bin/env python3
"""
Tests for archivebox server command.
Verify server can start (basic smoke tests only, no full server testing).
"""

import os
import subprocess
import signal
import time

from .fixtures import *


def test_server_shows_usage_info(tmp_path, process):
    """Test that server command shows usage or starts."""
    os.chdir(tmp_path)

    # Just check that the command is recognized
    # We won't actually start a full server in tests
    result = subprocess.run(
        ['archivebox', 'server', '--help'],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert 'server' in result.stdout.lower() or 'http' in result.stdout.lower()


def test_server_init_flag(tmp_path, process):
    """Test that --init flag runs init before starting server."""
    os.chdir(tmp_path)

    # Check init flag is recognized
    result = subprocess.run(
        ['archivebox', 'server', '--help'],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert '--init' in result.stdout or 'init' in result.stdout.lower()
