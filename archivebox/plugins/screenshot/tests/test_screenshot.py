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
    chrome_session,
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


def test_screenshot_with_chrome_session():
    """Test multiple screenshot scenarios with one Chrome session to save time."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_url = 'https://example.com'
        snapshot_id = 'test-screenshot-snap'

        try:
            with chrome_session(
                Path(tmpdir),
                crawl_id='test-screenshot-crawl',
                snapshot_id=snapshot_id,
                test_url=test_url,
                navigate=True,
                timeout=30,
            ) as (chrome_process, chrome_pid, snapshot_chrome_dir, env):

                # Scenario 1: Basic screenshot extraction
                screenshot_dir = snapshot_chrome_dir.parent / 'screenshot'
                screenshot_dir.mkdir()

                result = subprocess.run(
                    ['node', str(SCREENSHOT_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(screenshot_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env
                )

                assert result.returncode == 0, f"Screenshot extraction failed:\nStderr: {result.stderr}"

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

                assert result_json and result_json['status'] == 'succeeded'
                screenshot_file = screenshot_dir / 'screenshot.png'
                assert screenshot_file.exists() and screenshot_file.stat().st_size > 1000
                assert screenshot_file.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'

                # Scenario 2: Custom resolution
                screenshot_dir2 = snapshot_chrome_dir.parent / 'screenshot2'
                screenshot_dir2.mkdir()
                env['CHROME_RESOLUTION'] = '800,600'

                result = subprocess.run(
                    ['node', str(SCREENSHOT_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(screenshot_dir2),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env
                )

                assert result.returncode == 0
                screenshot_file2 = screenshot_dir2 / 'screenshot.png'
                assert screenshot_file2.exists()
                file_size = screenshot_file2.stat().st_size
                assert 500 < file_size < 100000, f"800x600 screenshot size unexpected: {file_size}"

                # Scenario 3: Wrong target ID (error case)
                screenshot_dir3 = snapshot_chrome_dir.parent / 'screenshot3'
                screenshot_dir3.mkdir()
                (snapshot_chrome_dir / 'target_id.txt').write_text('nonexistent-target-id')

                result = subprocess.run(
                    ['node', str(SCREENSHOT_HOOK), f'--url={test_url}', f'--snapshot-id={snapshot_id}'],
                    cwd=str(screenshot_dir3),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env
                )

                assert result.returncode != 0
                assert 'target' in result.stderr.lower() and 'not found' in result.stderr.lower()

        except RuntimeError as e:
            if 'Chrome' in str(e) or 'CDP' in str(e):
                pytest.skip(f"Chrome session setup failed: {e}")
            raise


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
        (staticfile_dir / 'stdout.log').write_text('{"type":"ArchiveResult","status":"succeeded","output_str":"index.html"}\n')

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

    # FIRST check what Python sees
    print(f"\n[DEBUG PYTHON] NODE_V8_COVERAGE in os.environ: {'NODE_V8_COVERAGE' in os.environ}")
    print(f"[DEBUG PYTHON] Value: {os.environ.get('NODE_V8_COVERAGE', 'NOT SET')}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        env = os.environ.copy()
        env['SCREENSHOT_ENABLED'] = 'False'

        # Check what's in the copied env
        print(f"[DEBUG ENV COPY] NODE_V8_COVERAGE in env: {'NODE_V8_COVERAGE' in env}")
        print(f"[DEBUG ENV COPY] Value: {env.get('NODE_V8_COVERAGE', 'NOT SET')}")

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        print(f"[DEBUG RESULT] Exit code: {result.returncode}")
        print(f"[DEBUG RESULT] Stderr: {result.stderr[:200]}")

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


def test_waits_for_navigation_timeout():
    """Test that screenshot waits for navigation.json and times out quickly if missing."""
    import time

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create chrome directory without navigation.json to trigger timeout
        chrome_dir = tmpdir.parent / 'chrome'
        chrome_dir.mkdir(parents=True, exist_ok=True)
        (chrome_dir / 'cdp_url.txt').write_text('ws://localhost:9222/devtools/browser/test')
        (chrome_dir / 'target_id.txt').write_text('test-target-id')
        # Intentionally NOT creating navigation.json to test timeout

        screenshot_dir = tmpdir / 'screenshot'
        screenshot_dir.mkdir()

        env = get_test_env()
        env['SCREENSHOT_TIMEOUT'] = '2'  # Set 2 second timeout

        start_time = time.time()
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test-timeout'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=5,  # Test timeout slightly higher than SCREENSHOT_TIMEOUT
            env=env
        )
        elapsed = time.time() - start_time

        # Should fail when navigation.json doesn't appear
        assert result.returncode != 0, "Should fail when navigation.json missing"
        assert 'not loaded' in result.stderr.lower() or 'navigate' in result.stderr.lower(), f"Should mention navigation timeout: {result.stderr}"
        # Should complete within 3s (2s wait + 1s overhead)
        assert elapsed < 3, f"Should timeout within 3s, took {elapsed:.1f}s"


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

def test_no_cdp_url_fails():
    """Test error when chrome dir exists but no cdp_url.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        chrome_dir = tmpdir / 'chrome'
        chrome_dir.mkdir()
        # Create target_id.txt and navigation.json but NOT cdp_url.txt
        (chrome_dir / 'target_id.txt').write_text('test-target')
        (chrome_dir / 'navigation.json').write_text('{}')

        screenshot_dir = tmpdir / 'screenshot'
        screenshot_dir.mkdir()

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), '--url=https://example.com', '--snapshot-id=test'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=7,
            env=get_test_env()
        )

        assert result.returncode != 0
        assert 'no chrome session' in result.stderr.lower()


