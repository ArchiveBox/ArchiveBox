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
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'singlefile'
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


def find_singlefile() -> str | None:
    """Find SingleFile binary."""
    singlefile = get_env('SINGLEFILE_BINARY')
    if singlefile and os.path.isfile(singlefile):
        return singlefile

    for name in ['single-file', 'singlefile']:
        binary = shutil.which(name)
        if binary:
            return binary

    return None


def find_chrome() -> str | None:
    """Find Chrome/Chromium binary."""
    chrome = get_env('CHROME_BINARY')
    if chrome and os.path.isfile(chrome):
        return chrome

    for name in ALL_CHROME_BINARIES:
        if '/' in name:
            if os.path.isfile(name):
                return name
        else:
            binary = shutil.which(name)
            if binary:
                return binary

    return None


def get_version(binary: str) -> str:
    """Get SingleFile version."""
    try:
        result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()[:64]
    except Exception:
        return ''


CHROME_SESSION_DIR = '../chrome_session'


def get_cdp_url() -> str | None:
    """Get CDP URL from chrome_session if available."""
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

    If a Chrome session exists (from chrome_session extractor), connects to it via CDP.
    Otherwise launches a new Chrome instance.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (with SINGLEFILE_ prefix or fallback to ARCHIVING_CONFIG style)
    timeout = get_env_int('SINGLEFILE_TIMEOUT') or get_env_int('TIMEOUT', 120)
    user_agent = get_env('SINGLEFILE_USER_AGENT') or get_env('USER_AGENT', '')
    check_ssl = get_env_bool('SINGLEFILE_CHECK_SSL_VALIDITY', get_env_bool('CHECK_SSL_VALIDITY', True))
    cookies_file = get_env('SINGLEFILE_COOKIES_FILE') or get_env('COOKIES_FILE', '')
    extra_args = get_env('SINGLEFILE_EXTRA_ARGS', '')
    chrome = find_chrome()

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

    start_ts = datetime.now(timezone.utc)
    version = ''
    output = None
    status = 'failed'
    error = ''
    binary = None
    cmd_str = ''

    try:
        # Check if SingleFile is enabled
        if not get_env_bool('SAVE_SINGLEFILE', True):
            print('Skipping SingleFile (SAVE_SINGLEFILE=False)')
            status = 'skipped'
            end_ts = datetime.now(timezone.utc)
            print(f'START_TS={start_ts.isoformat()}')
            print(f'END_TS={end_ts.isoformat()}')
            print(f'STATUS={status}')
            print(f'RESULT_JSON={json.dumps({"extractor": EXTRACTOR_NAME, "status": status, "url": url, "snapshot_id": snapshot_id})}')
            sys.exit(0)

        # Check if staticfile extractor already handled this (permanent skip)
        if has_staticfile_output():
            print(f'Skipping SingleFile - staticfile extractor already downloaded this')
            print(f'START_TS={start_ts.isoformat()}')
            print(f'END_TS={datetime.now(timezone.utc).isoformat()}')
            print(f'STATUS=skipped')
            print(f'RESULT_JSON={json.dumps({"extractor": EXTRACTOR_NAME, "status": "skipped", "url": url, "snapshot_id": snapshot_id})}')
            sys.exit(0)  # Permanent skip - staticfile already handled

        # Find binary
        binary = find_singlefile()
        if not binary:
            print(f'ERROR: SingleFile binary not found', file=sys.stderr)
            print(f'DEPENDENCY_NEEDED={BIN_NAME}', file=sys.stderr)
            print(f'BIN_PROVIDERS={BIN_PROVIDERS}', file=sys.stderr)
            print(f'INSTALL_HINT=npm install -g single-file-cli', file=sys.stderr)
            sys.exit(1)

        version = get_version(binary)
        cmd_str = f'{binary} {url} {OUTPUT_FILE}'

        # Run extraction
        success, output, error = save_singlefile(url, binary)
        status = 'succeeded' if success else 'failed'

        if success and output:
            size = Path(output).stat().st_size
            print(f'SingleFile saved ({size} bytes)')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    # Print results
    end_ts = datetime.now(timezone.utc)
    duration = (end_ts - start_ts).total_seconds()

    print(f'START_TS={start_ts.isoformat()}')
    print(f'END_TS={end_ts.isoformat()}')
    print(f'DURATION={duration:.2f}')
    if cmd_str:
        print(f'CMD={cmd_str}')
    if version:
        print(f'VERSION={version}')
    if output:
        print(f'OUTPUT={output}')
    print(f'STATUS={status}')

    if error:
        print(f'ERROR={error}', file=sys.stderr)

    # Print JSON result
    result_json = {
        'extractor': EXTRACTOR_NAME,
        'url': url,
        'snapshot_id': snapshot_id,
        'status': status,
        'start_ts': start_ts.isoformat(),
        'end_ts': end_ts.isoformat(),
        'duration': round(duration, 2),
        'cmd_version': version,
        'output': output,
        'error': error or None,
    }
    print(f'RESULT_JSON={json.dumps(result_json)}')

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
