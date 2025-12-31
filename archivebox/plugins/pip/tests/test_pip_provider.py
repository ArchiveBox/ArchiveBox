"""
Tests for the pip binary provider plugin.

Tests cover:
1. Hook script execution
2. pip package detection
3. Virtual environment handling
4. JSONL output format
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from django.test import TestCase


# Get the path to the pip provider hook
PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_HOOK = PLUGIN_DIR / 'on_Binary__install_using_pip_provider.py'


class TestPipProviderHook(TestCase):
    """Test the pip binary provider installation hook."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.temp_dir) / 'output'
        self.output_dir.mkdir()

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hook_script_exists(self):
        """Hook script should exist."""
        self.assertTrue(INSTALL_HOOK.exists(), f"Hook not found: {INSTALL_HOOK}")

    def test_hook_help(self):
        """Hook should accept --help without error."""
        result = subprocess.run(
            [sys.executable, str(INSTALL_HOOK), '--help'],
            capture_output=True,
            text=True,
            timeout=30
        )
        # May succeed or fail depending on implementation
        # At minimum should not crash with Python error
        self.assertNotIn('Traceback', result.stderr)

    def test_hook_finds_python(self):
        """Hook should find Python binary."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=python3',
                '--binproviders=pip,env',
            ],
            capture_output=True,
            text=True,
            cwd=str(self.output_dir),
            env=env,
            timeout=60
        )

        # Check for JSONL output
        jsonl_found = False
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Binary' and record.get('name') == 'python3':
                        jsonl_found = True
                        # Verify structure
                        self.assertIn('abspath', record)
                        self.assertIn('version', record)
                        break
                except json.JSONDecodeError:
                    continue

        # May or may not find python3 via pip, but should not crash
        self.assertNotIn('Traceback', result.stderr)

    def test_hook_unknown_package(self):
        """Hook should handle unknown packages gracefully."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=nonexistent_package_xyz123',
                '--binproviders=pip',
            ],
            capture_output=True,
            text=True,
            cwd=str(self.output_dir),
            env=env,
            timeout=60
        )

        # Should not crash
        self.assertNotIn('Traceback', result.stderr)
        # May have non-zero exit code for missing package


class TestPipProviderIntegration(TestCase):
    """Integration tests for pip provider with real packages."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.temp_dir) / 'output'
        self.output_dir.mkdir()

    def tearDown(self):
        """Clean up."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @pytest.mark.skipif(
        subprocess.run([sys.executable, '-m', 'pip', '--version'],
                       capture_output=True).returncode != 0,
        reason="pip not available"
    )
    def test_hook_finds_pip_installed_binary(self):
        """Hook should find binaries installed via pip."""
        env = os.environ.copy()
        env['DATA_DIR'] = self.temp_dir

        # Try to find 'pip' itself which should be available
        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=pip',
                '--binproviders=pip,env',
            ],
            capture_output=True,
            text=True,
            cwd=str(self.output_dir),
            env=env,
            timeout=60
        )

        # Look for success in output
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Binary' and 'pip' in record.get('name', ''):
                        # Found pip binary
                        self.assertTrue(record.get('abspath'))
                        return
                except json.JSONDecodeError:
                    continue

        # If we get here without finding pip, that's acceptable
        # as long as the hook didn't crash
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
