#!/usr/bin/env python3

"""
archivebox snapshot [urls_or_crawl_ids...] [--tag=TAG] [--plugins=NAMES]

Create Snapshots from URLs or Crawl jobs. Accepts URLs, Crawl JSONL, or Crawl IDs.

Input formats:
    - Plain URLs (one per line)
    - JSONL: {"type": "Crawl", "id": "...", "urls": "..."}
    - JSONL: {"type": "Snapshot", "url": "...", "title": "...", "tags": "..."}
    - Crawl UUIDs (one per line)

Output (JSONL):
    {"type": "Snapshot", "id": "...", "url": "...", "status": "queued", ...}

Examples:
    # Create snapshots from URLs directly
    archivebox snapshot https://example.com https://foo.com

    # Pipe from crawl command
    archivebox crawl https://example.com | archivebox snapshot

    # Chain with extract
    archivebox crawl https://example.com | archivebox snapshot | archivebox extract

    # Run specific plugins after creating snapshots
    archivebox snapshot --plugins=screenshot,singlefile https://example.com

    # Process existing Snapshot by ID
    archivebox snapshot 01234567-89ab-cdef-0123-456789abcdef
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
    from archivebox.core.models import Snapshot

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
    args: tuple,
    tag: str = '',
    plugins: str = '',
    created_by_id: Optional[int] = None,
) -> int:
    """
    Create Snapshots from URLs, Crawl JSONL, or Crawl IDs.

    Reads from args or stdin, creates Snapshot objects, outputs JSONL.
    If --plugins is passed, also runs specified plugins (blocking).

    Exit codes:
        0: Success
        1: Failure
    """
    from rich import print as rprint
    from django.utils import timezone

    from archivebox.misc.jsonl import (
        read_args_or_stdin, write_record,
        TYPE_SNAPSHOT, TYPE_CRAWL
    )
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    created_by_id = created_by_id or get_or_create_system_user_pk()
    is_tty = sys.stdout.isatty()

    # Collect all input records
    records = list(read_args_or_stdin(args))

    if not records:
        rprint('[yellow]No URLs or Crawls provided. Pass URLs as arguments or via stdin.[/yellow]', file=sys.stderr)
        return 1

    # Process each record - handle Crawls and plain URLs/Snapshots
    created_snapshots = []
    for record in records:
        record_type = record.get('type')

        try:
            if record_type == TYPE_CRAWL:
                # Input is a Crawl - get or create it, then create Snapshots for its URLs
                crawl = None
                crawl_id = record.get('id')
                if crawl_id:
                    try:
                        crawl = Crawl.objects.get(id=crawl_id)
                    except Crawl.DoesNotExist:
                        # Crawl doesn't exist, create it
                        crawl = Crawl.from_jsonl(record, overrides={'created_by_id': created_by_id})
                else:
                    # No ID, create new crawl
                    crawl = Crawl.from_jsonl(record, overrides={'created_by_id': created_by_id})

                if not crawl:
                    continue

                # Create snapshots for each URL in the crawl
                for url in crawl.get_urls_list():
                    # Merge CLI tags with crawl tags
                    merged_tags = crawl.tags_str
                    if tag:
                        if merged_tags:
                            merged_tags = f"{merged_tags},{tag}"
                        else:
                            merged_tags = tag
                    snapshot_record = {
                        'url': url,
                        'tags': merged_tags,
                        'crawl_id': str(crawl.id),
                        'depth': 0,
                    }
                    snapshot = Snapshot.from_jsonl(snapshot_record, overrides={'created_by_id': created_by_id})
                    if snapshot:
                        created_snapshots.append(snapshot)
                        if not is_tty:
                            write_record(snapshot.to_jsonl())

            elif record_type == TYPE_SNAPSHOT or record.get('url'):
                # Input is a Snapshot or plain URL
                # Add tags if provided via CLI
                if tag and not record.get('tags'):
                    record['tags'] = tag

                snapshot = Snapshot.from_jsonl(record, overrides={'created_by_id': created_by_id})
                if snapshot:
                    created_snapshots.append(snapshot)
                    if not is_tty:
                        write_record(snapshot.to_jsonl())

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

    # If --plugins is passed, create ArchiveResults and run the orchestrator
    if plugins:
        from archivebox.core.models import ArchiveResult
        from archivebox.workers.orchestrator import Orchestrator

        # Parse comma-separated plugins list
        plugins_list = [p.strip() for p in plugins.split(',') if p.strip()]

        # Create ArchiveResults for the specific plugins on each snapshot
        for snapshot in created_snapshots:
            for plugin_name in plugins_list:
                result, created = ArchiveResult.objects.get_or_create(
                    snapshot=snapshot,
                    plugin=plugin_name,
                    defaults={
                        'status': ArchiveResult.StatusChoices.QUEUED,
                        'retry_at': timezone.now(),
                    }
                )
                if not created and result.status in [ArchiveResult.StatusChoices.FAILED, ArchiveResult.StatusChoices.SKIPPED]:
                    # Reset for retry
                    result.status = ArchiveResult.StatusChoices.QUEUED
                    result.retry_at = timezone.now()
                    result.save()

        rprint(f'[blue]Running plugins: {plugins}...[/blue]', file=sys.stderr)
        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.runloop()

    return 0


def is_snapshot_id(value: str) -> bool:
    """Check if value looks like a Snapshot UUID."""
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    if not uuid_pattern.match(value):
        return False
    # Verify it's actually a Snapshot (not a Crawl or other object)
    from archivebox.core.models import Snapshot
    return Snapshot.objects.filter(id=value).exists()


@click.command()
@click.option('--tag', '-t', default='', help='Comma-separated tags to add to each snapshot')
@click.option('--plugins', '-p', default='', help='Comma-separated list of plugins to run after creating snapshots (e.g., screenshot,singlefile)')
@click.argument('args', nargs=-1)
def main(tag: str, plugins: str, args: tuple):
    """Create Snapshots from URLs/Crawls, or process existing Snapshots by ID"""
    from archivebox.misc.jsonl import read_args_or_stdin

    # Read all input
    records = list(read_args_or_stdin(args))

    if not records:
        from rich import print as rprint
        rprint('[yellow]No URLs, Crawl IDs, or Snapshot IDs provided. Pass as arguments or via stdin.[/yellow]', file=sys.stderr)
        sys.exit(1)

    # Check if input looks like existing Snapshot IDs to process
    # If ALL inputs are UUIDs with no URL and exist as Snapshots, process them
    all_are_snapshot_ids = all(
        is_snapshot_id(r.get('id') or r.get('url', ''))
        for r in records
        if r.get('type') != 'Crawl'  # Don't check Crawl records as Snapshot IDs
    )

    # But also check that we're not receiving Crawl JSONL
    has_crawl_records = any(r.get('type') == 'Crawl' for r in records)

    if all_are_snapshot_ids and not has_crawl_records:
        # Process existing Snapshots by ID
        exit_code = 0
        for record in records:
            snapshot_id = record.get('id') or record.get('url')
            result = process_snapshot_by_id(snapshot_id)
            if result != 0:
                exit_code = result
        sys.exit(exit_code)
    else:
        # Create new Snapshots from URLs or Crawls
        sys.exit(create_snapshots(args, tag=tag, plugins=plugins))


if __name__ == '__main__':
    main()
