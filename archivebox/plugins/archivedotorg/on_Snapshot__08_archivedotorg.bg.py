#!/usr/bin/env python3
"""
Submit a URL to archive.org for archiving.

Usage: on_Snapshot__archivedotorg.bg.py --url=<url> --snapshot-id=<uuid>
Output: Writes archive.org.txt to $PWD with the archived URL

Environment variables:
    ARCHIVEDOTORG_TIMEOUT: Timeout in seconds (default: 60)
    USER_AGENT: User agent string

    # Fallback to ARCHIVING_CONFIG values if ARCHIVEDOTORG_* not set:
    TIMEOUT: Fallback timeout

Note: This extractor uses the 'requests' library which is bundled with ArchiveBox.
      It can run standalone if requests is installed: pip install requests
"""

import json
import os
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'archivedotorg'
OUTPUT_DIR = '.'
OUTPUT_FILE = 'archive.org.txt'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def submit_to_archivedotorg(url: str) -> tuple[bool, str | None, str]:
    """
    Submit URL to archive.org Wayback Machine.

    Returns: (success, output_path, error_message)
    """
    def log(message: str) -> None:
        print(f'[archivedotorg] {message}', file=sys.stderr)

    try:
        import requests
    except ImportError:
        return False, None, 'requests library not installed'

    timeout = get_env_int('ARCHIVEDOTORG_TIMEOUT') or get_env_int('TIMEOUT', 60)
    user_agent = get_env('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')

    submit_url = f'https://web.archive.org/save/{url}'
    log(f'Submitting to Wayback Machine (timeout={timeout}s)')
    log(f'GET {submit_url}')

    try:
        response = requests.get(
            submit_url,
            timeout=timeout,
            headers={'User-Agent': user_agent},
            allow_redirects=True,
        )
        log(f'HTTP {response.status_code} final_url={response.url}')

        # Check for successful archive
        content_location = response.headers.get('Content-Location', '')
        x_archive_orig_url = response.headers.get('X-Archive-Orig-Url', '')
        if content_location:
            log(f'Content-Location: {content_location}')
        if x_archive_orig_url:
            log(f'X-Archive-Orig-Url: {x_archive_orig_url}')

        # Build archive URL
        if content_location:
            archive_url = f'https://web.archive.org{content_location}'
            Path(OUTPUT_FILE).write_text(archive_url, encoding='utf-8')
            log(f'Saved archive URL -> {archive_url}')
            return True, OUTPUT_FILE, ''
        elif 'web.archive.org' in response.url:
            # We were redirected to an archive page
            Path(OUTPUT_FILE).write_text(response.url, encoding='utf-8')
            log(f'Redirected to archive page -> {response.url}')
            return True, OUTPUT_FILE, ''
        else:
            # Check for errors in response
            if 'RobotAccessControlException' in response.text:
                # Blocked by robots.txt - save submit URL for manual retry
                Path(OUTPUT_FILE).write_text(submit_url, encoding='utf-8')
                log('Blocked by robots.txt, saved submit URL for manual retry')
                return True, OUTPUT_FILE, ''  # Consider this a soft success
            elif response.status_code >= 400:
                return False, None, f'HTTP {response.status_code}'
            else:
                # Save submit URL anyway
                Path(OUTPUT_FILE).write_text(submit_url, encoding='utf-8')
                log('No archive URL returned, saved submit URL for manual retry')
                return True, OUTPUT_FILE, ''

    except requests.Timeout:
        return False, None, f'Request timed out after {timeout} seconds'
    except requests.RequestException as e:
        return False, None, f'{type(e).__name__}: {e}'
    except Exception as e:
        return False, None, f'{type(e).__name__}: {e}'


@click.command()
@click.option('--url', required=True, help='URL to submit to archive.org')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Submit a URL to archive.org for archiving."""

    # Check if feature is enabled
    if get_env('ARCHIVEDOTORG_ENABLED', 'True').lower() in ('false', '0', 'no', 'off'):
        print('Skipping archive.org submission (ARCHIVEDOTORG_ENABLED=False)', file=sys.stderr)
        # Temporary failure (config disabled) - NO JSONL emission
        sys.exit(0)

    try:
        # Run extraction
        success, output, error = submit_to_archivedotorg(url)

        if success:
            # Success - emit ArchiveResult with output file
            result = {
                'type': 'ArchiveResult',
                'status': 'succeeded',
                'output_str': output or '',
            }
            print(json.dumps(result))
            sys.exit(0)
        else:
            # Transient error (network, timeout, HTTP error) - emit NO JSONL
            # System will retry later
            print(f'ERROR: {error}', file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        # Unexpected error - also transient, emit NO JSONL
        print(f'ERROR: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
