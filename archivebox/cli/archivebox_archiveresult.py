#!/usr/bin/env python3

"""
archivebox archiveresult <action> [args...] [--filters]

Manage ArchiveResult records (plugin extraction results).

Actions:
    create  - Emit plugin extraction request records for Snapshots
    list    - List ArchiveResults as JSONL (with optional filters)
    update  - Update ArchiveResults from stdin JSONL
    delete  - Delete ArchiveResults from stdin JSONL

Examples:
    # Emit extraction requests; `archivebox run` schedules their parent snapshots
    archivebox snapshot list --status=queued | archivebox archiveresult create
    archivebox archiveresult create --plugin=screenshot --snapshot-id=<uuid>

    # List with filters
    archivebox archiveresult list --status=failed
    archivebox archiveresult list --plugin=screenshot --status=succeeded

    # Delete
    archivebox archiveresult list --plugin=singlefile | archivebox archiveresult delete --yes

    # Re-run failed extractions
    archivebox archiveresult list --status=failed | archivebox run
"""

__package__ = "archivebox.cli"
__command__ = "archivebox archiveresult"

import sys

import rich_click as click
from rich import print as rprint

from archivebox.cli.cli_util import apply_filters


def build_archiveresult_request(snapshot_id: str, plugin: str, hook_name: str = "", status: str = "queued") -> dict:
    return {
        "type": "ArchiveResult",
        "snapshot_id": str(snapshot_id),
        "plugin": plugin,
        "hook_name": hook_name,
        "status": status,
    }


# =============================================================================
# CREATE
# =============================================================================


def create_archiveresults(
    snapshot_id: str | None = None,
    plugin: str | None = None,
    status: str = "queued",
) -> int:
    """
    Create ArchiveResult request records for Snapshots.

    Reads Snapshot records from stdin and emits ArchiveResult request JSONL.
    Pass-through: Non-Snapshot/ArchiveResult records are output unchanged.
    If --plugin is specified, only emits requests for that plugin.
    Otherwise, emits requests for all enabled snapshot hooks.

    Exit codes:
        0: Success
        1: Failure
    """
    from archivebox.config.common import get_config
    from archivebox.plugins.hooks import discover_hooks
    from archivebox.misc.jsonl import read_stdin, write_record, TYPE_SNAPSHOT, TYPE_ARCHIVERESULT
    from archivebox.core.models import Snapshot

    is_tty = sys.stdout.isatty()

    # If snapshot_id provided directly, use that
    if snapshot_id:
        try:
            snapshots = [Snapshot.objects.get(id=snapshot_id)]
            pass_through_records = []
        except Snapshot.DoesNotExist:
            rprint(f"[red]Snapshot not found: {snapshot_id}[/red]", file=sys.stderr)
            return 1
    else:
        # Read from stdin
        records = list(read_stdin())
        if not records:
            rprint("[yellow]No Snapshot records provided via stdin[/yellow]", file=sys.stderr)
            return 1

        # Separate snapshot records from pass-through records
        snapshot_ids = []
        pass_through_records = []

        for record in records:
            record_type = record.get("type", "")

            if record_type == TYPE_SNAPSHOT:
                # Pass through the Snapshot record itself
                pass_through_records.append(record)
                if record.get("id"):
                    snapshot_ids.append(record["id"])

            elif record_type == TYPE_ARCHIVERESULT:
                # ArchiveResult records: pass through if they have an id
                if record.get("id"):
                    pass_through_records.append(record)
                # If no id, we could create it, but for now just pass through
                else:
                    pass_through_records.append(record)

            elif record_type:
                # Other typed records (Crawl, Tag, etc): pass through
                pass_through_records.append(record)

            elif record.get("id"):
                # Untyped record with id - assume it's a snapshot ID
                snapshot_ids.append(record["id"])

        # Output pass-through records first
        if not is_tty:
            for record in pass_through_records:
                write_record(record)

        if not snapshot_ids:
            if pass_through_records:
                rprint(f"[dim]Passed through {len(pass_through_records)} records, no new snapshots to process[/dim]", file=sys.stderr)
                return 0
            rprint("[yellow]No valid Snapshot IDs in input[/yellow]", file=sys.stderr)
            return 1

        snapshots = list(Snapshot.objects.filter(id__in=snapshot_ids))

    if not snapshots:
        rprint("[yellow]No matching snapshots found[/yellow]", file=sys.stderr)
        return 0 if pass_through_records else 1

    created_count = 0
    for snapshot in snapshots:
        config = get_config(crawl=snapshot.crawl, snapshot=snapshot)
        hooks = [
            hook
            for hook in discover_hooks("Snapshot", filter_disabled=not plugin, config=config)
            if not plugin or hook.parent.name == plugin
        ]
        for hook_path in hooks:
            hook_name = hook_path.stem
            plugin_name = hook_path.parent.name
            if not is_tty:
                write_record(build_archiveresult_request(snapshot.id, plugin_name, hook_name=hook_name, status=status))
            created_count += 1

    rprint(f"[green]Created {created_count} extraction request records[/green]", file=sys.stderr)
    return 0


