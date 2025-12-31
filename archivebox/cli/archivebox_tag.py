#!/usr/bin/env python3

"""
archivebox tag <action> [args...] [--filters]

Manage Tag records.

Actions:
    create  - Create Tags
    list    - List Tags as JSONL (with optional filters)
    update  - Update Tags from stdin JSONL
    delete  - Delete Tags from stdin JSONL

Examples:
    # Create
    archivebox tag create news tech science
    archivebox tag create "important stuff"

    # List
    archivebox tag list
    archivebox tag list --name__icontains=news

    # Update (rename tags)
    archivebox tag list --name=oldname | archivebox tag update --name=newname

    # Delete
    archivebox tag list --name=unused | archivebox tag delete --yes
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox tag'

import sys
from typing import Optional, Iterable

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_utils import apply_filters


# =============================================================================
# CREATE
# =============================================================================

def create_tags(names: Iterable[str]) -> int:
    """
    Create Tags from names.

    Exit codes:
        0: Success
        1: Failure
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.core.models import Tag

    is_tty = sys.stdout.isatty()

    # Convert to list if needed
    name_list = list(names) if names else []

    if not name_list:
        rprint('[yellow]No tag names provided. Pass names as arguments.[/yellow]', file=sys.stderr)
        return 1

    created_count = 0
    for name in name_list:
        name = name.strip()
        if not name:
            continue

        tag, created = Tag.objects.get_or_create(name=name)

        if not is_tty:
            write_record(tag.to_json())

        if created:
            created_count += 1
            rprint(f'[green]Created tag: {name}[/green]', file=sys.stderr)
        else:
            rprint(f'[dim]Tag already exists: {name}[/dim]', file=sys.stderr)

    rprint(f'[green]Created {created_count} new tags[/green]', file=sys.stderr)
    return 0


# =============================================================================
# LIST
# =============================================================================

def list_tags(
    name: Optional[str] = None,
    name__icontains: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    List Tags as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.core.models import Tag

    is_tty = sys.stdout.isatty()

    queryset = Tag.objects.all().order_by('name')

    # Apply filters
    filter_kwargs = {
        'name': name,
        'name__icontains': name__icontains,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for tag in queryset:
        snapshot_count = tag.snapshot_set.count()
        if is_tty:
            rprint(f'[cyan]{tag.name:30}[/cyan] [dim]({snapshot_count} snapshots)[/dim]')
        else:
            write_record(tag.to_json())
        count += 1

    rprint(f'[dim]Listed {count} tags[/dim]', file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================

def update_tags(name: Optional[str] = None) -> int:
    """
    Update Tags from stdin JSONL.

    Reads Tag records from stdin and applies updates.
    Uses PATCH semantics - only specified fields are updated.

    Exit codes:
        0: Success
        1: No input or error
    """
    from archivebox.misc.jsonl import read_stdin, write_record
    from archivebox.core.models import Tag

    is_tty = sys.stdout.isatty()

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        tag_id = record.get('id')
        old_name = record.get('name')

        if not tag_id and not old_name:
            continue

        try:
            if tag_id:
                tag = Tag.objects.get(id=tag_id)
            else:
                tag = Tag.objects.get(name=old_name)

            # Apply updates from CLI flags
            if name:
                tag.name = name
                tag.save()

            updated_count += 1

            if not is_tty:
                write_record(tag.to_json())

        except Tag.DoesNotExist:
            rprint(f'[yellow]Tag not found: {tag_id or old_name}[/yellow]', file=sys.stderr)
            continue

    rprint(f'[green]Updated {updated_count} tags[/green]', file=sys.stderr)
    return 0


# =============================================================================
# DELETE
# =============================================================================

def delete_tags(yes: bool = False, dry_run: bool = False) -> int:
    """
    Delete Tags from stdin JSONL.

    Requires --yes flag to confirm deletion.

    Exit codes:
        0: Success
        1: No input or missing --yes flag
    """
    from archivebox.misc.jsonl import read_stdin
    from archivebox.core.models import Tag

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    # Collect tag IDs or names
    tag_ids = []
    tag_names = []
    for r in records:
        if r.get('id'):
            tag_ids.append(r['id'])
        elif r.get('name'):
            tag_names.append(r['name'])

    if not tag_ids and not tag_names:
        rprint('[yellow]No valid tag IDs or names in input[/yellow]', file=sys.stderr)
        return 1

    from django.db.models import Q
    query = Q()
    if tag_ids:
        query |= Q(id__in=tag_ids)
    if tag_names:
        query |= Q(name__in=tag_names)

    tags = Tag.objects.filter(query)
    count = tags.count()

    if count == 0:
        rprint('[yellow]No matching tags found[/yellow]', file=sys.stderr)
        return 0

    if dry_run:
        rprint(f'[yellow]Would delete {count} tags (dry run)[/yellow]', file=sys.stderr)
        for tag in tags:
            rprint(f'  {tag.name}', file=sys.stderr)
        return 0

    if not yes:
        rprint('[red]Use --yes to confirm deletion[/red]', file=sys.stderr)
        return 1

    # Perform deletion
    deleted_count, _ = tags.delete()
    rprint(f'[green]Deleted {deleted_count} tags[/green]', file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
def main():
    """Manage Tag records."""
    pass


@main.command('create')
@click.argument('names', nargs=-1)
def create_cmd(names: tuple):
    """Create Tags from names."""
    sys.exit(create_tags(names))


@main.command('list')
@click.option('--name', help='Filter by exact name')
@click.option('--name__icontains', help='Filter by name contains')
@click.option('--limit', '-n', type=int, help='Limit number of results')
def list_cmd(name: Optional[str], name__icontains: Optional[str], limit: Optional[int]):
    """List Tags as JSONL."""
    sys.exit(list_tags(name=name, name__icontains=name__icontains, limit=limit))


@main.command('update')
@click.option('--name', '-n', help='Set new name')
def update_cmd(name: Optional[str]):
    """Update Tags from stdin JSONL."""
    sys.exit(update_tags(name=name))


@main.command('delete')
@click.option('--yes', '-y', is_flag=True, help='Confirm deletion')
@click.option('--dry-run', is_flag=True, help='Show what would be deleted')
def delete_cmd(yes: bool, dry_run: bool):
    """Delete Tags from stdin JSONL."""
    sys.exit(delete_tags(yes=yes, dry_run=dry_run))


if __name__ == '__main__':
    main()
