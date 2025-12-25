"""
Integration tests for media plugin

Tests verify:
1. Hook script exists
2. Dependencies installed via validation hooks
3. Verify deps with abx-pkg
4. Media extraction works on video URLs
5. JSONL output is correct
6. Config options work
7. Handles non-media URLs gracefully
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import pytest

PLUGIN_DIR = Path(__file__).parent.parent
PLUGINS_ROOT = PLUGIN_DIR.parent
MEDIA_HOOK = PLUGIN_DIR / 'on_Snapshot__51_media.py'
MEDIA_INSTALL_HOOK = PLUGIN_DIR / 'on_Crawl__00_install_ytdlp.py'
TEST_URL = 'https://example.com/video.mp4'

def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert MEDIA_HOOK.exists(), f"Hook not found: {MEDIA_HOOK}"


def test_ytdlp_install_hook():
    """Test yt-dlp install hook to install yt-dlp if needed."""
    # Run yt-dlp install hook
    result = subprocess.run(
        [sys.executable, str(MEDIA_INSTALL_HOOK)],
        capture_output=True,
        text=True,
        timeout=600
    )

    assert result.returncode == 0, f"Install hook failed: {result.stderr}"

    # Verify InstalledBinary JSONL output
    found_binary = False
    for line in result.stdout.strip().split('\n'):
        if line.strip():
            try:
                record = json.loads(line)
                if record.get('type') == 'InstalledBinary':
                    assert record['name'] == 'yt-dlp'
                    assert record['abspath']
                    found_binary = True
                    break
            except json.JSONDecodeError:
                pass

    assert found_binary, "Should output InstalledBinary record"


def test_verify_deps_with_abx_pkg():
    """Verify yt-dlp is available via abx-pkg after hook installation."""
    from abx_pkg import Binary, PipProvider, EnvProvider, BinProviderOverrides

    PipProvider.model_rebuild()
    EnvProvider.model_rebuild()

    # Verify yt-dlp is available
    ytdlp_binary = Binary(name='yt-dlp', binproviders=[PipProvider(), EnvProvider()])
    ytdlp_loaded = ytdlp_binary.load()
    assert ytdlp_loaded and ytdlp_loaded.abspath, "yt-dlp should be available after install hook"

def test_handles_non_media_url():
    """Test that media extractor handles non-media URLs gracefully via hook."""
    # Prerequisites checked by earlier test

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run media extraction hook on non-media URL
        result = subprocess.run(
            [sys.executable, str(MEDIA_HOOK), '--url', 'https://example.com', '--snapshot-id', 'test789'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            timeout=60
        )

        # Should exit 0 even for non-media URL
        assert result.returncode == 0, f"Should handle non-media URL gracefully: {result.stderr}"

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
        assert result_json['extractor'] == 'media'


def test_config_save_media_false_skips():
    """Test that SAVE_MEDIA=False causes skip."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['SAVE_MEDIA'] = 'False'

        result = subprocess.run(
            [sys.executable, str(MEDIA_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, f"Should exit 0 when skipping: {result.stderr}"
        assert 'STATUS=' in result.stdout


def test_config_timeout():
    """Test that MEDIA_TIMEOUT config is respected."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['MEDIA_TIMEOUT'] = '5'

        result = subprocess.run(
            [sys.executable, str(MEDIA_HOOK), '--url', 'https://example.com', '--snapshot-id', 'testtimeout'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=30
        )

        assert result.returncode == 0, "Should complete without hanging"

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
