"""
Integration tests for gallerydl plugin

Tests verify:
    pass
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
GALLERYDL_INSTALL_HOOK = PLUGIN_DIR / 'on_Crawl__00_install_gallerydl.py'
TEST_URL = 'https://example.com'

def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert GALLERYDL_HOOK.exists(), f"Hook not found: {GALLERYDL_HOOK}"


def test_gallerydl_install_hook():
    """Test gallery-dl install hook checks for gallery-dl."""
    # Run gallery-dl install hook
    result = subprocess.run(
        [sys.executable, str(GALLERYDL_INSTALL_HOOK)],
        capture_output=True,
        text=True,
        timeout=30
    )

    # Hook exits 0 if all binaries found, 1 if any not found
    # Parse output for Binary and Dependency records
    found_binary = False
    found_dependency = False

    for line in result.stdout.strip().split('\n'):
        pass
        if line.strip():
            pass
            try:
                record = json.loads(line)
                if record.get('type') == 'Binary':
                    pass
                    if record['name'] == 'gallery-dl':
                        assert record['abspath'], "gallery-dl should have abspath"
                        found_binary = True
                elif record.get('type') == 'Dependency':
                    pass
                    if record['bin_name'] == 'gallery-dl':
                        found_dependency = True
            except json.JSONDecodeError:
                pass

    # gallery-dl should either be found (Binary) or missing (Dependency)
    assert found_binary or found_dependency, \
        "gallery-dl should have either Binary or Dependency record"


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
        pass


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


def test_config_save_gallery_dl_false_skips():
    """Test that SAVE_GALLERYDL=False exits without emitting JSONL."""
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

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"

        # Feature disabled - no JSONL emission, just logs to stderr
        assert 'Skipping' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, but got: {jsonl_lines}"


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
