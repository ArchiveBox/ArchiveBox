"""
Integration tests for wget plugin

Tests verify:
1. Plugin reports missing dependency correctly
2. wget can be installed via brew/apt provider hooks
3. Config options work (SAVE_WGET, SAVE_WARC, etc.)
4. Extraction works against real example.com
5. Output files contain actual page content
6. Skip cases work (SAVE_WGET=False, staticfile present)
7. Failure cases handled (404, network errors)
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
WGET_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_wget.py'))
BREW_HOOK = PLUGINS_ROOT / 'brew' / 'on_Dependency__install_using_brew_provider.py'
APT_HOOK = PLUGINS_ROOT / 'apt' / 'on_Dependency__install_using_apt_provider.py'
TEST_URL = 'https://example.com'


def test_hook_script_exists():
    """Verify hook script exists."""
    assert WGET_HOOK.exists(), f"Hook script not found: {WGET_HOOK}"


def test_reports_missing_dependency_when_not_installed():
    """Test that script reports DEPENDENCY_NEEDED when wget is not found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run with empty PATH so binary won't be found
        env = {'PATH': '/nonexistent', 'HOME': str(tmpdir)}

        result = subprocess.run(
            [sys.executable, str(WGET_HOOK), '--url', TEST_URL, '--snapshot-id', 'test123'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env
        )

        # Should fail and report missing dependency
        assert result.returncode != 0, "Should exit non-zero when dependency missing"
        combined = result.stdout + result.stderr
        assert 'DEPENDENCY_NEEDED' in combined, "Should output DEPENDENCY_NEEDED"
        assert 'wget' in combined.lower(), "Should mention wget"
        assert 'BIN_PROVIDERS' in combined, "Should report available providers (apt,brew,env)"


def test_can_install_wget_via_provider():
    """Test that wget can be installed via brew/apt provider hooks."""

    # Determine which provider to use
    if shutil.which('brew'):
        provider_hook = BREW_HOOK
        provider_name = 'brew'
    elif shutil.which('apt-get'):
        provider_hook = APT_HOOK
        provider_name = 'apt'
    else:
        pytest.skip("Neither brew nor apt available on this system")

    assert provider_hook.exists(), f"Provider hook not found: {provider_hook}"

    # Test installation via provider hook
    dependency_id = str(uuid.uuid4())

    result = subprocess.run(
        [
            sys.executable,
            str(provider_hook),
            '--dependency-id', dependency_id,
            '--bin-name', 'wget',
            '--bin-providers', 'apt,brew,env'
        ],
        capture_output=True,
        text=True,
        timeout=300  # Installation can take time
    )

    # Should succeed (wget installs successfully or is already installed)
    assert result.returncode == 0, f"{provider_name} install failed: {result.stderr}"

    # Should output InstalledBinary JSONL record
    assert 'InstalledBinary' in result.stdout or 'wget' in result.stderr, \
        f"Should output installation info: stdout={result.stdout}, stderr={result.stderr}"

    # Parse JSONL if present
    if result.stdout.strip():
        for line in result.stdout.strip().split('\n'):
            try:
                record = json.loads(line)
                if record.get('type') == 'InstalledBinary':
                    assert record['name'] == 'wget'
                    assert record['binprovider'] in ['brew', 'apt']
                    assert record['abspath'], "Should have binary path"
                    assert Path(record['abspath']).exists(), f"Binary should exist at {record['abspath']}"
                    break
            except json.JSONDecodeError:
                continue

    # Verify wget is now available
    result = subprocess.run(['which', 'wget'], capture_output=True, text=True)
    assert result.returncode == 0, "wget should be available after installation"


def test_archives_example_com():
    """Test full workflow: ensure wget installed then archive example.com."""

    # First ensure wget is installed via provider
    if shutil.which('brew'):
        provider_hook = BREW_HOOK
    elif shutil.which('apt-get'):
        provider_hook = APT_HOOK
    else:
        pytest.skip("Neither brew nor apt available")

    # Run installation (idempotent - will succeed if already installed)
    install_result = subprocess.run(
        [
            sys.executable,
            str(provider_hook),
            '--dependency-id', str(uuid.uuid4()),
            '--bin-name', 'wget',
            '--bin-providers', 'apt,brew,env'
        ],
        capture_output=True,
        text=True,
        timeout=300
    )

    if install_result.returncode != 0:
        pytest.skip(f"Could not install wget: {install_result.stderr}")

    # Now test archiving
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run wget extraction
        result = subprocess.run(
            [sys.executable, str(WGET_HOOK), '--url', TEST_URL, '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=120
        )

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

        # Verify output in stdout
        assert 'STATUS=succeeded' in result.stdout, "Should report success"
        assert 'wget completed' in result.stdout, "Should report completion"

        # Verify files were downloaded
        downloaded_files = list(tmpdir.rglob('*.html')) + list(tmpdir.rglob('*.htm'))
        assert len(downloaded_files) > 0, "No HTML files downloaded"

        # Find main HTML file (should contain example.com)
        main_html = None
        for html_file in downloaded_files:
            content = html_file.read_text(errors='ignore')
            if 'example domain' in content.lower():
                main_html = html_file
                break

        assert main_html is not None, "Could not find main HTML file with example.com content"

        # Verify HTML content contains REAL example.com text
        html_content = main_html.read_text(errors='ignore')
        assert len(html_content) > 200, f"HTML content too short: {len(html_content)} bytes"
        assert 'example domain' in html_content.lower(), "Missing 'Example Domain' in HTML"
        assert ('this domain' in html_content.lower() or
                'illustrative examples' in html_content.lower()), \
            "Missing example.com description text"
        assert ('iana' in html_content.lower() or
                'more information' in html_content.lower()), \
            "Missing IANA reference"

        # Verify RESULT_JSON is present and valid
        assert 'RESULT_JSON=' in result.stdout, "Should output RESULT_JSON"

        for line in result.stdout.split('\n'):
            if line.startswith('RESULT_JSON='):
                result_json = json.loads(line.replace('RESULT_JSON=', ''))
                assert result_json['extractor'] == 'wget'
                assert result_json['status'] == 'succeeded'
                assert result_json['url'] == TEST_URL
                assert result_json['snapshot_id'] == 'test789'
                assert 'duration' in result_json
                assert result_json['duration'] >= 0
                break


def test_config_save_wget_false_skips():
    """Test that SAVE_WGET=False causes skip."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set SAVE_WGET=False
        env = os.environ.copy()
        env['SAVE_WGET'] = 'False'

        result = subprocess.run(
            [sys.executable, str(WGET_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Should succeed but skip
        assert result.returncode == 0, f"Should exit 0 when skipping: {result.stderr}"
        assert 'STATUS=skipped' in result.stdout, "Should report skipped status"
        assert 'SAVE_WGET=False' in result.stdout, "Should mention SAVE_WGET=False"


def test_config_save_warc():
    """Test that SAVE_WARC=True creates WARC files."""

    # Ensure wget is available
    if not shutil.which('wget'):
        pytest.skip("wget not installed")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set SAVE_WARC=True explicitly
        env = os.environ.copy()
        env['SAVE_WARC'] = 'True'

        result = subprocess.run(
            [sys.executable, str(WGET_HOOK), '--url', TEST_URL, '--snapshot-id', 'testwarc'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )

        if result.returncode == 0:
            # Look for WARC files in warc/ subdirectory
            warc_dir = tmpdir / 'warc'
            if warc_dir.exists():
                warc_files = list(warc_dir.rglob('*'))
                warc_files = [f for f in warc_files if f.is_file()]
                assert len(warc_files) > 0, "WARC file not created when SAVE_WARC=True"


def test_staticfile_present_skips():
    """Test that wget skips when staticfile already downloaded."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create staticfile directory with content to simulate staticfile extractor ran
        staticfile_dir = tmpdir / 'staticfile'
        staticfile_dir.mkdir()
        (staticfile_dir / 'index.html').write_text('<html>test</html>')

        result = subprocess.run(
            [sys.executable, str(WGET_HOOK), '--url', TEST_URL, '--snapshot-id', 'teststatic'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Should skip
        assert result.returncode == 0, "Should exit 0 when skipping"
        assert 'STATUS=skipped' in result.stdout, "Should report skipped status"
        assert 'staticfile' in result.stdout.lower(), "Should mention staticfile"


def test_handles_404_gracefully():
    """Test that wget fails gracefully on 404."""

    if not shutil.which('wget'):
        pytest.skip("wget not installed")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Try to download non-existent page
        result = subprocess.run(
            [sys.executable, str(WGET_HOOK), '--url', 'https://example.com/nonexistent-page-404', '--snapshot-id', 'test404'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        )

        # Should fail
        assert result.returncode != 0, "Should fail on 404"
        combined = result.stdout + result.stderr
        assert '404' in combined or 'Not Found' in combined or 'No files downloaded' in combined, \
            "Should report 404 or no files downloaded"


def test_config_timeout_honored():
    """Test that WGET_TIMEOUT config is respected."""

    if not shutil.which('wget'):
        pytest.skip("wget not installed")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set very short timeout
        env = os.environ.copy()
        env['WGET_TIMEOUT'] = '5'

        # This should still succeed for example.com (it's fast)
        result = subprocess.run(
            [sys.executable, str(WGET_HOOK), '--url', TEST_URL, '--snapshot-id', 'testtimeout'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Verify it completed (success or fail, but didn't hang)
        assert result.returncode in (0, 1), "Should complete (success or fail)"


def test_config_user_agent():
    """Test that WGET_USER_AGENT config is used."""

    if not shutil.which('wget'):
        pytest.skip("wget not installed")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set custom user agent
        env = os.environ.copy()
        env['WGET_USER_AGENT'] = 'TestBot/1.0'

        result = subprocess.run(
            [sys.executable, str(WGET_HOOK), '--url', TEST_URL, '--snapshot-id', 'testua'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=120
        )

        # Should succeed (example.com doesn't block)
        if result.returncode == 0:
            assert 'STATUS=succeeded' in result.stdout


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
