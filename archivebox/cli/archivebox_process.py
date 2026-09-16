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

__package__ = "archivebox.cli"
__command__ = "archivebox process"

import sys

import rich_click as click

from archivebox.cli.cli_util import apply_filters


# =============================================================================
# LIST
# =============================================================================


def list_processes(binary_name: str | None = None, machine_id: str | None = None, limit: int | None = None) -> int:
    """List processes as JSONL, or exit codes and binary names in a terminal."""
    from archivebox.machine.models import Process
    from archivebox.cli.cli_util import list_records

    def render(process):
        name = process.binary.name if process.binary else "unknown"
        exit_code = process.exit_code if process.exit_code is not None else "?"
        color = "green" if process.exit_code == 0 else "red" if process.exit_code else "yellow"
        return f"[{color}]exit={exit_code:3}[/{color}] [cyan]{name:15}[/cyan] [dim]{process.id}[/dim]"

    queryset = Process.objects.select_related("binary", "machine").order_by("-started_at", "-created_at")
    filters = {"binary__name": binary_name or None, "machine_id": machine_id or None}
    return list_records(apply_filters(queryset, filters, limit=limit), plural="processes", render=render)


# =============================================================================
# CLI Commands
# =============================================================================


@click.group()
def main():
    """Manage Process records (read-only, system-managed)."""
    pass


@main.command("list")
@click.option("--binary-name", "-b", help="Filter by binary name")
@click.option("--machine-id", "-m", help="Filter by machine ID")
@click.option("--limit", "-n", type=int, help="Limit number of results")
def list_cmd(binary_name: str | None, machine_id: str | None, limit: int | None):
    """List Processes as JSONL."""
    sys.exit(
        list_processes(
            binary_name=binary_name,
            machine_id=machine_id,
            limit=limit,
        ),
    )


if __name__ == "__main__":
    main()
