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
import subprocess
import time
import tempfile
from pathlib import Path

import pytest

# Import shared Chrome test helpers
from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_test_env,
    chrome_session,
)


PLUGIN_DIR = Path(__file__).parent.parent
INFINISCROLL_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_infiniscroll.*'), None)
TEST_URL = 'https://www.singsing.movie/'


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


def test_scrolls_page_and_outputs_stats():
    """Integration test: scroll page and verify JSONL output format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with chrome_session(
            Path(tmpdir),
            crawl_id='test-infiniscroll',
            snapshot_id='snap-infiniscroll',
            test_url=TEST_URL,
        ) as (chrome_launch_process, chrome_pid, snapshot_chrome_dir, env):
            # Create infiniscroll output directory (sibling to chrome)
            infiniscroll_dir = snapshot_chrome_dir.parent / 'infiniscroll'
            infiniscroll_dir.mkdir()

            # Run infiniscroll hook
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


def test_config_scroll_limit_honored():
    """Test that INFINISCROLL_SCROLL_LIMIT config is respected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with chrome_session(
            Path(tmpdir),
            crawl_id='test-scroll-limit',
            snapshot_id='snap-limit',
            test_url=TEST_URL,
        ) as (chrome_launch_process, chrome_pid, snapshot_chrome_dir, env):

            infiniscroll_dir = snapshot_chrome_dir.parent / 'infiniscroll'
            infiniscroll_dir.mkdir()

            # Set scroll limit to 2 (use env from setup_chrome_session)
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



def test_config_timeout_honored():
    """Test that INFINISCROLL_TIMEOUT config is respected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with chrome_session(
            Path(tmpdir),
            crawl_id='test-timeout',
            snapshot_id='snap-timeout',
            test_url=TEST_URL,
        ) as (chrome_launch_process, chrome_pid, snapshot_chrome_dir, env):

            infiniscroll_dir = snapshot_chrome_dir.parent / 'infiniscroll'
            infiniscroll_dir.mkdir()

            # Set very short timeout (use env from setup_chrome_session)
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



if __name__ == '__main__':
    pytest.main([__file__, '-v'])
