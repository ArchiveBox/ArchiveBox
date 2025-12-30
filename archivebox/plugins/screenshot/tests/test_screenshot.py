"""
Integration tests for screenshot plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via chrome validation hooks
3. Verify deps with abx-pkg
4. Screenshot extraction works on https://example.com
5. JSONL output is correct
6. Filesystem output is valid PNG image
7. Config options work
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
SCREENSHOT_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_screenshot.*'), None)
TEST_URL = 'https://example.com'

# Get LIB_DIR for NODE_MODULES_DIR
def get_lib_dir():
    """Get LIB_DIR for tests."""
    from archivebox.config.common import STORAGE_CONFIG
    return Path(os.environ.get('LIB_DIR') or str(STORAGE_CONFIG.LIB_DIR))

LIB_DIR = get_lib_dir()
NODE_MODULES_DIR = LIB_DIR / 'npm' / 'node_modules'

def get_test_env():
    """Get environment with NODE_MODULES_DIR set correctly."""
    env = os.environ.copy()
    env['NODE_MODULES_DIR'] = str(NODE_MODULES_DIR)
    env['LIB_DIR'] = str(LIB_DIR)
    return env


def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert SCREENSHOT_HOOK.exists(), f"Hook not found: {SCREENSHOT_HOOK}"


def test_verify_deps_with_abx_pkg():
    """Verify dependencies are available via abx-pkg after hook installation."""
    from abx_pkg import Binary, EnvProvider, BinProviderOverrides

    EnvProvider.model_rebuild()

    # Verify node is available
    node_binary = Binary(name='node', binproviders=[EnvProvider()])
    node_loaded = node_binary.load()
    assert node_loaded and node_loaded.abspath, "Node.js required for screenshot plugin"


def test_extracts_screenshot_from_example_com():
    """Test full workflow: extract screenshot from real example.com via hook."""
    # Prerequisites checked by earlier test

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run screenshot extraction hook
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=120
        )

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

        # Parse JSONL output (clean format without RESULT_JSON= prefix)
        result_json = None
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line.startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'ArchiveResult':
                        result_json = record
                        break
                except json.JSONDecodeError:
                    pass

        assert result_json, "Should have ArchiveResult JSONL output"
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"
        assert result_json['output_str'] == 'screenshot.png'

        # Verify filesystem output (hook creates screenshot.png directly in working dir)
        screenshot_file = tmpdir / 'screenshot.png'
        assert screenshot_file.exists(), "screenshot.png not created"

        # Verify file is valid PNG
        file_size = screenshot_file.stat().st_size
        assert file_size > 1000, f"Screenshot too small: {file_size} bytes"
        assert file_size < 10 * 1024 * 1024, f"Screenshot suspiciously large: {file_size} bytes"

        # Check PNG magic bytes
        screenshot_data = screenshot_file.read_bytes()
        assert screenshot_data[:8] == b'\x89PNG\r\n\x1a\n', "Should be valid PNG file"


def test_config_save_screenshot_false_skips():
    """Test that SCREENSHOT_ENABLED=False exits without emitting JSONL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        env = os.environ.copy()
        env['SCREENSHOT_ENABLED'] = 'False'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"

        # Feature disabled - temporary failure, should NOT emit JSONL
        assert 'Skipping' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, but got: {jsonl_lines}"


def test_reports_missing_chrome():
    """Test that script reports error when Chrome is not found."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set CHROME_BINARY to nonexistent path
        env = os.environ.copy()
        env['CHROME_BINARY'] = '/nonexistent/chrome'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test123'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Should fail and report missing Chrome
        if result.returncode != 0:
            combined = result.stdout + result.stderr
            assert 'chrome' in combined.lower() or 'browser' in combined.lower() or 'ERROR=' in combined


def test_config_timeout_honored():
    """Test that CHROME_TIMEOUT config is respected."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set very short timeout
        env = os.environ.copy()
        env['CHROME_TIMEOUT'] = '5'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=testtimeout'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Should complete (success or fail, but not hang)
        assert result.returncode in (0, 1), "Should complete without hanging"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
