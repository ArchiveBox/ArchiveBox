"""
Tests for the env binary provider plugin.

Tests the real env provider hook with actual system binaries.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from django.test import TestCase


# Get the path to the env provider hook
PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_HOOK = next(PLUGIN_DIR.glob('on_Binary__*_env_install.py'), None)


class TestEnvProviderHook(TestCase):
    """Test the env binary provider hook."""

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

    def test_hook_finds_python(self):
        """Hook should find python3 binary in PATH."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=python3',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should succeed and output JSONL
        self.assertEqual(result.returncode, 0, f"Hook failed: {result.stderr}")

        # Parse JSONL output
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Binary' and record.get('name') == 'python3':
                        self.assertEqual(record['binprovider'], 'env')
                        self.assertTrue(record['abspath'])
                        self.assertTrue(Path(record['abspath']).exists())
                        return
                except json.JSONDecodeError:
                    continue

        self.fail("No Binary JSONL record found in output")

    def test_hook_finds_bash(self):
        """Hook should find bash binary in PATH."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=bash',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should succeed and output JSONL
        self.assertEqual(result.returncode, 0, f"Hook failed: {result.stderr}")

        # Parse JSONL output
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Binary' and record.get('name') == 'bash':
                        self.assertEqual(record['binprovider'], 'env')
                        self.assertTrue(record['abspath'])
                        return
                except json.JSONDecodeError:
                    continue

        self.fail("No Binary JSONL record found in output")

    def test_hook_fails_for_missing_binary(self):
        """Hook should fail for binary not in PATH."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=nonexistent_binary_xyz123',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should fail with exit code 1
        self.assertEqual(result.returncode, 1)
        self.assertIn('not found', result.stderr.lower())

    def test_hook_skips_when_env_not_allowed(self):
        """Hook should skip when env not in allowed binproviders."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=python3',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
                '--binproviders=pip,apt',  # env not allowed
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should exit cleanly (code 0) when env not allowed
        self.assertEqual(result.returncode, 0)
        self.assertIn('env provider not allowed', result.stderr)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
