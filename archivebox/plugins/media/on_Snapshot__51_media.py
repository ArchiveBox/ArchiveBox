#!/usr/bin/env python3
"""
Download media from a URL using yt-dlp.

Usage: on_Snapshot__media.py --url=<url> --snapshot-id=<uuid>
Output: Downloads media files to $PWD/media/

Environment variables:
    YTDLP_BINARY: Path to yt-dlp binary
    YTDLP_TIMEOUT: Timeout in seconds (default: 3600 for large media)
    YTDLP_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: True)
    YTDLP_EXTRA_ARGS: Extra arguments for yt-dlp (space-separated)

    # Media feature toggles
    USE_YTDLP: Enable yt-dlp media extraction (default: True)
    SAVE_MEDIA: Alias for USE_YTDLP

    # Media size limits
    MEDIA_MAX_SIZE: Maximum media file size (default: 750m)

    # Fallback to ARCHIVING_CONFIG values if YTDLP_* not set:
    MEDIA_TIMEOUT: Fallback timeout for media
    TIMEOUT: Fallback timeout
    CHECK_SSL_VALIDITY: Fallback SSL check
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'media'
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


def find_ytdlp() -> str | None:
    """Find yt-dlp binary."""
    ytdlp = get_env('YTDLP_BINARY') or get_env('YOUTUBEDL_BINARY')
    if ytdlp and os.path.isfile(ytdlp):
        return ytdlp

    for name in ['yt-dlp', 'youtube-dl']:
        binary = shutil.which(name)
        if binary:
            return binary

    return None


def get_version(binary: str) -> str:
    """Get yt-dlp version."""
    try:
        result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()[:64]
    except Exception:
        return ''


# Default yt-dlp args (from old YTDLP_CONFIG)
def get_ytdlp_default_args(media_max_size: str = '750m') -> list[str]:
    """Build default yt-dlp arguments."""
    return [
        '--restrict-filenames',
        '--trim-filenames', '128',
        '--write-description',
        '--write-info-json',
        '--write-annotations',
        '--write-thumbnail',
        '--no-call-home',
        '--write-sub',
        '--write-auto-subs',
        '--convert-subs=srt',
        '--yes-playlist',
        '--continue',
        '--no-abort-on-error',
        '--ignore-errors',
        '--geo-bypass',
        '--add-metadata',
        f'--format=(bv*+ba/b)[filesize<={media_max_size}][filesize_approx<=?{media_max_size}]/(bv*+ba/b)',
    ]


def save_media(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Download media using yt-dlp.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (with YTDLP_ prefix or fallback to ARCHIVING_CONFIG style)
    timeout = get_env_int('YTDLP_TIMEOUT') or get_env_int('MEDIA_TIMEOUT') or get_env_int('TIMEOUT', 3600)
    check_ssl = get_env_bool('YTDLP_CHECK_SSL_VALIDITY', get_env_bool('CHECK_SSL_VALIDITY', True))
    extra_args = get_env('YTDLP_EXTRA_ARGS') or get_env('YOUTUBEDL_EXTRA_ARGS', '')
    media_max_size = get_env('MEDIA_MAX_SIZE', '750m')

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    # Build command (later options take precedence)
    cmd = [
        binary,
        *get_ytdlp_default_args(media_max_size),
        '--no-progress',
        '-o', f'{OUTPUT_DIR}/%(title)s.%(ext)s',
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
@click.option('--url', required=True, help='URL to download media from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download media from a URL using yt-dlp."""

    start_ts = datetime.now(timezone.utc)
    version = ''
    output = None
    status = 'failed'
    error = ''
    binary = None
    cmd_str = ''

    try:
        # Check if yt-dlp is enabled
        if not (get_env_bool('USE_YTDLP', True) and get_env_bool('SAVE_MEDIA', True)):
            print('Skipping media (USE_YTDLP=False or SAVE_MEDIA=False)', file=sys.stderr)
            print(json.dumps({'type': 'ArchiveResult', 'status': 'skipped', 'output_str': 'USE_YTDLP=False'}))
            sys.exit(0)

        # Check if staticfile extractor already handled this (permanent skip)
        if has_staticfile_output():
            print('Skipping media - staticfile extractor already downloaded this', file=sys.stderr)
            print(json.dumps({'type': 'ArchiveResult', 'status': 'skipped', 'output_str': 'staticfile already exists'}))
            sys.exit(0)

        # Find binary
        binary = find_ytdlp()
        if not binary:
            print(f'ERROR: {BIN_NAME} binary not found', file=sys.stderr)
            print(f'DEPENDENCY_NEEDED={BIN_NAME}', file=sys.stderr)
            print(f'BIN_PROVIDERS={BIN_PROVIDERS}', file=sys.stderr)
            print(f'INSTALL_HINT=pip install yt-dlp OR brew install yt-dlp', file=sys.stderr)
            sys.exit(1)

        version = get_version(binary)
        cmd_str = f'{binary} {url}'

        # Run extraction
        success, output, error = save_media(url, binary)
        status = 'succeeded' if success else 'failed'

        if success:
            output_dir = Path(OUTPUT_DIR)
            files = list(output_dir.glob('*'))
            file_count = len([f for f in files if f.is_file()])
            if file_count > 0:
                print(f'yt-dlp completed: {file_count} files downloaded')
            else:
                print(f'yt-dlp completed: no media found on page (this is normal)')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    # Calculate duration
    end_ts = datetime.now(timezone.utc)

    if error:
        print(f'ERROR: {error}', file=sys.stderr)

    # Output clean JSONL (no RESULT_JSON= prefix)
    result = {
        'type': 'ArchiveResult',
        'status': status,
        'output_str': output or error or '',
    }
    if binary:
        result['cmd'] = [binary, url]
    if version:
        result['cmd_version'] = version
    print(json.dumps(result))

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
