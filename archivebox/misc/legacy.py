"""
Legacy archive import utilities.

These functions are used to import data from old ArchiveBox archive formats
(JSON indexes, archive directory structures) into the new database.

This is separate from the hooks-based parser system which handles importing
new URLs from bookmark files, RSS feeds, etc.
"""

__package__ = "archivebox.misc"

import os
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import TypedDict
from collections.abc import Iterator


class SnapshotDict(TypedDict, total=False):
    """
    Dictionary type representing a snapshot/link, compatible with Snapshot model fields.
    """

    url: str  # Required: the URL to archive
    timestamp: str  # Optional: unix timestamp string
    title: str  # Optional: page title
    tags: str  # Optional: comma-separated tags string
    sources: list[str]  # Optional: list of source file paths


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
        with open(index_path, encoding="utf-8") as f:
            data = json.load(f)

        links = data.get("links", [])
        for link in links:
            yield {
                "url": link.get("url", ""),
                "timestamp": link.get("timestamp", str(datetime.now(timezone.utc).timestamp())),
                "title": link.get("title"),
                "tags": link.get("tags", ""),
            }
    except (json.JSONDecodeError, KeyError, TypeError):
        return


def parse_json_links_details(out_dir: Path, config=None, **config_kwargs) -> Iterator[SnapshotDict]:
    """
    Parse links from individual snapshot index.jsonl/index.json files in archive directories.

    Walks through archive/*/index.jsonl and archive/*/index.json files to discover orphaned snapshots.
    Prefers index.jsonl (new format) over index.json (legacy format).
    """
    from archivebox.config import CONSTANTS
    from archivebox.config.common import get_config

    config = config or get_config(**config_kwargs)
    archive_dir = config.ARCHIVE_DIR if Path(out_dir).resolve() == CONSTANTS.DATA_DIR.resolve() else out_dir / CONSTANTS.ARCHIVE_DIR_NAME
    if not archive_dir.exists():
        return

    for entry in os.scandir(archive_dir):
        if not entry.is_dir():
            continue
        entry_path = Path(entry.path)
        if entry_path.name in CONSTANTS.RESERVED_ARCHIVE_DIR_NAMES or entry_path.name.startswith("."):
            continue
        try:
            ts_int = int(float(entry_path.name))
        except (TypeError, ValueError, OverflowError):
            continue
        if not 788918400 <= ts_int <= 2082758400:
            continue

        # Try index.jsonl first (new format)
        jsonl_file = entry_path / CONSTANTS.JSONL_INDEX_FILENAME
        json_file = entry_path / CONSTANTS.JSON_INDEX_FILENAME

        link = None

        if jsonl_file.exists():
            try:
                with open(jsonl_file, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("{"):
                            record = json.loads(line)
                            if record.get("type") == "Snapshot":
                                link = record
                                break
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        if link is None and json_file.exists():
            try:
                with open(json_file, encoding="utf-8") as f:
                    link = json.load(f)
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        if link:
            yield {
                "url": link.get("url", ""),
                "timestamp": link.get("timestamp", entry.name),
                "title": link.get("title"),
                "tags": link.get("tags", ""),
            }
