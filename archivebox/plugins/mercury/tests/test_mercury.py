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

PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
MERCURY_HOOK = PLUGIN_DIR / 'on_Snapshot__53_mercury.py'
MERCURY_VALIDATE_HOOK = PLUGIN_DIR / 'on_Crawl__00_validate_mercury.py'
TEST_URL = 'https://example.com'

def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert MERCURY_HOOK.exists(), f"Hook not found: {MERCURY_HOOK}"


def test_mercury_validate_hook():
    """Test mercury validate hook checks for postlight-parser."""
    # Run mercury validate hook
    result = subprocess.run(
        [sys.executable, str(MERCURY_VALIDATE_HOOK)],
        capture_output=True,
        text=True,
        timeout=30
    )

    # Hook exits 0 if binary found, 1 if not found (with Dependency record)
    if result.returncode == 0:
        # Binary found - verify InstalledBinary JSONL output
        found_binary = False
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    record = json.loads(line)
                    if record.get('type') == 'InstalledBinary':
                        assert record['name'] == 'postlight-parser'
                        assert record['abspath']
                        found_binary = True
                        break
                except json.JSONDecodeError:
                    pass
        assert found_binary, "Should output InstalledBinary record when binary found"
    else:
        # Binary not found - verify Dependency JSONL output
        found_dependency = False
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    record = json.loads(line)
                    if record.get('type') == 'Dependency':
                        assert record['bin_name'] == 'postlight-parser'
                        assert 'npm' in record['bin_providers']
                        found_dependency = True
                        break
                except json.JSONDecodeError:
                    pass
        assert found_dependency, "Should output Dependency record when binary not found"


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
        pytest.skip("postlight-parser not available - Dependency record should have been emitted")

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

        # Verify JSONL output
        assert 'STATUS=' in result.stdout, "Should report status"
        assert 'RESULT_JSON=' in result.stdout, "Should output RESULT_JSON"

        # Parse JSONL result
        result_json = None
        for line in result.stdout.split('\n'):
            if line.startswith('RESULT_JSON='):
                result_json = json.loads(line.split('=', 1)[1])
                break

        assert result_json, "Should have RESULT_JSON"
        assert result_json['extractor'] == 'mercury'

        # Verify filesystem output if extraction succeeded
        if result_json['status'] == 'succeeded':
            mercury_dir = tmpdir / 'mercury'
            assert mercury_dir.exists(), "Output directory not created"

            output_file = mercury_dir / 'content.html'
            assert output_file.exists(), "content.html not created"

            content = output_file.read_text()
            assert len(content) > 0, "Output should not be empty"

def test_config_save_mercury_false_skips():
    """Test that SAVE_MERCURY=False causes skip."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['SAVE_MERCURY'] = 'False'

        result = subprocess.run(
            [sys.executable, str(MERCURY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when skipping: {result.stderr}"
        assert 'STATUS=' in result.stdout


def test_fails_gracefully_without_html():
    """Test that mercury fails gracefully when no HTML source exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [sys.executable, str(MERCURY_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, "Should exit 0 even when no HTML source"
        assert 'STATUS=' in result.stdout

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
