#!/usr/bin/env python3

"""
archivebox snapshot <action> [args...] [--filters]

Manage Snapshot records.

Actions:
    create  - Create Snapshots from URLs or Crawl JSONL
    list    - List Snapshots as JSONL (with optional filters)
    update  - Update Snapshots from stdin JSONL
    delete  - Delete Snapshots from stdin JSONL

Examples:
    # Create
    archivebox snapshot create https://example.com --tag=news
    archivebox crawl create https://example.com | archivebox snapshot create

    # List with filters
    archivebox snapshot list --status=queued
    archivebox snapshot list --url__icontains=example.com

    # Update
    archivebox snapshot list --tag=old | archivebox snapshot update --tag=new

    # Delete
    archivebox snapshot list --url__icontains=spam.com | archivebox snapshot delete --yes
"""

__package__ = "archivebox.cli"
__command__ = "archivebox snapshot"

import sys
from collections.abc import Iterable, Iterator
from itertools import islice

import rich_click as click
from rich import print as rprint
from django.db.models import QuerySet

SNAPSHOT_FILTER_TYPE_CHOICES = ("exact", "substring", "regex", "domain", "tag", "timestamp")
SNAPSHOT_LIST_CHUNK_SIZE = 5000


def iter_snapshot_json(queryset: QuerySet) -> Iterator[dict[str, object]]:
    from archivebox.config import VERSION
    from archivebox.core.models import SnapshotTag

    fields = (
        "id",
        "crawl_id",
        "url",
        "title",
        "bookmarked_at",
        "created_at",
        "timestamp",
        "depth",
        "status",
        "fs_version",
        "output_size",
    )
    rows = queryset.values(*fields).iterator(chunk_size=SNAPSHOT_LIST_CHUNK_SIZE)
    while batch := list(islice(rows, SNAPSHOT_LIST_CHUNK_SIZE)):
        tags_by_snapshot = {row["id"]: [] for row in batch}
        tag_rows = (
            SnapshotTag.objects.filter(snapshot_id__in=tags_by_snapshot).order_by("tag__name").values_list("snapshot_id", "tag__name")
        )
        for snapshot_id, tag_name in tag_rows:
            tags_by_snapshot[snapshot_id].append(tag_name)

        for row in batch:
            archive_size = int(row["output_size"] or 0)
            yield {
                "type": "Snapshot",
                "schema_version": VERSION,
                "id": str(row["id"]),
                "crawl_id": str(row["crawl_id"]),
                "url": row["url"],
                "title": row["title"],
                "tags": ",".join(sorted(tags_by_snapshot[row["id"]])),
                "bookmarked_at": row["bookmarked_at"].isoformat() if row["bookmarked_at"] else None,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "timestamp": row["timestamp"],
                "depth": row["depth"],
                "status": row["status"],
                "fs_version": row["fs_version"],
                "archive_size": archive_size,
                "output_size": archive_size,
            }


# =============================================================================
# CREATE
# =============================================================================


