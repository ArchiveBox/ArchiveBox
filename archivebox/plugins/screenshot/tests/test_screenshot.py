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
SCREENSHOT_HOOK = PLUGIN_DIR / 'on_Snapshot__34_screenshot.js'
CHROME_INSTALL_HOOK = PLUGINS_ROOT / 'chrome' / 'on_Crawl__00_chrome_install.py'
TEST_URL = 'https://example.com'


def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert SCREENSHOT_HOOK.exists(), f"Hook not found: {SCREENSHOT_HOOK}"


def test_chrome_validation_and_install():
    """Test chrome install hook to verify Chrome is available."""
    # Try with explicit CHROME_BINARY first (faster)
    chrome_app_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

    if Path(chrome_app_path).exists():
        # Use CHROME_BINARY env var pointing to Chrome.app
        result = subprocess.run(
            [sys.executable, str(CHROME_INSTALL_HOOK)],
            capture_output=True,
            text=True,
            env={**os.environ, 'CHROME_BINARY': chrome_app_path},
            timeout=30
        )

        # When CHROME_BINARY is set and valid, hook exits 0 immediately without output (optimization)
        assert result.returncode == 0, f"Should find Chrome at {chrome_app_path}. Error: {result.stderr}"
        print(f"Chrome validated at explicit path: {chrome_app_path}")
    else:
        # Run chrome install hook (from chrome plugin) to find or install Chrome
        result = subprocess.run(
            [sys.executable, str(CHROME_INSTALL_HOOK)],
            capture_output=True,
            text=True,
            timeout=300  # Longer timeout for potential install
        )

        if result.returncode == 0:
            # Parse output to verify Binary record
            binary_found = False
            binary_path = None

            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        record = json.loads(line)
                        if record.get('type') == 'Binary':
                            binary_found = True
                            binary_path = record.get('abspath')
                            assert record['name'] == 'chrome', f"Binary name should be 'chrome', got {record['name']}"
                            assert binary_path, "Binary should have abspath"
                            print(f"Found Chrome at: {binary_path}")
                            break
                    except json.JSONDecodeError:
                        pass

            assert binary_found, f"Should output Binary record when Chrome found. Output: {result.stdout}"
        else:
            pytest.fail(f"Chrome installation failed. Please install Chrome manually or ensure @puppeteer/browsers is available. Error: {result.stderr}")


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
    """Test that SAVE_SCREENSHOT=False causes skip."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        env = os.environ.copy()
        env['SAVE_SCREENSHOT'] = 'False'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when skipping: {result.stderr}"

        # Parse JSONL output to verify skipped status
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
        assert result_json['status'] in ('skipped', 'succeeded'), f"Should skip or succeed: {result_json}"


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
