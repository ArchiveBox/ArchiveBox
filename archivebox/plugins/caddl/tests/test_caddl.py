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
        """Test size limit parsing logic from the actual implementation."""
        # Test the actual parseSizeLimit function from the script
        test_js = f"""
        const script = require('{self.script_path}');
        // Extract and test the parseSizeLimit function by executing the script's code
        const {{parseSizeLimit}} = require('module')._load('{self.script_path}', null, true);
        """

        # Since the functions aren't exported, we need to extract and test them
        # by executing a wrapper that sources the implementation
        test_code = f"""
        const fs = require('fs');
        const scriptContent = fs.readFileSync('{self.script_path}', 'utf8');

        // Extract the parseSizeLimit function
        const parseSizeLimitMatch = scriptContent.match(/function parseSizeLimit\\([^)]*\\)\\s*\\{{[\\s\\S]*?^\\}}/m);
        if (!parseSizeLimitMatch) {{
            console.error('Could not find parseSizeLimit function');
            process.exit(1);
        }}

        // Execute the function definition
        eval(parseSizeLimitMatch[0]);

        // Test it
        console.log(parseSizeLimit('100m'));
        console.log(parseSizeLimit('1g'));
        console.log(parseSizeLimit('500k'));
        console.log(parseSizeLimit(''));
        console.log(parseSizeLimit('invalid'));
        """

        result = subprocess.run(
            ['node', '-e', test_code],
            capture_output=True,
            text=True,
            timeout=5
        )

        self.assertEqual(result.returncode, 0, f"Failed to test parseSizeLimit: {result.stderr}")
        lines = result.stdout.strip().split('\n')
        self.assertEqual(lines[0], str(100 * 1024 * 1024))  # 100m
        self.assertEqual(lines[1], str(1024 * 1024 * 1024))  # 1g
        self.assertEqual(lines[2], str(500 * 1024))  # 500k
        self.assertEqual(lines[3], str(750 * 1024 * 1024))  # default
        self.assertEqual(lines[4], str(750 * 1024 * 1024))  # invalid -> default

    def test_sanitize_filename(self):
        """Test filename sanitization from the actual implementation."""
        # Test the actual sanitizeFilename function from the script
        test_code = f"""
        const fs = require('fs');
        const path = require('path');
        const scriptContent = fs.readFileSync('{self.script_path}', 'utf8');

        // Extract the sanitizeFilename function
        const sanitizeFilenameMatch = scriptContent.match(/function sanitizeFilename\\([^)]*\\)\\s*\\{{[\\s\\S]*?^\\}}/m);
        if (!sanitizeFilenameMatch) {{
            console.error('Could not find sanitizeFilename function');
            process.exit(1);
        }}

        // Execute the function definition
        eval(sanitizeFilenameMatch[0]);

        // Test it
        console.log(sanitizeFilename('model.stl'));
        console.log(sanitizeFilename('/path/to/file.obj'));
        console.log(sanitizeFilename('..'));
        console.log(sanitizeFilename('.'));
        console.log(sanitizeFilename(''));
        console.log(sanitizeFilename('model with spaces.gltf'));
        console.log(sanitizeFilename('../../../etc/passwd'));
        """

        result = subprocess.run(
            ['node', '-e', test_code],
            capture_output=True,
            text=True,
            timeout=5
        )

        self.assertEqual(result.returncode, 0, f"Failed to test sanitizeFilename: {result.stderr}")
        lines = result.stdout.strip().split('\n')
        self.assertEqual(lines[0], 'model.stl')
        self.assertEqual(lines[1], 'file.obj')
        self.assertEqual(lines[2], 'asset.bin')  # Dangerous filename replaced
        self.assertEqual(lines[3], 'asset.bin')  # Dangerous filename replaced
        self.assertEqual(lines[4], 'asset.bin')  # Empty filename replaced
        self.assertEqual(lines[5], 'model_with_spaces.gltf')
        self.assertEqual(lines[6], 'passwd')  # Path traversal prevented


if __name__ == '__main__':
    unittest.main()
