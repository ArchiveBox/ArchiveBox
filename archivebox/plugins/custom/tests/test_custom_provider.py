"""
Tests for the custom binary provider plugin.

Tests the custom bash binary installer with safe commands.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from django.test import TestCase


# Get the path to the custom provider hook
PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_HOOK = next(PLUGIN_DIR.glob('on_Binary__*_custom_install.py'), None)


class TestCustomProviderHook(TestCase):
    """Test the custom binary provider hook."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hook_script_exists(self):
        """Hook script should exist."""
        self.assertTrue(INSTALL_HOOK and INSTALL_HOOK.exists(), f"Hook not found: {INSTALL_HOOK}")

    def test_hook_skips_when_custom_not_allowed(self):
        """Hook should skip when custom not in allowed binproviders."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=echo',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
                '--binproviders=pip,apt',  # custom not allowed
                '--custom-cmd=echo hello',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should exit cleanly (code 0) when custom not allowed
        self.assertEqual(result.returncode, 0)
        self.assertIn('custom provider not allowed', result.stderr)

    def test_hook_runs_custom_command_and_finds_binary(self):
        """Hook should run custom command and find the binary in PATH."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        # Use a simple echo command that doesn't actually install anything
        # Then check for 'echo' which is already in PATH
        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=echo',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
                '--custom-cmd=echo "custom install simulation"',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should succeed since echo is in PATH
        self.assertEqual(result.returncode, 0, f"Hook failed: {result.stderr}")

        # Parse JSONL output
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Binary' and record.get('name') == 'echo':
                        self.assertEqual(record['binprovider'], 'custom')
                        self.assertTrue(record['abspath'])
                        return
                except json.JSONDecodeError:
                    continue

        self.fail("No Binary JSONL record found in output")

    def test_hook_fails_for_missing_binary_after_command(self):
        """Hook should fail if binary not found after running custom command."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=nonexistent_binary_xyz123',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
                '--custom-cmd=echo "failed install"',  # Doesn't actually install
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should fail since binary not found after command
        self.assertEqual(result.returncode, 1)
        self.assertIn('not found', result.stderr.lower())

    def test_hook_fails_for_failing_command(self):
        """Hook should fail if custom command returns non-zero exit code."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=echo',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
                '--custom-cmd=exit 1',  # Command that fails
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should fail with exit code 1
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
