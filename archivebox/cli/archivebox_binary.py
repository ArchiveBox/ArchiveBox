#!/usr/bin/env python3

"""
archivebox binary <action> [args...] [--filters]

Manage Binary records (detected executables like chrome, wget, etc.).

Actions:
    create  - Create/register a Binary
    list    - List Binaries as JSONL (with optional filters)
    update  - Update Binaries from stdin JSONL
    delete  - Delete Binaries from stdin JSONL

Examples:
    # List all binaries
    archivebox binary list

    # List specific binary
    archivebox binary list --name=chrome

    # List binaries with specific version
    archivebox binary list --version__icontains=120

    # Delete old binary entries
    archivebox binary list --name=chrome | archivebox binary delete --yes
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox binary'

import sys
from typing import Optional

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_utils import apply_filters


# =============================================================================
# CREATE
# =============================================================================

def create_binary(
    name: str,
    abspath: str,
    version: str = '',
) -> int:
    """
    Create/register a Binary.

    Exit codes:
        0: Success
        1: Failure
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.machine.models import Binary

    is_tty = sys.stdout.isatty()

    if not name or not abspath:
        rprint('[red]Both --name and --abspath are required[/red]', file=sys.stderr)
        return 1

    try:
        binary, created = Binary.objects.get_or_create(
            name=name,
            abspath=abspath,
            defaults={'version': version}
        )

        if not is_tty:
            write_record(binary.to_json())

        if created:
            rprint(f'[green]Created binary: {name} at {abspath}[/green]', file=sys.stderr)
        else:
            rprint(f'[dim]Binary already exists: {name} at {abspath}[/dim]', file=sys.stderr)

        return 0

    except Exception as e:
        rprint(f'[red]Error creating binary: {e}[/red]', file=sys.stderr)
        return 1


# =============================================================================
# LIST
# =============================================================================

def list_binaries(
    name: Optional[str] = None,
    abspath__icontains: Optional[str] = None,
    version__icontains: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    List Binaries as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.machine.models import Binary

    is_tty = sys.stdout.isatty()

    queryset = Binary.objects.all().order_by('name', '-loaded_at')

    # Apply filters
    filter_kwargs = {
        'name': name,
        'abspath__icontains': abspath__icontains,
        'version__icontains': version__icontains,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for binary in queryset:
        if is_tty:
            rprint(f'[cyan]{binary.name:20}[/cyan] [dim]{binary.version:15}[/dim] {binary.abspath}')
        else:
            write_record(binary.to_json())
        count += 1

    rprint(f'[dim]Listed {count} binaries[/dim]', file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================

def update_binaries(
    version: Optional[str] = None,
    abspath: Optional[str] = None,
) -> int:
    """
    Update Binaries from stdin JSONL.

    Reads Binary records from stdin and applies updates.
    Uses PATCH semantics - only specified fields are updated.

    Exit codes:
        0: Success
        1: No input or error
    """
    from archivebox.misc.jsonl import read_stdin, write_record
    from archivebox.machine.models import Binary

    is_tty = sys.stdout.isatty()

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        binary_id = record.get('id')
        if not binary_id:
            continue

        try:
            binary = Binary.objects.get(id=binary_id)

            # Apply updates from CLI flags
            if version:
                binary.version = version
            if abspath:
                binary.abspath = abspath

            binary.save()
            updated_count += 1

            if not is_tty:
                write_record(binary.to_json())

        except Binary.DoesNotExist:
            rprint(f'[yellow]Binary not found: {binary_id}[/yellow]', file=sys.stderr)
            continue

    rprint(f'[green]Updated {updated_count} binaries[/green]', file=sys.stderr)
    return 0


# =============================================================================
# DELETE
# =============================================================================

def delete_binaries(yes: bool = False, dry_run: bool = False) -> int:
    """
    Delete Binaries from stdin JSONL.

    Requires --yes flag to confirm deletion.

    Exit codes:
        0: Success
        1: No input or missing --yes flag
    """
    from archivebox.misc.jsonl import read_stdin
    from archivebox.machine.models import Binary

    records = list(read_stdin())
    if not records:
        rprint('[yellow]No records provided via stdin[/yellow]', file=sys.stderr)
        return 1

    binary_ids = [r.get('id') for r in records if r.get('id')]

    if not binary_ids:
        rprint('[yellow]No valid binary IDs in input[/yellow]', file=sys.stderr)
        return 1

    binaries = Binary.objects.filter(id__in=binary_ids)
    count = binaries.count()

    if count == 0:
        rprint('[yellow]No matching binaries found[/yellow]', file=sys.stderr)
        return 0

    if dry_run:
        rprint(f'[yellow]Would delete {count} binaries (dry run)[/yellow]', file=sys.stderr)
        for binary in binaries:
            rprint(f'  {binary.name} {binary.abspath}', file=sys.stderr)
        return 0

    if not yes:
        rprint('[red]Use --yes to confirm deletion[/red]', file=sys.stderr)
        return 1

    # Perform deletion
    deleted_count, _ = binaries.delete()
    rprint(f'[green]Deleted {deleted_count} binaries[/green]', file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
def main():
    """Manage Binary records (detected executables)."""
    pass


@main.command('create')
@click.option('--name', '-n', required=True, help='Binary name (e.g., chrome, wget)')
@click.option('--abspath', '-p', required=True, help='Absolute path to binary')
@click.option('--version', '-v', default='', help='Binary version')
def create_cmd(name: str, abspath: str, version: str):
    """Create/register a Binary."""
    sys.exit(create_binary(name=name, abspath=abspath, version=version))


@main.command('list')
@click.option('--name', '-n', help='Filter by name')
@click.option('--abspath__icontains', help='Filter by path contains')
@click.option('--version__icontains', help='Filter by version contains')
@click.option('--limit', type=int, help='Limit number of results')
def list_cmd(name: Optional[str], abspath__icontains: Optional[str],
             version__icontains: Optional[str], limit: Optional[int]):
    """List Binaries as JSONL."""
    sys.exit(list_binaries(
        name=name,
        abspath__icontains=abspath__icontains,
        version__icontains=version__icontains,
        limit=limit,
    ))


@main.command('update')
@click.option('--version', '-v', help='Set version')
@click.option('--abspath', '-p', help='Set path')
def update_cmd(version: Optional[str], abspath: Optional[str]):
    """Update Binaries from stdin JSONL."""
    sys.exit(update_binaries(version=version, abspath=abspath))


@main.command('delete')
@click.option('--yes', '-y', is_flag=True, help='Confirm deletion')
@click.option('--dry-run', is_flag=True, help='Show what would be deleted')
def delete_cmd(yes: bool, dry_run: bool):
    """Delete Binaries from stdin JSONL."""
    sys.exit(delete_binaries(yes=yes, dry_run=dry_run))


if __name__ == '__main__':
    main()
