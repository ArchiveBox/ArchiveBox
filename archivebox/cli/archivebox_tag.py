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

__package__ = "archivebox.cli"
__command__ = "archivebox tag"

import sys
from collections.abc import Iterable

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_util import apply_filters


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
        rprint("[yellow]No tag names provided. Pass names as arguments.[/yellow]", file=sys.stderr)
        return 1

    created_count = 0
    for name in name_list:
        name = name.strip()
        if not name:
            continue

        tag, created = Tag.get_or_create_by_name(name)

        if not is_tty:
            write_record(tag.to_json())

        if created:
            created_count += 1
            rprint(f"[green]Created tag: {name}[/green]", file=sys.stderr)
        else:
            rprint(f"[dim]Tag already exists: {name}[/dim]", file=sys.stderr)

    rprint(f"[green]Created {created_count} new tags[/green]", file=sys.stderr)
    return 0


# =============================================================================
# LIST
# =============================================================================


def list_tags(name: str | None = None, name__icontains: str | None = None, limit: int | None = None) -> int:
    """List tags as JSONL, or formatted rows in a terminal."""
    from archivebox.core.models import Tag
    from archivebox.cli.cli_util import list_records

    queryset = apply_filters(Tag.objects.order_by("name"), {"name": name, "name__icontains": name__icontains}, limit=limit)
    return list_records(
        queryset,
        plural="tags",
        render=lambda tag: f"[cyan]{tag.name:30}[/cyan] [dim]({tag.snapshot_set.count()} snapshots)[/dim]",
    )


# =============================================================================
# UPDATE
# =============================================================================


def update_tags(name: str | None = None) -> int:
    """Apply supplied fields to each JSONL-selected Tag."""
    from archivebox.core.models import Tag
    from archivebox.cli.cli_util import update_records

    def update(tag):
        if name:
            tag.rename(name)

    return update_records(Tag, update, plural="tags", by_name=True)


# =============================================================================
# DELETE
# =============================================================================


def delete_tags(yes: bool = False, dry_run: bool = False) -> int:
    """Delete tags selected by stdin JSONL; --yes confirms, --dry-run previews."""
    from archivebox.cli.cli_util import delete_records
    from archivebox.core.models import Tag

    return delete_records(
        Tag,
        label="tag",
        plural="tags",
        preview=lambda obj: obj.name,
        yes=yes,
        dry_run=dry_run,
        by_name=True,
    )


# =============================================================================
# CLI Commands
# =============================================================================


@click.group()
def main():
    """Manage Tag records."""
    pass


@main.command("create")
@click.argument("names", nargs=-1)
def create_cmd(names: tuple):
    """Create Tags from names."""
    sys.exit(create_tags(names))


@main.command("list")
@click.option("--name", help="Filter by exact name")
@click.option("--name__icontains", help="Filter by name contains")
@click.option("--limit", "-n", type=int, help="Limit number of results")
def list_cmd(name: str | None, name__icontains: str | None, limit: int | None):
    """List Tags as JSONL."""
    sys.exit(list_tags(name=name, name__icontains=name__icontains, limit=limit))


@main.command("update")
@click.option("--name", "-n", help="Set new name")
def update_cmd(name: str | None):
    """Update Tags from stdin JSONL."""
    sys.exit(update_tags(name=name))


@main.command("delete")
@click.option("--yes", "-y", is_flag=True, help="Confirm deletion")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
def delete_cmd(yes: bool, dry_run: bool):
    """Delete Tags from stdin JSONL."""
    sys.exit(delete_tags(yes=yes, dry_run=dry_run))


if __name__ == "__main__":
    main()
