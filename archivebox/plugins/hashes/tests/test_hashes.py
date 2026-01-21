"""
Tests for the hashes plugin.

Tests the real merkle tree generation with actual files.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from django.test import TestCase


# Get the path to the hashes hook
PLUGIN_DIR = Path(__file__).parent.parent
HASHES_HOOK = PLUGIN_DIR / 'on_Snapshot__93_hashes.py'


class TestHashesPlugin(TestCase):
    """Test the hashes plugin."""

    def test_hashes_hook_exists(self):
        """Hashes hook script should exist."""
        self.assertTrue(HASHES_HOOK.exists(), f"Hook not found: {HASHES_HOOK}")

    def test_hashes_generates_tree_for_files(self):
        """Hashes hook should generate merkle tree for files in snapshot directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a mock snapshot directory structure
            snapshot_dir = Path(temp_dir) / 'snapshot'
            snapshot_dir.mkdir()

            # Create output directory for hashes
            output_dir = snapshot_dir / 'hashes'
            output_dir.mkdir()

            # Create some test files
            (snapshot_dir / 'index.html').write_text('<html><body>Test</body></html>')
            (snapshot_dir / 'screenshot.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

            subdir = snapshot_dir / 'media'
            subdir.mkdir()
            (subdir / 'video.mp4').write_bytes(b'\x00\x00\x00\x18ftypmp42')

            # Run the hook from the output directory
            env = os.environ.copy()
            env['HASHES_ENABLED'] = 'true'

            result = subprocess.run(
                [
                    sys.executable, str(HASHES_HOOK),
                    '--url=https://example.com',
                    '--snapshot-id=test-snapshot',
                ],
                capture_output=True,
                text=True,
                cwd=str(output_dir),  # Hook expects to run from output dir
                env=env,
                timeout=30
            )

            # Should succeed
            self.assertEqual(result.returncode, 0, f"Hook failed: {result.stderr}")

            # Check output file exists
            output_file = output_dir / 'hashes.json'
            self.assertTrue(output_file.exists(), "hashes.json not created")

            # Parse and verify output
            with open(output_file) as f:
                data = json.load(f)

            self.assertIn('root_hash', data)
            self.assertIn('files', data)
            self.assertIn('metadata', data)

            # Should have indexed our test files
            file_paths = [f['path'] for f in data['files']]
            self.assertIn('index.html', file_paths)
            self.assertIn('screenshot.png', file_paths)

            # Verify metadata
            self.assertGreater(data['metadata']['file_count'], 0)
            self.assertGreater(data['metadata']['total_size'], 0)

    def test_hashes_skips_when_disabled(self):
        """Hashes hook should skip when HASHES_ENABLED=false."""
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_dir = Path(temp_dir) / 'snapshot'
            snapshot_dir.mkdir()
            output_dir = snapshot_dir / 'hashes'
            output_dir.mkdir()

            env = os.environ.copy()
            env['HASHES_ENABLED'] = 'false'

            result = subprocess.run(
                [
                    sys.executable, str(HASHES_HOOK),
                    '--url=https://example.com',
                    '--snapshot-id=test-snapshot',
                ],
                capture_output=True,
                text=True,
                cwd=str(output_dir),
                env=env,
                timeout=30
            )

            # Should succeed (exit 0) but skip
            self.assertEqual(result.returncode, 0)
            self.assertIn('skipped', result.stdout)

    def test_hashes_handles_empty_directory(self):
        """Hashes hook should handle empty snapshot directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_dir = Path(temp_dir) / 'snapshot'
            snapshot_dir.mkdir()
            output_dir = snapshot_dir / 'hashes'
            output_dir.mkdir()

            env = os.environ.copy()
            env['HASHES_ENABLED'] = 'true'

            result = subprocess.run(
                [
                    sys.executable, str(HASHES_HOOK),
                    '--url=https://example.com',
                    '--snapshot-id=test-snapshot',
                ],
                capture_output=True,
                text=True,
                cwd=str(output_dir),
                env=env,
                timeout=30
            )

            # Should succeed even with empty directory
            self.assertEqual(result.returncode, 0, f"Hook failed: {result.stderr}")

            # Check output file exists
            output_file = output_dir / 'hashes.json'
            self.assertTrue(output_file.exists())

            with open(output_file) as f:
                data = json.load(f)

            # Should have empty file list
            self.assertEqual(data['metadata']['file_count'], 0)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
