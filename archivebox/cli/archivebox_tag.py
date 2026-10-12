#!/usr/bin/env python3

"""
archivebox tag <action> [args...] [--filters]

Manage Tag records.

Actions:
    create  - Create Tags
    list    - List Tags as JSONL (with optional filters)
    update  - Update Tags from stdin JSONL
    delete  - Delete Tags from stdin JSONL
    repair  - Remove one-character tags split out of other tag names

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

    # Repair tags split into single characters (preview first)
    archivebox tag repair --dry-run
    archivebox tag repair --yes
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

        tag, created = Tag.objects.get_or_create(name=name)

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


def list_tags(
    name: str | None = None,
    name__icontains: str | None = None,
    limit: int | None = None,
) -> int:
    """
    List Tags as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record
    from archivebox.core.models import Tag

    is_tty = sys.stdout.isatty()

    queryset = Tag.objects.all().order_by("name")

    # Apply filters
    filter_kwargs = {
        "name": name,
        "name__icontains": name__icontains,
    }
    queryset = apply_filters(queryset, filter_kwargs, limit=limit)

    count = 0
    for tag in queryset:
        snapshot_count = tag.snapshot_set.count()
        if is_tty:
            rprint(f"[cyan]{tag.name:30}[/cyan] [dim]({snapshot_count} snapshots)[/dim]")
        else:
            write_record(tag.to_json())
        count += 1

    rprint(f"[dim]Listed {count} tags[/dim]", file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================


def update_tags(name: str | None = None) -> int:
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
        rprint("[yellow]No records provided via stdin[/yellow]", file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        tag_id = record.get("id")
        old_name = record.get("name")

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
            rprint(f"[yellow]Tag not found: {tag_id or old_name}[/yellow]", file=sys.stderr)
            continue

    rprint(f"[green]Updated {updated_count} tags[/green]", file=sys.stderr)
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
        rprint("[yellow]No records provided via stdin[/yellow]", file=sys.stderr)
        return 1

    # Collect tag IDs or names
    tag_ids = []
    tag_names = []
    for r in records:
        if r.get("id"):
            tag_ids.append(r["id"])
        elif r.get("name"):
            tag_names.append(r["name"])

    if not tag_ids and not tag_names:
        rprint("[yellow]No valid tag IDs or names in input[/yellow]", file=sys.stderr)
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
        rprint("[yellow]No matching tags found[/yellow]", file=sys.stderr)
        return 0

    if dry_run:
        rprint(f"[yellow]Would delete {count} tags (dry run)[/yellow]", file=sys.stderr)
        for tag in tags:
            rprint(f"  {tag.name}", file=sys.stderr)
        return 0

    if not yes:
        rprint("[red]Use --yes to confirm deletion[/red]", file=sys.stderr)
        return 1

    # Perform deletion
    deleted_count, _ = tags.delete()
    rprint(f"[green]Deleted {deleted_count} tags[/green]", file=sys.stderr)
    return 0


# =============================================================================
# REPAIR
# =============================================================================


def exploded_tag_ids(tags: dict[int, str]) -> set[int]:
    """Return the IDs of one-character tags that are a split-up copy of the other tags.

    WHY: a tag string iterated character by character ("abc5,test" -> "a", "b",
    "c", "5", ",", "t", ...) leaves every character of the snapshot's real tags,
    including the "," separator, as its own tag next to the real ones. A tag is
    only treated as such a fragment when every one-character tag on the snapshot
    is a character of its comma-joined longer tags AND those characters spell out
    all of at least one longer tag. A deliberate short tag ("x", or "5" next to
    "abc5") never satisfies both, so it is kept.
    """
    chars = {tag_id: name.lower() for tag_id, name in tags.items() if len(name) == 1}
    longer = [name.lower() for name in tags.values() if len(name) > 1]
    if not chars or not longer:
        return set()
    if not set(chars.values()) <= set(",".join(longer)):
        return set()
    if not any(set(name) <= set(chars.values()) for name in longer):
        return set()
    return set(chars)


def repair_tags(yes: bool = False, dry_run: bool = False) -> int:
    """
    Remove one-character tags that were created by splitting a tag string into characters.

    Exit codes:
        0: Success (including nothing to repair)
        1: Missing --yes flag
    """
    from collections import defaultdict

    from django.db.models.functions import Length
    from rich.markup import escape

    from archivebox.core.models import Snapshot, SnapshotTag, Tag

    char_tag_ids = list(Tag.objects.annotate(name_length=Length("name")).filter(name_length=1).values_list("id", flat=True))
    candidate_ids = list(SnapshotTag.objects.filter(tag_id__in=char_tag_ids).values_list("snapshot_id", flat=True).distinct())

    repairs: dict[object, set[int]] = {}
    # Chunk the reads so collections with many affected snapshots stay bounded.
    for start in range(0, len(candidate_ids), 500):
        tags_by_snapshot: dict[object, dict[int, str]] = defaultdict(dict)
        rows = SnapshotTag.objects.filter(snapshot_id__in=candidate_ids[start : start + 500]).values_list(
            "snapshot_id",
            "tag_id",
            "tag__name",
        )
        for snapshot_id, tag_id, tag_name in rows:
            tags_by_snapshot[snapshot_id][tag_id] = tag_name
        for snapshot_id, tags in tags_by_snapshot.items():
            if bogus := exploded_tag_ids(tags):
                repairs[snapshot_id] = bogus

    if not repairs:
        rprint("[green]No split-up tags found[/green]", file=sys.stderr)
        return 0

    tag_names = dict(Tag.objects.filter(id__in={tag_id for ids in repairs.values() for tag_id in ids}).values_list("id", "name"))
    for snapshot in Snapshot.objects.filter(id__in=repairs).only("id", "url").order_by("url"):
        removed = " ".join(repr(tag_names[tag_id]) for tag_id in sorted(repairs[snapshot.id], key=lambda tag_id: tag_names[tag_id]))
        # WHY escape: tag names and URLs may contain "[...]", which rich would parse as markup.
        rprint(escape(f"  {snapshot.url}: {removed}"), file=sys.stderr)

    if dry_run:
        rprint(f"[yellow]Would remove split-up tags from {len(repairs)} snapshots (dry run)[/yellow]", file=sys.stderr)
        return 0

    if not yes:
        rprint("[red]Use --yes to confirm the repair (or --dry-run to preview it)[/red]", file=sys.stderr)
        return 1

    removed_count = 0
    for snapshot in Snapshot.objects.filter(id__in=repairs).only("id"):
        removed_count += snapshot.remove_tag_ids(repairs[snapshot.id])

    # Delete only the fragment tags that no snapshot uses anymore; a one-character
    # tag that is still attached somewhere was deliberately chosen there.
    orphaned = Tag.objects.filter(id__in=tag_names, snapshot_set__isnull=True)
    deleted_tags = sorted(orphaned.values_list("name", flat=True))
    orphaned.delete()

    rprint(
        f"[green]Removed {removed_count} split-up tag associations from {len(repairs)} snapshots "
        f"and deleted {len(deleted_tags)} orphaned tags: {escape(' '.join(map(repr, deleted_tags)))}[/green]",
        file=sys.stderr,
    )
    return 0


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


@main.command("repair")
@click.option("--yes", "-y", is_flag=True, help="Confirm the repair")
@click.option("--dry-run", is_flag=True, help="Show what would be removed")
def repair_cmd(yes: bool, dry_run: bool):
    """Remove one-character tags created by splitting a tag string into characters."""
    sys.exit(repair_tags(yes=yes, dry_run=dry_run))


if __name__ == "__main__":
    main()
