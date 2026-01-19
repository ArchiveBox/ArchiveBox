#!/usr/bin/env python3
"""
Convert HTML to plain text for search indexing.

This extractor reads HTML from other extractors (wget, singlefile, dom)
and converts it to plain text for full-text search.

Usage: on_Snapshot__htmltotext.py --url=<url> --snapshot-id=<uuid>
Output: Writes htmltotext.txt to $PWD

Environment variables:
    TIMEOUT: Timeout in seconds (not used, but kept for consistency)

Note: This extractor does not require any external binaries.
      It uses Python's built-in html.parser module.
"""

import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'htmltotext'
OUTPUT_DIR = '.'
OUTPUT_FILE = 'htmltotext.txt'


class HTMLTextExtractor(HTMLParser):
    """Extract text content from HTML, ignoring scripts/styles."""

    def __init__(self):
        super().__init__()
        self.result = []
        self.skip_tags = {'script', 'style', 'head', 'meta', 'link', 'noscript'}
        self.current_tag = None

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag.lower()

    def handle_endtag(self, tag):
        self.current_tag = None

    def handle_data(self, data):
        if self.current_tag not in self.skip_tags:
            text = data.strip()
            if text:
                self.result.append(text)

    def get_text(self) -> str:
        return ' '.join(self.result)


def html_to_text(html: str) -> str:
    """Convert HTML to plain text."""
    parser = HTMLTextExtractor()
    try:
        parser.feed(html)
        return parser.get_text()
    except Exception:
        # Fallback: strip HTML tags with regex
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


def find_html_source() -> str | None:
    """Find HTML content from other extractors in the snapshot directory."""
    # Hooks run in snapshot_dir, sibling extractor outputs are in subdirectories
    search_patterns = [
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
    ]

    for base in (Path.cwd(), Path.cwd().parent):
        for pattern in search_patterns:
            matches = list(base.glob(pattern))
            for match in matches:
                if match.is_file() and match.stat().st_size > 0:
                    try:
                        return match.read_text(errors='ignore')
                    except Exception:
                        continue

    return None


def extract_htmltotext(url: str) -> tuple[bool, str | None, str]:
    """
    Extract plain text from HTML sources.

    Returns: (success, output_path, error_message)
    """
    # Find HTML source from other extractors
    html_content = find_html_source()
    if not html_content:
        return False, None, 'No HTML source found (run singlefile, dom, or wget first)'

    # Convert HTML to text
    text = html_to_text(html_content)

    if not text or len(text) < 10:
        return False, None, 'No meaningful text extracted from HTML'

    # Output directory is current directory (hook already runs in output dir)
    output_dir = Path(OUTPUT_DIR)
    output_path = output_dir / OUTPUT_FILE
    output_path.write_text(text, encoding='utf-8')

    return True, str(output_path), ''


@click.command()
@click.option('--url', required=True, help='URL that was archived')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Convert HTML to plain text for search indexing."""

    try:
        # Run extraction
        success, output, error = extract_htmltotext(url)

        if success:
            # Success - emit ArchiveResult
            result = {
                'type': 'ArchiveResult',
                'status': 'succeeded',
                'output_str': output or ''
            }
            print(json.dumps(result))
            sys.exit(0)
        else:
            # Transient error - emit NO JSONL
            print(f'ERROR: {error}', file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        # Transient error - emit NO JSONL
        print(f'ERROR: {type(e).__name__}: {e}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