def create_snapshots(
    urls: Iterable[str],
    tag: str = "",
    status: str = "queued",
    depth: int = 0,
    created_by_id: int | None = None,
) -> int:
    """
    Create Snapshots from URLs or stdin JSONL (Crawl or Snapshot records).
    Pass-through: Records that are not Crawl/Snapshot/URL are output unchanged.

    Exit codes:
        0: Success
        1: Failure
    """
    from archivebox.misc.jsonl import (
        read_args_or_stdin,
        write_record,
        TYPE_SNAPSHOT,
        TYPE_CRAWL,
    )
    from archivebox.misc.util import validate_url
    from archivebox.base_models.models import get_or_create_system_user_pk
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    created_by_id = created_by_id or get_or_create_system_user_pk()
    is_tty = sys.stdout.isatty()

    # Collect all input records
    records = list(read_args_or_stdin(urls))

    if not records:
        rprint("[yellow]No URLs or Crawls provided. Pass URLs as arguments or via stdin.[/yellow]", file=sys.stderr)
        return 1

    # Process each record - handle Crawls and plain URLs/Snapshots
    created_snapshots = []
    pass_through_count = 0

    for record in records:
        record_type = record.get("type", "")

        try:
            if record_type == TYPE_CRAWL:
                # Pass through the Crawl record itself first
                if not is_tty:
                    write_record(record)

                # Input is a Crawl - get or create it, then create Snapshots for its URLs
                crawl = None
                crawl_id = record.get("id")
                if crawl_id:
                    try:
                        crawl = Crawl.objects.get(id=crawl_id)
                    except Crawl.DoesNotExist:
                        crawl = Crawl.from_json(record, overrides={"created_by_id": created_by_id})
                else:
                    crawl = Crawl.from_json(record, overrides={"created_by_id": created_by_id})

                if not crawl:
                    continue

                # Create snapshots for each URL in the crawl
                for url in crawl.get_urls_list():
                    try:
                        validate_url(url)
                    except ValueError as err:
                        rprint(f"[red]Error creating snapshot: {err}[/red]", file=sys.stderr)
                        continue
                    merged_tags = crawl.tags_str
                    if tag:
                        merged_tags = f"{merged_tags},{tag}" if merged_tags else tag
                    snapshot_record = {
                        "url": url,
                        "tags": merged_tags,
                        "crawl_id": str(crawl.id),
                        "depth": depth,
                        "status": status,
                    }
                    snapshot = Snapshot.from_json(snapshot_record, overrides={"created_by_id": created_by_id})
                    if snapshot:
                        created_snapshots.append(snapshot)
                        if not is_tty:
                            write_record(snapshot.to_json())

            elif record_type == TYPE_SNAPSHOT or record.get("url"):
                # Input is a Snapshot or plain URL
                if record.get("url"):
                    validate_url(str(record["url"]))
                if tag and not record.get("tags"):
                    record["tags"] = tag
                if status:
                    record["status"] = status
                record["depth"] = record.get("depth", depth)

                snapshot = Snapshot.from_json(record, overrides={"created_by_id": created_by_id})
                if snapshot:
                    created_snapshots.append(snapshot)
                    if not is_tty:
                        write_record(snapshot.to_json())

            else:
                # Pass-through: output records we don't handle
                if not is_tty:
                    write_record(record)
                pass_through_count += 1

        except Exception as e:
            rprint(f"[red]Error creating snapshot: {e}[/red]", file=sys.stderr)
            continue

    if not created_snapshots:
        if pass_through_count > 0:
            rprint(f"[dim]Passed through {pass_through_count} records, no new snapshots[/dim]", file=sys.stderr)
            return 0
        rprint("[red]No snapshots created[/red]", file=sys.stderr)
        return 1

    rprint(f"[green]Created {len(created_snapshots)} snapshots[/green]", file=sys.stderr)

    if is_tty:
        for snapshot in created_snapshots:
            rprint(f"  [dim]{snapshot.id}[/dim] {snapshot.url[:60]}", file=sys.stderr)

    return 0


# =============================================================================
# LIST
# =============================================================================


def snapshot_filter_options(*, default_filter_type: str):
    def decorate(func):
        for decorator in reversed(
            (
                click.option("--status", "-s", help="Filter by status (queued, started, sealed)"),
                click.option("--url__icontains", help="Filter by URL contains"),
                click.option("--url__istartswith", help="Filter by URL starts with"),
                click.option("--tag", "-t", help="Filter by tag name"),
                click.option("--crawl-id", help="Filter by crawl ID"),
                click.option("--limit", "-n", type=int, help="Limit number of results"),
                click.option("--sort", "-o", type=str, help="Field to sort by, e.g. url, created_at, bookmarked_at, downloaded_at"),
                click.option("--search", help="Search mode to use for positional query"),
                click.option("--before", type=float, help="Only snapshots bookmarked before timestamp"),
                click.option("--after", type=float, help="Only snapshots bookmarked after timestamp"),
                click.option(
                    "--filter-type",
                    "-f",
                    type=click.Choice(SNAPSHOT_FILTER_TYPE_CHOICES),
                    default=default_filter_type,
                    help="Type of pattern matching to use for positional filters",
                ),
                click.argument("filter_patterns", nargs=-1),
            ),
        ):
            func = decorator(func)
        return func

    return decorate


def snapshot_output_options(func):
    for decorator in reversed(
        (
            click.option("--csv", "-C", type=str, help="Print output as CSV with the provided fields, e.g.: timestamp,url,title"),
            click.option("--json", "as_json", is_flag=True, help="Print output as a JSON array"),
            click.option("--html", "as_html", is_flag=True, help="Print output as HTML"),
            click.option("--with-headers", is_flag=True, help="Include column headers in structured output"),
        ),
    ):
        func = decorator(func)
    return func


