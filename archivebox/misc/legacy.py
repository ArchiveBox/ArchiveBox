"""
Legacy archive import utilities.

These functions are used to import data from old ArchiveBox archive formats
(JSON indexes, archive directory structures) into the new database.

This is separate from the hooks-based parser system which handles importing
new URLs from bookmark files, RSS feeds, etc.
"""

__package__ = 'archivebox.misc'

import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterator, TypedDict, List


class SnapshotDict(TypedDict, total=False):
    """
    Dictionary type representing a snapshot/link, compatible with Snapshot model fields.
    """
    url: str              # Required: the URL to archive
    timestamp: str        # Optional: unix timestamp string
    title: str            # Optional: page title
    tags: str             # Optional: comma-separated tags string
    sources: List[str]    # Optional: list of source file paths


def parse_json_main_index(out_dir: Path) -> Iterator[SnapshotDict]:
    """
    Parse links from the main JSON index file (archive/index.json).

    This is used to recover links from old archive formats.
    """
    from archivebox.config import CONSTANTS

    index_path = out_dir / CONSTANTS.JSON_INDEX_FILENAME
    if not index_path.exists():
        return

    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        links = data.get('links', [])
        for link in links:
            yield {
                'url': link.get('url', ''),
                'timestamp': link.get('timestamp', str(datetime.now(timezone.utc).timestamp())),
                'title': link.get('title'),
                'tags': link.get('tags', ''),
            }
    except (json.JSONDecodeError, KeyError, TypeError):
        return


def parse_json_links_details(out_dir: Path) -> Iterator[SnapshotDict]:
    """
    Parse links from individual snapshot index.json files in archive directories.

    Walks through archive/*/index.json files to discover orphaned snapshots.
    """
    from archivebox.config import CONSTANTS

    archive_dir = out_dir / CONSTANTS.ARCHIVE_DIR_NAME
    if not archive_dir.exists():
        return

    for entry in os.scandir(archive_dir):
        if not entry.is_dir():
            continue

        index_file = Path(entry.path) / 'index.json'
        if not index_file.exists():
            continue

        try:
            with open(index_file, 'r', encoding='utf-8') as f:
                link = json.load(f)

            yield {
                'url': link.get('url', ''),
                'timestamp': link.get('timestamp', entry.name),
                'title': link.get('title'),
                'tags': link.get('tags', ''),
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
