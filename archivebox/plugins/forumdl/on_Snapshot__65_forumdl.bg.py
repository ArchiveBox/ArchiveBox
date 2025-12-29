#!/usr/bin/env python3
"""
Download forum content from a URL using forum-dl.

Usage: on_Snapshot__forumdl.py --url=<url> --snapshot-id=<uuid>
Output: Downloads forum content to $PWD/

Environment variables:
    FORUMDL_BINARY: Path to forum-dl binary
    FORUMDL_TIMEOUT: Timeout in seconds (default: 3600 for large forums)
    FORUMDL_OUTPUT_FORMAT: Output format (default: jsonl)
    FORUMDL_TEXTIFY: Convert HTML to plaintext (default: False - keeps HTML)
    FORUMDL_CHECK_SSL_VALIDITY: Whether to check SSL certificates (default: True)
    FORUMDL_EXTRA_ARGS: Extra arguments for forum-dl (space-separated)

    # Forum-dl feature toggles
    SAVE_FORUMDL: Enable forum-dl forum extraction (default: True)

    # Fallback to ARCHIVING_CONFIG values if FORUMDL_* not set:
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
PLUGIN_NAME = 'forumdl'
BIN_NAME = 'forum-dl'
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



def save_forum(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Download forum using forum-dl.

    Returns: (success, output_path, error_message)
    """
    # Get config from env
    timeout = get_env_int('TIMEOUT', 3600)
    check_ssl = get_env_bool('CHECK_SSL_VALIDITY', True)
    textify = get_env_bool('FORUMDL_TEXTIFY', False)
    extra_args = get_env('FORUMDL_EXTRA_ARGS', '')
    output_format = get_env('FORUMDL_OUTPUT_FORMAT', 'jsonl')

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    # Build output filename based on format
    if output_format == 'warc':
        output_file = output_dir / 'forum.warc.gz'
    elif output_format == 'jsonl':
        output_file = output_dir / 'forum.jsonl'
    elif output_format == 'maildir':
        output_file = output_dir / 'forum'  # maildir is a directory
    elif output_format in ('mbox', 'mh', 'mmdf', 'babyl'):
        output_file = output_dir / f'forum.{output_format}'
    else:
        output_file = output_dir / f'forum.{output_format}'

    # Build command
    cmd = [binary, '-f', output_format, '-o', str(output_file)]

    if textify:
        cmd.append('--textify')

    if not check_ssl:
        cmd.append('--no-check-certificate')

    if extra_args:
        cmd.extend(extra_args.split())

    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)

        # Check if output file was created
        if output_file.exists() and output_file.stat().st_size > 0:
            return True, str(output_file), ''
        else:
            stderr = result.stderr

            # These are NOT errors - page simply has no downloadable forum content
            stderr_lower = stderr.lower()
            if 'unsupported url' in stderr_lower:
                return True, None, ''  # Not a forum site - success, no output
            if 'no content' in stderr_lower:
                return True, None, ''  # No forum found - success, no output
            if 'extractornotfounderror' in stderr_lower:
                return True, None, ''  # No forum extractor for this URL - success, no output
            if result.returncode == 0:
                return True, None, ''  # forum-dl exited cleanly, just no forum - success

            # These ARE errors - something went wrong
            if '404' in stderr:
                return False, None, '404 Not Found'
            if '403' in stderr:
                return False, None, '403 Forbidden'
            if 'unable to extract' in stderr_lower:
                return False, None, 'Unable to extract forum info'

            return False, None, f'forum-dl error: {stderr[:200]}'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to download forum from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download forum content from a URL using forum-dl."""

    output = None
    status = 'failed'
    error = ''

    try:
        # Check if forum-dl is enabled
        if not get_env_bool('FORUMDL_ENABLED', True):
            print('Skipping forum-dl (FORUMDL_ENABLED=False)', file=sys.stderr)
            # Temporary failure (config disabled) - NO JSONL emission
            sys.exit(0)

        # Get binary from environment
        binary = get_env('FORUMDL_BINARY', 'forum-dl')

        # Run extraction
        success, output, error = save_forum(url, binary)

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
