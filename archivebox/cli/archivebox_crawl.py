#!/usr/bin/env python3

"""
archivebox crawl <action> [args...] [--filters]

Manage Crawl records.

Actions:
    create  - Create Crawl jobs from URLs
    list    - List Crawls as JSONL (with optional filters)
    update  - Update Crawls from stdin JSONL
    delete  - Delete Crawls from stdin JSONL

Examples:
    # Create
    archivebox crawl create https://example.com https://foo.com --depth=1
    archivebox crawl create --tag=news https://example.com

    # List with filters
    archivebox crawl list --status=queued
    archivebox crawl list --urls__icontains=example.com

    # Update
    archivebox crawl list --status=started | archivebox crawl update --status=queued

    # Delete
    archivebox crawl list --urls__icontains=spam.com | archivebox crawl delete --yes

    # Full pipeline
    archivebox crawl create https://example.com | archivebox snapshot create | archivebox run
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox crawl'

import sys
from typing import Optional, Iterable

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_utils import apply_filters


# =============================================================================
# CREATE
# =============================================================================

def create_crawl(
    urls: Iterable[str],
    depth: int = 0,
    tag: str = '',
    status: str = 'queued',
    created_by_id: Optional[int] = None,
) -> int:
    """
    Create a Crawl job from URLs.

    Takes URLs as args or stdin, creates one Crawl with all URLs, outputs JSONL.
    Pass-through: Records that are not URLs are output unchanged (for piping).

    Exit codes:
        0: Success
        1: Failure
    """
    from archivebox.misc.jsonl import read_args_or_stdin, write_record, TYPE_CRAWL
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.crawls.models import Crawl

    created_by_id = created_by_id or get_or_create_system_user_pk()
    is_tty = sys.stdout.isatty()

    # Collect all input records
    records = list(read_args_or_stdin(urls))

    if not records:
        rprint('[yellow]No URLs provided. Pass URLs as arguments or via stdin.[/yellow]', file=sys.stderr)
        return 1

    # Separate pass-through records from URL records
    url_list = []
    pass_through_records = []

    for record in records:
        record_type = record.get('type', '')

        # Pass-through: output records that aren't URL/Crawl types
        if record_type and record_type != TYPE_CRAWL and not record.get('url') and not record.get('urls'):
            pass_through_records.append(record)
            continue

        # Handle existing Crawl records (just pass through with id)
        if record_type == TYPE_CRAWL and record.get('id'):
            pass_through_records.append(record)
            continue

        # Collect URLs
        url = record.get('url')
        if url:
            url_list.append(url)

        # Handle 'urls' field (newline-separated)
        urls_field = record.get('urls')
        if urls_field:
            for line in urls_field.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    url_list.append(line)

    # Output pass-through records first
    if not is_tty:
        for record in pass_through_records:
            write_record(record)

    if not url_list:
        if pass_through_records:
            # If we had pass-through records but no URLs, that's OK
            rprint(f'[dim]Passed through {len(pass_through_records)} records, no new URLs[/dim]', file=sys.stderr)
            return 0
        rprint('[red]No valid URLs found[/red]', file=sys.stderr)
        return 1

    try:
        # Build crawl record with all URLs as newline-separated string
        crawl_record = {
            'urls': '\n'.join(url_list),
            'max_depth': depth,
            'tags_str': tag,
            'status': status,
            'label': '',
        }

        crawl = Crawl.from_json(crawl_record, overrides={'created_by_id': created_by_id})
        if not crawl:
            rprint('[red]Failed to create crawl[/red]', file=sys.stderr)
            return 1

        # Output JSONL record (only when piped)
        if not is_tty:
            write_record(crawl.to_json())

        rprint(f'[green]Created crawl with {len(url_list)} URLs[/green]', file=sys.stderr)

        # If TTY, show human-readable output
        if is_tty:
            rprint(f'  [dim]{crawl.id}[/dim]', file=sys.stderr)
            for url in url_list[:5]:  # Show first 5 URLs
                rprint(f'    {url[:70]}', file=sys.stderr)
            if len(url_list) > 5:
                rprint(f'    ... and {len(url_list) - 5} more', file=sys.stderr)

        return 0

    except Exception as e:
        rprint(f'[red]Error creating crawl: {e}[/red]', file=sys.stderr)
        return 1


# =============================================================================
# LIST
# =============================================================================

def list_crawls(
    status: Optional[str] = None,
    urls__icontains: Optional[str] = None,
    max_depth: Optional[int] = None,
    limit: Optional[int] = None,
) -> int:
    """
    List Crawls as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.crawls.models import Crawl

    is_tty = sys.stdout.isatty()

    queryset = Crawl.objects.all().order_by('-created_at')

    # Apply filters
    filter_kwargs = {
        'status': status,
        'urls__icontains': urls__icontains,
        'max_depth': max_depth,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for crawl in queryset:
        if is_tty:
            status_color = {
                'queued': 'yellow',
                'started': 'blue',
                'sealed': 'green',
            }.get(crawl.status, 'dim')
            url_preview = crawl.urls[:50].replace('\n', ' ')
            rprint(f'[{status_color}]{crawl.status:8}[/{status_color}] [dim]{crawl.id}[/dim] {url_preview}...')
        else:
            write_record(crawl.to_json())
        count += 1

    rprint(f'[dim]Listed {count} crawls[/dim]', file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================

def update_crawls(
    status: Optional[str] = None,
    max_depth: Optional[int] = None,
) -> int:
    """
    Update Crawls from stdin JSONL.

    Reads Crawl records from stdin and applies updates.
    Uses PATCH semantics - only specified fields are updated.

    Exit codes:
        0: Success
        1: No input or error
    """
    from django.utils import timezone

    from archivebox.misc.jsonl import read_stdin, write_record
    from archivebox.crawls.models import Crawl

    is_tty = sys.stdout.isatty()

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        crawl_id = record.get('id')
        if not crawl_id:
            continue

        try:
            crawl = Crawl.objects.get(id=crawl_id)

            # Apply updates from CLI flags
            if status:
                crawl.status = status
                crawl.retry_at = timezone.now()
            if max_depth is not None:
                crawl.max_depth = max_depth

            crawl.save()
            updated_count += 1

            if not is_tty:
                write_record(crawl.to_json())

        except Crawl.DoesNotExist:
            rprint(f'[yellow]Crawl not found: {crawl_id}[/yellow]', file=sys.stderr)
            continue

    rprint(f'[green]Updated {updated_count} crawls[/green]', file=sys.stderr)
    return 0


# =============================================================================
# DELETE
# =============================================================================

def delete_crawls(yes: bool = False, dry_run: bool = False) -> int:
    """
    Delete Crawls from stdin JSONL.

    Requires --yes flag to confirm deletion.

    Exit codes:
        0: Success
        1: No input or missing --yes flag
    """
    from archivebox.misc.jsonl import read_stdin
    from archivebox.crawls.models import Crawl

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    crawl_ids = [r.get('id') for r in records if r.get('id')]

    if not crawl_ids:
        rprint('[yellow]No valid crawl IDs in input[/yellow]', file=sys.stderr)
        return 1

    crawls = Crawl.objects.filter(id__in=crawl_ids)
    count = crawls.count()

    if count == 0:
        rprint('[yellow]No matching crawls found[/yellow]', file=sys.stderr)
        return 0

    if dry_run:
        rprint(f'[yellow]Would delete {count} crawls (dry run)[/yellow]', file=sys.stderr)
        for crawl in crawls:
            url_preview = crawl.urls[:50].replace('\n', ' ')
            rprint(f'  [dim]{crawl.id}[/dim] {url_preview}...', file=sys.stderr)
        return 0

    if not yes:
        rprint('[red]Use --yes to confirm deletion[/red]', file=sys.stderr)
        return 1

    # Perform deletion
    deleted_count, _ = crawls.delete()
    rprint(f'[green]Deleted {deleted_count} crawls[/green]', file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
def main():
    """Manage Crawl records."""
    pass


@main.command('create')
@click.argument('urls', nargs=-1)
@click.option('--depth', '-d', type=int, default=0, help='Max crawl depth (default: 0)')
@click.option('--tag', '-t', default='', help='Comma-separated tags to add')
@click.option('--status', '-s', default='queued', help='Initial status (default: queued)')
def create_cmd(urls: tuple, depth: int, tag: str, status: str):
    """Create a Crawl job from URLs or stdin."""
    sys.exit(create_crawl(urls, depth=depth, tag=tag, status=status))


@main.command('list')
@click.option('--status', '-s', help='Filter by status (queued, started, sealed)')
@click.option('--urls__icontains', help='Filter by URLs contains')
@click.option('--max-depth', type=int, help='Filter by max depth')
@click.option('--limit', '-n', type=int, help='Limit number of results')
def list_cmd(status: Optional[str], urls__icontains: Optional[str],
             max_depth: Optional[int], limit: Optional[int]):
    """List Crawls as JSONL."""
    sys.exit(list_crawls(
        status=status,
        urls__icontains=urls__icontains,
        max_depth=max_depth,
        limit=limit,
    ))


@main.command('update')
@click.option('--status', '-s', help='Set status')
@click.option('--max-depth', type=int, help='Set max depth')
def update_cmd(status: Optional[str], max_depth: Optional[int]):
    """Update Crawls from stdin JSONL."""
    sys.exit(update_crawls(status=status, max_depth=max_depth))


@main.command('delete')
@click.option('--yes', '-y', is_flag=True, help='Confirm deletion')
@click.option('--dry-run', is_flag=True, help='Show what would be deleted')
def delete_cmd(yes: bool, dry_run: bool):
    """Delete Crawls from stdin JSONL."""
    sys.exit(delete_crawls(yes=yes, dry_run=dry_run))


if __name__ == '__main__':
    main()
