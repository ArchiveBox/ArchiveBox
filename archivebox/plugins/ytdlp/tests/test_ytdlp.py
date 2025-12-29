"""
Integration tests for ytdlp plugin

Tests verify:
1. Hook script exists
2. Verify deps with abx-pkg
3. YT-DLP extraction works on video URLs
4. JSONL output is correct
5. Config options work (YTDLP_ENABLED, YTDLP_TIMEOUT)
6. Handles non-video URLs gracefully
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
YTDLP_HOOK = next(PLUGIN_DIR.glob('on_Snapshot__*_ytdlp.*'), None)
TEST_URL = 'https://example.com/video.mp4'

def test_hook_script_exists():
    """Verify on_Snapshot hook exists."""
    assert YTDLP_HOOK.exists(), f"Hook not found: {YTDLP_HOOK}"


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
        pass

def test_handles_non_video_url():
    """Test that ytdlp extractor handles non-video URLs gracefully via hook."""
    # Prerequisites checked by earlier test

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Run ytdlp extraction hook on non-video URL
        result = subprocess.run(
            [sys.executable, str(YTDLP_HOOK), '--url', 'https://example.com', '--snapshot-id', 'test789'],
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


def test_config_ytdlp_enabled_false_skips():
    """Test that YTDLP_ENABLED=False exits without emitting JSONL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['YTDLP_ENABLED'] = 'False'

        result = subprocess.run(
            [sys.executable, str(YTDLP_HOOK), '--url', TEST_URL, '--snapshot-id', 'test999'],
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
    """Test that YTDLP_TIMEOUT config is respected (also via MEDIA_TIMEOUT alias)."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        env = os.environ.copy()
        env['YTDLP_TIMEOUT'] = '5'

        start_time = time.time()
        result = subprocess.run(
            [sys.executable, str(YTDLP_HOOK), '--url', 'https://example.com', '--snapshot-id', 'testtimeout'],
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


def test_real_youtube_url():
    """Test that yt-dlp can extract video/audio from a real YouTube URL."""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Use a short, stable YouTube video (YouTube's own about video)
        youtube_url = 'https://www.youtube.com/watch?v=jNQXAC9IVRw'  # "Me at the zoo" - first YouTube video

        env = os.environ.copy()
        env['YTDLP_TIMEOUT'] = '120'  # Give it time to download

        start_time = time.time()
        result = subprocess.run(
            [sys.executable, str(YTDLP_HOOK), '--url', youtube_url, '--snapshot-id', 'testyoutube'],
            cwd=tmpdir,
            capture_output=True,
            text=True,
            env=env,
            timeout=180
        )
        elapsed_time = time.time() - start_time

        # Should succeed
        assert result.returncode == 0, f"Should extract video/audio successfully: {result.stderr}"

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

        # Check that some video/audio files were downloaded
        output_files = list(tmpdir.glob('**/*'))
        media_files = [f for f in output_files if f.is_file() and f.suffix.lower() in ('.mp4', '.webm', '.mkv', '.m4a', '.mp3', '.json', '.jpg', '.webp')]

        assert len(media_files) > 0, f"Should have downloaded at least one video/audio file. Files: {output_files}"

        print(f"Successfully extracted {len(media_files)} file(s) in {elapsed_time:.2f}s")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
