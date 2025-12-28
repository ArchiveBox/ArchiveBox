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
    """Test yt-dlp install hook checks for yt-dlp and dependencies (node, ffmpeg)."""
    # Run yt-dlp install hook
    result = subprocess.run(
        [sys.executable, str(MEDIA_INSTALL_HOOK)],
        capture_output=True,
        text=True,
        timeout=30
    )

    # Hook exits 0 if all binaries found, 1 if any not found
    # Parse output for Binary and Dependency records
    found_binaries = {'node': False, 'ffmpeg': False, 'yt-dlp': False}
    found_dependencies = {'node': False, 'ffmpeg': False, 'yt-dlp': False}

    for line in result.stdout.strip().split('\n'):
        if line.strip():
            try:
                record = json.loads(line)
                if record.get('type') == 'Binary':
                    name = record['name']
                    if name in found_binaries:
                        assert record['abspath'], f"{name} should have abspath"
                        found_binaries[name] = True
                elif record.get('type') == 'Dependency':
                    name = record['bin_name']
                    if name in found_dependencies:
                        found_dependencies[name] = True
            except json.JSONDecodeError:
                pass

    # Each binary should either be found (Binary) or missing (Dependency)
    for binary_name in ['yt-dlp', 'node', 'ffmpeg']:
        assert found_binaries[binary_name] or found_dependencies[binary_name], \
            f"{binary_name} should have either Binary or Dependency record"


def test_verify_deps_with_abx_pkg():
    """Verify yt-dlp, node, and ffmpeg are available via abx-pkg."""
    from abx_pkg import Binary, PipProvider, AptProvider, BrewProvider, EnvProvider, BinProviderOverrides

    missing_binaries = []

    # Verify yt-dlp is available
    ytdlp_binary = Binary(name='yt-dlp', binproviders=[PipProvider(), EnvProvider()])
    ytdlp_loaded = ytdlp_binary.load()
    if not (ytdlp_loaded and ytdlp_loaded.abspath):
        missing_binaries.append('yt-dlp')

    # Verify node is available (yt-dlp needs it for JS extraction)
    node_binary = Binary(
        name='node',
        binproviders=[AptProvider(), BrewProvider(), EnvProvider()]
    )
    node_loaded = node_binary.load()
    if not (node_loaded and node_loaded.abspath):
        missing_binaries.append('node')

    # Verify ffmpeg is available (yt-dlp needs it for video conversion)
    ffmpeg_binary = Binary(name='ffmpeg', binproviders=[AptProvider(), BrewProvider(), EnvProvider()])
    ffmpeg_loaded = ffmpeg_binary.load()
    if not (ffmpeg_loaded and ffmpeg_loaded.abspath):
        missing_binaries.append('ffmpeg')

    if missing_binaries:
        pytest.skip(f"Binaries not available: {', '.join(missing_binaries)} - Dependency records should have been emitted")

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

        assert result_json, "Should have ArchiveResult JSONL output"
        assert result_json['status'] == 'succeeded', f"Should succeed: {result_json}"


def test_config_save_media_false_skips():
    """Test that SAVE_MEDIA=False exits without emitting JSONL."""
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

        assert result.returncode == 0, f"Should exit 0 when feature disabled: {result.stderr}"

        # Feature disabled - no JSONL emission, just logs to stderr
        assert 'Skipping' in result.stderr or 'False' in result.stderr, "Should log skip reason to stderr"

        # Should NOT emit any JSONL
        jsonl_lines = [line for line in result.stdout.strip().split('\n') if line.strip().startswith('{')]
        assert len(jsonl_lines) == 0, f"Should not emit JSONL when feature disabled, but got: {jsonl_lines}"


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
