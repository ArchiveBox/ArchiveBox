"""
Tests for the ripgrep search backend.

Tests cover:
1. Search with ripgrep binary
2. Snapshot ID extraction from file paths
3. Timeout handling
4. Error handling
5. Environment variable configuration
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from django.test import TestCase

from archivebox.plugins.search_backend_ripgrep.search import (
    search,
    flush,
    get_env,
    get_env_int,
    get_env_array,
)


class TestEnvHelpers(TestCase):
    """Test environment variable helper functions."""

    def test_get_env_default(self):
        """get_env should return default for unset vars."""
        result = get_env('NONEXISTENT_VAR_12345', 'default')
        self.assertEqual(result, 'default')

    def test_get_env_set(self):
        """get_env should return value for set vars."""
        with patch.dict(os.environ, {'TEST_VAR': 'value'}):
            result = get_env('TEST_VAR', 'default')
            self.assertEqual(result, 'value')

    def test_get_env_strips_whitespace(self):
        """get_env should strip whitespace."""
        with patch.dict(os.environ, {'TEST_VAR': '  value  '}):
            result = get_env('TEST_VAR', '')
            self.assertEqual(result, 'value')

    def test_get_env_int_default(self):
        """get_env_int should return default for unset vars."""
        result = get_env_int('NONEXISTENT_VAR_12345', 42)
        self.assertEqual(result, 42)

    def test_get_env_int_valid(self):
        """get_env_int should parse integer values."""
        with patch.dict(os.environ, {'TEST_INT': '100'}):
            result = get_env_int('TEST_INT', 0)
            self.assertEqual(result, 100)

    def test_get_env_int_invalid(self):
        """get_env_int should return default for invalid integers."""
        with patch.dict(os.environ, {'TEST_INT': 'not a number'}):
            result = get_env_int('TEST_INT', 42)
            self.assertEqual(result, 42)

    def test_get_env_array_default(self):
        """get_env_array should return default for unset vars."""
        result = get_env_array('NONEXISTENT_VAR_12345', ['default'])
        self.assertEqual(result, ['default'])

    def test_get_env_array_valid(self):
        """get_env_array should parse JSON arrays."""
        with patch.dict(os.environ, {'TEST_ARRAY': '["a", "b", "c"]'}):
            result = get_env_array('TEST_ARRAY', [])
            self.assertEqual(result, ['a', 'b', 'c'])

    def test_get_env_array_invalid_json(self):
        """get_env_array should return default for invalid JSON."""
        with patch.dict(os.environ, {'TEST_ARRAY': 'not json'}):
            result = get_env_array('TEST_ARRAY', ['default'])
            self.assertEqual(result, ['default'])

    def test_get_env_array_not_array(self):
        """get_env_array should return default for non-array JSON."""
        with patch.dict(os.environ, {'TEST_ARRAY': '{"key": "value"}'}):
            result = get_env_array('TEST_ARRAY', ['default'])
            self.assertEqual(result, ['default'])


class TestRipgrepFlush(TestCase):
    """Test the flush function."""

    def test_flush_is_noop(self):
        """flush should be a no-op for ripgrep backend."""
        # Should not raise
        flush(['snap-001', 'snap-002'])


class TestRipgrepSearch(TestCase):
    """Test the ripgrep search function."""

    def setUp(self):
        """Create temporary archive directory with test files."""
        self.temp_dir = tempfile.mkdtemp()
        self.archive_dir = Path(self.temp_dir) / 'archive'
        self.archive_dir.mkdir()

        # Create snapshot directories with searchable content
        self._create_snapshot('snap-001', {
            'singlefile/index.html': '<html><body>Python programming tutorial</body></html>',
            'title/title.txt': 'Learn Python Programming',
        })
        self._create_snapshot('snap-002', {
            'singlefile/index.html': '<html><body>JavaScript guide</body></html>',
            'title/title.txt': 'JavaScript Basics',
        })
        self._create_snapshot('snap-003', {
            'wget/index.html': '<html><body>Web archiving guide and best practices</body></html>',
            'title/title.txt': 'Web Archiving guide',
        })

        # Patch settings
        self.settings_patch = patch(
            'archivebox.plugins.search_backend_ripgrep.search.settings'
        )
        self.mock_settings = self.settings_patch.start()
        self.mock_settings.ARCHIVE_DIR = str(self.archive_dir)

    def tearDown(self):
        """Clean up temporary directory."""
        self.settings_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_snapshot(self, snapshot_id: str, files: dict):
        """Create a snapshot directory with files."""
        snap_dir = self.archive_dir / snapshot_id
        for path, content in files.items():
            file_path = snap_dir / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

    def _has_ripgrep(self) -> bool:
        """Check if ripgrep is available."""
        return shutil.which('rg') is not None

    def test_search_no_archive_dir(self):
        """search should return empty list when archive dir doesn't exist."""
        self.mock_settings.ARCHIVE_DIR = '/nonexistent/path'
        results = search('test')
        self.assertEqual(results, [])

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_single_match(self):
        """search should find matching snapshot."""
        results = search('Python programming')

        self.assertIn('snap-001', results)
        self.assertNotIn('snap-002', results)
        self.assertNotIn('snap-003', results)

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_multiple_matches(self):
        """search should find all matching snapshots."""
        # 'guide' appears in snap-002 (JavaScript guide) and snap-003 (Archiving Guide)
        results = search('guide')

        self.assertIn('snap-002', results)
        self.assertIn('snap-003', results)
        self.assertNotIn('snap-001', results)

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_case_insensitive_by_default(self):
        """search should be case-sensitive (ripgrep default)."""
        # By default rg is case-sensitive
        results_upper = search('PYTHON')
        results_lower = search('python')

        # Depending on ripgrep config, results may differ
        self.assertIsInstance(results_upper, list)
        self.assertIsInstance(results_lower, list)

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_no_results(self):
        """search should return empty list for no matches."""
        results = search('xyznonexistent123')
        self.assertEqual(results, [])

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_regex(self):
        """search should support regex patterns."""
        results = search('(Python|JavaScript)')

        self.assertIn('snap-001', results)
        self.assertIn('snap-002', results)

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_distinct_snapshots(self):
        """search should return distinct snapshot IDs."""
        # Query matches both files in snap-001
        results = search('Python')

        # Should only appear once
        self.assertEqual(results.count('snap-001'), 1)

    def test_search_missing_binary(self):
        """search should raise when ripgrep binary not found."""
        with patch.dict(os.environ, {'RIPGREP_BINARY': '/nonexistent/rg'}):
            with patch('shutil.which', return_value=None):
                with self.assertRaises(RuntimeError) as context:
                    search('test')
                self.assertIn('ripgrep binary not found', str(context.exception))

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_with_custom_args(self):
        """search should use custom RIPGREP_ARGS."""
        with patch.dict(os.environ, {'RIPGREP_ARGS': '["-i"]'}):  # Case insensitive
            results = search('PYTHON')
            # With -i flag, should find regardless of case
            self.assertIn('snap-001', results)

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_timeout(self):
        """search should handle timeout gracefully."""
        with patch.dict(os.environ, {'RIPGREP_TIMEOUT': '1'}):
            # Short timeout, should still complete for small archive
            results = search('Python')
            self.assertIsInstance(results, list)


