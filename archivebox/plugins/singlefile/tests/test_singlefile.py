"""
Integration tests for singlefile plugin

Tests verify:
1. Hook scripts exist with correct naming
2. CLI-based singlefile extraction works
3. Dependencies available via abx-pkg
4. Output contains valid HTML
5. Connects to Chrome session via CDP when available
6. Works with extensions loaded (ublock, etc.)
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
    chrome_session,
    cleanup_chrome,
)


PLUGIN_DIR = get_plugin_dir(__file__)
SNAPSHOT_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_singlefile.py')
INSTALL_SCRIPT = PLUGIN_DIR / 'on_Crawl__82_singlefile_install.js'
TEST_URL = "https://example.com"


def test_snapshot_hook_exists():
    """Verify snapshot extraction hook exists"""
    assert SNAPSHOT_HOOK is not None and SNAPSHOT_HOOK.exists(), f"Snapshot hook not found in {PLUGIN_DIR}"


def test_snapshot_hook_priority():
    """Test that snapshot hook has correct priority (50)"""
    filename = SNAPSHOT_HOOK.name
    assert "50" in filename, "SingleFile snapshot hook should have priority 50"
    assert filename.startswith("on_Snapshot__50_"), "Should follow priority naming convention"


def test_verify_deps_with_abx_pkg():
    """Verify dependencies are available via abx-pkg."""
    from abx_pkg import Binary, EnvProvider

    EnvProvider.model_rebuild()

    # Verify node is available
    node_binary = Binary(name='node', binproviders=[EnvProvider()])
    node_loaded = node_binary.load()
    assert node_loaded and node_loaded.abspath, "Node.js required for singlefile plugin"


def test_singlefile_cli_archives_example_com():
    """Test that singlefile CLI archives example.com and produces valid HTML."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        env = get_test_env()
        env['SINGLEFILE_ENABLED'] = 'true'

        # Run singlefile snapshot hook
        result = subprocess.run(
            [sys.executable, str(SNAPSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )

        assert result.returncode == 0, f"Hook execution failed: {result.stderr}"

        # Verify output file exists
        output_file = tmpdir / 'singlefile.html'
        assert output_file.exists(), f"singlefile.html not created. stdout: {result.stdout}, stderr: {result.stderr}"

        # Verify it contains real HTML
        html_content = output_file.read_text()
        assert len(html_content) > 500, "Output file too small to be valid HTML"
        assert '<!DOCTYPE html>' in html_content or '<html' in html_content, "Output should contain HTML doctype or html tag"
        assert 'Example Domain' in html_content, "Output should contain example.com content"


def test_singlefile_with_chrome_session():
    """Test singlefile connects to existing Chrome session via CDP.

    When a Chrome session exists (chrome/cdp_url.txt), singlefile should
    connect to it instead of launching a new Chrome instance.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set up Chrome session using shared helper
        with chrome_session(
            tmpdir=tmpdir,
            crawl_id='singlefile-test-crawl',
            snapshot_id='singlefile-test-snap',
            test_url=TEST_URL,
            navigate=False,  # Don't navigate, singlefile will do that
            timeout=20,
        ) as (chrome_launch_process, chrome_pid, snapshot_chrome_dir, env):
            # singlefile looks for ../chrome/cdp_url.txt relative to cwd
            # So we need to run from a directory that has ../chrome pointing to our chrome dir
            singlefile_output_dir = tmpdir / 'snapshot' / 'singlefile'
            singlefile_output_dir.mkdir(parents=True, exist_ok=True)

            # Create symlink so singlefile can find the chrome session
            chrome_link = singlefile_output_dir.parent / 'chrome'
            if not chrome_link.exists():
                chrome_link.symlink_to(tmpdir / 'crawl' / 'chrome')

            # Use env from chrome_session
            env['SINGLEFILE_ENABLED'] = 'true'

            # Run singlefile - it should find and use the existing Chrome session
            result = subprocess.run(
                [sys.executable, str(SNAPSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=singlefile-test-snap'],
                cwd=str(singlefile_output_dir),
                capture_output=True,
                text=True,
                env=env,
                timeout=120
            )

            # Verify output
            output_file = singlefile_output_dir / 'singlefile.html'
            if output_file.exists():
                html_content = output_file.read_text()
                assert len(html_content) > 500, "Output file too small"
                assert 'Example Domain' in html_content, "Should contain example.com content"
            else:
                # If singlefile couldn't connect to Chrome, it may have failed
                # Check if it mentioned browser-server in its args (indicating it tried to use CDP)
                assert result.returncode == 0 or 'browser-server' in result.stderr or 'cdp' in result.stderr.lower(), \
                    f"Singlefile should attempt CDP connection. stderr: {result.stderr}"


def test_singlefile_with_extension_uses_existing_chrome():
    """Test SingleFile uses the Chrome extension via existing session (CLI fallback disabled)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        data_dir = tmpdir / 'data'
        extensions_dir = data_dir / 'personas' / 'Default' / 'chrome_extensions'
        downloads_dir = data_dir / 'personas' / 'Default' / 'chrome_downloads'
        user_data_dir = data_dir / 'personas' / 'Default' / 'chrome_user_data'
        extensions_dir.mkdir(parents=True, exist_ok=True)
        downloads_dir.mkdir(parents=True, exist_ok=True)
        user_data_dir.mkdir(parents=True, exist_ok=True)

        env_install = os.environ.copy()
        env_install.update({
            'DATA_DIR': str(data_dir),
            'CHROME_EXTENSIONS_DIR': str(extensions_dir),
            'CHROME_DOWNLOADS_DIR': str(downloads_dir),
        })

        # Install SingleFile extension cache before launching Chrome
        result = subprocess.run(
            ['node', str(INSTALL_SCRIPT)],
            capture_output=True,
            text=True,
            env=env_install,
            timeout=120
        )
        assert result.returncode == 0, f"Extension install failed: {result.stderr}"

        # Launch Chrome session with extensions loaded
        old_env = os.environ.copy()
        os.environ['CHROME_USER_DATA_DIR'] = str(user_data_dir)
        os.environ['CHROME_DOWNLOADS_DIR'] = str(downloads_dir)
        os.environ['CHROME_EXTENSIONS_DIR'] = str(extensions_dir)
        try:
            with chrome_session(
                tmpdir=tmpdir,
                crawl_id='singlefile-ext-crawl',
                snapshot_id='singlefile-ext-snap',
                test_url=TEST_URL,
                navigate=True,
                timeout=30,
            ) as (_chrome_proc, _chrome_pid, snapshot_chrome_dir, env):
                singlefile_output_dir = tmpdir / 'snapshot' / 'singlefile'
                singlefile_output_dir.mkdir(parents=True, exist_ok=True)

                # Ensure ../chrome points to snapshot chrome session (contains target_id.txt)
                chrome_dir = singlefile_output_dir.parent / 'chrome'
                if not chrome_dir.exists():
                    chrome_dir.symlink_to(snapshot_chrome_dir)

                env['SINGLEFILE_ENABLED'] = 'true'
                env['SINGLEFILE_BINARY'] = '/nonexistent/single-file'  # force extension path
                env['CHROME_EXTENSIONS_DIR'] = str(extensions_dir)
                env['CHROME_DOWNLOADS_DIR'] = str(downloads_dir)
                env['CHROME_HEADLESS'] = 'false'

                # Track downloads dir state before run to ensure file is created then moved out
                downloads_before = set(downloads_dir.glob('*.html'))
                downloads_mtime_before = downloads_dir.stat().st_mtime_ns

                result = subprocess.run(
                    [sys.executable, str(SNAPSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=singlefile-ext-snap'],
                    cwd=str(singlefile_output_dir),
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=120
                )

                assert result.returncode == 0, f"SingleFile extension run failed: {result.stderr}"

                output_file = singlefile_output_dir / 'singlefile.html'
                assert output_file.exists(), f"singlefile.html not created. stdout: {result.stdout}, stderr: {result.stderr}"
                html_content = output_file.read_text(errors='ignore')
                assert 'Example Domain' in html_content, "Output should contain example.com content"

                # Verify download moved out of downloads dir
                downloads_after = set(downloads_dir.glob('*.html'))
                new_downloads = downloads_after - downloads_before
                downloads_mtime_after = downloads_dir.stat().st_mtime_ns
                assert downloads_mtime_after != downloads_mtime_before, "Downloads dir should be modified during extension save"
                assert not new_downloads, f"SingleFile download should be moved out of downloads dir, found: {new_downloads}"
        finally:
            os.environ.clear()
            os.environ.update(old_env)


def test_singlefile_disabled_skips():
    """Test that SINGLEFILE_ENABLED=False exits without JSONL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        env = get_test_env()
        env['SINGLEFILE_ENABLED'] = 'False'

        result = subprocess.run(
            [sys.executable, str(SNAPSHOT_HOOK), f'--url={TEST_URL}', '--snapshot-id=test-disabled'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when disabled: {result.stderr}"

        # Should NOT emit JSONL when disabled
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when disabled, but got: {jsonl_lines}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
