#!/usr/bin/env python3
"""
Archive a URL using wget.

Usage: on_Snapshot__wget.py --url=<url> --snapshot-id=<uuid>
Output: Downloads files to $PWD

Environment variables:
    WGET_BINARY: Path to wget binary (optional, falls back to PATH)
    WGET_TIMEOUT: Timeout in seconds (default: 60)
    WGET_USER_AGENT: User agent string
    WGET_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: True)
    WGET_COOKIES_FILE: Path to cookies file (optional)
    WGET_RESTRICT_FILE_NAMES: Filename restriction mode (default: windows)
    WGET_EXTRA_ARGS: Extra arguments for wget (space-separated)

    # Wget feature toggles
    SAVE_WGET: Enable wget archiving (default: True)
    SAVE_WARC: Save WARC file (default: True)
    SAVE_WGET_REQUISITES: Download page requisites (default: True)

    # Fallback to ARCHIVING_CONFIG values if WGET_* not set:
    TIMEOUT: Fallback timeout
    USER_AGENT: Fallback user agent
    CHECK_SSL_VALIDITY: Fallback SSL check
    COOKIES_FILE: Fallback cookies file
    RESTRICT_FILE_NAMES: Fallback filename restriction
"""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'wget'
BIN_NAME = 'wget'
BIN_PROVIDERS = 'apt,brew,env'
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


def find_wget() -> str | None:
    """Find wget binary."""
    wget = get_env('WGET_BINARY')
    if wget and os.path.isfile(wget):
        return wget
    return shutil.which('wget')


def get_version(binary: str) -> str:
    """Get wget version."""
    try:
        result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
        return result.stdout.split('\n')[0].strip()[:64]
    except Exception:
        return ''


def check_wget_compression(binary: str) -> bool:
    """Check if wget supports --compression=auto."""
    try:
        result = subprocess.run(
            [binary, '--compression=auto', '--help'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


# Default wget args (from old WGET_CONFIG)
WGET_DEFAULT_ARGS = [
    '--no-verbose',
    '--adjust-extension',
    '--convert-links',
    '--force-directories',
    '--backup-converted',
    '--span-hosts',
    '--no-parent',
    '-e', 'robots=off',
]


def save_wget(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Archive URL using wget.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (with WGET_ prefix or fallback to ARCHIVING_CONFIG style)
    timeout = get_env_int('WGET_TIMEOUT') or get_env_int('TIMEOUT', 60)
    user_agent = get_env('WGET_USER_AGENT') or get_env('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')
    check_ssl = get_env_bool('WGET_CHECK_SSL_VALIDITY', get_env_bool('CHECK_SSL_VALIDITY', True))
    cookies_file = get_env('WGET_COOKIES_FILE') or get_env('COOKIES_FILE', '')
    restrict_names = get_env('WGET_RESTRICT_FILE_NAMES') or get_env('RESTRICT_FILE_NAMES', 'windows')
    extra_args = get_env('WGET_EXTRA_ARGS', '')

    # Feature toggles
    save_warc = get_env_bool('SAVE_WARC', True)
    save_requisites = get_env_bool('SAVE_WGET_REQUISITES', True)

    # Check for compression support
    supports_compression = check_wget_compression(binary)

    # Build wget command (later options take precedence)
    cmd = [
        binary,
        *WGET_DEFAULT_ARGS,
        f'--timeout={timeout}',
        '--tries=2',
    ]

    if user_agent:
        cmd.append(f'--user-agent={user_agent}')

    if restrict_names:
        cmd.append(f'--restrict-file-names={restrict_names}')

    if save_requisites:
        cmd.append('--page-requisites')

    if save_warc:
        warc_dir = Path('warc')
        warc_dir.mkdir(exist_ok=True)
        warc_path = warc_dir / str(int(datetime.now(timezone.utc).timestamp()))
        cmd.append(f'--warc-file={warc_path}')
    else:
        cmd.append('--timestamping')

    if cookies_file and Path(cookies_file).is_file():
        cmd.extend(['--load-cookies', cookies_file])

    if supports_compression:
        cmd.append('--compression=auto')

    if not check_ssl:
        cmd.extend(['--no-check-certificate', '--no-hsts'])

    if extra_args:
        cmd.extend(extra_args.split())

    cmd.append(url)

    # Run wget
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout * 2,  # Allow extra time for large downloads
        )

        # Find downloaded files
        downloaded_files = [
            f for f in Path('.').rglob('*')
            if f.is_file() and f.name != '.gitkeep' and not str(f).startswith('warc/')
        ]

        if not downloaded_files:
            stderr = result.stderr.decode('utf-8', errors='replace')
            stdout = result.stdout.decode('utf-8', errors='replace')
            combined = stderr + stdout

            if '403' in combined or 'Forbidden' in combined:
                return False, None, '403 Forbidden (try changing USER_AGENT)'
            elif '404' in combined or 'Not Found' in combined:
                return False, None, '404 Not Found'
            elif '500' in combined:
                return False, None, '500 Internal Server Error'
            else:
                return False, None, f'No files downloaded: {stderr[:200]}'

        # Find main HTML file
        html_files = [
            f for f in downloaded_files
            if re.search(r'\.[Ss]?[Hh][Tt][Mm][Ll]?$', str(f))
        ]
        output_path = str(html_files[0]) if html_files else str(downloaded_files[0])

        # Parse download stats from wget output
        output_tail = result.stderr.decode('utf-8', errors='replace').strip().split('\n')[-3:]
        files_count = len(downloaded_files)

        return True, output_path, ''

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout * 2} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to archive')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Archive a URL using wget."""

    start_ts = datetime.now(timezone.utc)
    version = ''
    output = None
    status = 'failed'
    error = ''
    binary = None
    cmd_str = ''

    try:
        # Check if wget is enabled
        if not get_env_bool('SAVE_WGET', True):
            print('Skipping wget (SAVE_WGET=False)', file=sys.stderr)
            print(json.dumps({'type': 'ArchiveResult', 'status': 'skipped', 'output_str': 'SAVE_WGET=False'}))
            sys.exit(0)

        # Check if staticfile extractor already handled this (permanent skip)
        if has_staticfile_output():
            print('Skipping wget - staticfile extractor already downloaded this', file=sys.stderr)
            print(json.dumps({'type': 'ArchiveResult', 'status': 'skipped', 'output_str': 'staticfile already exists'}))
            sys.exit(0)

        # Find binary
        binary = find_wget()
        if not binary:
            print(f'ERROR: {BIN_NAME} binary not found', file=sys.stderr)
            print(f'DEPENDENCY_NEEDED={BIN_NAME}', file=sys.stderr)
            print(f'BIN_PROVIDERS={BIN_PROVIDERS}', file=sys.stderr)
            print(f'INSTALL_HINT=apt install wget OR brew install wget', file=sys.stderr)
            sys.exit(1)

        version = get_version(binary)
        cmd_str = f'{binary} ... {url}'

        # Run extraction
        success, output, error = save_wget(url, binary)
        status = 'succeeded' if success else 'failed'

        if success:
            # Count downloaded files
            files = list(Path('.').rglob('*'))
            file_count = len([f for f in files if f.is_file()])
            print(f'wget completed: {file_count} files downloaded')

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
        result['cmd'] = [binary, '--no-verbose', url]
    if version:
        result['cmd_version'] = version
    print(json.dumps(result))

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
