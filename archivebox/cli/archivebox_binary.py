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

__package__ = "archivebox.cli"
__command__ = "archivebox binary"

import sys

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_util import apply_filters


# =============================================================================
# CREATE
# =============================================================================


def create_binary(
    name: str,
    abspath: str,
    version: str = "",
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
        rprint("[red]Both --name and --abspath are required[/red]", file=sys.stderr)
        return 1

    try:
        from archivebox.machine.models import Machine

        machine = Machine.current()
        created = not Binary.objects.filter(
            machine=machine,
            name=name,
            abspath=abspath,
            version=version,
        ).exists()

        # Mirror the Binary model lifecycle used elsewhere in the system so CLI
        # records are owned by the current machine and can be safely piped into
        # `archivebox run` without creating invalid rows missing machine_id.
        binary = Binary.from_json(
            {
                "name": name,
                "abspath": abspath,
                "version": version,
                "binproviders": "env",
                "binprovider": "env",
            },
        )
        if binary is None:
            raise ValueError("failed to create binary record")

        if not is_tty:
            write_record(binary.to_json())

        if created:
            rprint(f"[green]Created binary: {name} at {abspath}[/green]", file=sys.stderr)
        else:
            rprint(f"[dim]Binary already exists: {name} at {abspath}[/dim]", file=sys.stderr)

        return 0

    except Exception as e:
        rprint(f"[red]Error creating binary: {e}[/red]", file=sys.stderr)
        return 1


# =============================================================================
# LIST
# =============================================================================


def list_binaries(
    name: str | None = None,
    abspath__icontains: str | None = None,
    version__icontains: str | None = None,
    limit: int | None = None,
) -> int:
    """List binaries as JSONL, or formatted rows in a terminal."""
    from archivebox.machine.models import Binary
    from archivebox.cli.cli_util import list_records

    queryset = apply_filters(
        Binary.objects.order_by("name", "-modified_at", "-created_at"),
        {"name": name, "abspath__icontains": abspath__icontains, "version__icontains": version__icontains},
        limit=limit,
    )
    return list_records(
        queryset,
        plural="binaries",
        render=lambda binary: f"[cyan]{binary.name:20}[/cyan] [dim]{binary.version:15}[/dim] {binary.abspath}",
    )


# =============================================================================
# UPDATE
# =============================================================================


def update_binaries(version: str | None = None, abspath: str | None = None) -> int:
    """Apply supplied fields to each JSONL-selected Binary."""
    from archivebox.machine.models import Binary
    from archivebox.cli.cli_util import update_records

    def update(binary):
        if version:
            binary.version = version
        if abspath:
            binary.abspath = abspath
        binary.save()

    return update_records(Binary, update, plural="binaries")


# =============================================================================
# DELETE
# =============================================================================


def delete_binaries(yes: bool = False, dry_run: bool = False) -> int:
    """Delete binaries selected by stdin JSONL; --yes confirms, --dry-run previews."""
    from archivebox.cli.cli_util import delete_records
    from archivebox.machine.models import Binary

    return delete_records(
        Binary,
        label="binary",
        plural="binaries",
        preview=lambda obj: f"{obj.name} {obj.abspath}",
        yes=yes,
        dry_run=dry_run,
    )


# =============================================================================
# CLI Commands
# =============================================================================


@click.group()
def main():
    """Manage Binary records (detected executables)."""
    pass


@main.command("create")
@click.option("--name", "-n", required=True, help="Binary name (e.g., chrome, wget)")
@click.option("--abspath", "-p", required=True, help="Absolute path to binary")
@click.option("--version", "-v", default="", help="Binary version")
def create_cmd(**kwargs):
    """Create/register a Binary."""
    sys.exit(create_binary(**kwargs))


@main.command("list")
@click.option("--name", "-n", help="Filter by name")
@click.option("--abspath__icontains", help="Filter by path contains")
@click.option("--version__icontains", help="Filter by version contains")
@click.option("--limit", type=int, help="Limit number of results")
def list_cmd(**kwargs):
    """List Binaries as JSONL."""
    sys.exit(list_binaries(**kwargs))


@main.command("update")
@click.option("--version", "-v", help="Set version")
@click.option("--abspath", "-p", help="Set path")
def update_cmd(**kwargs):
    """Update Binaries from stdin JSONL."""
    sys.exit(update_binaries(**kwargs))


@main.command("delete")
@click.option("--yes", "-y", is_flag=True, help="Confirm deletion")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
def delete_cmd(**kwargs):
    """Delete Binaries from stdin JSONL."""
    sys.exit(delete_binaries(**kwargs))


if __name__ == "__main__":
    main()
