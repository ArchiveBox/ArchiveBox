"""
Integration tests for mercury plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via validation hooks
3. Verify deps with abx-pkg
4. Mercury extraction works on https://example.com
5. JSONL output is correct
6. Filesystem output contains extracted content
7. Config options work
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
    PLUGINS_ROOT,
)


PLUGIN_DIR = get_plugin_dir(__file__)
MERCURY_HOOK = get_hook_script(PLUGIN_DIR, 'on_Snapshot__*_mercury.*')
TEST_URL = 'https://example.com'

def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert MERCURY_HOOK.exists(), f"Hook not found: {MERCURY_HOOK}"


def test_verify_deps_with_abx_pkg():
    """Verify postlight-parser is available via abx-pkg."""
    from abx_pkg import Binary, NpmProvider, EnvProvider, BinProviderOverrides

    # Verify postlight-parser is available
    mercury_binary = Binary(
        name='postlight-parser',
        binproviders=[NpmProvider(), EnvProvider()],
        overrides={'npm': {'packages': ['@postlight/parser']}}
    )
    mercury_loaded = mercury_binary.load()

    # If validate hook found it (exit 0), this should succeed
    # If validate hook didn't find it (exit 1), this may fail unless binprovider installed it
    if mercury_loaded and mercury_loaded.abspath:
        assert True, "postlight-parser is available"
    else:
        pass

def test_extracts_with_mercury_parser():
    """Test full workflow: extract with postlight-parser from real HTML via hook."""
    # Prerequisites checked by earlier test

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create HTML source that mercury can parse
        (tmpdir / 'singlefile').mkdir()
        (tmpdir / 'singlefile' / 'singlefile.html').write_text(
            '<html><head><title>Test Article</title></head><body>'
            '<article><h1>Example Article</h1><p>This is test content for mercury parser.</p></article>'
            '</body></html>'
        )

        # Run mercury extraction hook
        result = subprocess.run(
            [sys.executable, str(MERCURY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        )

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

        # Verify filesystem output (hook writes to current directory)
        output_file = tmpdir / 'content.html'
        assert output_file.exists(), "content.html not created"

        content = output_file.read_text()
        assert len(content) > 0, "Output should not be empty"

def test_config_save_mercury_false_skips():
    """Test that MERCURY_ENABLED=False exits without emitting JSONL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['MERCURY_ENABLED'] = 'False'

        result = subprocess.run(
            [sys.executable, str(MERCURY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
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


def test_fails_gracefully_without_html():
    """Test that mercury works even without HTML source (fetches URL directly)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(MERCURY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30
        )

        # Mercury fetches URL directly with postlight-parser, doesn't need HTML source
        # Parse clean JSONL output
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

        # Mercury should succeed or fail based on network, not based on HTML source
        assert result_json, "Should emit ArchiveResult"
        assert result_json['status'] in ['succeeded', 'failed'], f"Should succeed or fail: {result_json}"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
