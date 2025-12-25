#!/usr/bin/env python3
"""
Submit a URL to archive.org for archiving.

Usage: on_Snapshot__archive_org.py --url=<url> --snapshot-id=<uuid>
Output: Writes archive.org.txt to $PWD with the archived URL

Environment variables:
    TIMEOUT: Timeout in seconds (default: 60)
    USER_AGENT: User agent string

Note: This extractor uses the 'requests' library which is bundled with ArchiveBox.
      It can run standalone if requests is installed: pip install requests
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import rich_click as click


# Extractor metadata
EXTRACTOR_NAME = 'archive_org'
OUTPUT_DIR = 'archive_org'
OUTPUT_FILE = 'archive.org.txt'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def submit_to_archive_org(url: str) -> tuple[bool, str | None, str]:
    """
    Submit URL to archive.org Wayback Machine.

    Returns: (success, output_path, error_message)
    """
    try:
        import requests
    except ImportError:
        return False, None, 'requests library not installed'

    timeout = get_env_int('TIMEOUT', 60)
    user_agent = get_env('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')

    submit_url = f'https://web.archive.org/save/{url}'

    try:
        response = requests.get(
            submit_url,
            timeout=timeout,
            headers={'User-Agent': user_agent},
            allow_redirects=True,
        )

        # Check for successful archive
        content_location = response.headers.get('Content-Location', '')
        x_archive_orig_url = response.headers.get('X-Archive-Orig-Url', '')

        # Build archive URL
        if content_location:
            archive_url = f'https://web.archive.org{content_location}'
            Path(OUTPUT_FILE).write_text(archive_url, encoding='utf-8')
            return True, OUTPUT_FILE, ''
        elif 'web.archive.org' in response.url:
            # We were redirected to an archive page
            Path(OUTPUT_FILE).write_text(response.url, encoding='utf-8')
            return True, OUTPUT_FILE, ''
        else:
            # Check for errors in response
            if 'RobotAccessControlException' in response.text:
                # Blocked by robots.txt - save submit URL for manual retry
                Path(OUTPUT_FILE).write_text(submit_url, encoding='utf-8')
                return True, OUTPUT_FILE, ''  # Consider this a soft success
            elif response.status_code >= 400:
                return False, None, f'HTTP {response.status_code}'
            else:
                # Save submit URL anyway
                Path(OUTPUT_FILE).write_text(submit_url, encoding='utf-8')
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

    start_ts = datetime.now(timezone.utc)
    output = None
    status = 'failed'
    error = ''

    try:
        # Run extraction
        success, output, error = submit_to_archive_org(url)
        status = 'succeeded' if success else 'failed'

        if success:
            archive_url = Path(output).read_text().strip()
            print(f'Archived at: {archive_url}')

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    # Print results
    end_ts = datetime.now(timezone.utc)
    duration = (end_ts - start_ts).total_seconds()

    print(f'START_TS={start_ts.isoformat()}')
    print(f'END_TS={end_ts.isoformat()}')
    print(f'DURATION={duration:.2f}')
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
        'output': output,
        'error': error or None,
    }
    print(f'RESULT_JSON={json.dumps(result_json)}')

    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
