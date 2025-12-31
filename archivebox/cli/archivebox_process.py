#!/usr/bin/env python3

"""
archivebox process <action> [--filters]

Manage Process records (system-managed, mostly read-only).

Process records track executions of binaries during extraction.
They are created automatically by the system and are primarily for debugging.

Actions:
    list    - List Processes as JSONL (with optional filters)

Examples:
    # List all processes
    archivebox process list

    # List processes by binary
    archivebox process list --binary-name=chrome

    # List recent processes
    archivebox process list --limit=10
"""

__package__ = 'archivebox.cli'
__command__ = 'archivebox process'

import sys
from typing import Optional

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_utils import apply_filters


# =============================================================================
# LIST
# =============================================================================

def list_processes(
    binary_name: Optional[str] = None,
    machine_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    List Processes as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.machine.models import Process

    is_tty = sys.stdout.isatty()

    queryset = Process.objects.all().select_related('binary', 'machine').order_by('-start_ts')

    # Apply filters
    filter_kwargs = {}
    if binary_name:
        filter_kwargs['binary__name'] = binary_name
    if machine_id:
        filter_kwargs['machine_id'] = machine_id

    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for process in queryset:
        if is_tty:
            binary_name_str = process.binary.name if process.binary else 'unknown'
            exit_code = process.returncode if process.returncode is not None else '?'
            status_color = 'green' if process.returncode == 0 else 'red' if process.returncode else 'yellow'
            rprint(f'[{status_color}]exit={exit_code:3}[/{status_color}] [cyan]{binary_name_str:15}[/cyan] [dim]{process.id}[/dim]')
        else:
            write_record(process.to_json())
        count += 1

    rprint(f'[dim]Listed {count} processes[/dim]', file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================

@click.group()
def main():
    """Manage Process records (read-only, system-managed)."""
    pass


@main.command('list')
@click.option('--binary-name', '-b', help='Filter by binary name')
@click.option('--machine-id', '-m', help='Filter by machine ID')
@click.option('--limit', '-n', type=int, help='Limit number of results')
def list_cmd(binary_name: Optional[str], machine_id: Optional[str], limit: Optional[int]):
    """List Processes as JSONL."""
    sys.exit(list_processes(
        binary_name=binary_name,
        machine_id=machine_id,
        limit=limit,
    ))


if __name__ == '__main__':
    main()
