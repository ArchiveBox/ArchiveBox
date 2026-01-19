#!/usr/bin/env python3
"""
Archive a URL using wget.

Usage: on_Snapshot__06_wget.bg.py --url=<url> --snapshot-id=<uuid>
Output: Downloads files to $PWD

Environment variables:
    WGET_ENABLED: Enable wget archiving (default: True)
    WGET_WARC_ENABLED: Save WARC file (default: True)
    WGET_BINARY: Path to wget binary (default: wget)
    WGET_TIMEOUT: Timeout in seconds (x-fallback: TIMEOUT)
    WGET_USER_AGENT: User agent string (x-fallback: USER_AGENT)
    WGET_COOKIES_FILE: Path to cookies file (x-fallback: COOKIES_FILE)
    WGET_CHECK_SSL_VALIDITY: Whether to check SSL certificates (x-fallback: CHECK_SSL_VALIDITY)
    WGET_ARGS: Default wget arguments (JSON array)
    WGET_ARGS_EXTRA: Extra arguments to append (JSON array)
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'wget'
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




def save_wget(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Archive URL using wget.

    Returns: (success, output_path, error_message)
    """
    # Get config from env (with WGET_ prefix, x-fallback handled by config loader)
    timeout = get_env_int('WGET_TIMEOUT') or get_env_int('TIMEOUT', 60)
    user_agent = get_env('WGET_USER_AGENT') or get_env('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')
    check_ssl = get_env_bool('WGET_CHECK_SSL_VALIDITY', True) if get_env('WGET_CHECK_SSL_VALIDITY') else get_env_bool('CHECK_SSL_VALIDITY', True)
    cookies_file = get_env('WGET_COOKIES_FILE') or get_env('COOKIES_FILE', '')
    wget_args = get_env_array('WGET_ARGS', [])
    wget_args_extra = get_env_array('WGET_ARGS_EXTRA', [])

    # Feature toggles
    warc_enabled = get_env_bool('WGET_WARC_ENABLED', True)

    # Build wget command (later options take precedence)
    cmd = [
        binary,
        *wget_args,
        f'--timeout={timeout}',
    ]

    if user_agent:
        cmd.append(f'--user-agent={user_agent}')

    if warc_enabled:
        warc_dir = Path('warc')
        warc_dir.mkdir(exist_ok=True)
        warc_path = warc_dir / str(int(datetime.now(timezone.utc).timestamp()))
        cmd.append(f'--warc-file={warc_path}')
    else:
        cmd.append('--timestamping')

    if cookies_file and Path(cookies_file).is_file():
        cmd.extend(['--load-cookies', cookies_file])

    if not check_ssl:
        cmd.extend(['--no-check-certificate', '--no-hsts'])

    if wget_args_extra:
        cmd.extend(wget_args_extra)

    cmd.append(url)

    # Run wget
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout * 2,  # Allow extra time for large downloads
        )

        # Find downloaded files
        downloaded_files = [
            f for f in Path('.').rglob('*')
            if f.is_file() and f.name != '.gitkeep' and not str(f).startswith('warc/')
        ]

        if not downloaded_files:
            if result.returncode != 0:
                return False, None, f'wget failed (exit={result.returncode})'
            return False, None, 'No files downloaded'

        # Find main HTML file
        html_files = [
            f for f in downloaded_files
            if re.search(r'\.[Ss]?[Hh][Tt][Mm][Ll]?$', str(f))
        ]
        output_path = str(html_files[0]) if html_files else str(downloaded_files[0])

        # Parse download stats from wget output
        stderr_text = (result.stderr or '')
        output_tail = stderr_text.strip().split('\n')[-3:] if stderr_text else []
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

    output = None
    status = 'failed'
    error = ''

    try:
        # Check if wget is enabled
        if not get_env_bool('WGET_ENABLED', True):
            print('Skipping wget (WGET_ENABLED=False)', file=sys.stderr)
            # Temporary failure (config disabled) - NO JSONL emission
            sys.exit(0)

        # Check if staticfile extractor already handled this (permanent skip)
        if has_staticfile_output():
            print('Skipping wget - staticfile extractor already downloaded this', file=sys.stderr)
            print(json.dumps({'type': 'ArchiveResult', 'status': 'skipped', 'output_str': 'staticfile already exists'}))
            sys.exit(0)

        # Get binary from environment
        binary = get_env('WGET_BINARY', 'wget')

        # Run extraction
        success, output, error = save_wget(url, binary)

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
