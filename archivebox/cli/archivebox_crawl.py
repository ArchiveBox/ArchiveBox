#!/usr/bin/env python3

"""
archivebox crawl [urls_or_snapshot_ids...] [--depth=N] [--plugin=NAME]

Discover outgoing links from URLs or existing Snapshots.

If a URL is passed, creates a Snapshot for it first, then runs parser plugins.
If a snapshot_id is passed, runs parser plugins on the existing Snapshot.
Outputs discovered outlink URLs as JSONL.

Pipe the output to `archivebox snapshot` to archive the discovered URLs.

Input formats:
    - Plain URLs (one per line)
    - Snapshot UUIDs (one per line)
    - JSONL: {"type": "Snapshot", "url": "...", ...}
    - JSONL: {"type": "Snapshot", "id": "...", ...}

Output (JSONL):
    {"type": "Snapshot", "url": "https://discovered-url.com", "via_extractor": "...", ...}

Examples:
    # Discover links from a page (creates snapshot first)
    archivebox crawl https://example.com

    # Discover links from an existing snapshot
    archivebox crawl 01234567-89ab-cdef-0123-456789abcdef

    # Full recursive crawl pipeline
    archivebox crawl https://example.com | archivebox snapshot | archivebox extract

    # Use only specific parser plugin
    archivebox crawl --plugin=parse_html_urls https://example.com

    # Chain: create snapshot, then crawl its outlinks
    archivebox snapshot https://example.com | archivebox crawl | archivebox snapshot | archivebox extract
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox crawl'

import sys
import json
from pathlib import Path
from typing import Optional

import rich_click as click

from archivebox.misc.util import docstring


def discover_outlinks(
    args: tuple,
    depth: int = 1,
    plugin: str = '',
    wait: bool = True,
) -> int:
    """
    Discover outgoing links from URLs or existing Snapshots.

    Accepts URLs or snapshot_ids. For URLs, creates Snapshots first.
    Runs parser plugins, outputs discovered URLs as JSONL.
    The output can be piped to `archivebox snapshot` to archive the discovered links.

    Exit codes:
        0: Success
        1: Failure
    """
    from rich import print as rprint
    from django.utils import timezone

    from archivebox.misc.jsonl import (
        read_args_or_stdin, write_record,
        TYPE_SNAPSHOT, get_or_create_snapshot
    )
    from archivebox.base_models.models import get_or_create_system_user_pk
    from core.models import Snapshot, ArchiveResult
    from crawls.models import Crawl
    from archivebox.config import CONSTANTS
    from workers.orchestrator import Orchestrator

    created_by_id = get_or_create_system_user_pk()
    is_tty = sys.stdout.isatty()

    # Collect all input records
    records = list(read_args_or_stdin(args))

    if not records:
        rprint('[yellow]No URLs or snapshot IDs provided. Pass as arguments or via stdin.[/yellow]', file=sys.stderr)
        return 1

    # Separate records into existing snapshots vs new URLs
    existing_snapshot_ids = []
    new_url_records = []

    for record in records:
        # Check if it's an existing snapshot (has id but no url, or looks like a UUID)
        if record.get('id') and not record.get('url'):
            existing_snapshot_ids.append(record['id'])
        elif record.get('id'):
            # Has both id and url - check if snapshot exists
            try:
                Snapshot.objects.get(id=record['id'])
                existing_snapshot_ids.append(record['id'])
            except Snapshot.DoesNotExist:
                new_url_records.append(record)
        elif record.get('url'):
            new_url_records.append(record)

    # For new URLs, create a Crawl and Snapshots
    snapshot_ids = list(existing_snapshot_ids)

    if new_url_records:
        # Create a Crawl to manage this operation
        sources_file = CONSTANTS.SOURCES_DIR / f'{timezone.now().strftime("%Y-%m-%d__%H-%M-%S")}__crawl.txt'
        sources_file.parent.mkdir(parents=True, exist_ok=True)
        sources_file.write_text('\n'.join(r.get('url', '') for r in new_url_records if r.get('url')))

        crawl = Crawl.from_file(
            sources_file,
            max_depth=depth,
            label=f'crawl --depth={depth}',
            created_by=created_by_id,
        )

        # Create snapshots for new URLs
        for record in new_url_records:
            try:
                record['crawl_id'] = str(crawl.id)
                record['depth'] = record.get('depth', 0)

                snapshot = get_or_create_snapshot(record, created_by_id=created_by_id)
                snapshot_ids.append(str(snapshot.id))

            except Exception as e:
                rprint(f'[red]Error creating snapshot: {e}[/red]', file=sys.stderr)
                continue

    if not snapshot_ids:
        rprint('[red]No snapshots to process[/red]', file=sys.stderr)
        return 1

    if existing_snapshot_ids:
        rprint(f'[blue]Using {len(existing_snapshot_ids)} existing snapshots[/blue]', file=sys.stderr)
    if new_url_records:
        rprint(f'[blue]Created {len(snapshot_ids) - len(existing_snapshot_ids)} new snapshots[/blue]', file=sys.stderr)
    rprint(f'[blue]Running parser plugins on {len(snapshot_ids)} snapshots...[/blue]', file=sys.stderr)

    # Create ArchiveResults for plugins
    # If --plugin is specified, only run that one. Otherwise, run all available plugins.
    # The orchestrator will handle dependency ordering (plugins declare deps in config.json)
    for snapshot_id in snapshot_ids:
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)

            if plugin:
                # User specified a single plugin to run
                ArchiveResult.objects.get_or_create(
                    snapshot=snapshot,
                    extractor=plugin,
                    defaults={
                        'status': ArchiveResult.StatusChoices.QUEUED,
                        'retry_at': timezone.now(),
                        'created_by_id': snapshot.created_by_id,
                    }
                )
            else:
                # Create pending ArchiveResults for all enabled plugins
                # This uses hook discovery to find available plugins dynamically
                snapshot.create_pending_archiveresults()

            # Mark snapshot as started
            snapshot.status = Snapshot.StatusChoices.STARTED
            snapshot.retry_at = timezone.now()
            snapshot.save()

        except Snapshot.DoesNotExist:
            continue

    # Run plugins
    if wait:
        rprint('[blue]Running outlink plugins...[/blue]', file=sys.stderr)
        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.runloop()

    # Collect discovered URLs from urls.jsonl files
    # Uses dynamic discovery - any plugin that outputs urls.jsonl is considered a parser
    from archivebox.hooks import collect_urls_from_extractors

    discovered_urls = {}
    for snapshot_id in snapshot_ids:
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)
            snapshot_dir = Path(snapshot.output_dir)

            # Dynamically collect urls.jsonl from ANY plugin subdirectory
            for entry in collect_urls_from_extractors(snapshot_dir):
                url = entry.get('url')
                if url and url not in discovered_urls:
                    # Add metadata for crawl tracking
                    entry['type'] = TYPE_SNAPSHOT
                    entry['depth'] = snapshot.depth + 1
                    entry['via_snapshot'] = str(snapshot.id)
                    discovered_urls[url] = entry

        except Snapshot.DoesNotExist:
            continue

    rprint(f'[green]Discovered {len(discovered_urls)} URLs[/green]', file=sys.stderr)

    # Output discovered URLs as JSONL (when piped) or human-readable (when TTY)
    for url, entry in discovered_urls.items():
        if is_tty:
            via = entry.get('via_extractor', 'unknown')
            rprint(f'  [dim]{via}[/dim] {url[:80]}', file=sys.stderr)
        else:
            write_record(entry)

    return 0


def process_crawl_by_id(crawl_id: str) -> int:
    """
    Process a single Crawl by ID (used by workers).

    Triggers the Crawl's state machine tick() which will:
    - Transition from queued -> started (creates root snapshot)
    - Transition from started -> sealed (when all snapshots done)
    """
    from rich import print as rprint
    from crawls.models import Crawl

    try:
        crawl = Crawl.objects.get(id=crawl_id)
    except Crawl.DoesNotExist:
        rprint(f'[red]Crawl {crawl_id} not found[/red]', file=sys.stderr)
        return 1

    rprint(f'[blue]Processing Crawl {crawl.id} (status={crawl.status})[/blue]', file=sys.stderr)

    try:
        crawl.sm.tick()
        crawl.refresh_from_db()
        rprint(f'[green]Crawl complete (status={crawl.status})[/green]', file=sys.stderr)
        return 0
    except Exception as e:
        rprint(f'[red]Crawl error: {type(e).__name__}: {e}[/red]', file=sys.stderr)
        return 1


def is_crawl_id(value: str) -> bool:
    """Check if value looks like a Crawl UUID."""
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    if not uuid_pattern.match(value):
        return False
    # Verify it's actually a Crawl (not a Snapshot or other object)
    from crawls.models import Crawl
    return Crawl.objects.filter(id=value).exists()


@click.command()
@click.option('--depth', '-d', type=int, default=1, help='Max depth for recursive crawling (default: 1)')
@click.option('--plugin', '-p', default='', help='Use only this parser plugin (e.g., parse_html_urls, parse_dom_outlinks)')
@click.option('--wait/--no-wait', default=True, help='Wait for plugins to complete (default: wait)')
@click.argument('args', nargs=-1)
def main(depth: int, plugin: str, wait: bool, args: tuple):
    """Discover outgoing links from URLs or existing Snapshots, or process Crawl by ID"""
    from archivebox.misc.jsonl import read_args_or_stdin

    # Read all input
    records = list(read_args_or_stdin(args))

    if not records:
        from rich import print as rprint
        rprint('[yellow]No URLs, Snapshot IDs, or Crawl IDs provided. Pass as arguments or via stdin.[/yellow]', file=sys.stderr)
        sys.exit(1)

    # Check if input looks like existing Crawl IDs to process
    # If ALL inputs are Crawl UUIDs, process them
    all_are_crawl_ids = all(
        is_crawl_id(r.get('id') or r.get('url', ''))
        for r in records
    )

    if all_are_crawl_ids:
        # Process existing Crawls by ID
        exit_code = 0
        for record in records:
            crawl_id = record.get('id') or record.get('url')
            result = process_crawl_by_id(crawl_id)
            if result != 0:
                exit_code = result
        sys.exit(exit_code)
    else:
        # Default behavior: discover outlinks from input (URLs or Snapshot IDs)
        sys.exit(discover_outlinks(args, depth=depth, plugin=plugin, wait=wait))


if __name__ == '__main__':
    main()
