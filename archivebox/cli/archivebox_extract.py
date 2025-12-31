#!/usr/bin/env python3

"""
archivebox extract [snapshot_ids...] [--plugins=NAMES]

Run plugins on Snapshots. Accepts snapshot IDs as arguments, from stdin, or via JSONL.

Input formats:
    - Snapshot UUIDs (one per line)
    - JSONL: {"type": "Snapshot", "id": "...", "url": "..."}
    - JSONL: {"type": "ArchiveResult", "snapshot_id": "...", "plugin": "..."}

Output (JSONL):
    {"type": "ArchiveResult", "id": "...", "snapshot_id": "...", "plugin": "...", "status": "..."}

Examples:
    # Extract specific snapshot
    archivebox extract 01234567-89ab-cdef-0123-456789abcdef

    # Pipe from snapshot command
    archivebox snapshot https://example.com | archivebox extract

    # Run specific plugins only
    archivebox extract --plugins=screenshot,singlefile 01234567-89ab-cdef-0123-456789abcdef

    # Chain commands
    archivebox crawl https://example.com | archivebox snapshot | archivebox extract
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox extract'

import sys
from typing import Optional, List

import rich_click as click


def process_archiveresult_by_id(archiveresult_id: str) -> int:
    """
    Run extraction for a single ArchiveResult by ID (used by workers).

    Triggers the ArchiveResult's state machine tick() to run the extractor plugin.
    """
    from rich import print as rprint
    from archivebox.core.models import ArchiveResult

    try:
        archiveresult = ArchiveResult.objects.get(id=archiveresult_id)
    except ArchiveResult.DoesNotExist:
        rprint(f'[red]ArchiveResult {archiveresult_id} not found[/red]', file=sys.stderr)
        return 1

    rprint(f'[blue]Extracting {archiveresult.plugin} for {archiveresult.snapshot.url}[/blue]', file=sys.stderr)

    try:
        # Trigger state machine tick - this runs the actual extraction
        archiveresult.sm.tick()
        archiveresult.refresh_from_db()

        if archiveresult.status == ArchiveResult.StatusChoices.SUCCEEDED:
            print(f'[green]Extraction succeeded: {archiveresult.output_str}[/green]')
            return 0
        elif archiveresult.status == ArchiveResult.StatusChoices.FAILED:
            print(f'[red]Extraction failed: {archiveresult.output_str}[/red]', file=sys.stderr)
            return 1
        else:
            # Still in progress or backoff - not a failure
            print(f'[yellow]Extraction status: {archiveresult.status}[/yellow]')
            return 0

    except Exception as e:
        print(f'[red]Extraction error: {type(e).__name__}: {e}[/red]', file=sys.stderr)
        return 1


def run_plugins(
    args: tuple,
    plugins: str = '',
    wait: bool = True,
) -> int:
    """
    Run plugins on Snapshots from input.

    Reads Snapshot IDs or JSONL from args/stdin, runs plugins, outputs JSONL.

    Exit codes:
        0: Success
        1: Failure
    """
    from rich import print as rprint
    from django.utils import timezone

    from archivebox.misc.jsonl import (
        read_args_or_stdin, write_record,
        TYPE_SNAPSHOT, TYPE_ARCHIVERESULT
    )
    from archivebox.core.models import Snapshot, ArchiveResult
    from archivebox.workers.orchestrator import Orchestrator

    is_tty = sys.stdout.isatty()

    # Parse comma-separated plugins list once (reused in creation and filtering)
    plugins_list = [p.strip() for p in plugins.split(',') if p.strip()] if plugins else []

    # Collect all input records
    records = list(read_args_or_stdin(args))

    if not records:
        rprint('[yellow]No snapshots provided. Pass snapshot IDs as arguments or via stdin.[/yellow]', file=sys.stderr)
        return 1

    # Gather snapshot IDs to process
    snapshot_ids = set()
    for record in records:
        record_type = record.get('type')

        if record_type == TYPE_SNAPSHOT:
            snapshot_id = record.get('id')
            if snapshot_id:
                snapshot_ids.add(snapshot_id)
            elif record.get('url'):
                # Look up by URL (get most recent if multiple exist)
                snap = Snapshot.objects.filter(url=record['url']).order_by('-created_at').first()
                if snap:
                    snapshot_ids.add(str(snap.id))
                else:
                    rprint(f'[yellow]Snapshot not found for URL: {record["url"]}[/yellow]', file=sys.stderr)

        elif record_type == TYPE_ARCHIVERESULT:
            snapshot_id = record.get('snapshot_id')
            if snapshot_id:
                snapshot_ids.add(snapshot_id)

        elif 'id' in record:
            # Assume it's a snapshot ID
            snapshot_ids.add(record['id'])

    if not snapshot_ids:
        rprint('[red]No valid snapshot IDs found in input[/red]', file=sys.stderr)
        return 1

    # Get snapshots and ensure they have pending ArchiveResults
    processed_count = 0
    for snapshot_id in snapshot_ids:
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)
        except Snapshot.DoesNotExist:
            rprint(f'[yellow]Snapshot {snapshot_id} not found[/yellow]', file=sys.stderr)
            continue

        # Create pending ArchiveResults if needed
        if plugins_list:
            # Only create for specific plugins
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
        else:
            # Create all pending plugins
            snapshot.create_pending_archiveresults()

        # Reset snapshot status to allow processing
        if snapshot.status == Snapshot.StatusChoices.SEALED:
            snapshot.status = Snapshot.StatusChoices.STARTED
            snapshot.retry_at = timezone.now()
            snapshot.save()

        processed_count += 1

    if processed_count == 0:
        rprint('[red]No snapshots to process[/red]', file=sys.stderr)
        return 1

    rprint(f'[blue]Queued {processed_count} snapshots for extraction[/blue]', file=sys.stderr)

    # Run orchestrator if --wait (default)
    if wait:
        rprint('[blue]Running plugins...[/blue]', file=sys.stderr)
        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.runloop()

    # Output results as JSONL (when piped) or human-readable (when TTY)
    for snapshot_id in snapshot_ids:
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)
            results = snapshot.archiveresult_set.all()
            if plugins_list:
                results = results.filter(plugin__in=plugins_list)

            for result in results:
                if is_tty:
                    status_color = {
                        'succeeded': 'green',
                        'failed': 'red',
                        'skipped': 'yellow',
                    }.get(result.status, 'dim')
                    rprint(f'  [{status_color}]{result.status}[/{status_color}] {result.plugin} → {result.output_str or ""}', file=sys.stderr)
                else:
                    write_record(result.to_json())
        except Snapshot.DoesNotExist:
            continue

    return 0


def is_archiveresult_id(value: str) -> bool:
    """Check if value looks like an ArchiveResult UUID."""
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    if not uuid_pattern.match(value):
        return False
    # Verify it's actually an ArchiveResult (not a Snapshot or other object)
    from archivebox.core.models import ArchiveResult
    return ArchiveResult.objects.filter(id=value).exists()


@click.command()
@click.option('--plugins', '-p', default='', help='Comma-separated list of plugins to run (e.g., screenshot,singlefile)')
@click.option('--wait/--no-wait', default=True, help='Wait for plugins to complete (default: wait)')
@click.argument('args', nargs=-1)
def main(plugins: str, wait: bool, args: tuple):
    """Run plugins on Snapshots, or process existing ArchiveResults by ID"""
    from archivebox.misc.jsonl import read_args_or_stdin

    # Read all input
    records = list(read_args_or_stdin(args))

    if not records:
        from rich import print as rprint
        rprint('[yellow]No Snapshot IDs or ArchiveResult IDs provided. Pass as arguments or via stdin.[/yellow]', file=sys.stderr)
        sys.exit(1)

    # Check if input looks like existing ArchiveResult IDs to process
    all_are_archiveresult_ids = all(
        is_archiveresult_id(r.get('id') or r.get('url', ''))
        for r in records
    )

    if all_are_archiveresult_ids:
        # Process existing ArchiveResults by ID
        exit_code = 0
        for record in records:
            archiveresult_id = record.get('id') or record.get('url')
            result = process_archiveresult_by_id(archiveresult_id)
            if result != 0:
                exit_code = result
        sys.exit(exit_code)
    else:
        # Default behavior: run plugins on Snapshots from input
        sys.exit(run_plugins(args, plugins=plugins, wait=wait))


if __name__ == '__main__':
    main()
