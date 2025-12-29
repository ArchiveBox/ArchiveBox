#!/usr/bin/env python3
"""
Tests for archivebox help command.
Verify command runs successfully and produces output.
"""

import os
import subprocess

from .fixtures import *


def test_help_runs_successfully(tmp_path):
    """Test that help command runs and produces output."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'help'], capture_output=True, text=True)

    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert len(combined) > 100
    assert 'archivebox' in combined.lower()


def test_help_in_initialized_dir(tmp_path, process):
    """Test help command in initialized data directory."""
    os.chdir(tmp_path)
    result = subprocess.run(['archivebox', 'help'], capture_output=True, text=True)

    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert 'init' in combined
    assert 'add' in combined
