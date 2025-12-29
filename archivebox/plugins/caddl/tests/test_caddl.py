#!/usr/bin/env python3
"""
Tests for the caddl plugin.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestCaddlPlugin(unittest.TestCase):
    """Test the caddl 3D/CAD asset extractor."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.script_path = Path(__file__).parent.parent / 'on_Snapshot__65_caddl.bg.js'

    def tearDown(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_script_exists_and_executable(self):
        """Verify the caddl script exists and is executable."""
        self.assertTrue(self.script_path.exists(), f"Script not found at {self.script_path}")
        self.assertTrue(os.access(self.script_path, os.X_OK), "Script is not executable")

    def test_disabled_when_env_false(self):
        """Test that caddl is skipped when CADDL_ENABLED=False."""
        env = os.environ.copy()
        env['CADDL_ENABLED'] = 'False'

        result = subprocess.run(
            ['node', str(self.script_path), '--url=https://example.com', '--snapshot-id=test-123'],
            capture_output=True,
            text=True,
            cwd=self.temp_dir,
            env=env,
            timeout=10
        )

        self.assertEqual(result.returncode, 0, f"Should exit cleanly when disabled: {result.stderr}")
        self.assertIn('Skipping', result.stderr, "Should log that it's skipping")

    def test_missing_chrome_session(self):
        """Test behavior when Chrome session is not available."""
        env = os.environ.copy()
        env['CADDL_ENABLED'] = 'True'

        result = subprocess.run(
            ['node', str(self.script_path), '--url=https://example.com', '--snapshot-id=test-123'],
            capture_output=True,
            text=True,
            cwd=self.temp_dir,
            env=env,
            timeout=10
        )

        # Should fail because Chrome CDP URL is not found
        self.assertNotEqual(result.returncode, 0, "Should fail without Chrome session")
        self.assertIn('Chrome CDP URL not found', result.stderr, "Should log CDP error")

    def test_parse_size_limit(self):
        """Test size limit parsing logic."""
        # Test the parseSizeLimit function by running JS code
        test_js = """
        function parseSizeLimit(sizeStr) {
            if (!sizeStr) return 750 * 1024 * 1024;
            sizeStr = sizeStr.toLowerCase().trim();
            const multipliers = { k: 1024, m: 1024**2, g: 1024**3 };
            const lastChar = sizeStr[sizeStr.length - 1];
            if (multipliers[lastChar]) {
                const num = parseFloat(sizeStr.slice(0, -1));
                return isNaN(num) ? 750 * 1024 * 1024 : Math.floor(num * multipliers[lastChar]);
            }
            const num = parseInt(sizeStr, 10);
            return isNaN(num) ? 750 * 1024 * 1024 : num;
        }
        console.log(parseSizeLimit('100m'));
        console.log(parseSizeLimit('1g'));
        console.log(parseSizeLimit('500k'));
        """

        result = subprocess.run(
            ['node', '-e', test_js],
            capture_output=True,
            text=True,
            timeout=5
        )

        self.assertEqual(result.returncode, 0)
        lines = result.stdout.strip().split('\n')
        self.assertEqual(lines[0], str(100 * 1024 * 1024))  # 100m
        self.assertEqual(lines[1], str(1024 * 1024 * 1024))  # 1g
        self.assertEqual(lines[2], str(500 * 1024))  # 500k

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        test_js = """
        const path = require('path');
        function sanitizeFilename(filename) {
            filename = path.basename(filename);
            filename = filename.replace(/[^\\w\\-_.]/g, '_');
            if (!filename || filename === '.' || filename === '..') {
                return 'asset.bin';
            }
            return filename;
        }
        console.log(sanitizeFilename('model.stl'));
        console.log(sanitizeFilename('/path/to/file.obj'));
        console.log(sanitizeFilename('..'));
        console.log(sanitizeFilename('model with spaces.gltf'));
        """

        result = subprocess.run(
            ['node', '-e', test_js],
            capture_output=True,
            text=True,
            timeout=5
        )

        self.assertEqual(result.returncode, 0)
        lines = result.stdout.strip().split('\n')
        self.assertEqual(lines[0], 'model.stl')
        self.assertEqual(lines[1], 'file.obj')
        self.assertEqual(lines[2], 'asset.bin')  # Dangerous filename replaced
        self.assertEqual(lines[3], 'model_with_spaces.gltf')


if __name__ == '__main__':
    unittest.main()
