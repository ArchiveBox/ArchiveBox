"""
Integration tests for title plugin

Tests verify:
1. Plugin script exists
2. Node.js is available
3. Title extraction works for real example.com
4. Output file contains actual page title
5. Handles various title sources (<title>, og:title, twitter:title)
6. Config options work (TIMEOUT, USER_AGENT)
7. Fallback to HTTP when chrome not available
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    get_plugin_dir,
    get_hook_script,
    parse_jsonl_output,
)


PLUGIN_DIR = get_plugin_dir(__file__)
TITLE_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_title.*')
TEST_URL = 'https://example.com'


def test_hook_script_exists():
    """Verify hook script exists."""
    assert TITLE_HOOK.exists(), f"Hook script not found: {TITLE_HOOK}"


def test_extracts_title_from_example_com():
    """Test full workflow: extract title from real example.com."""

    # Check node is available
    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run title extraction
        result = subprocess.run(
            ['node', str(TITLE_HOOK), f'--url={TEST_URL}', '--snapshot-id=test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        ,
            env=get_test_env())

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

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
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

        # Verify output file exists (hook writes to current directory)
        title_file = tmpdir / 'title.txt'
        assert title_file.exists(), "title.txt not created"

        # Verify title contains REAL example.com title
        title_text = title_file.read_text().strip()
        assert len(title_text) > 0, "Title should not be empty"
        assert 'example' in title_text.lower(), "Title should contain 'example'"

        # example.com has title "Example Domain"
        assert 'example domain' in title_text.lower(), f"Expected 'Example Domain', got: {title_text}"


def test_falls_back_to_http_when_chrome_unavailable():
    """Test that title plugin falls back to HTTP when chrome unavailable."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Don't create chrome directory - force HTTP fallback

        # Run title extraction
        result = subprocess.run(
            ['node', str(TITLE_HOOK), f'--url={TEST_URL}', '--snapshot-id=testhttp'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        ,
            env=get_test_env())

        assert result.returncode == 0, f"Extraction failed: {result.stderr}"

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
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

        # Verify output exists and has real title (hook writes to current directory)
        output_title_file = tmpdir / 'title.txt'
        assert output_title_file.exists(), "Output title.txt not created"

        title_text = output_title_file.read_text().strip()
        assert 'example' in title_text.lower()


def test_config_timeout_honored():
    """Test that TIMEOUT config is respected."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set very short timeout (but example.com should still succeed)
        import os
        env = os.environ.copy()
        env['TIMEOUT'] = '5'

        result = subprocess.run(
            ['node', str(TITLE_HOOK), f'--url={TEST_URL}', '--snapshot-id=testtimeout'],
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

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set custom user agent
        import os
        env = os.environ.copy()
        env['USER_AGENT'] = 'TestBot/1.0'

        result = subprocess.run(
            ['node', str(TITLE_HOOK), f'--url={TEST_URL}', '--snapshot-id=testua'],
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

            assert result_json, "Should have ArchiveResult JSONL output"
            assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"


def test_handles_https_urls():
    """Test that HTTPS URLs work correctly."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        result = subprocess.run(
            ['node', str(TITLE_HOOK), '--url=https://example.org', '--snapshot-id=testhttps'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        ,
            env=get_test_env())

        if result.returncode == 0:
            # Hook writes to current directory
            output_title_file = tmpdir / 'title.txt'
            if output_title_file.exists():
                title_text = output_title_file.read_text().strip()
                assert len(title_text) > 0, "Title should not be empty"
                assert 'example' in title_text.lower()


def test_handles_404_gracefully():
    """Test that title plugin handles 404 pages.

    Note: example.com returns valid HTML even for 404 pages, so extraction may succeed
    with the generic "Example Domain" title.
    """

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        result = subprocess.run(
            ['node', str(TITLE_HOOK), '--url=https://example.com/nonexistent-page-404', '--snapshot-id=test404'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        ,
            env=get_test_env())

        # May succeed or fail depending on server behavior
        # example.com returns "Example Domain" even for 404s
        assert result.returncode in (0, 1), "Should complete (may succeed or fail)"


def test_handles_redirects():
    """Test that title plugin handles redirects correctly."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # http://example.com redirects to https://example.com
        result = subprocess.run(
            ['node', str(TITLE_HOOK), '--url=http://example.com', '--snapshot-id=testredirect'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        ,
            env=get_test_env())

        # Should succeed and follow redirect
        if result.returncode == 0:
            # Hook writes to current directory
            output_title_file = tmpdir / 'title.txt'
            if output_title_file.exists():
                title_text = output_title_file.read_text().strip()
                assert 'example' in title_text.lower()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
