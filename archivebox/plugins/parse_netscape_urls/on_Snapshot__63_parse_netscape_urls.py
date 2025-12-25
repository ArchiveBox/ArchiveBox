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
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlparse

import rich_click as click

EXTRACTOR_NAME = 'parse_netscape_urls'

# Regex pattern for Netscape bookmark format
# Example: <DT><A HREF="https://example.com/?q=1+2" ADD_DATE="1497562974" TAGS="tag1,tag2">example title</A>
NETSCAPE_PATTERN = re.compile(
    r'<a\s+href="([^"]+)"\s+add_date="(\d+)"(?:\s+[^>]*?tags="([^"]*)")?[^>]*>([^<]+)</a>',
    re.UNICODE | re.IGNORECASE
)


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
@click.option('--snapshot-id', required=False, help='Snapshot UUID (unused but required by hook runner)')
def main(url: str, snapshot_id: str = None):
    """Parse Netscape bookmark HTML and extract URLs."""

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
            tags_str = match.group(3) or ''
            title = match.group(4).strip()

            entry = {
                'type': 'Snapshot',
                'url': unescape(bookmark_url),
                'via_extractor': EXTRACTOR_NAME,
            }
            if title:
                entry['title'] = unescape(title)
            if tags_str:
                entry['tags'] = tags_str
                # Collect unique tags
                for tag in tags_str.split(','):
                    tag = tag.strip()
                    if tag:
                        all_tags.add(tag)
            try:
                # Convert unix timestamp to ISO 8601
                entry['bookmarked_at'] = datetime.fromtimestamp(float(match.group(2)), tz=timezone.utc).isoformat()
            except (ValueError, OSError):
                pass
            urls_found.append(entry)

    if not urls_found:
        click.echo('No bookmarks found', err=True)
        sys.exit(1)

    # Write urls.jsonl
    with open('urls.jsonl', 'w') as f:
        # Write Tag records first
        for tag_name in sorted(all_tags):
            f.write(json.dumps({
                'type': 'Tag',
                'name': tag_name,
            }) + '\n')
        # Write Snapshot records
        for entry in urls_found:
            f.write(json.dumps(entry) + '\n')

    click.echo(f'Found {len(urls_found)} URLs, {len(all_tags)} tags')
    sys.exit(0)


if __name__ == '__main__':
    main()
