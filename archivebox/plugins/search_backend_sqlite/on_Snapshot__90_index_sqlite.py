#!/usr/bin/env python3
"""
SQLite FTS5 search backend - indexes snapshot content for full-text search.

This hook runs after all extractors and indexes text content in SQLite FTS5.
Only runs if SEARCH_BACKEND_ENGINE=sqlite.

Usage: on_Snapshot__90_index_sqlite.py --url=<url> --snapshot-id=<uuid>

Environment variables:
    SEARCH_BACKEND_ENGINE: Must be 'sqlite' for this hook to run
    USE_INDEXING_BACKEND: Enable search indexing (default: true)
    SQLITEFTS_DB: Database filename (default: search.sqlite3)
    FTS_TOKENIZERS: FTS5 tokenizer config (default: porter unicode61 remove_diacritics 2)
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import rich_click as click


# Extractor metadata
PLUGIN_NAME = 'index_sqlite'
OUTPUT_DIR = '.'

# Text file patterns to index, in priority order
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


def get_db_path() -> Path:
    """Get path to the search index database."""
    data_dir = get_env('DATA_DIR', str(Path.cwd().parent.parent))
    db_name = get_env('SQLITEFTS_DB', 'search.sqlite3')
    return Path(data_dir) / db_name


def index_in_sqlite(snapshot_id: str, texts: list[str]) -> None:
    """Index texts in SQLite FTS5."""
    db_path = get_db_path()
    tokenizers = get_env('FTS_TOKENIZERS', 'porter unicode61 remove_diacritics 2')
    conn = sqlite3.connect(str(db_path))

    try:
        # Create FTS5 table if needed
        conn.execute(f'''
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index
            USING fts5(snapshot_id, content, tokenize='{tokenizers}')
        ''')

        # Remove existing entries
        conn.execute('DELETE FROM search_index WHERE snapshot_id = ?', (snapshot_id,))

        # Insert new content
        content = '\n\n'.join(texts)
        conn.execute(
            'INSERT INTO search_index (snapshot_id, content) VALUES (?, ?)',
            (snapshot_id, content)
        )
        conn.commit()
    finally:
        conn.close()


@click.command()
@click.option('--url', required=True, help='URL that was archived')
@click.option('--snapshot-id', required=True, help='Snapshot UUID')
def main(url: str, snapshot_id: str):
    """Index snapshot content in SQLite FTS5."""

    output = None
    status = 'failed'
    error = ''
    indexed_sources = []

    try:
        # Check if this backend is enabled (permanent skips - don't retry)
        backend = get_env('SEARCH_BACKEND_ENGINE', 'sqlite')
        if backend != 'sqlite':
            print(f'Skipping SQLite indexing (SEARCH_BACKEND_ENGINE={backend})', file=sys.stderr)
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
                index_in_sqlite(snapshot_id, texts)
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
