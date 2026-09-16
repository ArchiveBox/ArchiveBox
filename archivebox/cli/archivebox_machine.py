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

__package__ = "archivebox.cli"
__command__ = "archivebox machine"

import sys

import rich_click as click

from archivebox.cli.cli_util import apply_filters


# =============================================================================
# LIST
# =============================================================================


def list_machines(hostname__icontains: str | None = None, os_platform: str | None = None, limit: int | None = None) -> int:
    """List machines as JSONL, or formatted rows in a terminal."""
    from archivebox.machine.models import Machine
    from archivebox.cli.cli_util import list_records

    queryset = apply_filters(
        Machine.objects.order_by("-created_at"),
        {"hostname__icontains": hostname__icontains, "os_platform": os_platform},
        limit=limit,
    )
    return list_records(
        queryset,
        plural="machines",
        render=lambda machine: f"[cyan]{machine.hostname:30}[/cyan] [dim]{machine.os_platform:10}[/dim] {machine.id}",
    )


# =============================================================================
# CLI Commands
# =============================================================================


@click.group()
def main():
    """Manage Machine records (read-only, system-managed)."""
    pass


@main.command("list")
@click.option("--hostname__icontains", help="Filter by hostname contains")
@click.option("--os-platform", help="Filter by OS platform")
@click.option("--limit", "-n", type=int, help="Limit number of results")
def list_cmd(hostname__icontains: str | None, os_platform: str | None, limit: int | None):
    """List Machines as JSONL."""
    sys.exit(
        list_machines(
            hostname__icontains=hostname__icontains,
            os_platform=os_platform,
            limit=limit,
        ),
    )


if __name__ == "__main__":
    main()
