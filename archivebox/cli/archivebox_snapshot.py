#!/usr/bin/env python3

"""
archivebox snapshot [urls...] [--depth=N] [--tag=TAG] [--plugins=...]

Create Snapshots from URLs. Accepts URLs as arguments, from stdin, or via JSONL.

Input formats:
    - Plain URLs (one per line)
    - JSONL: {"type": "Snapshot", "url": "...", "title": "...", "tags": "..."}

Output (JSONL):
    {"type": "Snapshot", "id": "...", "url": "...", "status": "queued", ...}

Examples:
    # Create snapshots from URLs
    archivebox snapshot https://example.com https://foo.com

    # Pipe from stdin
    echo 'https://example.com' | archivebox snapshot

    # Chain with extract
    archivebox snapshot https://example.com | archivebox extract

    # With crawl depth
    archivebox snapshot --depth=1 https://example.com
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox snapshot'

import sys
from typing import Optional

import rich_click as click

from archivebox.misc.util import docstring


def process_snapshot_by_id(snapshot_id: str) -> int:
    """
    Process a single Snapshot by ID (used by workers).

    Triggers the Snapshot's state machine tick() which will:
    - Transition from queued -> started (creates pending ArchiveResults)
    - Transition from started -> sealed (when all ArchiveResults done)
    """
    from rich import print as rprint
    from core.models import Snapshot

    try:
        snapshot = Snapshot.objects.get(id=snapshot_id)
    except Snapshot.DoesNotExist:
        rprint(f'[red]Snapshot {snapshot_id} not found[/red]', file=sys.stderr)
        return 1

    rprint(f'[blue]Processing Snapshot {snapshot.id} {snapshot.url[:50]} (status={snapshot.status})[/blue]', file=sys.stderr)

    try:
        snapshot.sm.tick()
        snapshot.refresh_from_db()
        rprint(f'[green]Snapshot complete (status={snapshot.status})[/green]', file=sys.stderr)
        return 0
    except Exception as e:
        rprint(f'[red]Snapshot error: {type(e).__name__}: {e}[/red]', file=sys.stderr)
        return 1


def create_snapshots(
    urls: tuple,
    depth: int = 0,
    tag: str = '',
    plugins: str = '',
    created_by_id: Optional[int] = None,
) -> int:
    """
    Create Snapshots from URLs or JSONL records.

    Reads from args or stdin, creates Snapshot objects, outputs JSONL.
    If --plugins is passed, also runs specified plugins (blocking).

    Exit codes:
        0: Success
        1: Failure
    """
    from rich import print as rprint
    from django.utils import timezone

    from archivebox.misc.jsonl import (
        read_args_or_stdin, write_record, snapshot_to_jsonl,
        TYPE_SNAPSHOT, TYPE_TAG, get_or_create_snapshot
    )
    from archivebox.base_models.models import get_or_create_system_user_pk
    from core.models import Snapshot
    from crawls.models import Seed, Crawl
    from archivebox.config import CONSTANTS

    created_by_id = created_by_id or get_or_create_system_user_pk()
    is_tty = sys.stdout.isatty()

    # Collect all input records
    records = list(read_args_or_stdin(urls))

    if not records:
        rprint('[yellow]No URLs provided. Pass URLs as arguments or via stdin.[/yellow]', file=sys.stderr)
        return 1

    # If depth > 0, we need a Crawl to manage recursive discovery
    crawl = None
    if depth > 0:
        # Create a seed for this batch
        sources_file = CONSTANTS.SOURCES_DIR / f'{timezone.now().strftime("%Y-%m-%d__%H-%M-%S")}__snapshot.txt'
        sources_file.parent.mkdir(parents=True, exist_ok=True)
        sources_file.write_text('\n'.join(r.get('url', '') for r in records if r.get('url')))

        seed = Seed.from_file(
            sources_file,
            label=f'snapshot --depth={depth}',
            created_by=created_by_id,
        )
        crawl = Crawl.from_seed(seed, max_depth=depth)

    # Process each record
    created_snapshots = []
    for record in records:
        if record.get('type') != TYPE_SNAPSHOT and 'url' not in record:
            continue

        try:
            # Add crawl info if we have one
            if crawl:
                record['crawl_id'] = str(crawl.id)
                record['depth'] = record.get('depth', 0)

            # Add tags if provided via CLI
            if tag and not record.get('tags'):
                record['tags'] = tag

            # Get or create the snapshot
            snapshot = get_or_create_snapshot(record, created_by_id=created_by_id)
            created_snapshots.append(snapshot)

            # Output JSONL record (only when piped)
            if not is_tty:
                write_record(snapshot_to_jsonl(snapshot))

        except Exception as e:
            rprint(f'[red]Error creating snapshot: {e}[/red]', file=sys.stderr)
            continue

    if not created_snapshots:
        rprint('[red]No snapshots created[/red]', file=sys.stderr)
        return 1

    rprint(f'[green]Created {len(created_snapshots)} snapshots[/green]', file=sys.stderr)

    # If TTY, show human-readable output
    if is_tty:
        for snapshot in created_snapshots:
            rprint(f'  [dim]{snapshot.id}[/dim] {snapshot.url[:60]}', file=sys.stderr)

    # If --plugins is passed, run the orchestrator for those plugins
    if plugins:
        from workers.orchestrator import Orchestrator
        rprint(f'[blue]Running plugins: {plugins or "all"}...[/blue]', file=sys.stderr)
        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.runloop()

    return 0


def is_snapshot_id(value: str) -> bool:
    """Check if value looks like a Snapshot UUID."""
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    return bool(uuid_pattern.match(value))


@click.command()
@click.option('--depth', '-d', type=int, default=0, help='Recursively crawl linked pages up to N levels deep')
@click.option('--tag', '-t', default='', help='Comma-separated tags to add to each snapshot')
@click.option('--plugins', '-p', default='', help='Comma-separated list of plugins to run after creating snapshots (e.g. title,screenshot)')
@click.argument('args', nargs=-1)
def main(depth: int, tag: str, plugins: str, args: tuple):
    """Create Snapshots from URLs, or process existing Snapshots by ID"""
    from archivebox.misc.jsonl import read_args_or_stdin

    # Read all input
    records = list(read_args_or_stdin(args))

    if not records:
        from rich import print as rprint
        rprint('[yellow]No URLs or Snapshot IDs provided. Pass as arguments or via stdin.[/yellow]', file=sys.stderr)
        sys.exit(1)

    # Check if input looks like existing Snapshot IDs to process
    # If ALL inputs are UUIDs with no URL, assume we're processing existing Snapshots
    all_are_ids = all(
        (r.get('id') and not r.get('url')) or is_snapshot_id(r.get('url', ''))
        for r in records
    )

    if all_are_ids:
        # Process existing Snapshots by ID
        exit_code = 0
        for record in records:
            snapshot_id = record.get('id') or record.get('url')
            result = process_snapshot_by_id(snapshot_id)
            if result != 0:
                exit_code = result
        sys.exit(exit_code)
    else:
        # Create new Snapshots from URLs
        sys.exit(create_snapshots(args, depth=depth, tag=tag, plugins=plugins))


if __name__ == '__main__':
    main()
