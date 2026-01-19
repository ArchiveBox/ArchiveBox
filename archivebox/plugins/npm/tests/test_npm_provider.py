"""
Tests for the npm binary provider plugin.

Tests cover:
1. Hook script execution
2. npm package installation
3. PATH and NODE_MODULES_DIR updates
4. JSONL output format
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from django.test import TestCase


# Get the path to the npm provider hook
PLUGIN_DIR = Path(__file__).parent.parent
INSTALL_HOOK = next(PLUGIN_DIR.glob('on_Binary__*_npm_install.py'), None)


def npm_available() -> bool:
    """Check if npm is installed."""
    return shutil.which('npm') is not None


class TestNpmProviderHook(TestCase):
    """Test the npm binary provider installation hook."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.lib_dir = Path(self.temp_dir) / 'lib' / 'x86_64-linux'
        self.lib_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hook_script_exists(self):
        """Hook script should exist."""
        self.assertTrue(INSTALL_HOOK and INSTALL_HOOK.exists(), f"Hook not found: {INSTALL_HOOK}")

    def test_hook_requires_lib_dir(self):
        """Hook should fail when LIB_DIR is not set."""
        env = os.environ.copy()
        env.pop('LIB_DIR', None)  # Remove LIB_DIR

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=some-package',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        self.assertIn('LIB_DIR environment variable not set', result.stderr)
        self.assertEqual(result.returncode, 1)

    def test_hook_skips_when_npm_not_allowed(self):
        """Hook should skip when npm not in allowed binproviders."""
        env = os.environ.copy()
        env['LIB_DIR'] = str(self.lib_dir)

        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=some-package',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
                '--binproviders=pip,apt',  # npm not allowed
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Should exit cleanly (code 0) when npm not allowed
        self.assertIn('npm provider not allowed', result.stderr)
        self.assertEqual(result.returncode, 0)

    @pytest.mark.skipif(not npm_available(), reason="npm not installed")
    def test_hook_creates_npm_prefix(self):
        """Hook should create npm prefix directory."""
        env = os.environ.copy()
        env['LIB_DIR'] = str(self.lib_dir)

        # Even if installation fails, the npm prefix should be created
        subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=nonexistent-xyz123',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        npm_prefix = self.lib_dir / 'npm'
        self.assertTrue(npm_prefix.exists())

    def test_hook_handles_overrides(self):
        """Hook should accept overrides JSON."""
        env = os.environ.copy()
        env['LIB_DIR'] = str(self.lib_dir)

        overrides = json.dumps({'npm': {'packages': ['custom-pkg']}})

        # Just verify it doesn't crash with overrides
        result = subprocess.run(
            [
                sys.executable, str(INSTALL_HOOK),
                '--name=test-pkg',
                '--binary-id=test-uuid',
                '--machine-id=test-machine',
                f'--overrides={overrides}',
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # May fail to install, but should not crash parsing overrides
        self.assertNotIn('Failed to parse overrides JSON', result.stderr)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
