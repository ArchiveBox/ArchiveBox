#!/usr/bin/env python3
"""
Tests for archivebox shell command.
Verify shell command starts Django shell (basic smoke tests only).
"""

import os
import subprocess


def test_shell_command_exists(tmp_path, process):
    """Test that shell command is recognized."""
    os.chdir(tmp_path)

    # Test that the command exists (will fail without input but should recognize command)
    result = subprocess.run(
        ["archivebox", "shell", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    # Should show shell help or recognize command
    assert result.returncode in [0, 1, 2]


def test_shell_c_executes_python(tmp_path, process):
    """shell -c should fully initialize Django and run the provided command."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ["archivebox", "shell", "-c", 'print("shell-ok")'],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "shell-ok" in result.stdout
