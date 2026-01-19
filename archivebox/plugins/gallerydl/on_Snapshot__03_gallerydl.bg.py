#!/usr/bin/env python3
"""
Download image galleries from a URL using gallery-dl.

Usage: on_Snapshot__03_gallerydl.bg.py --url=<url> --snapshot-id=<uuid>
Output: Downloads gallery images to $PWD/gallerydl/

Environment variables:
    GALLERYDL_ENABLED: Enable gallery-dl gallery extraction (default: True)
    GALLERYDL_BINARY: Path to gallery-dl binary (default: gallery-dl)
    GALLERYDL_TIMEOUT: Timeout in seconds (x-fallback: TIMEOUT)
    GALLERYDL_COOKIES_FILE: Path to cookies file (x-fallback: COOKIES_FILE)
    GALLERYDL_CHECK_SSL_VALIDITY: Whether to verify SSL certs (x-fallback: CHECK_SSL_VALIDITY)
    GALLERYDL_ARGS: Default gallery-dl arguments (JSON array)
    GALLERYDL_ARGS_EXTRA: Extra arguments to append (JSON array)
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'gallerydl'
BIN_NAME = 'gallery-dl'
BIN_PROVIDERS = 'pip,env'
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


def save_gallery(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Download gallery using gallery-dl.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (with GALLERYDL_ prefix, x-fallback handled by config loader)
    timeout = get_env_int('GALLERYDL_TIMEOUT') or get_env_int('TIMEOUT', 3600)
    check_ssl = get_env_bool('GALLERYDL_CHECK_SSL_VALIDITY', True) if get_env('GALLERYDL_CHECK_SSL_VALIDITY') else get_env_bool('CHECK_SSL_VALIDITY', True)
    gallerydl_args = get_env_array('GALLERYDL_ARGS', [])
    gallerydl_args_extra = get_env_array('GALLERYDL_ARGS_EXTRA', [])
    cookies_file = get_env('GALLERYDL_COOKIES_FILE') or get_env('COOKIES_FILE', '')

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    # Build command
    # Use -D for exact directory (flat structure) instead of -d (nested structure)
    cmd = [
        binary,
        *gallerydl_args,
        '-D', str(output_dir),
    ]

    if not check_ssl:
        cmd.append('--no-check-certificate')

    if cookies_file and Path(cookies_file).exists():
        cmd.extend(['-C', cookies_file])

    if gallerydl_args_extra:
        cmd.extend(gallerydl_args_extra)

    cmd.append(url)

    try:
        print(f'[gallerydl] Starting download (timeout={timeout}s)', file=sys.stderr)
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

        # Check if any gallery files were downloaded (search recursively)
        gallery_extensions = (
            '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg',
            '.mp4', '.webm', '.mkv', '.avi', '.mov', '.flv',
            '.json', '.txt', '.zip',
        )

        downloaded_files = [
            f for f in output_dir.rglob('*')
            if f.is_file() and f.suffix.lower() in gallery_extensions
        ]

        if downloaded_files:
            # Return first image file, or first file if no images
            image_files = [
                f for f in downloaded_files
                if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
            ]
            output = str(image_files[0]) if image_files else str(downloaded_files[0])
            return True, output, ''
        else:
            stderr = combined_output

            # These are NOT errors - page simply has no downloadable gallery
            # Return success with no output (legitimate "nothing to download")
            stderr_lower = stderr.lower()
            if 'unsupported url' in stderr_lower:
                return True, None, ''  # Not a gallery site - success, no output
            if 'no results' in stderr_lower:
                return True, None, ''  # No gallery found - success, no output
            if process.returncode == 0:
                return True, None, ''  # gallery-dl exited cleanly, just no gallery - success

            # These ARE errors - something went wrong
            if '404' in stderr:
                return False, None, '404 Not Found'
            if '403' in stderr:
                return False, None, '403 Forbidden'
            if 'unable to extract' in stderr_lower:
                return False, None, 'Unable to extract gallery info'

            return False, None, f'gallery-dl error: {stderr}'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to download gallery from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download image gallery from a URL using gallery-dl."""

    output = None
    status = 'failed'
    error = ''

    try:
        # Check if gallery-dl is enabled
        if not get_env_bool('GALLERYDL_ENABLED', True):
            print('Skipping gallery-dl (GALLERYDL_ENABLED=False)', file=sys.stderr)
            # Temporary failure (config disabled) - NO JSONL emission
            sys.exit(0)

        # Check if staticfile extractor already handled this (permanent skip)
        if has_staticfile_output():
            print(f'Skipping gallery-dl - staticfile extractor already downloaded this', file=sys.stderr)
            print(json.dumps({
                'type': 'ArchiveResult',
                'status': 'skipped',
                'output_str': 'staticfile already handled',
            }))
            sys.exit(0)

        # Get binary from environment
        binary = get_env('GALLERYDL_BINARY', 'gallery-dl')

        # Run extraction
        success, output, error = save_gallery(url, binary)

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
