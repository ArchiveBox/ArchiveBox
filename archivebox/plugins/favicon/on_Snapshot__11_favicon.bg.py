#!/usr/bin/env python3
"""
Extract favicon from a URL.

Usage: on_Snapshot__favicon.bg.py --url=<url> --snapshot-id=<uuid>
Output: Writes favicon.ico to $PWD

Environment variables:
    FAVICON_TIMEOUT: Timeout in seconds (default: 30)
    USER_AGENT: User agent string

    # Fallback to ARCHIVING_CONFIG values if FAVICON_* not set:
    TIMEOUT: Fallback timeout

Note: This extractor uses the 'requests' library which is bundled with ArchiveBox.
      It can run standalone if requests is installed: pip install requests
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'favicon'
OUTPUT_DIR = '.'
OUTPUT_FILE = 'favicon.ico'


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def get_favicon(url: str) -> tuple[bool, str | None, str]:
    """
    Fetch favicon from URL.

    Returns: (success, output_path, error_message)
    """
    try:
        import requests
    except ImportError:
        return False, None, 'requests library not installed'

    timeout = get_env_int('FAVICON_TIMEOUT') or get_env_int('TIMEOUT', 30)
    user_agent = get_env('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')
    headers = {'User-Agent': user_agent}

    # Build list of possible favicon URLs
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    favicon_urls = [
        urljoin(base_url, '/favicon.ico'),
        urljoin(base_url, '/favicon.png'),
        urljoin(base_url, '/apple-touch-icon.png'),
    ]

    # Try to extract favicon URL from HTML link tags
    try:
        response = requests.get(url, timeout=timeout, headers=headers)
        if response.ok:
            # Look for <link rel="icon" href="...">
            for match in re.finditer(
                r'<link[^>]+rel=["\'](?:shortcut )?icon["\'][^>]+href=["\']([^"\']+)["\']',
                response.text,
                re.I
            ):
                favicon_urls.insert(0, urljoin(url, match.group(1)))

            # Also check reverse order: href before rel
            for match in re.finditer(
                r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\'](?:shortcut )?icon["\']',
                response.text,
                re.I
            ):
                favicon_urls.insert(0, urljoin(url, match.group(1)))
    except Exception:
        pass  # Continue with default favicon URLs

    # Try each URL until we find one that works
    for favicon_url in favicon_urls:
        try:
            response = requests.get(favicon_url, timeout=15, headers=headers)
            if response.ok and len(response.content) > 0:
                Path(OUTPUT_FILE).write_bytes(response.content)
                return True, OUTPUT_FILE, ''
        except Exception:
            continue

    # Try Google's favicon service as fallback
    try:
        google_url = f'https://www.google.com/s2/favicons?domain={parsed.netloc}'
        response = requests.get(google_url, timeout=15, headers=headers)
        if response.ok and len(response.content) > 0:
            Path(OUTPUT_FILE).write_bytes(response.content)
            return True, OUTPUT_FILE, ''
    except Exception:
        pass

    return False, None, 'No favicon found'


@click.command()
@click.option('--url', required=True, help='URL to extract favicon from')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Extract favicon from a URL."""

    output = None
    status = 'failed'
    error = ''

    try:
        # Run extraction
        success, output, error = get_favicon(url)
        if success:
            status = 'succeeded'
        elif error == 'No favicon found':
            status = 'skipped'
        else:
            status = 'failed'

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

    sys.exit(0 if status in ('succeeded', 'skipped') else 1)


if __name__ == '__main__':
    main()
