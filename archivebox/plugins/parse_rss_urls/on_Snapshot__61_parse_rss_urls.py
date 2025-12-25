#!/usr/bin/env python3
"""
Parse RSS/Atom feeds and extract URLs.

This is a standalone extractor that can run without ArchiveBox.
It reads feed content from a URL and extracts article URLs.

Usage: ./on_Snapshot__51_parse_rss_urls.py --url=<url>
Output: Appends discovered URLs to urls.jsonl in current directory

Examples:
    ./on_Snapshot__51_parse_rss_urls.py --url=https://example.com/feed.rss
    ./on_Snapshot__51_parse_rss_urls.py --url=file:///path/to/feed.xml
"""

import json
import os
import sys
from datetime import datetime, timezone
from html import unescape
from time import mktime
from urllib.parse import urlparse

import rich_click as click

EXTRACTOR_NAME = 'parse_rss_urls'

try:
    import feedparser
except ImportError:
    feedparser = None


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
@click.option('--url', required=True, help='RSS/Atom feed URL to parse')
@click.option('--snapshot-id', required=False, help='Snapshot UUID (unused but required by hook runner)')
def main(url: str, snapshot_id: str = None):
    """Parse RSS/Atom feed and extract article URLs."""

    if feedparser is None:
        click.echo('feedparser library not installed', err=True)
        sys.exit(1)

    try:
        content = fetch_content(url)
    except Exception as e:
        click.echo(f'Failed to fetch {url}: {e}', err=True)
        sys.exit(1)

    # Parse the feed
    feed = feedparser.parse(content)

    if not feed.entries:
        click.echo('No entries found in feed', err=True)
        sys.exit(1)

    urls_found = []
    for item in feed.entries:
        item_url = getattr(item, 'link', None)
        if not item_url:
            continue

        title = getattr(item, 'title', None)

        # Get bookmarked_at (published/updated date as ISO 8601)
        bookmarked_at = None
        if hasattr(item, 'published_parsed') and item.published_parsed:
            bookmarked_at = datetime.fromtimestamp(mktime(item.published_parsed), tz=timezone.utc).isoformat()
        elif hasattr(item, 'updated_parsed') and item.updated_parsed:
            bookmarked_at = datetime.fromtimestamp(mktime(item.updated_parsed), tz=timezone.utc).isoformat()

        # Get tags
        tags = ''
        if hasattr(item, 'tags') and item.tags:
            try:
                tags = ','.join(tag.term for tag in item.tags if hasattr(tag, 'term'))
            except (AttributeError, TypeError):
                pass

        entry = {
            'type': 'Snapshot',
            'url': unescape(item_url),
            'via_extractor': EXTRACTOR_NAME,
        }
        if title:
            entry['title'] = unescape(title)
        if bookmarked_at:
            entry['bookmarked_at'] = bookmarked_at
        if tags:
            entry['tags'] = tags
        urls_found.append(entry)

    if not urls_found:
        click.echo('No valid URLs found in feed entries', err=True)
        sys.exit(1)

    # Collect unique tags
    all_tags = set()
    for entry in urls_found:
        if entry.get('tags'):
            for tag in entry['tags'].split(','):
                tag = tag.strip()
                if tag:
                    all_tags.add(tag)

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
