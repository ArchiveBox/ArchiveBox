#!/usr/bin/env python3
"""
Archive a URL using SingleFile.

Usage: on_Snapshot__singlefile.py --url=<url> --snapshot-id=<uuid>
Output: Writes singlefile.html to $PWD

Environment variables:
    SINGLEFILE_BINARY: Path to SingleFile binary
    SINGLEFILE_TIMEOUT: Timeout in seconds (default: 120)
    SINGLEFILE_USER_AGENT: User agent string (optional)
    SINGLEFILE_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: True)
    SINGLEFILE_COOKIES_FILE: Path to cookies file (optional)
    SINGLEFILE_EXTRA_ARGS: Extra arguments for SingleFile (space-separated)

    # Feature toggle
    SAVE_SINGLEFILE: Enable SingleFile archiving (default: True)

    # Chrome binary (SingleFile needs Chrome)
    CHROME_BINARY: Path to Chrome/Chromium binary

    # Fallback to ARCHIVING_CONFIG values if SINGLEFILE_* not set:
    TIMEOUT: Fallback timeout
    USER_AGENT: Fallback user agent
    CHECK_SSL_VALIDITY: Fallback SSL check
    COOKIES_FILE: Fallback cookies file
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'singlefile'
BIN_NAME = 'single-file'
BIN_PROVIDERS = 'npm,env'
OUTPUT_DIR = '.'
OUTPUT_FILE = 'singlefile.html'


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


# Chrome binary search paths
CHROMIUM_BINARY_NAMES_LINUX = [
    'chromium', 'chromium-browser', 'chromium-browser-beta',
    'chromium-browser-unstable', 'chromium-browser-canary', 'chromium-browser-dev',
]
CHROME_BINARY_NAMES_LINUX = [
    'google-chrome', 'google-chrome-stable', 'google-chrome-beta',
    'google-chrome-canary', 'google-chrome-unstable', 'google-chrome-dev', 'chrome',
]
CHROME_BINARY_NAMES_MACOS = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary',
]
CHROMIUM_BINARY_NAMES_MACOS = ['/Applications/Chromium.app/Contents/MacOS/Chromium']

ALL_CHROME_BINARIES = (
    CHROME_BINARY_NAMES_LINUX + CHROMIUM_BINARY_NAMES_LINUX +
    CHROME_BINARY_NAMES_MACOS + CHROMIUM_BINARY_NAMES_MACOS
)


CHROME_SESSION_DIR = '../chrome'


def get_cdp_url() -> str | None:
    """Get CDP URL from chrome plugin if available."""
    cdp_file = Path(CHROME_SESSION_DIR) / 'cdp_url.txt'
    if cdp_file.exists():
        return cdp_file.read_text().strip()
    return None


def get_port_from_cdp_url(cdp_url: str) -> str | None:
    """Extract port from CDP WebSocket URL (ws://127.0.0.1:PORT/...)."""
    import re
    match = re.search(r':(\d+)/', cdp_url)
    if match:
        return match.group(1)
    return None


def save_singlefile(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Archive URL using SingleFile.

    If a Chrome session exists (from chrome plugin), connects to it via CDP.
    Otherwise launches a new Chrome instance.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (with SINGLEFILE_ prefix or fallback to ARCHIVING_CONFIG style)
    timeout = get_env_int('SINGLEFILE_TIMEOUT') or get_env_int('TIMEOUT', 120)
    user_agent = get_env('SINGLEFILE_USER_AGENT') or get_env('USER_AGENT', '')
    check_ssl = get_env_bool('SINGLEFILE_CHECK_SSL_VALIDITY', get_env_bool('CHECK_SSL_VALIDITY', True))
    cookies_file = get_env('SINGLEFILE_COOKIES_FILE') or get_env('COOKIES_FILE', '')
    extra_args = get_env('SINGLEFILE_EXTRA_ARGS', '')
    chrome = get_env('CHROME_BINARY', '')

    cmd = [binary]

    # Try to use existing Chrome session via CDP
    cdp_url = get_cdp_url()
    if cdp_url:
        # SingleFile can connect to existing browser via WebSocket
        # Extract port from CDP URL (ws://127.0.0.1:PORT/...)
        port = get_port_from_cdp_url(cdp_url)
        if port:
            cmd.extend(['--browser-server', f'http://127.0.0.1:{port}'])
    elif chrome:
        cmd.extend(['--browser-executable-path', chrome])

    # Common options
    cmd.extend([
        '--browser-headless',
    ])

    # SSL handling
    if not check_ssl:
        cmd.append('--browser-ignore-insecure-certs')

    if user_agent:
        cmd.extend(['--browser-user-agent', user_agent])

    if cookies_file and Path(cookies_file).is_file():
        cmd.extend(['--browser-cookies-file', cookies_file])

    if extra_args:
        cmd.extend(extra_args.split())

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)
    output_path = output_dir / OUTPUT_FILE

    cmd.extend([url, str(output_path)])

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)

        if output_path.exists() and output_path.stat().st_size > 0:
            return True, str(output_path), ''
        else:
            stderr = result.stderr.decode('utf-8', errors='replace')
            if 'ERR_NAME_NOT_RESOLVED' in stderr:
                return False, None, 'DNS resolution failed'
            if 'ERR_CONNECTION_REFUSED' in stderr:
                return False, None, 'Connection refused'
            return False, None, f'SingleFile failed: {stderr[:200]}'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to archive')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Archive a URL using SingleFile."""

    output = None
    status = 'failed'
    error = ''

    try:
        # Check if SingleFile is enabled
        if not get_env_bool('SINGLEFILE_ENABLED', True):
            print('Skipping SingleFile (SINGLEFILE_ENABLED=False)', file=sys.stderr)
            # Feature disabled - no ArchiveResult, just exit
            sys.exit(0)

        # Check if staticfile extractor already handled this (permanent skip)
        if has_staticfile_output():
            print('Skipping SingleFile - staticfile extractor already downloaded this', file=sys.stderr)
            print(json.dumps({'type': 'ArchiveResult', 'status': 'skipped', 'output_str': 'staticfile already exists'}))
            sys.exit(0)

        # Get binary from environment
        binary = get_env('SINGLEFILE_BINARY', 'single-file')

        # Run extraction
        success, output, error = save_singlefile(url, binary)
        status = 'succeeded' if success else 'failed'

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    if error:
        print(f'ERROR: {error}', file=sys.stderr)

    # Output clean JSONL (no RESULT_JSON= prefix)
    result = {
        'type': 'ArchiveResult',
        'status': status,
        'output_str': output or error or '',
    }
    print(json.dumps(result))

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
