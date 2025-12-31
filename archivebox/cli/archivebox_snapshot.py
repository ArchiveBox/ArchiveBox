#!/usr/bin/env python3

"""
archivebox snapshot <action> [args...] [--filters]

Manage Snapshot records.

Actions:
    create  - Create Snapshots from URLs or Crawl JSONL
    list    - List Snapshots as JSONL (with optional filters)
    update  - Update Snapshots from stdin JSONL
    delete  - Delete Snapshots from stdin JSONL

Examples:
    # Create
    archivebox snapshot create https://example.com --tag=news
    archivebox crawl create https://example.com | archivebox snapshot create

    # List with filters
    archivebox snapshot list --status=queued
    archivebox snapshot list --url__icontains=example.com

    # Update
    archivebox snapshot list --tag=old | archivebox snapshot update --tag=new

    # Delete
    archivebox snapshot list --url__icontains=spam.com | archivebox snapshot delete --yes
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox snapshot'

import sys
from typing import Optional, Iterable

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_utils import apply_filters


# =============================================================================
# CREATE
# =============================================================================

def create_snapshots(
    urls: Iterable[str],
    tag: str = '',
    status: str = 'queued',
    depth: int = 0,
    created_by_id: Optional[int] = None,
) -> int:
    """
    Create Snapshots from URLs or stdin JSONL (Crawl or Snapshot records).
    Pass-through: Records that are not Crawl/Snapshot/URL are output unchanged.

    Exit codes:
        0: Success
        1: Failure
    """
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
    records = list(read_args_or_stdin(urls))

    if not records:
        rprint('[yellow]No URLs or Crawls provided. Pass URLs as arguments or via stdin.[/yellow]', file=sys.stderr)
        return 1

    # Process each record - handle Crawls and plain URLs/Snapshots
    created_snapshots = []
    pass_through_count = 0

    for record in records:
        record_type = record.get('type', '')

        try:
            if record_type == TYPE_CRAWL:
                # Pass through the Crawl record itself first
                if not is_tty:
                    write_record(record)

                # Input is a Crawl - get or create it, then create Snapshots for its URLs
                crawl = None
                crawl_id = record.get('id')
                if crawl_id:
                    try:
                        crawl = Crawl.objects.get(id=crawl_id)
                    except Crawl.DoesNotExist:
                        crawl = Crawl.from_json(record, overrides={'created_by_id': created_by_id})
                else:
                    crawl = Crawl.from_json(record, overrides={'created_by_id': created_by_id})

                if not crawl:
                    continue

                # Create snapshots for each URL in the crawl
                for url in crawl.get_urls_list():
                    merged_tags = crawl.tags_str
                    if tag:
                        merged_tags = f"{merged_tags},{tag}" if merged_tags else tag
                    snapshot_record = {
                        'url': url,
                        'tags': merged_tags,
                        'crawl_id': str(crawl.id),
                        'depth': depth,
                        'status': status,
                    }
                    snapshot = Snapshot.from_json(snapshot_record, overrides={'created_by_id': created_by_id})
                    if snapshot:
                        created_snapshots.append(snapshot)
                        if not is_tty:
                            write_record(snapshot.to_json())

            elif record_type == TYPE_SNAPSHOT or record.get('url'):
                # Input is a Snapshot or plain URL
                if tag and not record.get('tags'):
                    record['tags'] = tag
                if status:
                    record['status'] = status
                record['depth'] = record.get('depth', depth)

                snapshot = Snapshot.from_json(record, overrides={'created_by_id': created_by_id})
                if snapshot:
                    created_snapshots.append(snapshot)
                    if not is_tty:
                        write_record(snapshot.to_json())

            else:
                # Pass-through: output records we don't handle
                if not is_tty:
                    write_record(record)
                pass_through_count += 1

        except Exception as e:
            rprint(f'[red]Error creating snapshot: {e}[/red]', file=sys.stderr)
            continue

    if not created_snapshots:
        if pass_through_count > 0:
            rprint(f'[dim]Passed through {pass_through_count} records, no new snapshots[/dim]', file=sys.stderr)
            return 0
        rprint('[red]No snapshots created[/red]', file=sys.stderr)
        return 1

    rprint(f'[green]Created {len(created_snapshots)} snapshots[/green]', file=sys.stderr)

    if is_tty:
        for snapshot in created_snapshots:
            rprint(f'  [dim]{snapshot.id}[/dim] {snapshot.url[:60]}', file=sys.stderr)

    return 0


# =============================================================================
# LIST
# =============================================================================

def list_snapshots(
    status: Optional[str] = None,
    url__icontains: Optional[str] = None,
    url__istartswith: Optional[str] = None,
    tag: Optional[str] = None,
    crawl_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    List Snapshots as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.core.models import Snapshot

    is_tty = sys.stdout.isatty()

    queryset = Snapshot.objects.all().order_by('-created_at')

    # Apply filters
    filter_kwargs = {
        'status': status,
        'url__icontains': url__icontains,
        'url__istartswith': url__istartswith,
        'crawl_id': crawl_id,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    # Tag filter requires special handling (M2M)
    if tag:
        queryset = queryset.filter(tags__name__iexact=tag)

    count = 0
    for snapshot in queryset:
        if is_tty:
            status_color = {
                'queued': 'yellow',
                'started': 'blue',
                'sealed': 'green',
            }.get(snapshot.status, 'dim')
            rprint(f'[{status_color}]{snapshot.status:8}[/{status_color}] [dim]{snapshot.id}[/dim] {snapshot.url[:60]}')
        else:
            write_record(snapshot.to_json())
        count += 1

    rprint(f'[dim]Listed {count} snapshots[/dim]', file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================

def update_snapshots(
    status: Optional[str] = None,
    tag: Optional[str] = None,
) -> int:
    """
    Update Snapshots from stdin JSONL.

    Reads Snapshot records from stdin and applies updates.
    Uses PATCH semantics - only specified fields are updated.

    Exit codes:
        0: Success
        1: No input or error
    """
    from django.utils import timezone

    from archivebox.misc.jsonl import read_stdin, write_record
    from archivebox.core.models import Snapshot

    is_tty = sys.stdout.isatty()

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        snapshot_id = record.get('id')
        if not snapshot_id:
            continue

        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)

            # Apply updates from CLI flags (override stdin values)
            if status:
                snapshot.status = status
                snapshot.retry_at = timezone.now()
            if tag:
                # Add tag to existing tags
                snapshot.save()  # Ensure saved before M2M
                from archivebox.core.models import Tag
                tag_obj, _ = Tag.objects.get_or_create(name=tag)
                snapshot.tags.add(tag_obj)

            snapshot.save()
            updated_count += 1

            if not is_tty:
                write_record(snapshot.to_json())

        except Snapshot.DoesNotExist:
            rprint(f'[yellow]Snapshot not found: {snapshot_id}[/yellow]', file=sys.stderr)
            continue

    rprint(f'[green]Updated {updated_count} snapshots[/green]', file=sys.stderr)
    return 0


# =============================================================================
# DELETE
# =============================================================================

def delete_snapshots(yes: bool = False, dry_run: bool = False) -> int:
    """
    Delete Snapshots from stdin JSONL.

    Requires --yes flag to confirm deletion.

    Exit codes:
        0: Success
        1: No input or missing --yes flag
    """
    from archivebox.misc.jsonl import read_stdin
    from archivebox.core.models import Snapshot

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    snapshot_ids = [r.get('id') for r in records if r.get('id')]

    if not snapshot_ids:
        rprint('[yellow]No valid snapshot IDs in input[/yellow]', file=sys.stderr)
        return 1

    snapshots = Snapshot.objects.filter(id__in=snapshot_ids)
    count = snapshots.count()

    if count == 0:
        rprint('[yellow]No matching snapshots found[/yellow]', file=sys.stderr)
        return 0

    if dry_run:
        rprint(f'[yellow]Would delete {count} snapshots (dry run)[/yellow]', file=sys.stderr)
        for snapshot in snapshots:
            rprint(f'  [dim]{snapshot.id}[/dim] {snapshot.url[:60]}', file=sys.stderr)
        return 0

    if not yes:
        rprint('[red]Use --yes to confirm deletion[/red]', file=sys.stderr)
        return 1

    # Perform deletion
    deleted_count, _ = snapshots.delete()
    rprint(f'[green]Deleted {deleted_count} snapshots[/green]', file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
def main():
    """Manage Snapshot records."""
    pass


@main.command('create')
@click.argument('urls', nargs=-1)
@click.option('--tag', '-t', default='', help='Comma-separated tags to add')
@click.option('--status', '-s', default='queued', help='Initial status (default: queued)')
@click.option('--depth', '-d', type=int, default=0, help='Crawl depth (default: 0)')
def create_cmd(urls: tuple, tag: str, status: str, depth: int):
    """Create Snapshots from URLs or stdin JSONL."""
    sys.exit(create_snapshots(urls, tag=tag, status=status, depth=depth))


@main.command('list')
@click.option('--status', '-s', help='Filter by status (queued, started, sealed)')
@click.option('--url__icontains', help='Filter by URL contains')
@click.option('--url__istartswith', help='Filter by URL starts with')
@click.option('--tag', '-t', help='Filter by tag name')
@click.option('--crawl-id', help='Filter by crawl ID')
@click.option('--limit', '-n', type=int, help='Limit number of results')
def list_cmd(status: Optional[str], url__icontains: Optional[str], url__istartswith: Optional[str],
             tag: Optional[str], crawl_id: Optional[str], limit: Optional[int]):
    """List Snapshots as JSONL."""
    sys.exit(list_snapshots(
        status=status,
        url__icontains=url__icontains,
        url__istartswith=url__istartswith,
        tag=tag,
        crawl_id=crawl_id,
        limit=limit,
    ))


@main.command('update')
@click.option('--status', '-s', help='Set status')
@click.option('--tag', '-t', help='Add tag')
def update_cmd(status: Optional[str], tag: Optional[str]):
    """Update Snapshots from stdin JSONL."""
    sys.exit(update_snapshots(status=status, tag=tag))


@main.command('delete')
@click.option('--yes', '-y', is_flag=True, help='Confirm deletion')
@click.option('--dry-run', is_flag=True, help='Show what would be deleted')
def delete_cmd(yes: bool, dry_run: bool):
    """Delete Snapshots from stdin JSONL."""
    sys.exit(delete_snapshots(yes=yes, dry_run=dry_run))


if __name__ == '__main__':
    main()