def build_snapshot_queryset(
    **kwargs,
) -> QuerySet:
    from archivebox.core.models import Snapshot

    return Snapshot.objects.order_by("-created_at").search(**kwargs)


def list_snapshots(
    csv: str | None = None,
    as_json: bool = False,
    as_html: bool = False,
    with_headers: bool = False,
    **kwargs,
) -> int:
    """
    List Snapshots as JSONL with optional filters.

    Exit codes:
        0: Success (even if no results)
    """
    from archivebox.misc.jsonl import write_record

    output_formats = sum(bool(output_format) for output_format in (csv, as_json, as_html))
    if output_formats > 1:
        rprint("[red]Choose only one output format: --csv, --json, or --html[/red]", file=sys.stderr)
        return 2
    if with_headers and not output_formats:
        rprint("[red]--with-headers requires --csv, --json, or --html[/red]", file=sys.stderr)
        return 2

    is_tty = sys.stdout.isatty() and not output_formats

    try:
        queryset = build_snapshot_queryset(**kwargs)
    except ValueError as err:
        rprint(f"[red]{err}[/red]", file=sys.stderr)
        return 2

    count = 0
    if as_json:
        queryset = queryset.prefetch_related("tags")
        output = queryset.to_json(with_headers=with_headers)
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")
        rprint(f"[dim]Listed {queryset.count()} snapshots[/dim]", file=sys.stderr)
        return 0

    if as_html:
        queryset = queryset.prefetch_related("tags")
        output = queryset.to_html(with_headers=with_headers)
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            sys.stdout.write("\n")
        rprint(f"[dim]Listed {queryset.count()} snapshots[/dim]", file=sys.stderr)
        return 0

    if csv:
        cols = [col.strip() for col in csv.split(",") if col.strip()]
        if not cols:
            rprint("[red]No CSV columns provided[/red]", file=sys.stderr)
            return 2
        if with_headers:
            sys.stdout.write(",".join(cols))
            sys.stdout.write("\n")
        for snapshot in queryset.prefetch_related("tags").iterator(chunk_size=SNAPSHOT_LIST_CHUNK_SIZE):
            sys.stdout.write(snapshot.to_csv(cols=cols, separator=","))
            sys.stdout.write("\n")
            count += 1
        rprint(f"[dim]Listed {count} snapshots[/dim]", file=sys.stderr)
        return 0

    if not is_tty:
        for snapshot_json in iter_snapshot_json(queryset):
            write_record(snapshot_json)
            count += 1
        rprint(f"[dim]Listed {count} snapshots[/dim]", file=sys.stderr)
        return 0

    for snapshot in queryset.iterator(chunk_size=SNAPSHOT_LIST_CHUNK_SIZE):
        status_color = {
            "queued": "yellow",
            "started": "blue",
            "sealed": "green",
        }.get(snapshot.status, "dim")
        rprint(f"[{status_color}]{snapshot.status:8}[/{status_color}] [dim]{snapshot.id}[/dim] {snapshot.url[:60]}")
        count += 1

    rprint(f"[dim]Listed {count} snapshots[/dim]", file=sys.stderr)
    return 0


# =============================================================================
# UPDATE
# =============================================================================