# =============================================================================
# LIST
# =============================================================================


def list_archiveresults(
    status: str | None = None,
    plugin: str | None = None,
    snapshot_id: str | None = None,
    limit: int | None = None,
) -> int:
    """List archive results as JSONL, or formatted rows in a terminal."""
    from archivebox.core.models import ArchiveResult
    from archivebox.cli.cli_util import list_records, format_status

    queryset = apply_filters(
        ArchiveResult.objects.order_by("-start_ts"),
        {"status": status, "plugin": plugin, "snapshot_id": snapshot_id},
        limit=limit,
    )
    return list_records(
        queryset,
        plural="archive results",
        render=lambda result: f"{format_status(result.status, 10)} {result.plugin:15} [dim]{result.id}[/dim] {result.snapshot.url[:40]}",
    )


# =============================================================================
# UPDATE
# =============================================================================


def update_archiveresults(status: str | None = None) -> int:
    """Apply supplied fields to each JSONL-selected ArchiveResult."""
    from archivebox.core.models import ArchiveResult
    from archivebox.cli.cli_util import update_records

    def update(archiveresult):
        if status:
            archiveresult.status = status
        archiveresult.save()

    return update_records(ArchiveResult, update, plural="archive results")


# =============================================================================
# DELETE
# =============================================================================


def delete_archiveresults(yes: bool = False, dry_run: bool = False) -> int:
    """Delete archive results selected by stdin JSONL; --yes confirms, --dry-run previews."""
    from archivebox.cli.cli_util import delete_records
    from archivebox.core.models import ArchiveResult

    return delete_records(
        ArchiveResult,
        label="archive result",
        plural="archive results",
        preview=lambda obj: f"[dim]{obj.id}[/dim] {obj.plugin} {obj.snapshot.url[:40]}",
        yes=yes,
        dry_run=dry_run,
        preview_limit=10,
    )


# =============================================================================
# CLI Commands
# =============================================================================


@click.group()
def main():
    """Manage ArchiveResult records (plugin extraction results)."""
    pass


@main.command("create")
@click.option("--snapshot-id", help="Snapshot ID to create results for")
@click.option("--plugin", "-p", help="Plugin name (e.g., screenshot, singlefile)")
@click.option("--status", "-s", default="queued", help="Initial status (default: queued)")
def create_cmd(**kwargs):
    """Emit Snapshot plugin extraction requests as JSONL."""
    sys.exit(create_archiveresults(**kwargs))


@main.command("list")
@click.option("--status", "-s", help="Filter by status (queued, started, succeeded, failed, skipped)")
@click.option("--plugin", "-p", help="Filter by plugin name")
@click.option("--snapshot-id", help="Filter by snapshot ID")
@click.option("--limit", "-n", type=int, help="Limit number of results")
def list_cmd(**kwargs):
    """List ArchiveResults as JSONL."""
    sys.exit(list_archiveresults(**kwargs))


@main.command("update")
@click.option("--status", "-s", help="Set status")
def update_cmd(**kwargs):
    """Update ArchiveResults from stdin JSONL."""
    sys.exit(update_archiveresults(**kwargs))


@main.command("delete")
@click.option("--yes", "-y", is_flag=True, help="Confirm deletion")
@click.option("--dry-run", is_flag=True, help="Show what would be deleted")
def delete_cmd(**kwargs):
    """Delete ArchiveResults from stdin JSONL."""
    sys.exit(delete_archiveresults(**kwargs))


if __name__ == "__main__":
    main()
