#!/usr/bin/env python3
"""
Download video/audio from a URL using yt-dlp.

Usage: on_Snapshot__02_ytdlp.bg.py --url=<url> --snapshot-id=<uuid>
Output: Downloads video/audio files to $PWD

Environment variables:
    YTDLP_ENABLED: Enable yt-dlp extraction (default: True)
    YTDLP_BINARY: Path to yt-dlp binary (default: yt-dlp)
    YTDLP_NODE_BINARY: Path to Node.js binary (x-fallback: NODE_BINARY)
    YTDLP_TIMEOUT: Timeout in seconds (x-fallback: TIMEOUT)
    YTDLP_COOKIES_FILE: Path to cookies file (x-fallback: COOKIES_FILE)
    YTDLP_MAX_SIZE: Maximum file size (default: 750m)
    YTDLP_CHECK_SSL_VALIDITY: Whether to verify SSL certs (x-fallback: CHECK_SSL_VALIDITY)
    YTDLP_ARGS: Default yt-dlp arguments (JSON array)
    YTDLP_ARGS_EXTRA: Extra arguments to append (JSON array)
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import rich_click as click




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


def get_env_array(name: str, default: list[str] | None = None) -> list[str]:
    """Parse a JSON array from environment variable."""
    val = get_env(name, '')
    if not val:
        return default if default is not None else []
    try:
        result = json.loads(val)
        if isinstance(result, list):
            return [str(item) for item in result]
        return default if default is not None else []
    except json.JSONDecodeError:
        return default if default is not None else []


STATICFILE_DIR = '../staticfile'

def has_staticfile_output() -> bool:
    """Check if staticfile extractor already downloaded this URL."""
    staticfile_dir = Path(STATICFILE_DIR)
    if not staticfile_dir.exists():
        return False
    stdout_log = staticfile_dir / 'stdout.log'
    if not stdout_log.exists():
        return False
    for line in stdout_log.read_text(errors='ignore').splitlines():
        line = line.strip()
        if not line.startswith('{'):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get('type') == 'ArchiveResult' and record.get('status') == 'succeeded':
            return True
    return False


def save_ytdlp(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Download video/audio using yt-dlp.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (with YTDLP_ prefix, x-fallback handled by config loader)
    timeout = get_env_int('YTDLP_TIMEOUT') or get_env_int('TIMEOUT', 3600)
    check_ssl = get_env_bool('YTDLP_CHECK_SSL_VALIDITY', True) if get_env('YTDLP_CHECK_SSL_VALIDITY') else get_env_bool('CHECK_SSL_VALIDITY', True)
    cookies_file = get_env('YTDLP_COOKIES_FILE') or get_env('COOKIES_FILE', '')
    max_size = get_env('YTDLP_MAX_SIZE', '750m')
    node_binary = get_env('YTDLP_NODE_BINARY') or get_env('NODE_BINARY', 'node')
    ytdlp_args = get_env_array('YTDLP_ARGS', [])
    ytdlp_args_extra = get_env_array('YTDLP_ARGS_EXTRA', [])

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path('.')

    # Build command (later options take precedence)
    cmd = [
        binary,
        *ytdlp_args,
        # Format with max_size limit (appended after YTDLP_ARGS so it can be overridden by YTDLP_ARGS_EXTRA)
        f'--format=(bv*+ba/b)[filesize<={max_size}][filesize_approx<=?{max_size}]/(bv*+ba/b)',
        f'--js-runtimes=node:{node_binary}',
    ]

    if not check_ssl:
        cmd.append('--no-check-certificate')

    if cookies_file and Path(cookies_file).is_file():
        cmd.extend(['--cookies', cookies_file])

    if ytdlp_args_extra:
        cmd.extend(ytdlp_args_extra)

    if '--newline' not in cmd:
        cmd.append('--newline')

    cmd.append(url)

    try:
        print(f'[ytdlp] Starting download (timeout={timeout}s)', file=sys.stderr)

        output_lines: list[str] = []
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        def _read_output() -> None:
            if not process.stdout:
                return
            for line in process.stdout:
                output_lines.append(line)
                sys.stderr.write(line)

        reader = threading.Thread(target=_read_output, daemon=True)
        reader.start()

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            reader.join(timeout=1)
            return False, None, f'Timed out after {timeout} seconds'

        reader.join(timeout=1)
        combined_output = ''.join(output_lines)

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
            stderr = combined_output

            # These are NOT errors - page simply has no downloadable media
            # Return success with no output (legitimate "nothing to download")
            if 'ERROR: Unsupported URL' in stderr:
                return True, None, ''  # Not a media site - success, no output
            if 'URL could be a direct video link' in stderr:
                return True, None, ''  # Not a supported media URL - success, no output
            if process.returncode == 0:
                return True, None, ''  # yt-dlp exited cleanly, just no media - success

            # These ARE errors - something went wrong
            if 'HTTP Error 404' in stderr:
                return False, None, '404 Not Found'
            if 'HTTP Error 403' in stderr:
                return False, None, '403 Forbidden'
            if 'Unable to extract' in stderr:
                return False, None, 'Unable to extract media info'

            return False, None, f'yt-dlp error: {stderr}'

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
        # Check if yt-dlp downloading is enabled
        if not get_env_bool('YTDLP_ENABLED', True):
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