def update_snapshots(
    status: str | None = None,
    tag: str | None = None,
) -> int:
    """
    Update Snapshots from stdin JSONL.

    Reads Snapshot records from stdin and applies updates.
    Uses PATCH semantics - only specified fields are updated.

    Exit codes:
        0: Success
        1: No input or error
    """
    from django.utils import timezone

    from archivebox.misc.jsonl import read_stdin, write_record
    from archivebox.core.models import Snapshot

    is_tty = sys.stdout.isatty()

    records = list(read_stdin())
    if not records:
        rprint("[yellow]No records provided via stdin[/yellow]", file=sys.stderr)
        return 1

    updated_count = 0
    for record in records:
        snapshot_id = record.get("id")
        if not snapshot_id:
            continue

        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)

            if status:
                if status not in Snapshot.StatusChoices.values:
                    rprint(f"[red]Invalid snapshot status: {status}[/red]", file=sys.stderr)
                    continue
                if status == Snapshot.StatusChoices.SEALED:
                    snapshot.cancel()
                elif status == Snapshot.StatusChoices.PAUSED:
                    snapshot.pause()
                elif status == Snapshot.StatusChoices.QUEUED:
                    if snapshot.status == Snapshot.StatusChoices.PAUSED:
                        snapshot.resume()
                    else:
                        snapshot.update_and_requeue(status=Snapshot.StatusChoices.QUEUED, retry_at=timezone.now())
                elif status == Snapshot.StatusChoices.STARTED:
                    snapshot.update_and_requeue(status=Snapshot.StatusChoices.STARTED, retry_at=timezone.now())
            if tag:
                from archivebox.core.models import Tag

                tag_obj, _ = Tag.objects.get_or_create(name=tag)
                snapshot.tags.add(tag_obj)
                snapshot.safe_update({"modified_at": timezone.now()}, refresh=False)

            if not status and not tag:
                snapshot.safe_update({"modified_at": timezone.now()}, refresh=False)
            updated_count += 1

            if not is_tty:
                snapshot.refresh_from_db()
                write_record(snapshot.to_json())

        except Snapshot.DoesNotExist:
            rprint(f"[yellow]Snapshot not found: {snapshot_id}[/yellow]", file=sys.stderr)
            continue

    rprint(f"[green]Updated {updated_count} snapshots[/green]", file=sys.stderr)
    return 0


# =============================================================================
# DELETE
# =============================================================================


def delete_snapshots(yes: bool = False, dry_run: bool = False) -> int:
    """
    Delete Snapshots from stdin JSONL.

    Requires --yes flag to confirm deletion.

    Exit codes:
        0: Success
        1: No input or missing --yes flag
    """
    from archivebox.misc.jsonl import read_stdin
    from archivebox.core.models import Snapshot

    records = list(read_stdin())
    if not records:
        rprint("[yellow]No records provided via stdin[/yellow]", file=sys.stderr)
        return 1

    snapshot_ids = [r.get("id") for r in records if r.get("id")]

    if not snapshot_ids:
        rprint("[yellow]No valid snapshot IDs in input[/yellow]", file=sys.stderr)
        return 1

    snapshots = Snapshot.objects.filter(id__in=snapshot_ids)
    count = snapshots.count()

    if count == 0:
        rprint("[yellow]No matching snapshots found[/yellow]", file=sys.stderr)
        return 0

    if dry_run:
        rprint(f"[yellow]Would delete {count} snapshots (dry run)[/yellow]", file=sys.stderr)
        for snapshot in snapshots:
            rprint(f"  [dim]{snapshot.id}[/dim] {snapshot.url[:60]}", file=sys.stderr)
        return 0

    if not yes:
        rprint("[red]Use --yes to confirm deletion[/red]", file=sys.stderr)
        return 1

    # Perform deletion
    deleted_count, _ = snapshots.delete()
    rprint(f"[green]Deleted {deleted_count} snapshots[/green]", file=sys.stderr)
    return 0


# =============================================================================
# CLI Commands
# =============================================================================


@click.group()
def main():
    """Manage Snapshot records."""
    pass


@main.command("create")
@click.argument("urls", nargs=-1)
@click.option("--tag", "-t", default="", help="Comma-separated tags to add")
@click.option("--status", "-s", default="queued", help="Initial status (default: queued)")
@click.option("--depth", "-d", type=int, default=0, help="Crawl depth (default: 0)")
def create_cmd(urls: tuple, tag: str, status: str, depth: int):
    """Create Snapshots from URLs or stdin JSONL."""
    sys.exit(create_snapshots(urls, tag=tag, status=status, depth=depth))


@main.command("list")
@snapshot_output_options
@snapshot_filter_options(default_filter_type="substring")
def list_cmd(**kwargs):
    """List Snapshots as JSONL."""
    sys.exit(list_snapshots(**kwargs))


@main.command("update")
@click.option("--status", "-s", help="Set status")
@click.option("--tag", "-t", help="Add tag")
def update_cmd(status: str | None, tag: str | None):
    """Update Snapshots from stdin JSONL."""
    sys.exit(update_snapshots(status=status, tag=tag))


@main.command("delete")
@click.option("--yes", "-y", is_flag=True, help="Confirm deletion")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
def delete_cmd(yes: bool, dry_run: bool):
    """Delete Snapshots from stdin JSONL."""
    sys.exit(delete_snapshots(yes=yes, dry_run=dry_run))


if __name__ == "__main__":
    main()
