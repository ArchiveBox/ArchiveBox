#!/usr/bin/env python3
"""
Parse HTML files and extract href URLs.

This is a standalone extractor that can run without ArchiveBox.
It reads HTML content and extracts all <a href="..."> URLs.

NOTE: If parse_dom_outlinks already ran (parse_dom_outlinks/urls.jsonl exists),
this extractor will skip since parse_dom_outlinks provides better coverage via Chrome.

Usage: ./on_Snapshot__60_parse_html_urls.py --url=<url>
Output: Appends discovered URLs to urls.jsonl in current directory

Examples:
    ./on_Snapshot__60_parse_html_urls.py --url=file:///path/to/page.html
    ./on_Snapshot__60_parse_html_urls.py --url=https://example.com/page.html
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import rich_click as click

PLUGIN_NAME = 'parse_html_urls'

# Check if parse_dom_outlinks extractor already ran (sibling plugin output dir)
DOM_OUTLINKS_URLS_FILE = Path('..') / 'parse_dom_outlinks' / 'urls.jsonl'
URLS_FILE = Path('urls.jsonl')


# URL regex from archivebox/misc/util.py
URL_REGEX = re.compile(
    r'(?=('
    r'http[s]?://'
    r'(?:[a-zA-Z]|[0-9]'
    r'|[-_$@.&+!*\(\),]'
    r'|[^\u0000-\u007F])+'
    r'[^\]\[<>"\'\s]+'
    r'))',
    re.IGNORECASE | re.UNICODE,
)


class HrefParser(HTMLParser):
    """Extract href attributes from anchor tags."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr, value in attrs:
                if attr == 'href' and value:
                    self.urls.append(value)


def did_urljoin_misbehave(root_url: str, relative_path: str, final_url: str) -> bool:
    """Check if urljoin incorrectly stripped // from sub-URLs."""
    relative_path = relative_path.lower()
    if relative_path.startswith('http://') or relative_path.startswith('https://'):
        relative_path = relative_path.split('://', 1)[-1]

    original_path_had_suburl = '://' in relative_path
    original_root_had_suburl = '://' in root_url[8:]
    final_joined_has_suburl = '://' in final_url[8:]

    return (original_root_had_suburl or original_path_had_suburl) and not final_joined_has_suburl


def fix_urljoin_bug(url: str, nesting_limit=5) -> str:
    """Fix broken sub-URLs where :// was changed to :/."""
    input_url = url
    for _ in range(nesting_limit):
        url = re.sub(
            r'(?P<root>.+?)'
            r'(?P<separator>[-=/_&+%$#@!*\(\\])'
            r'(?P<subscheme>[a-zA-Z0-9+_-]{1,32}?):/'
            r'(?P<suburl>[^/\\]+)',
            r'\1\2\3://\4',
            input_url,
            re.IGNORECASE | re.UNICODE,
        )
        if url == input_url:
            break
        input_url = url
    return url


def normalize_url(url: str, root_url: str = None) -> str:
    """Normalize a URL, resolving relative paths if root_url provided."""
    url = clean_url_candidate(url)
    if not root_url:
        return _normalize_trailing_slash(url)

    url_is_absolute = url.lower().startswith('http://') or url.lower().startswith('https://')

    if url_is_absolute:
        return url

    # Resolve relative URL
    resolved = urljoin(root_url, url)

    # Fix urljoin bug with sub-URLs
    if did_urljoin_misbehave(root_url, url, resolved):
        resolved = fix_urljoin_bug(resolved)

    return _normalize_trailing_slash(resolved)


