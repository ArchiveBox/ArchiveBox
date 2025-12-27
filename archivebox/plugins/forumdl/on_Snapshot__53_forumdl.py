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
import shutil
import subprocess
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'forumdl'
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


def find_forumdl() -> str | None:
    """Find forum-dl binary."""
    forumdl = get_env('FORUMDL_BINARY')
    if forumdl and os.path.isfile(forumdl):
        return forumdl

    binary = shutil.which('forum-dl')
    if binary:
        return binary

    return None


def get_version(binary: str) -> str:
    """Get forum-dl version."""
    try:
        result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=10)
        return result.stdout.strip()[:64]
    except Exception:
        return ''


def save_forum(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Download forum using forum-dl.

    Returns: (success, output_path, error_message)
    """
    # Get config from env
    timeout = get_env_int('FORUMDL_TIMEOUT') or get_env_int('TIMEOUT', 3600)
    check_ssl = get_env_bool('FORUMDL_CHECK_SSL_VALIDITY', get_env_bool('CHECK_SSL_VALIDITY', True))
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

    version = ''
    output = None
    status = 'failed'
    error = ''
    binary = None
    cmd_str = ''

    try:
        # Check if forum-dl is enabled
        if not get_env_bool('SAVE_FORUMDL', True):
            print('Skipping forum-dl (SAVE_FORUMDL=False)')
            status = 'skipped'
            print(f'STATUS={status}')
            print(f'RESULT_JSON={json.dumps({"extractor": EXTRACTOR_NAME, "status": status, "url": url, "snapshot_id": snapshot_id})}')
            sys.exit(0)

        # Find binary
        binary = find_forumdl()
        if not binary:
            print(f'ERROR: {BIN_NAME} binary not found', file=sys.stderr)
            print(f'DEPENDENCY_NEEDED={BIN_NAME}', file=sys.stderr)
            print(f'BIN_PROVIDERS={BIN_PROVIDERS}', file=sys.stderr)
            print(f'INSTALL_HINT=pip install forum-dl', file=sys.stderr)
            sys.exit(1)

        version = get_version(binary)
        cmd_str = f'{binary} {url}'

        # Run extraction
        success, output, error = save_forum(url, binary)
        status = 'succeeded' if success else 'failed'

        if success:
            if output:
                output_path = Path(output)
                file_size = output_path.stat().st_size
                print(f'forum-dl completed: {output_path.name} ({file_size} bytes)')
            else:
                print(f'forum-dl completed: no forum content found on page (this is normal)')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    # Print results
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
        'cmd_version': version,
        'output': output,
        'error': error or None,
    }
    print(f'RESULT_JSON={json.dumps(result_json)}')

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
