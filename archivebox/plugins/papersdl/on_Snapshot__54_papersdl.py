#!/usr/bin/env python3
"""
Download scientific papers from a URL using papers-dl.

Usage: on_Snapshot__papersdl.py --url=<url> --snapshot-id=<uuid>
Output: Downloads paper PDFs to $PWD/

Environment variables:
    PAPERSDL_BINARY: Path to papers-dl binary
    PAPERSDL_TIMEOUT: Timeout in seconds (default: 300 for paper downloads)
    PAPERSDL_EXTRA_ARGS: Extra arguments for papers-dl (space-separated)

    # papers-dl feature toggles
    SAVE_PAPERSDL: Enable papers-dl paper extraction (default: True)

    # Fallback to ARCHIVING_CONFIG values if PAPERSDL_* not set:
    TIMEOUT: Fallback timeout
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'papersdl'
BIN_NAME = 'papers-dl'
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


def extract_doi_from_url(url: str) -> str | None:
    """Extract DOI from common paper URLs."""
    # Match DOI pattern in URL
    doi_pattern = r'10\.\d{4,}/[^\s]+'
    match = re.search(doi_pattern, url)
    if match:
        return match.group(0)
    return None


def save_paper(url: str, binary: str) -> tuple[bool, str | None, str]:
    """
    Download paper using papers-dl.

    Returns: (success, output_path, error_message)
    """
    # Get config from env
    timeout = get_env_int('PAPERSDL_TIMEOUT') or get_env_int('TIMEOUT', 300)
    extra_args = get_env('PAPERSDL_EXTRA_ARGS', '')

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    # Try to extract DOI from URL
    doi = extract_doi_from_url(url)
    if not doi:
        # If no DOI found, papers-dl might handle the URL directly
        identifier = url
    else:
        identifier = doi

    # Build command - papers-dl fetch <identifier> -o <output_dir>
    cmd = [binary, 'fetch', identifier, '-o', str(output_dir)]

    if extra_args:
        cmd.extend(extra_args.split())

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)

        # Check if any PDF files were downloaded
        pdf_files = list(output_dir.glob('*.pdf'))

        if pdf_files:
            # Return first PDF file
            return True, str(pdf_files[0]), ''
        else:
            stderr = result.stderr
            stdout = result.stdout

            # These are NOT errors - page simply has no downloadable paper
            stderr_lower = stderr.lower()
            stdout_lower = stdout.lower()
            if 'not found' in stderr_lower or 'not found' in stdout_lower:
                return True, None, ''  # Paper not available - success, no output
            if 'no results' in stderr_lower or 'no results' in stdout_lower:
                return True, None, ''  # No paper found - success, no output
            if result.returncode == 0:
                return True, None, ''  # papers-dl exited cleanly, just no paper - success

            # These ARE errors - something went wrong
            if '404' in stderr or '404' in stdout:
                return False, None, '404 Not Found'
            if '403' in stderr or '403' in stdout:
                return False, None, '403 Forbidden'

            return False, None, f'papers-dl error: {stderr[:200] or stdout[:200]}'

    except subprocess.TimeoutExpired:
        return False, None, f'Timed out after {timeout} seconds'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to download paper from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Download scientific paper from a URL using papers-dl."""

    output = None
    status = 'failed'
    error = ''

    try:
        # Check if papers-dl is enabled
        if not get_env_bool('SAVE_PAPERSDL', True):
            print('Skipping papers-dl (SAVE_PAPERSDL=False)', file=sys.stderr)
            # Feature disabled - no ArchiveResult, just exit
            sys.exit(0)

        # Get binary from environment
        binary = get_env('PAPERSDL_BINARY', 'papers-dl')

        # Run extraction
        success, output, error = save_paper(url, binary)
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
