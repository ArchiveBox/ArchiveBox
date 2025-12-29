#!/usr/bin/env python3
"""
Parse plain text files and extract URLs.

This is a standalone extractor that can run without ArchiveBox.
It reads text content from a URL (file:// or https://) and extracts all URLs found.

Usage: ./on_Snapshot__52_parse_txt_urls.py --url=<url>
Output: Appends discovered URLs to urls.jsonl in current directory

Examples:
    ./on_Snapshot__52_parse_txt_urls.py --url=file:///path/to/urls.txt
    ./on_Snapshot__52_parse_txt_urls.py --url=https://example.com/urls.txt
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

import rich_click as click

PLUGIN_NAME = 'parse_txt_urls'

# URL regex from archivebox/misc/util.py
# https://mathiasbynens.be/demo/url-regex
URL_REGEX = re.compile(
    r'(?=('
    r'http[s]?://'                     # start matching from allowed schemes
    r'(?:[a-zA-Z]|[0-9]'               # followed by allowed alphanum characters
    r'|[-_$@.&+!*\(\),]'               #   or allowed symbols (keep hyphen first to match literal hyphen)
    r'|[^\u0000-\u007F])+'             #   or allowed unicode bytes
    r'[^\]\[<>"\'\s]+'                 # stop parsing at these symbols
    r'))',
    re.IGNORECASE | re.UNICODE,
)


def parens_are_matched(string: str, open_char='(', close_char=')') -> bool:
    """Check that all parentheses in a string are balanced and nested properly."""
    count = 0
    for c in string:
        if c == open_char:
            count += 1
        elif c == close_char:
            count -= 1
        if count < 0:
            return False
    return count == 0


def fix_url_from_markdown(url_str: str) -> str:
    """
    Cleanup a regex-parsed URL that may contain trailing parens from markdown syntax.
    Example: https://wiki.org/article_(Disambiguation).html?q=1).text -> https://wiki.org/article_(Disambiguation).html?q=1
    """
    trimmed_url = url_str

    # Cut off trailing characters until parens are balanced
    while not parens_are_matched(trimmed_url):
        trimmed_url = trimmed_url[:-1]

    # Verify trimmed URL is still valid
    if re.findall(URL_REGEX, trimmed_url):
        return trimmed_url

    return url_str


def find_all_urls(text: str):
    """Find all URLs in a text string."""
    for url in re.findall(URL_REGEX, text):
        yield fix_url_from_markdown(url)


def fetch_content(url: str) -> str:
    """Fetch content from a URL (supports file:// and https://)."""
    parsed = urlparse(url)

    if parsed.scheme == 'file':
        # Local file
        file_path = parsed.path
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    else:
        # Remote URL
        timeout = int(os.environ.get('TIMEOUT', '60'))
        user_agent = os.environ.get('USER_AGENT', 'Mozilla/5.0 (compatible; ArchiveBox/1.0)')

        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode('utf-8', errors='replace')


@click.command()
@click.option('--url', required=True, help='URL to parse (file:// or https://)')
@click.option('--snapshot-id', required=False, help='Snapshot UUID (unused but required by hook runner)')
def main(url: str, snapshot_id: str = None):
    """Parse plain text and extract URLs."""

    try:
        content = fetch_content(url)
    except Exception as e:
        click.echo(f'Failed to fetch {url}: {e}', err=True)
        sys.exit(1)

    urls_found = set()
    for found_url in find_all_urls(content):
        cleaned_url = unescape(found_url)
        # Skip the source URL itself
        if cleaned_url != url:
            urls_found.add(cleaned_url)

    # Emit Snapshot records to stdout (JSONL)
    for found_url in sorted(urls_found):
        record = {
            'type': 'Snapshot',
            'url': found_url,
            'plugin': PLUGIN_NAME,
        }
        if snapshot_id:
            record['parent_snapshot_id'] = snapshot_id
        print(json.dumps(record))

    # Emit ArchiveResult record to mark completion
    status = 'succeeded' if urls_found else 'skipped'
    output_str = f'Found {len(urls_found)} URLs' if urls_found else 'No URLs found'
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
