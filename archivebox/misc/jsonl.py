"""
JSONL (JSON Lines) utilities for ArchiveBox.

Provides functions for reading, writing, and processing typed JSONL records.
All CLI commands that accept stdin can read both plain URLs and typed JSONL.

CLI Pipeline:
    archivebox crawl URL    -> {"type": "Crawl", "id": "...", "urls": "...", ...}
    archivebox snapshot     -> {"type": "Snapshot", "id": "...", "url": "...", ...}
    archivebox extract      -> {"type": "ArchiveResult", "id": "...", "snapshot_id": "...", ...}

Typed JSONL Format:
    {"type": "Crawl", "id": "...", "urls": "...", "max_depth": 0, ...}
    {"type": "Snapshot", "id": "...", "url": "https://example.com", "title": "...", ...}
    {"type": "ArchiveResult", "id": "...", "snapshot_id": "...", "plugin": "...", ...}
    {"type": "Tag", "name": "..."}

Plain URLs (also supported):
    https://example.com
    https://foo.com
"""

__package__ = 'archivebox.misc'

import sys
import json
from typing import Iterator, Dict, Any, Optional, TextIO
from pathlib import Path


# Type constants for JSONL records
TYPE_SNAPSHOT = 'Snapshot'
TYPE_ARCHIVERESULT = 'ArchiveResult'
TYPE_TAG = 'Tag'
TYPE_CRAWL = 'Crawl'
TYPE_BINARY = 'Binary'
TYPE_PROCESS = 'Process'
TYPE_MACHINE = 'Machine'

VALID_TYPES = {TYPE_SNAPSHOT, TYPE_ARCHIVERESULT, TYPE_TAG, TYPE_CRAWL, TYPE_BINARY, TYPE_PROCESS, TYPE_MACHINE}


def parse_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single line of input as either JSONL or plain URL.

    Returns a dict with at minimum {'type': '...', 'url': '...'} or None if invalid.
    """
    line = line.strip()
    if not line or line.startswith('#'):
        return None

    # Try to parse as JSON first
    if line.startswith('{'):
        try:
            record = json.loads(line)
            # If it has a type, validate it
            if 'type' in record and record['type'] not in VALID_TYPES:
                # Unknown type, treat as raw data
                pass
            # If it has url but no type, assume Snapshot
            if 'url' in record and 'type' not in record:
                record['type'] = TYPE_SNAPSHOT
            return record
        except json.JSONDecodeError:
            pass

    # Treat as plain URL if it looks like one
    if line.startswith('http://') or line.startswith('https://') or line.startswith('file://'):
        return {'type': TYPE_SNAPSHOT, 'url': line}

    # Could be a snapshot ID (UUID)
    if len(line) == 36 and line.count('-') == 4:
        return {'type': TYPE_SNAPSHOT, 'id': line}

    # Unknown format, skip
    return None


def read_stdin(stream: Optional[TextIO] = None) -> Iterator[Dict[str, Any]]:
    """
    Read JSONL or plain URLs from stdin.

    Yields parsed records as dicts.
    Supports both JSONL format and plain URLs (one per line).
    """
    stream = stream or sys.stdin

    # Don't block if stdin is a tty with no input
    if stream.isatty():
        return

    for line in stream:
        record = parse_line(line)
        if record:
            yield record


def read_file(path: Path) -> Iterator[Dict[str, Any]]:
    """
    Read JSONL or plain URLs from a file.

    Yields parsed records as dicts.
    """
    with open(path, 'r') as f:
        for line in f:
            record = parse_line(line)
            if record:
                yield record


def read_args_or_stdin(args: tuple, stream: Optional[TextIO] = None) -> Iterator[Dict[str, Any]]:
    """
    Read from CLI arguments if provided, otherwise from stdin.

    Handles both URLs and JSONL from either source.
    """
    if args:
        for arg in args:
            # Check if it's a file path
            path = Path(arg)
            if path.exists() and path.is_file():
                yield from read_file(path)
            else:
                record = parse_line(arg)
                if record:
                    yield record
    else:
        yield from read_stdin(stream)


def write_record(record: Dict[str, Any], stream: Optional[TextIO] = None) -> None:
    """
    Write a single JSONL record to stdout (or provided stream).
    """
    stream = stream or sys.stdout
    stream.write(json.dumps(record) + '\n')
    stream.flush()


def write_records(records: Iterator[Dict[str, Any]], stream: Optional[TextIO] = None) -> int:
    """
    Write multiple JSONL records to stdout (or provided stream).

    Returns count of records written.
    """
    count = 0
    for record in records:
        write_record(record, stream)
        count += 1
    return count

