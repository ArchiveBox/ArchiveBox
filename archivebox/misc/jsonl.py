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

Local filesystem paths and file:// URLs are intentionally not accepted here.
Pipe file contents through stdin instead of passing a path/URI as a crawl URL.
"""

__package__ = "archivebox.misc"

# Bootable: stdlib only. MUST NOT import archivebox.config, archivebox.core, or Django.
# Used by CLI commands at entry, before Django setup.

import sys
import json
from typing import Any, TextIO
from collections.abc import Iterable, Iterator


# Type constants for JSONL records
TYPE_SNAPSHOT = "Snapshot"
TYPE_ARCHIVERESULT = "ArchiveResult"
TYPE_TAG = "Tag"
TYPE_CRAWL = "Crawl"
TYPE_BINARYREQUEST = "BinaryRequest"
TYPE_BINARY = "Binary"
TYPE_PROCESS = "Process"
TYPE_MACHINE = "Machine"

VALID_TYPES = {
    TYPE_SNAPSHOT,
    TYPE_ARCHIVERESULT,
    TYPE_TAG,
    TYPE_CRAWL,
    TYPE_BINARYREQUEST,
    TYPE_BINARY,
    TYPE_PROCESS,
    TYPE_MACHINE,
}


def parse_line(line: str) -> dict[str, Any] | None:
    """
    Parse a single line of input as either JSONL or plain URL.

    Returns a dict with at minimum {'type': '...', 'url': '...'} or None if invalid.
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None

    # Try to parse as JSON first
    if line.startswith("{"):
        try:
            record = json.loads(line)
            # If it has a type, validate it
            if "type" in record and record["type"] not in VALID_TYPES:
                # Unknown type, treat as raw data
                pass
            # If it has url but no type, assume Snapshot
            if "url" in record and "type" not in record:
                record["type"] = TYPE_SNAPSHOT
            return record
        except json.JSONDecodeError:
            pass

    # Treat as plain URL if it looks like one
    if line.startswith("http://") or line.startswith("https://"):
        return {"type": TYPE_SNAPSHOT, "url": line}

    # Could be a snapshot ID (UUID with dashes or compact 32-char hex)
    if len(line) == 36 and line.count("-") == 4:
        return {"type": TYPE_SNAPSHOT, "id": line}
    if len(line) == 32:
        try:
            int(line, 16)
        except ValueError:
            pass
        else:
            return {"type": TYPE_SNAPSHOT, "id": line}

    # Unknown format, skip
    return None


def read_stdin(stream: TextIO | None = None) -> Iterator[dict[str, Any]]:
    """
    Read JSONL or plain URLs from stdin.

    Yields parsed records as dicts.
    Supports both JSONL format and plain URLs (one per line).
    """
    active_stream: TextIO = sys.stdin if stream is None else stream

    # Don't block if stdin is a tty with no input
    if active_stream.isatty():
        return

    for line in active_stream:
        record = parse_line(line)
        if record:
            yield record


def read_args_or_stdin(args: Iterable[str], stream: TextIO | None = None) -> Iterator[dict[str, Any]]:
    """
    Read from CLI arguments if provided, otherwise from stdin.

    Handles both URLs and JSONL from either source.
    Does not expand local file path arguments; pipe file contents via stdin.
    """
    if args:
        for arg in args:
            record = parse_line(arg)
            if record:
                yield record
    else:
        yield from read_stdin(stream)


def write_record(record: dict[str, Any], stream: TextIO | None = None) -> None:
    """
    Write a single JSONL record to stdout (or provided stream).
    """
    active_stream: TextIO = sys.stdout if stream is None else stream
    active_stream.write(json.dumps(record) + "\n")
    active_stream.flush()
