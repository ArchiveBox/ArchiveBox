#!/usr/bin/env python3

"""
archivebox archiveresult <action> [args...] [--filters]

Manage ArchiveResult records (plugin extraction results).

Actions:
    create  - Create ArchiveResults for Snapshots (queue extractions)
    list    - List ArchiveResults as JSONL (with optional filters)
    update  - Update ArchiveResults from stdin JSONL
    delete  - Delete ArchiveResults from stdin JSONL

Examples:
    # Create ArchiveResults for snapshots (queue for extraction)
    archivebox snapshot list --status=queued | archivebox archiveresult create
    archivebox archiveresult create --plugin=screenshot --snapshot-id=<uuid>

    # List with filters
    archivebox archiveresult list --status=failed
    archivebox archiveresult list --plugin=screenshot --status=succeeded

    # Update (reset failed extractions to queued)
    archivebox archiveresult list --status=failed | archivebox archiveresult update --status=queued

    # Delete
    archivebox archiveresult list --plugin=singlefile | archivebox archiveresult delete --yes

    # Re-run failed extractions
    archivebox archiveresult list --status=failed | archivebox run
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox archiveresult'

import sys
from typing import Optional

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_utils import apply_filters


# =============================================================================
# CREATE
# =============================================================================

def create_archiveresults(
    snapshot_id: Optional[str] = None,
    plugin: Optional[str] = None,
    status: str = 'queued',
) -> int:
    """
    Create ArchiveResults for Snapshots.

    Reads Snapshot records from stdin and creates ArchiveResult entries.
    Pass-through: Non-Snapshot/ArchiveResult records are output unchanged.
    If --plugin is specified, only creates results for that plugin.
    Otherwise, creates results for all pending plugins.

    Exit codes:
        0: Success
        1: Failure
    """
    from django.utils import timezone

    from archivebox.misc.jsonl import read_stdin, write_record, TYPE_SNAPSHOT, TYPE_ARCHIVERESULT
    from archivebox.core.models import Snapshot, ArchiveResult

    is_tty = sys.stdout.isatty()

    # If snapshot_id provided directly, use that
    if snapshot_id:
        try:
            snapshots = [Snapshot.objects.get(id=snapshot_id)]
            pass_through_records = []
        except Snapshot.DoesNotExist:
            rprint(f'[red]Snapshot not found: {snapshot_id}[/red]', file=sys.stderr)
            return 1
    else:
        # Read from stdin
        records = list(read_stdin())
        if not records:
            rprint('[yellow]No Snapshot records provided via stdin[/yellow]', file=sys.stderr)
            return 1

        # Separate snapshot records from pass-through records
        snapshot_ids = []
        pass_through_records = []

        for record in records:
            record_type = record.get('type', '')

            if record_type == TYPE_SNAPSHOT:
                # Pass through the Snapshot record itself
                pass_through_records.append(record)
                if record.get('id'):
                    snapshot_ids.append(record['id'])

            elif record_type == TYPE_ARCHIVERESULT:
                # ArchiveResult records: pass through if they have an id
                if record.get('id'):
                    pass_through_records.append(record)
                # If no id, we could create it, but for now just pass through
                else:
                    pass_through_records.append(record)

            elif record_type:
                # Other typed records (Crawl, Tag, etc): pass through
                pass_through_records.append(record)

            elif record.get('id'):
                # Untyped record with id - assume it's a snapshot ID
                snapshot_ids.append(record['id'])

        # Output pass-through records first
        if not is_tty:
            for record in pass_through_records:
                write_record(record)

        if not snapshot_ids:
            if pass_through_records:
                rprint(f'[dim]Passed through {len(pass_through_records)} records, no new snapshots to process[/dim]', file=sys.stderr)
                return 0
            rprint('[yellow]No valid Snapshot IDs in input[/yellow]', file=sys.stderr)
            return 1

        snapshots = list(Snapshot.objects.filter(id__in=snapshot_ids))

    if not snapshots:
        rprint('[yellow]No matching snapshots found[/yellow]', file=sys.stderr)
        return 0 if pass_through_records else 1

    created_count = 0
    for snapshot in snapshots:
        if plugin:
            # Create for specific plugin only
            result, created = ArchiveResult.objects.get_or_create(
                snapshot=snapshot,
                plugin=plugin,
                defaults={
                    'status': status,
                    'retry_at': timezone.now(),
                }
            )
            if not created and result.status in [ArchiveResult.StatusChoices.FAILED, ArchiveResult.StatusChoices.SKIPPED]:
                # Reset for retry
                result.status = status
                result.retry_at = timezone.now()
                result.save()

            if not is_tty:
                write_record(result.to_json())
            created_count += 1
        else:
            # Create all pending plugins
            snapshot.create_pending_archiveresults()
            for result in snapshot.archiveresult_set.filter(status=ArchiveResult.StatusChoices.QUEUED):
                if not is_tty:
                    write_record(result.to_json())
                created_count += 1

    rprint(f'[green]Created/queued {created_count} archive results[/green]', file=sys.stderr)
    return 0


# =============================================================================
# LIST
# =============================================================================

def list_archiveresults(
    status: Optional[str] = None,
    plugin: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    List ArchiveResults as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.core.models import ArchiveResult

    is_tty = sys.stdout.isatty()

    queryset = ArchiveResult.objects.all().order_by('-start_ts')

    # Apply filters
    filter_kwargs = {
        'status': status,
        'plugin': plugin,
        'snapshot_id': snapshot_id,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for result in queryset:
        if is_tty:
            status_color = {
                'queued': 'yellow',
                'started': 'blue',
                'succeeded': 'green',
                'failed': 'red',
                'skipped': 'dim',
                'backoff': 'magenta',
            }.get(result.status, 'dim')
            rprint(f'[{status_color}]{result.status:10}[/{status_color}] {result.plugin:15} [dim]{result.id}[/dim] {result.snapshot.url[:40]}')
        else:
            write_record(result.to_json())
        count += 1

    rprint(f'[dim]Listed {count} archive results[/dim]', file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================

def update_archiveresults(
    status: Optional[str] = None,
) -> int:
    """
    Update ArchiveResults from stdin JSONL.

    Reads ArchiveResult records from stdin and applies updates.
    Uses PATCH semantics - only specified fields are updated.

    Exit codes:
        0: Success
        1: No input or error
    """
    from django.utils import timezone

    from archivebox.misc.jsonl import read_stdin, write_record
    from archivebox.core.models import ArchiveResult

    is_tty = sys.stdout.isatty()

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        result_id = record.get('id')
        if not result_id:
            continue

        try:
            result = ArchiveResult.objects.get(id=result_id)

            # Apply updates from CLI flags
            if status:
                result.status = status
                result.retry_at = timezone.now()

            result.save()
            updated_count += 1

            if not is_tty:
                write_record(result.to_json())

        except ArchiveResult.DoesNotExist:
            rprint(f'[yellow]ArchiveResult not found: {result_id}[/yellow]', file=sys.stderr)
            continue

    rprint(f'[green]Updated {updated_count} archive results[/green]', file=sys.stderr)
    return 0


# =============================================================================
# DELETE
# =============================================================================

def delete_archiveresults(yes: bool = False, dry_run: bool = False) -> int:
    """
    Delete ArchiveResults from stdin JSONL.

    Requires --yes flag to confirm deletion.

    Exit codes:
        0: Success
        1: No input or missing --yes flag
    """
    from archivebox.misc.jsonl import read_stdin
    from archivebox.core.models import ArchiveResult

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    result_ids = [r.get('id') for r in records if r.get('id')]

    if not result_ids:
        rprint('[yellow]No valid archive result IDs in input[/yellow]', file=sys.stderr)
        return 1

    results = ArchiveResult.objects.filter(id__in=result_ids)
    count = results.count()

    if count == 0:
        rprint('[yellow]No matching archive results found[/yellow]', file=sys.stderr)
        return 0

    if dry_run:
        rprint(f'[yellow]Would delete {count} archive results (dry run)[/yellow]', file=sys.stderr)
        for result in results[:10]:
            rprint(f'  [dim]{result.id}[/dim] {result.plugin} {result.snapshot.url[:40]}', file=sys.stderr)
        if count > 10:
            rprint(f'  ... and {count - 10} more', file=sys.stderr)
        return 0

    if not yes:
        rprint('[red]Use --yes to confirm deletion[/red]', file=sys.stderr)
        return 1

    # Perform deletion
    deleted_count, _ = results.delete()
    rprint(f'[green]Deleted {deleted_count} archive results[/green]', file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
def main():
    """Manage ArchiveResult records (plugin extraction results)."""
    pass


@main.command('create')
@click.option('--snapshot-id', help='Snapshot ID to create results for')
@click.option('--plugin', '-p', help='Plugin name (e.g., screenshot, singlefile)')
@click.option('--status', '-s', default='queued', help='Initial status (default: queued)')
def create_cmd(snapshot_id: Optional[str], plugin: Optional[str], status: str):
    """Create ArchiveResults for Snapshots from stdin JSONL."""
    sys.exit(create_archiveresults(snapshot_id=snapshot_id, plugin=plugin, status=status))


@main.command('list')
@click.option('--status', '-s', help='Filter by status (queued, started, succeeded, failed, skipped)')
@click.option('--plugin', '-p', help='Filter by plugin name')
@click.option('--snapshot-id', help='Filter by snapshot ID')
@click.option('--limit', '-n', type=int, help='Limit number of results')
def list_cmd(status: Optional[str], plugin: Optional[str],
             snapshot_id: Optional[str], limit: Optional[int]):
    """List ArchiveResults as JSONL."""
    sys.exit(list_archiveresults(
        status=status,
        plugin=plugin,
        snapshot_id=snapshot_id,
        limit=limit,
    ))


@main.command('update')
@click.option('--status', '-s', help='Set status')
def update_cmd(status: Optional[str]):
    """Update ArchiveResults from stdin JSONL."""
    sys.exit(update_archiveresults(status=status))


@main.command('delete')
@click.option('--yes', '-y', is_flag=True, help='Confirm deletion')
@click.option('--dry-run', is_flag=True, help='Show what would be deleted')
def delete_cmd(yes: bool, dry_run: bool):
    """Delete ArchiveResults from stdin JSONL."""
    sys.exit(delete_archiveresults(yes=yes, dry_run=dry_run))


if __name__ == '__main__':
    main()
