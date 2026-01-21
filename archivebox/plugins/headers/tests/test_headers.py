"""
Integration tests for headers plugin

Tests verify:
    pass
1. Plugin script exists and is executable
2. Node.js is available
3. Headers extraction works for real example.com
4. Output JSON contains actual HTTP headers
5. Config options work (TIMEOUT, USER_AGENT)
"""

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from archivebox.plugins.chrome.tests.chrome_test_helpers import (
    CHROME_NAVIGATE_HOOK,
    get_test_env,
    chrome_session,
)

PLUGIN_DIR = Path(__file__).parent.parent
HEADERS_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_headers.*'), None)
TEST_URL = 'https://example.com'

def normalize_root_url(url: str) -> str:
    return url.rstrip('/')

def run_headers_capture(headers_dir, snapshot_chrome_dir, env, url, snapshot_id):
    hook_proc = subprocess.Popen(
        ['node', str(HEADERS_HOOK), f'--url={url}', f'--snapshot-id={snapshot_id}'],
        cwd=headers_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    nav_result = subprocess.run(
        ['node', str(CHROME_NAVIGATE_HOOK), f'--url={url}', f'--snapshot-id={snapshot_id}'],
        cwd=snapshot_chrome_dir,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    headers_file = headers_dir / 'headers.json'
    for _ in range(60):
        if headers_file.exists() and headers_file.stat().st_size > 0:
            break
        time.sleep(1)

    if hook_proc.poll() is None:
        hook_proc.terminate()
        try:
            stdout, stderr = hook_proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            hook_proc.kill()
            stdout, stderr = hook_proc.communicate()
    else:
        stdout, stderr = hook_proc.communicate()

    return hook_proc.returncode, stdout, stderr, nav_result, headers_file


def test_hook_script_exists():
    """Verify hook script exists."""
    assert HEADERS_HOOK.exists(), f"Hook script not found: {HEADERS_HOOK}"


def test_node_is_available():
    """Test that Node.js is available on the system."""
    result = subprocess.run(
        ['which', 'node'],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        pass

    binary_path = result.stdout.strip()
    assert Path(binary_path).exists(), f"Binary should exist at {binary_path}"

    # Test that node is executable and get version
    result = subprocess.run(
        ['node', '--version'],
        capture_output=True,
        text=True,
        timeout=10
    ,
            env=get_test_env())
    assert result.returncode == 0, f"node not executable: {result.stderr}"
    assert result.stdout.startswith('v'), f"Unexpected node version format: {result.stdout}"


def test_extracts_headers_from_example_com():
    """Test full workflow: extract headers from real example.com."""

    # Check node is available
    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        with chrome_session(tmpdir, test_url=TEST_URL, navigate=False) as (_process, _pid, snapshot_chrome_dir, env):
            headers_dir = snapshot_chrome_dir.parent / 'headers'
            headers_dir.mkdir(exist_ok=True)

            result = run_headers_capture(
                headers_dir,
                snapshot_chrome_dir,
                env,
                TEST_URL,
                'test789',
            )

        hook_code, stdout, stderr, nav_result, headers_file = result
        assert nav_result.returncode == 0, f"Navigation failed: {nav_result.stderr}"
        assert hook_code == 0, f"Extraction failed: {stderr}"

        # Parse clean JSONL output
        result_json = None
        for line in stdout.strip().split('\n'):
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
        assert headers_file.exists(), "headers.json not created"

        # Verify headers JSON contains REAL example.com response
        headers_data = json.loads(headers_file.read_text())

        assert 'url' in headers_data, "Should have url field"
        assert normalize_root_url(headers_data['url']) == normalize_root_url(TEST_URL), f"URL should be {TEST_URL}"

        assert 'status' in headers_data, "Should have status field"
        assert headers_data['status'] in [200, 301, 302], \
            f"Should have valid HTTP status, got {headers_data['status']}"

        assert 'request_headers' in headers_data, "Should have request_headers field"
        assert isinstance(headers_data['request_headers'], dict), "Request headers should be a dict"

        assert 'response_headers' in headers_data, "Should have response_headers field"
        assert isinstance(headers_data['response_headers'], dict), "Response headers should be a dict"
        assert len(headers_data['response_headers']) > 0, "Response headers dict should not be empty"

        assert 'headers' in headers_data, "Should have headers field"
        assert isinstance(headers_data['headers'], dict), "Headers should be a dict"

        # Verify common HTTP headers are present
        headers_lower = {k.lower(): v for k, v in headers_data['response_headers'].items()}
        assert 'content-type' in headers_lower or 'content-length' in headers_lower, \
            "Should have at least one common HTTP header"

        assert headers_data['response_headers'].get(':status') == str(headers_data['status']), \
            "Response headers should include :status pseudo header"


def test_headers_output_structure():
    """Test that headers plugin produces correctly structured output."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        with chrome_session(tmpdir, test_url=TEST_URL, navigate=False) as (_process, _pid, snapshot_chrome_dir, env):
            headers_dir = snapshot_chrome_dir.parent / 'headers'
            headers_dir.mkdir(exist_ok=True)

            result = run_headers_capture(
                headers_dir,
                snapshot_chrome_dir,
                env,
                TEST_URL,
                'testformat',
            )

        hook_code, stdout, stderr, nav_result, headers_file = result
        assert nav_result.returncode == 0, f"Navigation failed: {nav_result.stderr}"
        assert hook_code == 0, f"Extraction failed: {stderr}"

        # Parse clean JSONL output
        result_json = None
        for line in stdout.strip().split('\n'):
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

        # Verify output structure
        assert headers_file.exists(), "Output headers.json not created"

        output_data = json.loads(headers_file.read_text())

        # Verify all required fields are present
        assert 'url' in output_data, "Output should have url field"
        assert 'status' in output_data, "Output should have status field"
        assert 'request_headers' in output_data, "Output should have request_headers field"
        assert 'response_headers' in output_data, "Output should have response_headers field"
        assert 'headers' in output_data, "Output should have headers field"

        # Verify data types
        assert isinstance(output_data['status'], int), "Status should be integer"
        assert isinstance(output_data['request_headers'], dict), "Request headers should be dict"
        assert isinstance(output_data['response_headers'], dict), "Response headers should be dict"
        assert isinstance(output_data['headers'], dict), "Headers should be dict"

        # Verify example.com returns expected headers
        assert normalize_root_url(output_data['url']) == normalize_root_url(TEST_URL)
        assert output_data['status'] in [200, 301, 302]


def test_fails_without_chrome_session():
    """Test that headers plugin fails when chrome session is missing."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run headers extraction
        result = subprocess.run(
            ['node', str(HEADERS_HOOK), f'--url={TEST_URL}', '--snapshot-id=testhttp'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        ,
            env=get_test_env())

        assert result.returncode != 0, "Should fail without chrome session"
        assert 'No Chrome session found (chrome plugin must run first)' in (result.stdout + result.stderr)


def test_config_timeout_honored():
    """Test that TIMEOUT config is respected."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set very short timeout (but example.com should still succeed)
        import os
        env_override = os.environ.copy()
        env_override['TIMEOUT'] = '5'

        with chrome_session(tmpdir, test_url=TEST_URL, navigate=False) as (_process, _pid, snapshot_chrome_dir, env):
            headers_dir = snapshot_chrome_dir.parent / 'headers'
            headers_dir.mkdir(exist_ok=True)
            env.update(env_override)

            result = run_headers_capture(
                headers_dir,
                snapshot_chrome_dir,
                env,
                TEST_URL,
                'testtimeout',
            )

        # Should complete (success or fail, but not hang)
        hook_code, _stdout, _stderr, nav_result, _headers_file = result
        assert nav_result.returncode == 0, f"Navigation failed: {nav_result.stderr}"
        assert hook_code in (0, 1), "Should complete without hanging"


def test_config_user_agent():
    """Test that USER_AGENT config is used."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Set custom user agent
        import os
        env_override = os.environ.copy()
        env_override['USER_AGENT'] = 'TestBot/1.0'

        with chrome_session(tmpdir, test_url=TEST_URL, navigate=False) as (_process, _pid, snapshot_chrome_dir, env):
            headers_dir = snapshot_chrome_dir.parent / 'headers'
            headers_dir.mkdir(exist_ok=True)
            env.update(env_override)

            result = run_headers_capture(
                headers_dir,
                snapshot_chrome_dir,
                env,
                TEST_URL,
                'testua',
            )

        # Should succeed (example.com doesn't block)
        hook_code, stdout, _stderr, nav_result, _headers_file = result
        assert nav_result.returncode == 0, f"Navigation failed: {nav_result.stderr}"
        if hook_code == 0:
            # Parse clean JSONL output
            result_json = None
            for line in stdout.strip().split('\n'):
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

        with chrome_session(tmpdir, test_url='https://example.org', navigate=False) as (_process, _pid, snapshot_chrome_dir, env):
            headers_dir = snapshot_chrome_dir.parent / 'headers'
            headers_dir.mkdir(exist_ok=True)
            result = run_headers_capture(
                headers_dir,
                snapshot_chrome_dir,
                env,
                'https://example.org',
                'testhttps',
            )

        hook_code, _stdout, _stderr, nav_result, headers_file = result
        assert nav_result.returncode == 0, f"Navigation failed: {nav_result.stderr}"
        if hook_code == 0:
            if headers_file.exists():
                output_data = json.loads(headers_file.read_text())
                assert normalize_root_url(output_data['url']) == normalize_root_url('https://example.org')
                assert output_data['status'] in [200, 301, 302]


def test_handles_404_gracefully():
    """Test that headers plugin handles 404s gracefully."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        with chrome_session(tmpdir, test_url='https://example.com/nonexistent-page-404', navigate=False) as (_process, _pid, snapshot_chrome_dir, env):
            headers_dir = snapshot_chrome_dir.parent / 'headers'
            headers_dir.mkdir(exist_ok=True)
            result = run_headers_capture(
                headers_dir,
                snapshot_chrome_dir,
                env,
                'https://example.com/nonexistent-page-404',
                'test404',
            )

        # May succeed or fail depending on server behavior
        # If it succeeds, verify 404 status is captured
        hook_code, _stdout, _stderr, nav_result, headers_file = result
        assert nav_result.returncode == 0, f"Navigation failed: {nav_result.stderr}"
        if hook_code == 0:
            if headers_file.exists():
                output_data = json.loads(headers_file.read_text())
                assert output_data['status'] == 404, "Should capture 404 status"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
