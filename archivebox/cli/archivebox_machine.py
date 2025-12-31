#!/usr/bin/env python3

"""
archivebox machine <action> [--filters]

Manage Machine records (system-managed, mostly read-only).

Machine records track the host machines where ArchiveBox runs.
They are created automatically by the system and are primarily for debugging.

Actions:
    list    - List Machines as JSONL (with optional filters)

Examples:
    # List all machines
    archivebox machine list

    # List machines by hostname
    archivebox machine list --hostname__icontains=myserver
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox machine'

import sys
from typing import Optional

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_utils import apply_filters


# =============================================================================
# LIST
# =============================================================================

def list_machines(
    hostname__icontains: Optional[str] = None,
    os_platform: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    List Machines as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.machine.models import Machine

    is_tty = sys.stdout.isatty()

    queryset = Machine.objects.all().order_by('-created_at')

    # Apply filters
    filter_kwargs = {
        'hostname__icontains': hostname__icontains,
        'os_platform': os_platform,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for machine in queryset:
        if is_tty:
            rprint(f'[cyan]{machine.hostname:30}[/cyan] [dim]{machine.os_platform:10}[/dim] {machine.id}')
        else:
            write_record(machine.to_json())
        count += 1

    rprint(f'[dim]Listed {count} machines[/dim]', file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
def main():
    """Manage Machine records (read-only, system-managed)."""
    pass


@main.command('list')
@click.option('--hostname__icontains', help='Filter by hostname contains')
@click.option('--os-platform', help='Filter by OS platform')
@click.option('--limit', '-n', type=int, help='Limit number of results')
def list_cmd(hostname__icontains: Optional[str], os_platform: Optional[str], limit: Optional[int]):
    """List Machines as JSONL."""
    sys.exit(list_machines(
        hostname__icontains=hostname__icontains,
        os_platform=os_platform,
        limit=limit,
    ))


if __name__ == '__main__':
    main()