def _normalize_trailing_slash(url: str) -> str:
    """Drop trailing slash for non-root paths when no query/fragment."""
    try:
        parsed = urlparse(url)
        path = parsed.path or ''
        if path != '/' and path.endswith('/') and not parsed.query and not parsed.fragment:
            path = path.rstrip('/')
            return urlunparse((parsed.scheme, parsed.netloc, path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        pass
    return url


def clean_url_candidate(url: str) -> str:
    """Strip obvious surrounding/trailing punctuation from extracted URLs."""
    cleaned = (url or '').strip()
    if not cleaned:
        return cleaned

    # Strip common wrappers
    cleaned = cleaned.strip(' \t\r\n')
    cleaned = cleaned.strip('"\''"'"'<>[]()')

    # Strip trailing punctuation and escape artifacts
    cleaned = cleaned.rstrip('.,;:!?)\\\'"')
    cleaned = cleaned.rstrip('"')

    # Strip leading punctuation artifacts
    cleaned = cleaned.lstrip('("'\''<')

    return cleaned


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


def find_html_sources() -> list[str]:
    """Find HTML content from other extractors in the snapshot directory."""
    search_patterns = [
        'readability/content.html',
        '*_readability/content.html',
        'mercury/content.html',
        '*_mercury/content.html',
        'singlefile/singlefile.html',
        '*_singlefile/singlefile.html',
        'singlefile/*.html',
        '*_singlefile/*.html',
        'dom/output.html',
        '*_dom/output.html',
        'dom/*.html',
        '*_dom/*.html',
        'wget/**/*.html',
        '*_wget/**/*.html',
        'wget/**/*.htm',
        '*_wget/**/*.htm',
        'wget/**/*.htm*',
        '*_wget/**/*.htm*',
    ]

    sources: list[str] = []
    for base in (Path.cwd(), Path.cwd().parent):
        for pattern in search_patterns:
            for match in base.glob(pattern):
                if not match.is_file() or match.stat().st_size == 0:
                    continue
                try:
                    sources.append(match.read_text(errors='ignore'))
                except Exception:
                    continue

    return sources


@click.command()
@click.option('--url', required=True, help='HTML URL to parse')
@click.option('--snapshot-id', required=False, help='Parent Snapshot UUID')
@click.option('--crawl-id', required=False, help='Crawl UUID')
@click.option('--depth', type=int, default=0, help='Current depth level')
def main(url: str, snapshot_id: str = None, crawl_id: str = None, depth: int = 0):
    """Parse HTML and extract href URLs."""
    env_depth = os.environ.get('SNAPSHOT_DEPTH')
    if env_depth is not None:
        try:
            depth = int(env_depth)
        except Exception:
            pass
    crawl_id = crawl_id or os.environ.get('CRAWL_ID')

    # Skip only if parse_dom_outlinks already ran AND found URLs (it uses Chrome for better coverage)
    # If parse_dom_outlinks ran but found nothing, we still try static HTML parsing as fallback
    if DOM_OUTLINKS_URLS_FILE.exists() and DOM_OUTLINKS_URLS_FILE.stat().st_size > 0:
        click.echo(f'Skipping parse_html_urls - parse_dom_outlinks already extracted URLs')
        sys.exit(0)

    contents = find_html_sources()
    if not contents:
        try:
            contents = [fetch_content(url)]
        except Exception as e:
            click.echo(f'Failed to fetch {url}: {e}', err=True)
            sys.exit(1)

    urls_found = set()
    for content in contents:
        # Parse HTML for hrefs
        parser = HrefParser()
        try:
            parser.feed(content)
        except Exception:
            pass

        for href in parser.urls:
            normalized = normalize_url(href, root_url=url)
            if normalized.lower().startswith('http://') or normalized.lower().startswith('https://'):
                if normalized != url:
                    urls_found.add(unescape(normalized))

        # Also capture explicit URLs in the HTML text
        for match in URL_REGEX.findall(content):
            normalized = normalize_url(match, root_url=url)
            if normalized.lower().startswith('http://') or normalized.lower().startswith('https://'):
                if normalized != url:
                    urls_found.add(unescape(normalized))

    # Emit Snapshot records to stdout (JSONL) and urls.jsonl for crawl system
    records = []
    for found_url in sorted(urls_found):
        record = {
            'type': 'Snapshot',
            'url': found_url,
            'plugin': PLUGIN_NAME,
            'depth': depth + 1,
        }
        if snapshot_id:
            record['parent_snapshot_id'] = snapshot_id
        if crawl_id:
            record['crawl_id'] = crawl_id

        records.append(record)
        print(json.dumps(record))

    URLS_FILE.write_text('\n'.join(json.dumps(r) for r in records) + ('\n' if records else ''))

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
