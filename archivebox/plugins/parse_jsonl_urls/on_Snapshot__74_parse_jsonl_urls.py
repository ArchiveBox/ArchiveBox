#!/usr/bin/env python3
"""
Parse JSONL bookmark files and extract URLs.

This is a standalone extractor that can run without ArchiveBox.
It reads JSONL-format bookmark exports (one JSON object per line).

Usage: ./on_Snapshot__54_parse_jsonl_urls.py --url=<url>
Output: Appends discovered URLs to urls.jsonl in current directory

Expected JSONL format (one object per line):
    {"url": "https://example.com", "title": "Example", "tags": "tag1,tag2"}
    {"href": "https://other.com", "description": "Other Site"}

Supports various field names for URL, title, timestamp, and tags.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from html import unescape
from urllib.parse import urlparse

import rich_click as click

PLUGIN_NAME = 'parse_jsonl_urls'
URLS_FILE = Path('urls.jsonl')


def parse_bookmarked_at(link: dict) -> str | None:
    """Parse timestamp from various JSON formats, return ISO 8601."""
    from datetime import timezone

    def json_date(s: str) -> datetime:
        # Try ISO 8601 format
        return datetime.strptime(s.split(',', 1)[0], '%Y-%m-%dT%H:%M:%S%z')

    def to_iso(dt: datetime) -> str:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()

    try:
        if link.get('bookmarked_at'):
            # Already in our format, pass through
            return link['bookmarked_at']
        elif link.get('timestamp'):
            # Chrome/Firefox histories use microseconds
            return to_iso(datetime.fromtimestamp(link['timestamp'] / 1000000, tz=timezone.utc))
        elif link.get('time'):
            return to_iso(json_date(link['time']))
        elif link.get('created_at'):
            return to_iso(json_date(link['created_at']))
        elif link.get('created'):
            return to_iso(json_date(link['created']))
        elif link.get('date'):
            return to_iso(json_date(link['date']))
        elif link.get('bookmarked'):
            return to_iso(json_date(link['bookmarked']))
        elif link.get('saved'):
            return to_iso(json_date(link['saved']))
    except (ValueError, TypeError, KeyError):
        pass

    return None


def json_object_to_entry(link: dict) -> dict | None:
    """Convert a JSON bookmark object to a URL entry."""
    # Parse URL (try various field names)
    url = link.get('href') or link.get('url') or link.get('URL')
    if not url:
        return None

    entry = {
        'type': 'Snapshot',
        'url': unescape(url),
        'plugin': PLUGIN_NAME,
    }

    # Parse title
    title = None
    if link.get('title'):
        title = link['title'].strip()
    elif link.get('description'):
        title = link['description'].replace(' — Readability', '').strip()
    elif link.get('name'):
        title = link['name'].strip()
    if title:
        entry['title'] = unescape(title)

    # Parse bookmarked_at (ISO 8601)
    bookmarked_at = parse_bookmarked_at(link)
    if bookmarked_at:
        entry['bookmarked_at'] = bookmarked_at

    # Parse tags
    tags = link.get('tags', '')
    if isinstance(tags, list):
        tags = ','.join(tags)
    elif isinstance(tags, str) and ',' not in tags and tags:
        # If no comma, assume space-separated
        tags = tags.replace(' ', ',')
    if tags:
        entry['tags'] = unescape(tags)

    return entry


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
@click.option('--url', required=True, help='JSONL file URL to parse')
@click.option('--snapshot-id', required=False, help='Parent Snapshot UUID')
@click.option('--crawl-id', required=False, help='Crawl UUID')
@click.option('--depth', type=int, default=0, help='Current depth level')
def main(url: str, snapshot_id: str = None, crawl_id: str = None, depth: int = 0):
    """Parse JSONL bookmark file and extract URLs."""
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
        line = line.strip()
        if not line:
            continue

        try:
            link = json.loads(line)
            entry = json_object_to_entry(link)
            if entry:
                # Add crawl tracking metadata
                entry['depth'] = depth + 1
                if snapshot_id:
                    entry['parent_snapshot_id'] = snapshot_id
                if crawl_id:
                    entry['crawl_id'] = crawl_id

                # Collect tags
                if entry.get('tags'):
                    for tag in entry['tags'].split(','):
                        tag = tag.strip()
                        if tag:
                            all_tags.add(tag)

                urls_found.append(entry)
        except json.JSONDecodeError:
            # Skip malformed lines
            continue

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