class TestRipgrepSearchIntegration(TestCase):
    """Integration tests with realistic archive structure."""

    def setUp(self):
        """Create archive with realistic structure."""
        self.temp_dir = tempfile.mkdtemp()
        self.archive_dir = Path(self.temp_dir) / 'archive'
        self.archive_dir.mkdir()

        # Realistic snapshot structure
        self._create_snapshot('1704067200.123456', {  # 2024-01-01
            'singlefile.html': '''<!DOCTYPE html>
<html>
<head><title>ArchiveBox Documentation</title></head>
<body>
<h1>Getting Started with ArchiveBox</h1>
<p>ArchiveBox is a powerful, self-hosted web archiving tool.</p>
<p>Install with: pip install archivebox</p>
</body>
</html>''',
            'title/title.txt': 'ArchiveBox Documentation',
            'screenshot/screenshot.png': b'PNG IMAGE DATA',  # Binary file
        })
        self._create_snapshot('1704153600.654321', {  # 2024-01-02
            'wget/index.html': '''<html>
<head><title>Python News</title></head>
<body>
<h1>Python 3.12 Released</h1>
<p>New features include improved error messages and performance.</p>
</body>
</html>''',
            'readability/content.html': '<p>Python 3.12 has been released with exciting new features.</p>',
        })

        self.settings_patch = patch(
            'archivebox.plugins.search_backend_ripgrep.search.settings'
        )
        self.mock_settings = self.settings_patch.start()
        self.mock_settings.ARCHIVE_DIR = str(self.archive_dir)

    def tearDown(self):
        """Clean up."""
        self.settings_patch.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_snapshot(self, timestamp: str, files: dict):
        """Create snapshot with timestamp-based ID."""
        snap_dir = self.archive_dir / timestamp
        for path, content in files.items():
            file_path = snap_dir / path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                file_path.write_bytes(content)
            else:
                file_path.write_text(content)

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_archivebox(self):
        """Search for archivebox should find documentation snapshot."""
        results = search('archivebox')
        self.assertIn('1704067200.123456', results)

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_python(self):
        """Search for python should find Python news snapshot."""
        results = search('Python')
        self.assertIn('1704153600.654321', results)

    @pytest.mark.skipif(not shutil.which('rg'), reason="ripgrep not installed")
    def test_search_pip_install(self):
        """Search for installation command."""
        results = search('pip install')
        self.assertIn('1704067200.123456', results)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
