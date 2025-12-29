#!/usr/bin/env python3
"""
Download video/audio from a URL using yt-dlp.

Usage: on_Snapshot__ytdlp.py --url=<url> --snapshot-id=<uuid>
Output: Downloads video/audio files to $PWD/ytdlp/

Environment variables:
    YTDLP_BINARY: Path to yt-dlp binary
    YTDLP_TIMEOUT: Timeout in seconds (default: 3600 for large downloads)
    YTDLP_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: True)
    YTDLP_ARGS: JSON array of yt-dlp arguments (overrides defaults)
    YTDLP_EXTRA_ARGS: Extra arguments for yt-dlp (space-separated, appended)
    YTDLP_MAX_SIZE: Maximum file size (default: 750m)

    # Feature toggles (with backwards-compatible aliases)
    YTDLP_ENABLED: Enable yt-dlp extraction (default: True)
    SAVE_YTDLP: Alias for YTDLP_ENABLED
    MEDIA_ENABLED: Backwards-compatible alias for YTDLP_ENABLED

    # Fallback to ARCHIVING_CONFIG values if YTDLP_* not set:
    TIMEOUT: Fallback timeout
    CHECK_SSL_VALIDITY: Fallback SSL check
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'ytdlp'
BIN_NAME = 'yt-dlp'
BIN_PROVIDERS = 'pip,apt,brew,env'
OUTPUT_DIR = '.'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_bool(name: str, default: bool = False) -> bool:
    val = get_env(name, '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


STATICFILE_DIR = '../staticfile'

def has_staticfile_output() -> bool:
    """Check if staticfile extractor already downloaded this URL."""
    staticfile_dir = Path(STATICFILE_DIR)
    return staticfile_dir.exists() and any(staticfile_dir.iterdir())


# Default yt-dlp args (can be overridden via YTDLP_ARGS env var)
YTDLP_DEFAULT_ARGS = [
    '--restrict-filenames',
    '--trim-filenames', '128',
    '--write-description',
    '--write-info-json',
    '--write-thumbnail',
    '--write-sub',
    '--write-auto-subs',
    '--convert-subs=srt',
    '--yes-playlist',
    '--continue',
    '--no-abort-on-error',
    '--ignore-errors',
    '--geo-bypass',
    '--add-metadata',
    '--no-progress',
    '-o', '%(title)s.%(ext)s',
]


def get_ytdlp_args() -> list[str]:
    """Get yt-dlp arguments from YTDLP_ARGS env var or use defaults."""
    ytdlp_args_str = get_env('YTDLP_ARGS', '')
    if ytdlp_args_str:
        try:
            # Try to parse as JSON array
            args = json.loads(ytdlp_args_str)
            if isinstance(args, list):
                return [str(arg) for arg in args]
        except json.JSONDecodeError:
            pass
    return YTDLP_DEFAULT_ARGS


def save_ytdlp(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Download video/audio using yt-dlp.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (YTDLP_* primary, MEDIA_* as fallback via aliases)
    timeout = get_env_int('TIMEOUT', 3600)
    check_ssl = get_env_bool('CHECK_SSL_VALIDITY', True)
    extra_args = get_env('YTDLP_EXTRA_ARGS', '')
    max_size = get_env('YTDLP_MAX_SIZE', '') or get_env('MEDIA_MAX_SIZE', '750m')

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    # Build command using configurable YTDLP_ARGS (later options take precedence)
    cmd = [
        binary,
        *get_ytdlp_args(),
        # Format with max_size limit (appended after YTDLP_ARGS so it can be overridden by YTDLP_EXTRA_ARGS)
        f'--format=(bv*+ba/b)[filesize<={max_size}][filesize_approx<=?{max_size}]/(bv*+ba/b)',
    ]

    if not check_ssl:
        cmd.append('--no-check-certificate')

    if extra_args:
        cmd.extend(extra_args.split())

    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)

        # Check if any media files were downloaded
        media_extensions = (
            '.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.m4v',
            '.mp3', '.m4a', '.ogg', '.wav', '.flac', '.aac', '.opus',
            '.json', '.jpg', '.png', '.webp', '.jpeg',
            '.vtt', '.srt', '.ass', '.lrc',
            '.description',
        )

        downloaded_files = [
            f for f in output_dir.glob('*')
            if f.is_file() and f.suffix.lower() in media_extensions
        ]

        if downloaded_files:
            # Return first video/audio file, or first file if no media
            video_audio = [
                f for f in downloaded_files
                if f.suffix.lower() in ('.mp4', '.webm', '.mkv', '.avi', '.mov', '.mp3', '.m4a', '.ogg', '.wav', '.flac')
            ]
            output = str(video_audio[0]) if video_audio else str(downloaded_files[0])
            return True, output, ''
        else:
            stderr = result.stderr

            # These are NOT errors - page simply has no downloadable media
            # Return success with no output (legitimate "nothing to download")
            if 'ERROR: Unsupported URL' in stderr:
                return True, None, ''  # Not a media site - success, no output
            if 'URL could be a direct video link' in stderr:
                return True, None, ''  # Not a supported media URL - success, no output
            if result.returncode == 0:
                return True, None, ''  # yt-dlp exited cleanly, just no media - success

            # These ARE errors - something went wrong
            if 'HTTP Error 404' in stderr:
                return False, None, '404 Not Found'
            if 'HTTP Error 403' in stderr:
                return False, None, '403 Forbidden'
            if 'Unable to extract' in stderr:
                return False, None, 'Unable to extract media info'

            return False, None, f'yt-dlp error: {stderr[:200]}'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to download video/audio from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download video/audio from a URL using yt-dlp."""

    try:
        # Check if yt-dlp downloading is enabled (YTDLP_ENABLED primary, MEDIA_ENABLED fallback)
        ytdlp_enabled = get_env_bool('YTDLP_ENABLED', True) and get_env_bool('MEDIA_ENABLED', True)
        if not ytdlp_enabled:
            print('Skipping ytdlp (YTDLP_ENABLED=False)', file=sys.stderr)
            # Temporary failure (config disabled) - NO JSONL emission
            sys.exit(0)

        # Check if staticfile extractor already handled this (permanent skip)
        if has_staticfile_output():
            print('Skipping ytdlp - staticfile extractor already downloaded this', file=sys.stderr)
            print(json.dumps({'type': 'ArchiveResult', 'status': 'skipped', 'output_str': 'staticfile already exists'}))
            sys.exit(0)

        # Get binary from environment
        binary = get_env('YTDLP_BINARY', 'yt-dlp')

        # Run extraction
        success, output, error = save_ytdlp(url, binary)

        if success:
            # Success - emit ArchiveResult
            result = {
                'type': 'ArchiveResult',
                'status': 'succeeded',
                'output_str': output or ''
            }
            print(json.dumps(result))
            sys.exit(0)
        else:
            # Transient error - emit NO JSONL
            print(f'ERROR: {error}', file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        # Transient error - emit NO JSONL
        print(f'ERROR: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
