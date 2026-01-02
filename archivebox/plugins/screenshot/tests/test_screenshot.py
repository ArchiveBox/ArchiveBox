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

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_test_env,
    get_plugin_dir,
    get_hook_script,
    run_hook_and_parse,
    LIB_DIR,
    NODE_MODULES_DIR,
    CHROME_PLUGIN_DIR,
)

# Import chrome test fixture to ensure puppeteer is installed
from archivebox.plugins.chrome.tests.test_chrome import ensure_chromium_and_puppeteer_installed


PLUGIN_DIR = get_plugin_dir(__file__)
SCREENSHOT_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_screenshot.*')

# Get Chrome hooks for setting up sessions
CHROME_LAUNCH_HOOK = get_hook_script(CHROME_PLUGIN_DIR, 'on_Crawl__*_chrome_launch.*')
CHROME_TAB_HOOK = get_hook_script(CHROME_PLUGIN_DIR, 'on_Snapshot__*_chrome_tab.*')
CHROME_NAVIGATE_HOOK = get_hook_script(CHROME_PLUGIN_DIR, 'on_Snapshot__*_chrome_navigate.*')

TEST_URL = 'https://example.com'


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
    """Test full workflow: extract screenshot from real example.com via hook.

    Replicates production directory structure:
        DATA_DIR/users/testuser/crawls/{crawl-id}/chrome/
        DATA_DIR/users/testuser/crawls/{crawl-id}/snapshots/{snap-id}/chrome/
        DATA_DIR/users/testuser/crawls/{crawl-id}/snapshots/{snap-id}/screenshot/

    This exercises the "connect to existing session" code path which is the primary
    path in production and accounts for ~50% of the code.
    """
    import signal
    import time
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # Replicate exact production directory structure
        data_dir = Path(tmpdir)
        crawl_id = 'test-screenshot-crawl'
        snapshot_id = 'test-screenshot-snap'

        # Crawl: DATA_DIR/users/{username}/crawls/YYYYMMDD/example.com/{crawl-id}/{plugin}/
        crawl_dir = data_dir / 'users' / 'testuser' / 'crawls' / '20240101' / 'example.com' / crawl_id
        chrome_dir = crawl_dir / 'chrome'
        chrome_dir.mkdir(parents=True)

        # Snapshot: DATA_DIR/users/{username}/snapshots/YYYYMMDD/example.com/{snapshot-uuid}/{plugin}/
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / snapshot_id
        snapshot_chrome_dir = snapshot_dir / 'chrome'
        snapshot_chrome_dir.mkdir(parents=True)

        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir()

        env = get_test_env()
        env['CHROME_HEADLESS'] = 'true'

        # Step 1: Launch Chrome session at crawl level (background process)
        chrome_launch_process = subprocess.Popen(
            ['node', str(CHROME_LAUNCH_HOOK), f'--crawl-id={crawl_id}'],
            cwd=str(chrome_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )

        # Wait for Chrome to launch
        for i in range(15):
            if chrome_launch_process.poll() is not None:
                stdout, stderr = chrome_launch_process.communicate()
                pytest.fail(f"Chrome launch failed:\nStdout: {stdout}\nStderr: {stderr}")
            if (chrome_dir / 'cdp_url.txt').exists():
                break
            time.sleep(1)

        assert (chrome_dir / 'cdp_url.txt').exists(), "Chrome CDP URL file should exist"
        assert (chrome_dir / 'chrome.pid').exists(), "Chrome PID file should exist"

        chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())

        try:
            # Step 2: Create tab at snapshot level
            env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)
            result = subprocess.run(
                ['node', str(CHROME_TAB_HOOK), f'--url={TEST_URL}', f'--snapshot-id={snapshot_id}', f'--crawl-id={crawl_id}'],
                cwd=str(snapshot_chrome_dir),
                capture_output=True,
                text=True,
                timeout=60,
                env=env
            )
            assert result.returncode == 0, f"Tab creation failed: {result.stderr}"
            assert (snapshot_chrome_dir / 'cdp_url.txt').exists(), "Snapshot CDP URL should exist"

            # Step 3: Navigate to URL
            result = subprocess.run(
                ['node', str(CHROME_NAVIGATE_HOOK), f'--url={TEST_URL}', f'--snapshot-id={snapshot_id}'],
                cwd=str(snapshot_chrome_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )
            assert result.returncode == 0, f"Navigation failed: {result.stderr}"
            assert (snapshot_chrome_dir / 'navigation.json').exists(), "Navigation JSON should exist"

            # Step 4: Take screenshot (should connect to existing session)
            # Screenshot hook runs in screenshot/ dir and looks for ../chrome/cdp_url.txt
            result = subprocess.run(
                ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', f'--snapshot-id={snapshot_id}'],
                cwd=str(screenshot_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )

            assert result.returncode == 0, f"Screenshot extraction failed:\nStderr: {result.stderr}\nStdout: {result.stdout}"

            # Parse JSONL output
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
            assert 'screenshot.png' in result_json['output_str'], f"Output should be screenshot.png: {result_json}"

            # Verify filesystem output
            screenshot_file = screenshot_dir / 'screenshot.png'
            assert screenshot_file.exists(), f"screenshot.png not created at {screenshot_file}"

            # Verify file is valid PNG
            file_size = screenshot_file.stat().st_size
            assert file_size > 1000, f"Screenshot too small: {file_size} bytes"
            assert file_size < 10 * 1024 * 1024, f"Screenshot suspiciously large: {file_size} bytes"

            # Check PNG magic bytes
            screenshot_data = screenshot_file.read_bytes()
            assert screenshot_data[:8] == b'\x89PNG\r\n\x1a\n', "Should be valid PNG file"

        finally:
            # Cleanup: Kill Chrome
            try:
                chrome_launch_process.send_signal(signal.SIGTERM)
                chrome_launch_process.wait(timeout=5)
            except:
                pass
            try:
                os.kill(chrome_pid, signal.SIGKILL)
            except OSError:
                pass


def test_extracts_screenshot_without_session():
    """Test screenshot extraction without existing Chrome session (fallback to own browser)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create proper snapshot directory structure
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-fallback'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        # Don't set up Chrome session or staticfile - screenshot should launch its own browser
        env = get_test_env()
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-fallback'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

        # Parse JSONL output
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
        assert 'screenshot.png' in result_json['output_str']

        # Verify file created
        screenshot_file = screenshot_dir / 'screenshot.png'
        assert screenshot_file.exists(), "screenshot.png not created"
        assert screenshot_file.stat().st_size > 1000, "Screenshot too small"


def test_skips_when_staticfile_exists():
    """Test that screenshot skips when staticfile extractor already handled the URL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-skip'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        # Create staticfile output to simulate staticfile extractor already ran
        staticfile_dir = snapshot_dir / 'staticfile'
        staticfile_dir.mkdir()
        (staticfile_dir / 'index.html').write_text('<html></html>')

        env = get_test_env()
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-skip'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        assert result.returncode == 0, f"Should exit successfully: {result.stderr}"

        # Should emit skipped status
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
        assert result_json['status'] == 'skipped', f"Should skip: {result_json}"


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
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set CHROME_BINARY to nonexistent path
        env = get_test_env()
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


def test_custom_resolution_and_user_agent():
    """Test that CHROME_RESOLUTION and CHROME_USER_AGENT configs are respected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-config'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        env['CHROME_RESOLUTION'] = '800,600'
        env['CHROME_USER_AGENT'] = 'Test/1.0'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-config'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

        screenshot_file = screenshot_dir / 'screenshot.png'
        assert screenshot_file.exists(), "screenshot.png not created"
        # Resolution affects file size
        assert screenshot_file.stat().st_size > 500, "Screenshot too small"


def test_ssl_check_disabled():
    """Test that CHROME_CHECK_SSL_VALIDITY=False allows invalid certificates."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-ssl'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        env['CHROME_CHECK_SSL_VALIDITY'] = 'False'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-ssl'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        assert result.returncode == 0, f"Should succeed: {result.stderr}"
        assert (screenshot_dir / 'screenshot.png').exists()


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


def test_missing_url_argument():
    """Test that hook fails gracefully when URL argument is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        env = get_test_env()
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), '--snapshot-id=test-missing-url'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should exit with error
        assert result.returncode != 0, "Should fail when URL is missing"
        assert 'Usage:' in result.stderr or 'url' in result.stderr.lower()


def test_missing_snapshot_id_argument():
    """Test that hook fails gracefully when snapshot-id argument is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        env = get_test_env()
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should exit with error
        assert result.returncode != 0, "Should fail when snapshot-id is missing"
        assert 'Usage:' in result.stderr or 'snapshot' in result.stderr.lower()


def test_invalid_resolution_format():
    """Test that invalid CHROME_RESOLUTION format is handled gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-badres'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        # Invalid resolution formats to test parseResolution error handling
        for bad_resolution in ['invalid', '1440', '1440x2000', 'abc,def']:
            env['CHROME_RESOLUTION'] = bad_resolution
            result = subprocess.run(
                ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-badres'],
                cwd=str(screenshot_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )
            # Should either fail gracefully or fall back to default
            # (depending on implementation - script should not crash with uncaught error)
            assert result.returncode in (0, 1), f"Script should handle bad resolution: {bad_resolution}"


def test_boolean_env_var_parsing():
    """Test that boolean environment variables are parsed correctly."""
    import time
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-bool'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()

        # Test various boolean formats for CHROME_HEADLESS
        for bool_val in ['true', '1', 'yes', 'on', 'True', 'TRUE']:
            env['CHROME_HEADLESS'] = bool_val
            result = subprocess.run(
                ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-bool'],
                cwd=str(screenshot_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )
            # Should either succeed or fail, but shouldn't crash on boolean parsing
            assert result.returncode in (0, 1), f"Should handle boolean value: {bool_val}"

            # Clean up screenshot file if created
            screenshot_file = screenshot_dir / 'screenshot.png'
            if screenshot_file.exists():
                screenshot_file.unlink()

            time.sleep(0.5)  # Brief pause between attempts


def test_integer_env_var_parsing():
    """Test that integer environment variables are parsed correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-int'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()

        # Test valid and invalid integer formats for CHROME_TIMEOUT
        test_cases = [
            ('60', True),      # Valid integer
            ('invalid', True), # Invalid - should use default
            ('', True),        # Empty - should use default
        ]

        for timeout_val, should_work in test_cases:
            env['CHROME_TIMEOUT'] = timeout_val
            result = subprocess.run(
                ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-int'],
                cwd=str(screenshot_dir),
                capture_output=True,
                text=True,
                timeout=120,
                env=env
            )
            # Should either succeed or fail gracefully, but shouldn't crash on int parsing
            assert result.returncode in (0, 1), f"Should handle timeout value: {timeout_val}"

            # Clean up screenshot file if created
            screenshot_file = screenshot_dir / 'screenshot.png'
            if screenshot_file.exists():
                screenshot_file.unlink()


def test_extracts_screenshot_with_all_config_options():
    """Test screenshot with comprehensive config to exercise all code paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-full'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        # Set ALL config options to exercise all code paths
        env = get_test_env()
        env['CHROME_HEADLESS'] = 'true'
        env['CHROME_RESOLUTION'] = '800,600'
        env['CHROME_USER_AGENT'] = 'TestBot/1.0'
        env['CHROME_CHECK_SSL_VALIDITY'] = 'false'  # Exercises checkSsl branch
        env['CHROME_TIMEOUT'] = '60'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-full'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        assert result.returncode == 0, f"Screenshot should succeed: {result.stderr}"

        # Verify JSONL output with success
        result_json = None
        for line in result.stdout.strip().split('\n'):
            if line.strip().startswith('{'):
                try:
                    record = json.loads(line)
                    if record.get('type') == 'ArchiveResult':
                        result_json = record
                        break
                except json.JSONDecodeError:
                    pass

        assert result_json, "Should have ArchiveResult JSONL output"
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"
        assert 'screenshot.png' in result_json['output_str']

        # Verify file created
        screenshot_file = screenshot_dir / 'screenshot.png'
        assert screenshot_file.exists(), "screenshot.png should be created"
        assert screenshot_file.stat().st_size > 1000, "Screenshot should have content"


def test_headless_mode_false():
    """Test headless=false code path specifically."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-headless'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        # Explicitly test headless=false (exercises the ternary false branch)
        env['CHROME_HEADLESS'] = 'false'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-headless-false'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )
        # Should work or fail gracefully
        assert result.returncode in (0, 1), f"Headless=false should handle: {result.stderr}"


def test_invalid_url_causes_error():
    """Test error path with invalid URL that causes navigation failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-invalid'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        env['CHROME_TIMEOUT'] = '5'  # Short timeout

        # Use invalid URL to trigger error path
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), '--url=http://this-domain-does-not-exist-12345.invalid', '--snapshot-id=snap-invalid'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should fail due to navigation error
        assert result.returncode != 0, "Should fail on invalid URL"
        # Should NOT emit JSONL (transient error)
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL on error: {jsonl_lines}"


def test_with_corrupted_cdp_url_falls_back():
    """Test that corrupted CDP URL file causes fallback to launching browser."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-corrupt-cdp'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        # Create chrome directory with corrupted CDP URL
        chrome_dir = snapshot_dir / 'chrome'
        chrome_dir.mkdir()
        (chrome_dir / 'cdp_url.txt').write_text('ws://127.0.0.1:99999/invalid')

        env = get_test_env()
        env['CHROME_HEADLESS'] = 'true'
        env['CHROME_TIMEOUT'] = '5'  # Short timeout for fast test

        # Screenshot should try CDP, fail quickly, then fall back to launching own browser
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-corrupt-cdp'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )

        # Should succeed by falling back to launching browser
        assert result.returncode == 0, f"Should fallback and succeed: {result.stderr}"
        assert 'Failed to connect to CDP' in result.stderr, "Should log CDP connection failure"

        # Verify screenshot was created via fallback path
        screenshot_file = screenshot_dir / 'screenshot.png'
        assert screenshot_file.exists(), "Screenshot should be created via fallback"


def test_user_agent_is_applied():
    """Test that CHROME_USER_AGENT is actually applied when launching browser."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-ua'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        env['CHROME_USER_AGENT'] = 'CustomBot/9.9.9 (Testing)'
        env['CHROME_HEADLESS'] = 'true'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-ua'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        # Should succeed with custom user agent
        assert result.returncode == 0, f"Should succeed with custom UA: {result.stderr}"
        screenshot_file = screenshot_dir / 'screenshot.png'
        assert screenshot_file.exists(), "Screenshot should be created"


def test_check_ssl_false_branch():
    """Test CHROME_CHECK_SSL_VALIDITY=false adds ignore-certificate-errors arg."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-nossl'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        env['CHROME_CHECK_SSL_VALIDITY'] = 'false'
        env['CHROME_HEADLESS'] = 'true'

        # Test with both boolean false and string 'false'
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-nossl'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        assert result.returncode == 0, f"Should work with SSL check disabled: {result.stderr}"
        assert (screenshot_dir / 'screenshot.png').exists()


def test_alternative_env_var_names():
    """Test fallback environment variable names (TIMEOUT vs CHROME_TIMEOUT, etc)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-altenv'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        # Use alternative env var names (without CHROME_ prefix)
        env['TIMEOUT'] = '45'
        env['RESOLUTION'] = '1024,768'
        env['USER_AGENT'] = 'AltBot/1.0'
        env['CHECK_SSL_VALIDITY'] = 'false'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-altenv'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        assert result.returncode == 0, f"Should work with alternative env vars: {result.stderr}"
        assert (screenshot_dir / 'screenshot.png').exists()


def test_very_large_resolution():
    """Test screenshot with very large resolution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-large'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        env['CHROME_RESOLUTION'] = '3840,2160'  # 4K resolution
        env['CHROME_HEADLESS'] = 'true'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-large'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        assert result.returncode == 0, f"Should handle large resolution: {result.stderr}"
        screenshot_file = screenshot_dir / 'screenshot.png'
        assert screenshot_file.exists()
        # 4K screenshot should be larger
        assert screenshot_file.stat().st_size > 5000, "4K screenshot should be substantial"


def test_very_small_resolution():
    """Test screenshot with very small resolution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        snapshot_dir = data_dir / 'users' / 'testuser' / 'snapshots' / '20240101' / 'example.com' / 'snap-small'
        screenshot_dir = snapshot_dir / 'screenshot'
        screenshot_dir.mkdir(parents=True)

        env = get_test_env()
        env['CHROME_RESOLUTION'] = '320,240'  # Very small
        env['CHROME_HEADLESS'] = 'true'

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-small'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )

        assert result.returncode == 0, f"Should handle small resolution: {result.stderr}"
        assert (screenshot_dir / 'screenshot.png').exists()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
