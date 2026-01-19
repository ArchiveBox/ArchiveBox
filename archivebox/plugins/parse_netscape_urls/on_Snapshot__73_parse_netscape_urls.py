#!/usr/bin/env python3
"""
Parse Netscape bookmark HTML files and extract URLs.

This is a standalone extractor that can run without ArchiveBox.
It reads Netscape-format bookmark exports (produced by all major browsers).

Usage: ./on_Snapshot__53_parse_netscape_urls.py --url=<url>
Output: Appends discovered URLs to urls.jsonl in current directory

Examples:
    ./on_Snapshot__53_parse_netscape_urls.py --url=file:///path/to/bookmarks.html
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse

import rich_click as click

PLUGIN_NAME = 'parse_netscape_urls'
URLS_FILE = Path('urls.jsonl')

# Constants for timestamp epoch detection
UNIX_EPOCH = 0  # 1970-01-01 00:00:00 UTC
MAC_COCOA_EPOCH = 978307200  # 2001-01-01 00:00:00 UTC (Mac/Cocoa/NSDate epoch)

# Reasonable date range for bookmarks (to detect correct epoch/unit)
MIN_REASONABLE_YEAR = 1995  # Netscape Navigator era
MAX_REASONABLE_YEAR = 2035  # Far enough in future

# Regex pattern for Netscape bookmark format
# Example: <DT><A HREF="https://example.com/?q=1+2" ADD_DATE="1497562974" TAGS="tag1,tag2">example title</A>
# Make ADD_DATE optional and allow negative numbers
NETSCAPE_PATTERN = re.compile(
    r'<a\s+href="([^"]+)"(?:\s+add_date="([^"]*)")?(?:\s+[^>]*?tags="([^"]*)")?[^>]*>([^<]+)</a>',
    re.UNICODE | re.IGNORECASE
)


def parse_timestamp(timestamp_str: str) -> datetime | None:
    """
    Intelligently parse bookmark timestamp with auto-detection of format and epoch.

    Browsers use different timestamp formats:
    - Firefox: Unix epoch (1970) in seconds (10 digits): 1609459200
    - Safari: Mac/Cocoa epoch (2001) in seconds (9-10 digits): 631152000
    - Chrome: Unix epoch in microseconds (16 digits): 1609459200000000
    - Others: Unix epoch in milliseconds (13 digits): 1609459200000

    Strategy:
    1. Try parsing with different epoch + unit combinations
    2. Pick the one that yields a reasonable date (1995-2035)
    3. Prioritize more common formats (Unix seconds, then Mac seconds, etc.)
    """
    if not timestamp_str or timestamp_str == '':
        return None

    try:
        timestamp_num = float(timestamp_str)
    except (ValueError, TypeError):
        return None

    # Detect sign and work with absolute value
    is_negative = timestamp_num < 0
    abs_timestamp = abs(timestamp_num)

    # Determine number of digits to guess the unit
    if abs_timestamp == 0:
        num_digits = 1
    else:
        num_digits = len(str(int(abs_timestamp)))

    # Try different interpretations in order of likelihood
    candidates = []

    # Unix epoch seconds (10-11 digits) - Most common: Firefox, Chrome HTML export
    if 9 <= num_digits <= 11:
        try:
            dt = datetime.fromtimestamp(timestamp_num, tz=timezone.utc)
            if MIN_REASONABLE_YEAR <= dt.year <= MAX_REASONABLE_YEAR:
                candidates.append((dt, 'unix_seconds', 100))  # Highest priority
        except (ValueError, OSError, OverflowError):
            pass

    # Mac/Cocoa epoch seconds (9-10 digits) - Safari
    # Only consider if Unix seconds didn't work or gave unreasonable date
    if 8 <= num_digits <= 11:
        try:
            dt = datetime.fromtimestamp(timestamp_num + MAC_COCOA_EPOCH, tz=timezone.utc)
            if MIN_REASONABLE_YEAR <= dt.year <= MAX_REASONABLE_YEAR:
                candidates.append((dt, 'mac_seconds', 90))
        except (ValueError, OSError, OverflowError):
            pass

    # Unix epoch milliseconds (13 digits) - JavaScript exports
    if 12 <= num_digits <= 14:
        try:
            dt = datetime.fromtimestamp(timestamp_num / 1000, tz=timezone.utc)
            if MIN_REASONABLE_YEAR <= dt.year <= MAX_REASONABLE_YEAR:
                candidates.append((dt, 'unix_milliseconds', 95))
        except (ValueError, OSError, OverflowError):
            pass

    # Mac/Cocoa epoch milliseconds (12-13 digits) - Rare
    if 11 <= num_digits <= 14:
        try:
            dt = datetime.fromtimestamp((timestamp_num / 1000) + MAC_COCOA_EPOCH, tz=timezone.utc)
            if MIN_REASONABLE_YEAR <= dt.year <= MAX_REASONABLE_YEAR:
                candidates.append((dt, 'mac_milliseconds', 85))
        except (ValueError, OSError, OverflowError):
            pass

    # Unix epoch microseconds (16-17 digits) - Chrome WebKit timestamps
    if 15 <= num_digits <= 18:
        try:
            dt = datetime.fromtimestamp(timestamp_num / 1_000_000, tz=timezone.utc)
            if MIN_REASONABLE_YEAR <= dt.year <= MAX_REASONABLE_YEAR:
                candidates.append((dt, 'unix_microseconds', 98))
        except (ValueError, OSError, OverflowError):
            pass

    # Mac/Cocoa epoch microseconds (15-16 digits) - Very rare
    if 14 <= num_digits <= 18:
        try:
            dt = datetime.fromtimestamp((timestamp_num / 1_000_000) + MAC_COCOA_EPOCH, tz=timezone.utc)
            if MIN_REASONABLE_YEAR <= dt.year <= MAX_REASONABLE_YEAR:
                candidates.append((dt, 'mac_microseconds', 80))
        except (ValueError, OSError, OverflowError):
            pass

    # If no candidates found, return None
    if not candidates:
        return None

    # Sort by priority (highest first) and return best match
    candidates.sort(key=lambda x: x[2], reverse=True)
    best_dt, best_format, _ = candidates[0]

    return best_dt


def fetch_content(url: str) -> str:
    """Fetch content from a URL (supports file:// and https://)."""
    parsed = urlparse(url)

    if parsed.scheme == 'file':
        file_path = parsed.path
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    else:
        timeout = int(os.environ.get('TIMEOUT', '60'))
        user_agent = os.environ.get('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')

        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode('utf-8', errors='replace')


@click.command()
@click.option('--url', required=True, help='Netscape bookmark file URL to parse')
@click.option('--snapshot-id', required=False, help='Parent Snapshot UUID')
@click.option('--crawl-id', required=False, help='Crawl UUID')
@click.option('--depth', type=int, default=0, help='Current depth level')
def main(url: str, snapshot_id: str = None, crawl_id: str = None, depth: int = 0):
    """Parse Netscape bookmark HTML and extract URLs."""
    env_depth = os.environ.get('SNAPSHOT_DEPTH')
    if env_depth is not None:
        try:
            depth = int(env_depth)
        except Exception:
            pass
    crawl_id = crawl_id or os.environ.get('CRAWL_ID')

    try:
        content = fetch_content(url)
    except Exception as e:
        click.echo(f'Failed to fetch {url}: {e}', err=True)
        sys.exit(1)

    urls_found = []
    all_tags = set()

    for line in content.splitlines():
        match = NETSCAPE_PATTERN.search(line)
        if match:
            bookmark_url = match.group(1)
            timestamp_str = match.group(2)
            tags_str = match.group(3) or ''
            title = match.group(4).strip()

            entry = {
                'type': 'Snapshot',
                'url': unescape(bookmark_url),
                'plugin': PLUGIN_NAME,
                'depth': depth + 1,
            }
            if snapshot_id:
                entry['parent_snapshot_id'] = snapshot_id
            if crawl_id:
                entry['crawl_id'] = crawl_id
            if title:
                entry['title'] = unescape(title)
            if tags_str:
                entry['tags'] = tags_str
                # Collect unique tags
                for tag in tags_str.split(','):
                    tag = tag.strip()
                    if tag:
                        all_tags.add(tag)

            # Parse timestamp with intelligent format detection
            if timestamp_str:
                dt = parse_timestamp(timestamp_str)
                if dt:
                    entry['bookmarked_at'] = dt.isoformat()

            urls_found.append(entry)

    # Emit Tag records first (to stdout as JSONL)
    for tag_name in sorted(all_tags):
        print(json.dumps({
            'type': 'Tag',
            'name': tag_name,
        }))

    # Emit Snapshot records (to stdout as JSONL)
    for entry in urls_found:
        print(json.dumps(entry))

    # Write urls.jsonl to disk for crawl system
    URLS_FILE.write_text('\n'.join(json.dumps(r) for r in urls_found) + ('\n' if urls_found else ''))

    # Emit ArchiveResult record to mark completion
    status = 'succeeded' if urls_found else 'skipped'
    output_str = URLS_FILE.name
    ar_record = {
        'type': 'ArchiveResult',
        'status': status,
        'output_str': output_str,
    }
    print(json.dumps(ar_record))

    click.echo(output_str, err=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
