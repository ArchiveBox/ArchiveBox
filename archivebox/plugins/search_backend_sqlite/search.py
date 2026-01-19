"""
SQLite FTS5 search backend - search and flush operations.

This module provides the search interface for the SQLite FTS backend.

Environment variables:
    SQLITEFTS_DB: Database filename (default: search.sqlite3)
    FTS_SEPARATE_DATABASE: Use separate database file (default: true)
    FTS_TOKENIZERS: FTS5 tokenizer config (default: porter unicode61 remove_diacritics 2)
"""

import os
import sqlite3
from pathlib import Path
from typing import List, Iterable


# Config with old var names for backwards compatibility
SQLITEFTS_DB = os.environ.get('SQLITEFTS_DB', 'search.sqlite3').strip()
FTS_SEPARATE_DATABASE = os.environ.get('FTS_SEPARATE_DATABASE', 'true').lower() in ('true', '1', 'yes')
FTS_TOKENIZERS = os.environ.get('FTS_TOKENIZERS', 'porter unicode61 remove_diacritics 2').strip()


def _get_data_dir() -> Path:
    data_dir = os.environ.get('DATA_DIR', '').strip()
    if data_dir:
        return Path(data_dir)
    return Path.cwd() / 'data'


def get_db_path() -> Path:
    """Get path to the search index database."""
    return _get_data_dir() / SQLITEFTS_DB


def search(query: str) -> List[str]:
    """Search for snapshots matching the query."""
    db_path = get_db_path()
    if not db_path.exists():
        return []

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            'SELECT DISTINCT snapshot_id FROM search_index WHERE search_index MATCH ?',
            (query,)
        )
        return [row[0] for row in cursor.fetchall()]
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        return []
    finally:
        conn.close()


def flush(snapshot_ids: Iterable[str]) -> None:
    """Remove snapshots from the index."""
    db_path = get_db_path()
    if not db_path.exists():
        return

    conn = sqlite3.connect(str(db_path))
    try:
        for snapshot_id in snapshot_ids:
            conn.execute('DELETE FROM search_index WHERE snapshot_id = ?', (snapshot_id,))
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Table doesn't exist
    finally:
        conn.close()
