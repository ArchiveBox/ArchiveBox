"""
Integration tests for headers plugin

Tests verify:
    pass
1. Plugin script exists and is executable
2. Node.js is available
3. Headers extraction works for real example.com
4. Output JSON contains actual HTTP headers
5. HTTP fallback works correctly
6. Config options work (TIMEOUT, USER_AGENT)
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


PLUGIN_DIR = Path(__file__).parent.parent
HEADERS_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_headers.*'), None)
TEST_URL = 'https://example.com'


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

        # Run headers extraction
        result = subprocess.run(
            ['node', str(HEADERS_HOOK), f'--url={TEST_URL}', '--snapshot-id=test789'],
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
        headers_file = tmpdir / 'headers.json'
        assert headers_file.exists(), "headers.json not created"

        # Verify headers JSON contains REAL example.com response
        headers_data = json.loads(headers_file.read_text())

        assert 'url' in headers_data, "Should have url field"
        assert headers_data['url'] == TEST_URL, f"URL should be {TEST_URL}"

        assert 'status' in headers_data, "Should have status field"
        assert headers_data['status'] in [200, 301, 302], \
            f"Should have valid HTTP status, got {headers_data['status']}"

        assert 'headers' in headers_data, "Should have headers field"
        assert isinstance(headers_data['headers'], dict), "Headers should be a dict"
        assert len(headers_data['headers']) > 0, "Headers dict should not be empty"

        # Verify common HTTP headers are present
        headers_lower = {k.lower(): v for k, v in headers_data['headers'].items()}
        assert 'content-type' in headers_lower or 'content-length' in headers_lower, \
            "Should have at least one common HTTP header"


def test_headers_output_structure():
    """Test that headers plugin produces correctly structured output."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run headers extraction against real example.com
        result = subprocess.run(
            ['node', str(HEADERS_HOOK), f'--url={TEST_URL}', '--snapshot-id=testformat'],
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

        # Verify output structure
        output_headers_file = tmpdir / 'headers.json'
        assert output_headers_file.exists(), "Output headers.json not created"

        output_data = json.loads(output_headers_file.read_text())

        # Verify all required fields are present
        assert 'url' in output_data, "Output should have url field"
        assert 'status' in output_data, "Output should have status field"
        assert 'headers' in output_data, "Output should have headers field"

        # Verify data types
        assert isinstance(output_data['status'], int), "Status should be integer"
        assert isinstance(output_data['headers'], dict), "Headers should be dict"

        # Verify example.com returns expected headers
        assert output_data['url'] == TEST_URL
        assert output_data['status'] in [200, 301, 302]


def test_falls_back_to_http_when_chrome_unavailable():
    """Test that headers plugin falls back to HTTP HEAD when chrome unavailable."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Don't create chrome directory - force HTTP fallback

        # Run headers extraction
        result = subprocess.run(
            ['node', str(HEADERS_HOOK), f'--url={TEST_URL}', '--snapshot-id=testhttp'],
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

        # Verify output exists and has real HTTP headers
        output_headers_file = tmpdir / 'headers.json'
        assert output_headers_file.exists(), "Output headers.json not created"

        output_data = json.loads(output_headers_file.read_text())
        assert output_data['url'] == TEST_URL
        assert output_data['status'] in [200, 301, 302]
        assert isinstance(output_data['headers'], dict)
        assert len(output_data['headers']) > 0


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
            ['node', str(HEADERS_HOOK), f'--url={TEST_URL}', '--snapshot-id=testtimeout'],
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
            ['node', str(HEADERS_HOOK), f'--url={TEST_URL}', '--snapshot-id=testua'],
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
            ['node', str(HEADERS_HOOK), '--url=https://example.org', '--snapshot-id=testhttps'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        ,
            env=get_test_env())

        if result.returncode == 0:
            output_headers_file = tmpdir / 'headers.json'
            if output_headers_file.exists():
                output_data = json.loads(output_headers_file.read_text())
                assert output_data['url'] == 'https://example.org'
                assert output_data['status'] in [200, 301, 302]


def test_handles_404_gracefully():
    """Test that headers plugin handles 404s gracefully."""

    if not shutil.which('node'):
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        result = subprocess.run(
            ['node', str(HEADERS_HOOK), '--url=https://example.com/nonexistent-page-404', '--snapshot-id=test404'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        ,
            env=get_test_env())

        # May succeed or fail depending on server behavior
        # If it succeeds, verify 404 status is captured
        if result.returncode == 0:
            output_headers_file = tmpdir / 'headers.json'
            if output_headers_file.exists():
                output_data = json.loads(output_headers_file.read_text())
                assert output_data['status'] == 404, "Should capture 404 status"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
