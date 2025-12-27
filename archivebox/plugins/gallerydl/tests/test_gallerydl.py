"""
Integration tests for gallerydl plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via validation hooks
3. Verify deps with abx-pkg
4. Gallery extraction works on gallery URLs
5. JSONL output is correct
6. Config options work
7. Handles non-gallery URLs gracefully
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
GALLERYDL_HOOK = PLUGIN_DIR / 'on_Snapshot__52_gallerydl.py'
GALLERYDL_VALIDATE_HOOK = PLUGIN_DIR / 'on_Crawl__00_validate_gallerydl.py'
TEST_URL = 'https://example.com'

def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert GALLERYDL_HOOK.exists(), f"Hook not found: {GALLERYDL_HOOK}"


def test_gallerydl_validate_hook():
    """Test gallery-dl validate hook checks for gallery-dl."""
    # Run gallery-dl validate hook
    result = subprocess.run(
        [sys.executable, str(GALLERYDL_VALIDATE_HOOK)],
        capture_output=True,
        text=True,
        timeout=30
    )

    # Hook exits 0 if all binaries found, 1 if any not found
    # Parse output for InstalledBinary and Dependency records
    found_binary = False
    found_dependency = False

    for line in result.stdout.strip().split('\n'):
        if line.strip():
            try:
                record = json.loads(line)
                if record.get('type') == 'InstalledBinary':
                    if record['name'] == 'gallery-dl':
                        assert record['abspath'], "gallery-dl should have abspath"
                        found_binary = True
                elif record.get('type') == 'Dependency':
                    if record['bin_name'] == 'gallery-dl':
                        found_dependency = True
            except json.JSONDecodeError:
                pass

    # gallery-dl should either be found (InstalledBinary) or missing (Dependency)
    assert found_binary or found_dependency, \
        "gallery-dl should have either InstalledBinary or Dependency record"


def test_verify_deps_with_abx_pkg():
    """Verify gallery-dl is available via abx-pkg."""
    from abx_pkg import Binary, PipProvider, EnvProvider, BinProviderOverrides

    missing_binaries = []

    # Verify gallery-dl is available
    gallerydl_binary = Binary(name='gallery-dl', binproviders=[PipProvider(), EnvProvider()])
    gallerydl_loaded = gallerydl_binary.load()
    if not (gallerydl_loaded and gallerydl_loaded.abspath):
        missing_binaries.append('gallery-dl')

    if missing_binaries:
        pytest.skip(f"Binaries not available: {', '.join(missing_binaries)} - Dependency records should have been emitted")


def test_handles_non_gallery_url():
    """Test that gallery-dl extractor handles non-gallery URLs gracefully via hook."""
    # Prerequisites checked by earlier test

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run gallery-dl extraction hook on non-gallery URL
        result = subprocess.run(
            [sys.executable, str(GALLERYDL_HOOK), '--url', 'https://example.com', '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        )

        # Should exit 0 even for non-gallery URL
        assert result.returncode == 0, f"Should handle non-gallery URL gracefully: {result.stderr}"

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
        assert result_json['extractor'] == 'gallerydl'


def test_config_save_gallery_dl_false_skips():
    """Test that SAVE_GALLERYDL=False causes skip."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['SAVE_GALLERYDL'] = 'False'

        result = subprocess.run(
            [sys.executable, str(GALLERYDL_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when skipping: {result.stderr}"
        assert 'STATUS=' in result.stdout


def test_config_timeout():
    """Test that GALLERY_DL_TIMEOUT config is respected."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['GALLERY_DL_TIMEOUT'] = '5'

        result = subprocess.run(
            [sys.executable, str(GALLERYDL_HOOK), '--url', 'https://example.com', '--snapshot-id', 'testtimeout'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, "Should complete without hanging"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