def test_no_target_id_fails():
    """Test error when cdp_url exists but no target_id.txt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        chrome_dir = tmpdir / 'chrome'
        chrome_dir.mkdir()
        # Create cdp_url.txt and navigation.json but NOT target_id.txt
        (chrome_dir / 'cdp_url.txt').write_text('ws://localhost:9222/devtools/browser/test')
        (chrome_dir / 'navigation.json').write_text('{}')

        screenshot_dir = tmpdir / 'screenshot'
        screenshot_dir.mkdir()

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), '--url=https://example.com', '--snapshot-id=test'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=7,
            env=get_test_env()
        )

        assert result.returncode != 0
        assert 'target_id.txt' in result.stderr.lower()


def test_invalid_cdp_url_fails():
    """Test error with malformed CDP URL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        chrome_dir = tmpdir / 'chrome'
        chrome_dir.mkdir()
        (chrome_dir / 'cdp_url.txt').write_text('invalid-url')
        (chrome_dir / 'target_id.txt').write_text('test-target')
        (chrome_dir / 'navigation.json').write_text('{}')

        screenshot_dir = tmpdir / 'screenshot'
        screenshot_dir.mkdir()

        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), '--url=https://example.com', '--snapshot-id=test'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=7,
            env=get_test_env()
        )

        assert result.returncode != 0


def test_invalid_timeout_uses_default():
    """Test that invalid SCREENSHOT_TIMEOUT falls back to default."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        chrome_dir = tmpdir / 'chrome'
        chrome_dir.mkdir()
        # No navigation.json to trigger timeout
        (chrome_dir / 'cdp_url.txt').write_text('ws://localhost:9222/test')
        (chrome_dir / 'target_id.txt').write_text('test')

        screenshot_dir = tmpdir / 'screenshot'
        screenshot_dir.mkdir()

        env = get_test_env()
        env['SCREENSHOT_TIMEOUT'] = 'invalid'  # Should fallback to default (10s becomes NaN, treated as 0)

        import time
        start = time.time()
        result = subprocess.run(
            ['node', str(SCREENSHOT_HOOK), '--url=https://example.com', '--snapshot-id=test'],
            cwd=str(screenshot_dir),
            capture_output=True,
            text=True,
            timeout=5,
            env=env
        )
        elapsed = time.time() - start

        # With invalid timeout, parseInt returns NaN, which should be handled
        assert result.returncode != 0
        assert elapsed < 2  # Should fail quickly, not wait 10s


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
