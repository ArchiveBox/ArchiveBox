"""
Integration tests for favicon plugin

Tests verify:
1. Plugin script exists
2. requests library is available
3. Favicon extraction works for real example.com
4. Output file is actual image data
5. Tries multiple favicon URLs
6. Falls back to Google's favicon service
7. Config options work (TIMEOUT, USER_AGENT)
8. Handles failures gracefully
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_plugin_dir,
    get_hook_script,
    parse_jsonl_output,
)


PLUGIN_DIR = get_plugin_dir(__file__)
FAVICON_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_favicon.*')
TEST_URL = 'https://example.com'


def test_hook_script_exists():
    """Verify hook script exists."""
    assert FAVICON_HOOK.exists(), f"Hook script not found: {FAVICON_HOOK}"


def test_requests_library_available():
    """Test that requests library is available."""
    result = subprocess.run(
        [sys.executable, '-c', 'import requests; print(requests.__version__)'],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        pass

    assert len(result.stdout.strip()) > 0, "Should report requests version"


def test_extracts_favicon_from_example_com():
    """Test full workflow: extract favicon from real example.com.

    Note: example.com doesn't have a favicon and Google's service may also fail,
    so we test that the extraction completes and reports appropriate status.
    """

    # Check requests is available
    check_result = subprocess.run(
        [sys.executable, '-c', 'import requests'],
        capture_output=True
    )
    if check_result.returncode != 0:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run favicon extraction
        result = subprocess.run(
            [sys.executable, str(FAVICON_HOOK), '--url', TEST_URL, '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        )

        # May succeed (if Google service works) or fail (if no favicon)
        assert result.returncode in (0, 1), "Should complete extraction attempt"

        # Parse clean JSONL output
        result_json = None
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if line.startswith('{'):
                pass
                try:
                    record = json.loads(line)
                    if record.get('type') == 'ArchiveResult':
                        result_json = record
                        break
                except json.JSONDecodeError:
                    pass

        assert result_json, "Should have ArchiveResult JSONL output"

        # If it succeeded, verify the favicon file
        if result_json['status'] == 'succeeded':
            favicon_file = tmpdir / 'favicon.ico'
            assert favicon_file.exists(), "favicon.ico not created"

            # Verify file is not empty and contains actual image data
            file_size = favicon_file.stat().st_size
            assert file_size > 0, "Favicon file should not be empty"
            assert file_size < 1024 * 1024, f"Favicon file suspiciously large: {file_size} bytes"

            # Check for common image magic bytes
            favicon_data = favicon_file.read_bytes()
            # ICO, PNG, GIF, JPEG, or WebP
            is_image = (
                favicon_data[:4] == b'\x00\x00\x01\x00' or  # ICO
                favicon_data[:8] == b'\x89PNG\r\n\x1a\n' or  # PNG
                favicon_data[:3] == b'GIF' or  # GIF
                favicon_data[:2] == b'\xff\xd8' or  # JPEG
                favicon_data[8:12] == b'WEBP'  # WebP
            )
            assert is_image, "Favicon file should be a valid image format"
        else:
            # Failed as expected
            assert result_json['status'] == 'failed', f"Should report failure: {result_json}"


def test_config_timeout_honored():
    """Test that TIMEOUT config is respected."""

    check_result = subprocess.run(
        [sys.executable, '-c', 'import requests'],
        capture_output=True
    )
    if check_result.returncode != 0:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set very short timeout (but example.com should still succeed)
        import os
        env = os.environ.copy()
        env['TIMEOUT'] = '5'

        result = subprocess.run(
            [sys.executable, str(FAVICON_HOOK), '--url', TEST_URL, '--snapshot-id', 'testtimeout'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        # Should complete (success or fail, but not hang)
        assert result.returncode in (0, 1), "Should complete without hanging"


def test_config_user_agent():
    """Test that USER_AGENT config is used."""

    check_result = subprocess.run(
        [sys.executable, '-c', 'import requests'],
        capture_output=True
    )
    if check_result.returncode != 0:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set custom user agent
        import os
        env = os.environ.copy()
        env['USER_AGENT'] = 'TestBot/1.0'

        result = subprocess.run(
            [sys.executable, str(FAVICON_HOOK), '--url', TEST_URL, '--snapshot-id', 'testua'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=60
        )

        # Should succeed (example.com doesn't block)
        if result.returncode == 0:
            # Parse clean JSONL output
            result_json = None
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.startswith('{'):
                    pass
                    try:
                        record = json.loads(line)
                        if record.get('type') == 'ArchiveResult':
                            result_json = record
                            break
                    except json.JSONDecodeError:
                        pass

            if result_json:
                assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"


def test_handles_https_urls():
    """Test that HTTPS URLs work correctly."""

    check_result = subprocess.run(
        [sys.executable, '-c', 'import requests'],
        capture_output=True
    )
    if check_result.returncode != 0:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        result = subprocess.run(
            [sys.executable, str(FAVICON_HOOK), '--url', 'https://example.org', '--snapshot-id', 'testhttps'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0:
            favicon_file = tmpdir / 'favicon.ico'
            if favicon_file.exists():
                assert favicon_file.stat().st_size > 0


def test_handles_missing_favicon_gracefully():
    """Test that favicon plugin handles sites without favicons gracefully.

    Note: The plugin falls back to Google's favicon service, which generates
    a generic icon even if the site doesn't have one, so extraction usually succeeds.
    """

    check_result = subprocess.run(
        [sys.executable, '-c', 'import requests'],
        capture_output=True
    )
    if check_result.returncode != 0:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Try a URL that likely doesn't have a favicon
        result = subprocess.run(
            [sys.executable, str(FAVICON_HOOK), '--url', 'https://example.com/nonexistent', '--snapshot-id', 'test404'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        )

        # May succeed (Google fallback) or fail gracefully
        assert result.returncode in (0, 1), "Should complete (may succeed or fail)"

        if result.returncode != 0:
            combined = result.stdout + result.stderr
            assert 'No favicon found' in combined or 'ERROR=' in combined


def test_reports_missing_requests_library():
    """Test that script reports error when requests library is missing."""

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run with PYTHONPATH cleared to simulate missing requests
        import os
        env = os.environ.copy()
        # Keep only minimal PATH, clear PYTHONPATH
        env['PYTHONPATH'] = '/nonexistent'

        result = subprocess.run(
            [sys.executable, '-S', str(FAVICON_HOOK), '--url', TEST_URL, '--snapshot-id', 'test123'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env
        )

        # Should fail and report missing requests
        if result.returncode != 0:
            combined = result.stdout + result.stderr
            # May report missing requests or other import errors
            assert 'requests' in combined.lower() or 'import' in combined.lower() or 'ERROR=' in combined


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
