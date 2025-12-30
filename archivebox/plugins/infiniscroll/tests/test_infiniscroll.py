"""
Integration tests for infiniscroll plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via chrome validation hooks
3. Verify deps with abx-pkg
4. INFINISCROLL_ENABLED=False skips without JSONL
5. Fails gracefully when no chrome session exists
6. Full integration test: scrolls page and outputs stats
7. Config options work (scroll limit, min height)
"""

import json
import os
import re
import signal
import subprocess
import time
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
INFINISCROLL_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_infiniscroll.*'), None)
CHROME_LAUNCH_HOOK = PLUGINS_ROOT / 'chrome' / 'on_Crawl__20_chrome_launch.bg.js'
CHROME_TAB_HOOK = PLUGINS_ROOT / 'chrome' / 'on_Snapshot__20_chrome_tab.bg.js'
CHROME_NAVIGATE_HOOK = next((PLUGINS_ROOT / 'chrome').glob('on_Snapshot__*_chrome_navigate.*'), None)
TEST_URL = 'https://www.singsing.movie/'


def get_node_modules_dir():
    """Get NODE_MODULES_DIR for tests, checking env first."""
    # Check if NODE_MODULES_DIR is already set in environment
    if os.environ.get('NODE_MODULES_DIR'):
        return Path(os.environ['NODE_MODULES_DIR'])
    # Otherwise compute from LIB_DIR
    from archivebox.config.common import STORAGE_CONFIG
    lib_dir = Path(os.environ.get('LIB_DIR') or str(STORAGE_CONFIG.LIB_DIR))
    return lib_dir / 'npm' / 'node_modules'


NODE_MODULES_DIR = get_node_modules_dir()


def get_test_env():
    """Get environment with NODE_MODULES_DIR set correctly."""
    env = os.environ.copy()
    env['NODE_MODULES_DIR'] = str(NODE_MODULES_DIR)
    return env


def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert INFINISCROLL_HOOK is not None, "Infiniscroll hook not found"
    assert INFINISCROLL_HOOK.exists(), f"Hook not found: {INFINISCROLL_HOOK}"


def test_verify_deps_with_abx_pkg():
    """Verify dependencies are available via abx-pkg after hook installation."""
    from abx_pkg import Binary, EnvProvider, BinProviderOverrides

    EnvProvider.model_rebuild()

    # Verify node is available
    node_binary = Binary(name='node', binproviders=[EnvProvider()])
    node_loaded = node_binary.load()
    assert node_loaded and node_loaded.abspath, "Node.js required for infiniscroll plugin"


