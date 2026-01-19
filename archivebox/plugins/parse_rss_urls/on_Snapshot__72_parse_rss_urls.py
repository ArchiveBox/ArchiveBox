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
from pathlib import Path
from datetime import datetime, timezone
from html import unescape
from time import mktime
from urllib.parse import urlparse

import rich_click as click

PLUGIN_NAME = 'parse_rss_urls'
URLS_FILE = Path('urls.jsonl')

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
@click.option('--snapshot-id', required=False, help='Parent Snapshot UUID')
@click.option('--crawl-id', required=False, help='Crawl UUID')
@click.option('--depth', type=int, default=0, help='Current depth level')
def main(url: str, snapshot_id: str = None, crawl_id: str = None, depth: int = 0):
    """Parse RSS/Atom feed and extract article URLs."""
    env_depth = os.environ.get('SNAPSHOT_DEPTH')
    if env_depth is not None:
        try:
            depth = int(env_depth)
        except Exception:
            pass
    crawl_id = crawl_id or os.environ.get('CRAWL_ID')

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

    urls_found = []
    all_tags = set()

    if not feed.entries:
        # No entries - will emit skipped status at end
        pass
    else:
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
                    # Collect unique tags
                    for tag in tags.split(','):
                        tag = tag.strip()
                        if tag:
                            all_tags.add(tag)
                except (AttributeError, TypeError):
                    pass

            entry = {
                'type': 'Snapshot',
                'url': unescape(item_url),
                'plugin': PLUGIN_NAME,
                'depth': depth + 1,
            }
            if snapshot_id:
                entry['parent_snapshot_id'] = snapshot_id
            if crawl_id:
                entry['crawl_id'] = crawl_id
            if title:
                entry['title'] = unescape(title)
            if bookmarked_at:
                entry['bookmarked_at'] = bookmarked_at
            if tags:
                entry['tags'] = tags
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
