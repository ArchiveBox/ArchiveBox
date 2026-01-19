#!/usr/bin/env python3
"""
Download scientific papers from a URL using papers-dl.

Usage: on_Snapshot__papersdl.py --url=<url> --snapshot-id=<uuid>
Output: Downloads paper PDFs to $PWD/

Environment variables:
    PAPERSDL_BINARY: Path to papers-dl binary
    PAPERSDL_TIMEOUT: Timeout in seconds (default: 300 for paper downloads)
    PAPERSDL_ARGS: Default papers-dl arguments (JSON array, default: ["fetch"])
    PAPERSDL_ARGS_EXTRA: Extra arguments to append (JSON array)

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
import threading
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'papersdl'
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
    timeout = get_env_int('TIMEOUT', 300)
    papersdl_args = get_env_array('PAPERSDL_ARGS', [])
    papersdl_args_extra = get_env_array('PAPERSDL_ARGS_EXTRA', [])

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)

    # Try to extract DOI from URL
    doi = extract_doi_from_url(url)
    if not doi:
        # If no DOI found, papers-dl might handle the URL directly
        identifier = url
    else:
        identifier = doi

    # Build command - papers-dl <args> <identifier> -o <output_dir>
    cmd = [binary, *papersdl_args, identifier, '-o', str(output_dir)]

    if papersdl_args_extra:
        cmd.extend(papersdl_args_extra)

    try:
        print(f'[papersdl] Starting download (timeout={timeout}s)', file=sys.stderr)
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

        # Check if any PDF files were downloaded
        pdf_files = list(output_dir.glob('*.pdf'))

        if pdf_files:
            # Return first PDF file
            return True, str(pdf_files[0]), ''
        else:
            stderr = combined_output
            stdout = combined_output

            # These are NOT errors - page simply has no downloadable paper
            stderr_lower = stderr.lower()
            stdout_lower = stdout.lower()
            if 'not found' in stderr_lower or 'not found' in stdout_lower:
                return True, None, ''  # Paper not available - success, no output
            if 'no results' in stderr_lower or 'no results' in stdout_lower:
                return True, None, ''  # No paper found - success, no output
            if process.returncode == 0:
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
        if not get_env_bool('PAPERSDL_ENABLED', True):
            print('Skipping papers-dl (PAPERSDL_ENABLED=False)', file=sys.stderr)
            # Temporary failure (config disabled) - NO JSONL emission
            sys.exit(0)

        # Get binary from environment
        binary = get_env('PAPERSDL_BINARY', 'papers-dl')

        # Run extraction
        success, output, error = save_paper(url, binary)

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