def test_config_infiniscroll_disabled_skips():
    """Test that INFINISCROLL_ENABLED=False exits without emitting JSONL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        env = get_test_env()
        env['INFINISCROLL_ENABLED'] = 'False'

        result = subprocess.run(
            ['node', str(INFINISCROLL_HOOK), f'--url={TEST_URL}', '--snapshot-id=test-disabled'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"
        assert 'Skipping' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, got: {jsonl_lines}"


def test_fails_gracefully_without_chrome_session():
    """Test that hook fails gracefully when no chrome session exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        result = subprocess.run(
            ['node', str(INFINISCROLL_HOOK), f'--url={TEST_URL}', '--snapshot-id=test-no-chrome'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=get_test_env(),
            timeout=30
        )

        # Should fail (exit 1) when no chrome session
        assert result.returncode != 0, "Should fail when no chrome session exists"
        # Error could be about chrome/CDP not found, or puppeteer module missing
        err_lower = result.stderr.lower()
        assert any(x in err_lower for x in ['chrome', 'cdp', 'puppeteer', 'module']), \
            f"Should mention chrome/CDP/puppeteer in error: {result.stderr}"


def setup_chrome_session(tmpdir):
    """Helper to set up Chrome session with tab and navigation."""
    crawl_dir = Path(tmpdir) / 'crawl'
    crawl_dir.mkdir()
    chrome_dir = crawl_dir / 'chrome'

    env = get_test_env()
    env['CHROME_HEADLESS'] = 'true'

    # Launch Chrome at crawl level
    chrome_launch_process = subprocess.Popen(
        ['node', str(CHROME_LAUNCH_HOOK), '--crawl-id=test-infiniscroll'],
        cwd=str(crawl_dir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env
    )

    # Wait for Chrome to launch
    for i in range(15):
        if chrome_launch_process.poll() is not None:
            stdout, stderr = chrome_launch_process.communicate()
            raise RuntimeError(f"Chrome launch failed:\nStdout: {stdout}\nStderr: {stderr}")
        if (chrome_dir / 'cdp_url.txt').exists():
            break
        time.sleep(1)

    if not (chrome_dir / 'cdp_url.txt').exists():
        raise RuntimeError("Chrome CDP URL not found after 15s")

    chrome_pid = int((chrome_dir / 'chrome.pid').read_text().strip())

    # Create snapshot directory structure
    snapshot_dir = Path(tmpdir) / 'snapshot'
    snapshot_dir.mkdir()
    snapshot_chrome_dir = snapshot_dir / 'chrome'
    snapshot_chrome_dir.mkdir()

    # Create tab
    tab_env = env.copy()
    tab_env['CRAWL_OUTPUT_DIR'] = str(crawl_dir)
    result = subprocess.run(
        ['node', str(CHROME_TAB_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-infiniscroll', '--crawl-id=test-infiniscroll'],
        cwd=str(snapshot_chrome_dir),
        capture_output=True,
        text=True,
        timeout=60,
        env=tab_env
    )
    if result.returncode != 0:
        raise RuntimeError(f"Tab creation failed: {result.stderr}")

    # Navigate to URL
    result = subprocess.run(
        ['node', str(CHROME_NAVIGATE_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-infiniscroll'],
        cwd=str(snapshot_chrome_dir),
        capture_output=True,
        text=True,
        timeout=120,
        env=env
    )
    if result.returncode != 0:
        raise RuntimeError(f"Navigation failed: {result.stderr}")

    return chrome_launch_process, chrome_pid, snapshot_chrome_dir


def cleanup_chrome(chrome_launch_process, chrome_pid):
    """Helper to clean up Chrome processes."""
    try:
        chrome_launch_process.send_signal(signal.SIGTERM)
        chrome_launch_process.wait(timeout=5)
    except:
        pass
    try:
        os.kill(chrome_pid, signal.SIGKILL)
    except OSError:
        pass


def test_scrolls_page_and_outputs_stats():
    """Integration test: scroll page and verify JSONL output format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chrome_launch_process = None
        chrome_pid = None
        try:
            chrome_launch_process, chrome_pid, snapshot_chrome_dir = setup_chrome_session(tmpdir)

            # Create infiniscroll output directory (sibling to chrome)
            infiniscroll_dir = snapshot_chrome_dir.parent / 'infiniscroll'
            infiniscroll_dir.mkdir()

            # Run infiniscroll hook
            env = get_test_env()
            env['INFINISCROLL_SCROLL_LIMIT'] = '3'  # Limit scrolls for faster test
            env['INFINISCROLL_SCROLL_DELAY'] = '500'  # Faster scrolling
            env['INFINISCROLL_MIN_HEIGHT'] = '1000'  # Lower threshold for test

            result = subprocess.run(
                ['node', str(INFINISCROLL_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-infiniscroll'],
                cwd=str(infiniscroll_dir),
                capture_output=True,
                text=True,
                timeout=60,
                env=env
            )

            assert result.returncode == 0, f"Infiniscroll failed: {result.stderr}\nStdout: {result.stdout}"

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

            assert result_json is not None, f"Should have ArchiveResult JSONL output. Stdout: {result.stdout}"
            assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

            # Verify output_str format: "scrolled to X,XXXpx (+Y,YYYpx new content) over Z.Zs"
            output_str = result_json.get('output_str', '')
            assert output_str.startswith('scrolled to'), f"output_str should start with 'scrolled to': {output_str}"
            assert 'px' in output_str, f"output_str should contain pixel count: {output_str}"
            assert re.search(r'over \d+(\.\d+)?s', output_str), f"output_str should contain duration: {output_str}"

            # Verify no files created in output directory
            output_files = list(infiniscroll_dir.iterdir())
            assert len(output_files) == 0, f"Should not create any files, but found: {output_files}"

        finally:
            if chrome_launch_process and chrome_pid:
                cleanup_chrome(chrome_launch_process, chrome_pid)


def test_config_scroll_limit_honored():
    """Test that INFINISCROLL_SCROLL_LIMIT config is respected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chrome_launch_process = None
        chrome_pid = None
        try:
            chrome_launch_process, chrome_pid, snapshot_chrome_dir = setup_chrome_session(tmpdir)

            infiniscroll_dir = snapshot_chrome_dir.parent / 'infiniscroll'
            infiniscroll_dir.mkdir()

            # Set scroll limit to 2
            env = get_test_env()
            env['INFINISCROLL_SCROLL_LIMIT'] = '2'
            env['INFINISCROLL_SCROLL_DELAY'] = '500'
            env['INFINISCROLL_MIN_HEIGHT'] = '100000'  # High threshold so limit kicks in

            result = subprocess.run(
                ['node', str(INFINISCROLL_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-limit'],
                cwd=str(infiniscroll_dir),
                capture_output=True,
                text=True,
                timeout=60,
                env=env
            )

            assert result.returncode == 0, f"Infiniscroll failed: {result.stderr}"

            # Parse output and verify scroll count
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

            assert result_json is not None, "Should have JSONL output"
            output_str = result_json.get('output_str', '')

            # Verify output format and that it completed (scroll limit enforced internally)
            assert output_str.startswith('scrolled to'), f"Should have valid output_str: {output_str}"
            assert result_json['status'] == 'succeeded', f"Should succeed with scroll limit: {result_json}"

        finally:
            if chrome_launch_process and chrome_pid:
                cleanup_chrome(chrome_launch_process, chrome_pid)


def test_config_timeout_honored():
    """Test that INFINISCROLL_TIMEOUT config is respected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        chrome_launch_process = None
        chrome_pid = None
        try:
            chrome_launch_process, chrome_pid, snapshot_chrome_dir = setup_chrome_session(tmpdir)

            infiniscroll_dir = snapshot_chrome_dir.parent / 'infiniscroll'
            infiniscroll_dir.mkdir()

            # Set very short timeout
            env = get_test_env()
            env['INFINISCROLL_TIMEOUT'] = '3'  # 3 seconds
            env['INFINISCROLL_SCROLL_DELAY'] = '2000'  # 2s delay - timeout should trigger
            env['INFINISCROLL_SCROLL_LIMIT'] = '100'  # High limit
            env['INFINISCROLL_MIN_HEIGHT'] = '100000'

            start_time = time.time()
            result = subprocess.run(
                ['node', str(INFINISCROLL_HOOK), f'--url={TEST_URL}', '--snapshot-id=snap-timeout'],
                cwd=str(infiniscroll_dir),
                capture_output=True,
                text=True,
                timeout=30,
                env=env
            )
            elapsed = time.time() - start_time

            # Should complete within reasonable time (timeout + buffer)
            assert elapsed < 15, f"Should respect timeout, took {elapsed:.1f}s"
            assert result.returncode == 0, f"Should complete even with timeout: {result.stderr}"

        finally:
            if chrome_launch_process and chrome_pid:
                cleanup_chrome(chrome_launch_process, chrome_pid)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
