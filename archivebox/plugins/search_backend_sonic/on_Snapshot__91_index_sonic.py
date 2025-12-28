#!/usr/bin/env python3
"""
Sonic search backend - indexes snapshot content in Sonic server.

This hook runs after all extractors and indexes text content in Sonic.
Only runs if SEARCH_BACKEND_ENGINE=sonic.

Usage: on_Snapshot__91_index_sonic.py --url=<url> --snapshot-id=<uuid>

Environment variables:
    SEARCH_BACKEND_ENGINE: Must be 'sonic' for this hook to run
    USE_INDEXING_BACKEND: Enable search indexing (default: true)
    SEARCH_BACKEND_HOST_NAME: Sonic server host (default: 127.0.0.1)
    SEARCH_BACKEND_PORT: Sonic server port (default: 1491)
    SEARCH_BACKEND_PASSWORD: Sonic server password (default: SecretPassword)
    SONIC_COLLECTION: Collection name (default: archivebox)
    SONIC_BUCKET: Bucket name (default: snapshots)
"""

import json
import os
import re
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'index_sonic'
OUTPUT_DIR = '.'

# Text file patterns to index
INDEXABLE_FILES = [
    ('readability', 'content.txt'),
    ('readability', 'content.html'),
    ('mercury', 'content.txt'),
    ('mercury', 'content.html'),
    ('htmltotext', 'output.txt'),
    ('singlefile', 'singlefile.html'),
    ('dom', 'output.html'),
    ('wget', '**/*.html'),
    ('wget', '**/*.htm'),
    ('title', 'title.txt'),
]


def get_env(name: str, default: str = '') -> str:
    return os.environ.get(name, default).strip()


def get_env_bool(name: str, default: bool = False) -> bool:
    val = get_env(name, '').lower()
    if val in ('true', '1', 'yes', 'on'):
        return True
    if val in ('false', '0', 'no', 'off'):
        return False
    return default


def get_env_int(name: str, default: int = 0) -> int:
    try:
        return int(get_env(name, str(default)))
    except ValueError:
        return default


def strip_html_tags(html: str) -> str:
    """Remove HTML tags, keeping text content."""
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = html.replace('&nbsp;', ' ').replace('&amp;', '&')
    html = html.replace('&lt;', '<').replace('&gt;', '>')
    html = html.replace('&quot;', '"')
    html = re.sub(r'\s+', ' ', html)
    return html.strip()


def find_indexable_content() -> list[tuple[str, str]]:
    """Find text content to index from extractor outputs."""
    results = []
    cwd = Path.cwd()

    for extractor, file_pattern in INDEXABLE_FILES:
        plugin_dir = cwd / extractor
        if not plugin_dir.exists():
            continue

        if '*' in file_pattern:
            matches = list(plugin_dir.glob(file_pattern))
        else:
            match = plugin_dir / file_pattern
            matches = [match] if match.exists() else []

        for match in matches:
            if match.is_file() and match.stat().st_size > 0:
                try:
                    content = match.read_text(encoding='utf-8', errors='ignore')
                    if content.strip():
                        if match.suffix in ('.html', '.htm'):
                            content = strip_html_tags(content)
                        results.append((f'{extractor}/{match.name}', content))
                except Exception:
                    continue

    return results


def get_sonic_config() -> dict:
    """Get Sonic connection configuration."""
    return {
        'host': get_env('SEARCH_BACKEND_HOST_NAME', '127.0.0.1'),
        'port': get_env_int('SEARCH_BACKEND_PORT', 1491),
        'password': get_env('SEARCH_BACKEND_PASSWORD', 'SecretPassword'),
        'collection': get_env('SONIC_COLLECTION', 'archivebox'),
        'bucket': get_env('SONIC_BUCKET', 'snapshots'),
    }


def index_in_sonic(snapshot_id: str, texts: list[str]) -> None:
    """Index texts in Sonic."""
    try:
        from sonic import IngestClient
    except ImportError:
        raise RuntimeError('sonic-client not installed. Run: pip install sonic-client')

    config = get_sonic_config()

    with IngestClient(config['host'], config['port'], config['password']) as ingest:
        # Flush existing content
        try:
            ingest.flush_object(config['collection'], config['bucket'], snapshot_id)
        except Exception:
            pass

        # Index new content in chunks (Sonic has size limits)
        content = ' '.join(texts)
        chunk_size = 10000
        for i in range(0, len(content), chunk_size):
            chunk = content[i:i + chunk_size]
            ingest.push(config['collection'], config['bucket'], snapshot_id, chunk)


@click.command()
@click.option('--url', required=True, help='URL that was archived')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Index snapshot content in Sonic."""

    output = None
    status = 'failed'
    error = ''
    indexed_sources = []

    try:
        # Check if this backend is enabled (permanent skips - don't retry)
        backend = get_env('SEARCH_BACKEND_ENGINE', 'sqlite')
        if backend != 'sonic':
            print(f'Skipping Sonic indexing (SEARCH_BACKEND_ENGINE={backend})', file=sys.stderr)
            sys.exit(0)  # Permanent skip - different backend selected
        if not get_env_bool('USE_INDEXING_BACKEND', True):
            print('Skipping indexing (USE_INDEXING_BACKEND=False)', file=sys.stderr)
            sys.exit(0)  # Permanent skip - indexing disabled
        else:
            contents = find_indexable_content()
            indexed_sources = [source for source, _ in contents]

            if not contents:
                status = 'skipped'
                print('No indexable content found', file=sys.stderr)
            else:
                texts = [content for _, content in contents]
                index_in_sonic(snapshot_id, texts)
                status = 'succeeded'
                output = OUTPUT_DIR

    except Exception as e:
        error = f'{type(e).__name__}: {e}'
        status = 'failed'

    if error:
        print(f'ERROR: {error}', file=sys.stderr)

    # Search indexing hooks don't emit ArchiveResult - they're utility hooks
    # Exit code indicates success/failure
    sys.exit(0 if status == 'succeeded' else 1)


if __name__ == '__main__':
    main()
