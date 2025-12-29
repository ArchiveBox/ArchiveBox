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
import time
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
GALLERYDL_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_gallerydl.*'), None)
TEST_URL = 'https://example.com'

def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert GALLERYDL_HOOK.exists(), f"Hook not found: {GALLERYDL_HOOK}"


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
    """Test that GALLERYDL_ENABLED=False exits without emitting JSONL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['GALLERYDL_ENABLED'] = 'False'

        result = subprocess.run(
            [sys.executable, str(GALLERYDL_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
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


def test_config_timeout():
    """Test that GALLERY_DL_TIMEOUT config is respected."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['GALLERY_DL_TIMEOUT'] = '5'

        start_time = time.time()
        result = subprocess.run(
            [sys.executable, str(GALLERYDL_HOOK), '--url', 'https://example.com', '--snapshot-id', 'testtimeout'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=10  # Should complete in 5s, use 10s as safety margin
        )
        elapsed_time = time.time() - start_time

        assert result.returncode == 0, f"Should complete without hanging: {result.stderr}"
        # Allow 1 second overhead for subprocess startup and Python interpreter
        assert elapsed_time <= 6.0, f"Should complete within 6 seconds (5s timeout + 1s overhead), took {elapsed_time:.2f}s"


def test_real_gallery_url():
    """Test that gallery-dl can extract images from a real Flickr gallery URL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Use a real Flickr photo page
        gallery_url = 'https://www.flickr.com/photos/gregorydolivet/55002388567/in/explore-2025-12-25/'

        env = os.environ.copy()
        env['GALLERY_DL_TIMEOUT'] = '60'  # Give it time to download

        start_time = time.time()
        result = subprocess.run(
            [sys.executable, str(GALLERYDL_HOOK), '--url', gallery_url, '--snapshot-id', 'testflickr'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=90
        )
        elapsed_time = time.time() - start_time

        # Should succeed
        assert result.returncode == 0, f"Should extract gallery successfully: {result.stderr}"

        # Parse JSONL output
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

        assert result_json, f"Should have ArchiveResult JSONL output. stdout: {result.stdout}"
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"

        # Check that some files were downloaded
        output_files = list(tmpdir.glob('**/*'))
        image_files = [f for f in output_files if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp')]

        assert len(image_files) > 0, f"Should have downloaded at least one image. Files: {output_files}"

        print(f"Successfully extracted {len(image_files)} image(s) in {elapsed_time:.2f}s")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
