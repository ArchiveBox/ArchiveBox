"""
JSONL (JSON Lines) utilities for ArchiveBox.

Provides functions for reading, writing, and processing typed JSONL records.
All CLI commands that accept stdin can read both plain URLs and typed JSONL.

Typed JSONL Format:
    {"type": "Snapshot", "url": "https://example.com", "title": "...", "tags": "..."}
    {"type": "ArchiveResult", "snapshot_id": "...", "extractor": "wget", ...}
    {"type": "Tag", "name": "..."}

Plain URLs (also supported):
    https://example.com
    https://foo.com
"""

__package__ = 'archivebox.misc'

import sys
import json
from typing import Iterator, Dict, Any, Optional, TextIO, Callable, Union, List
from pathlib import Path


# Type constants for JSONL records
TYPE_SNAPSHOT = 'Snapshot'
TYPE_ARCHIVERESULT = 'ArchiveResult'
TYPE_TAG = 'Tag'
TYPE_CRAWL = 'Crawl'
TYPE_INSTALLEDBINARY = 'InstalledBinary'

VALID_TYPES = {TYPE_SNAPSHOT, TYPE_ARCHIVERESULT, TYPE_TAG, TYPE_CRAWL, TYPE_INSTALLEDBINARY}


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


def filter_by_type(records: Iterator[Dict[str, Any]], record_type: str) -> Iterator[Dict[str, Any]]:
    """
    Filter records by type.
    """
    for record in records:
        if record.get('type') == record_type:
            yield record


def snapshot_to_jsonl(snapshot) -> Dict[str, Any]:
    """
    Convert a Snapshot model instance to a JSONL record.
    """
    return {
        'type': TYPE_SNAPSHOT,
        'id': str(snapshot.id),
        'url': snapshot.url,
        'title': snapshot.title,
        'tags': snapshot.tags_str() if hasattr(snapshot, 'tags_str') else '',
        'bookmarked_at': snapshot.bookmarked_at.isoformat() if snapshot.bookmarked_at else None,
        'created_at': snapshot.created_at.isoformat() if snapshot.created_at else None,
        'timestamp': snapshot.timestamp,
        'depth': getattr(snapshot, 'depth', 0),
        'status': snapshot.status if hasattr(snapshot, 'status') else None,
    }


def archiveresult_to_jsonl(result) -> Dict[str, Any]:
    """
    Convert an ArchiveResult model instance to a JSONL record.
    """
    record = {
        'type': TYPE_ARCHIVERESULT,
        'id': str(result.id),
        'snapshot_id': str(result.snapshot_id),
        'extractor': result.extractor,
        'status': result.status,
        'output_str': result.output_str,
        'start_ts': result.start_ts.isoformat() if result.start_ts else None,
        'end_ts': result.end_ts.isoformat() if result.end_ts else None,
    }
    # Include optional fields if set
    if result.output_json:
        record['output_json'] = result.output_json
    if result.output_files:
        record['output_files'] = result.output_files
    if result.output_size:
        record['output_size'] = result.output_size
    if result.output_mimetypes:
        record['output_mimetypes'] = result.output_mimetypes
    if result.cmd:
        record['cmd'] = result.cmd
    if result.cmd_version:
        record['cmd_version'] = result.cmd_version
    return record


def tag_to_jsonl(tag) -> Dict[str, Any]:
    """
    Convert a Tag model instance to a JSONL record.
    """
    return {
        'type': TYPE_TAG,
        'id': str(tag.id),
        'name': tag.name,
        'slug': tag.slug,
    }


def crawl_to_jsonl(crawl) -> Dict[str, Any]:
    """
    Convert a Crawl model instance to a JSONL record.
    """
    return {
        'type': TYPE_CRAWL,
        'id': str(crawl.id),
        'urls': crawl.urls,
        'status': crawl.status,
        'max_depth': crawl.max_depth,
        'created_at': crawl.created_at.isoformat() if crawl.created_at else None,
    }


def process_records(
    records: Iterator[Dict[str, Any]],
    handlers: Dict[str, Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]]
) -> Iterator[Dict[str, Any]]:
    """
    Process records through type-specific handlers.

    Args:
        records: Input record iterator
        handlers: Dict mapping type names to handler functions
                 Handlers return output records or None to skip

    Yields output records from handlers.
    """
    for record in records:
        record_type = record.get('type')
        handler = handlers.get(record_type)
        if handler:
            result = handler(record)
            if result:
                yield result


def get_or_create_snapshot(record: Dict[str, Any], created_by_id: Optional[int] = None):
    """
    Get or create a Snapshot from a JSONL record.

    Returns the Snapshot instance.
    """
    from core.models import Snapshot
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.misc.util import parse_date

    created_by_id = created_by_id or get_or_create_system_user_pk()

    # Extract fields from record
    url = record.get('url')
    if not url:
        raise ValueError("Record missing required 'url' field")

    title = record.get('title')
    tags_str = record.get('tags', '')
    bookmarked_at = record.get('bookmarked_at')
    depth = record.get('depth', 0)
    crawl_id = record.get('crawl_id')

    # Parse bookmarked_at if string
    if bookmarked_at and isinstance(bookmarked_at, str):
        bookmarked_at = parse_date(bookmarked_at)

    # Use the manager's create_or_update_from_dict method
    snapshot = Snapshot.objects.create_or_update_from_dict(
        {'url': url, 'title': title, 'tags': tags_str},
        created_by_id=created_by_id
    )

    # Update additional fields if provided
    update_fields = []
    if depth and snapshot.depth != depth:
        snapshot.depth = depth
        update_fields.append('depth')
    if bookmarked_at and snapshot.bookmarked_at != bookmarked_at:
        snapshot.bookmarked_at = bookmarked_at
        update_fields.append('bookmarked_at')
    if crawl_id and str(snapshot.crawl_id) != str(crawl_id):
        snapshot.crawl_id = crawl_id
        update_fields.append('crawl_id')

    if update_fields:
        snapshot.save(update_fields=update_fields + ['modified_at'])

    return snapshot


def get_or_create_tag(record: Dict[str, Any]):
    """
    Get or create a Tag from a JSONL record.

    Returns the Tag instance.
    """
    from core.models import Tag

    name = record.get('name')
    if not name:
        raise ValueError("Record missing required 'name' field")

    tag, _ = Tag.objects.get_or_create(name=name)
    return tag


def process_jsonl_records(records: Iterator[Dict[str, Any]], created_by_id: Optional[int] = None) -> Dict[str, List]:
    """
    Process JSONL records, creating Tags and Snapshots as needed.

    Args:
        records: Iterator of JSONL record dicts
        created_by_id: User ID for created objects

    Returns:
        Dict with 'tags' and 'snapshots' lists of created objects
    """
    from archivebox.base_models.models import get_or_create_system_user_pk

    created_by_id = created_by_id or get_or_create_system_user_pk()

    results = {
        'tags': [],
        'snapshots': [],
    }

    for record in records:
        record_type = record.get('type', TYPE_SNAPSHOT)

        if record_type == TYPE_TAG:
            try:
                tag = get_or_create_tag(record)
                results['tags'].append(tag)
            except ValueError:
                continue

        elif record_type == TYPE_SNAPSHOT or 'url' in record:
            try:
                snapshot = get_or_create_snapshot(record, created_by_id=created_by_id)
                results['snapshots'].append(snapshot)
            except ValueError:
                continue

    return results
