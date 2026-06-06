#!/usr/bin/env python3

"""
archivebox extract [snapshot_ids...] [--plugins=NAMES]

Run plugins on Snapshots. Accepts snapshot IDs as arguments, from stdin, or via JSONL.

Input formats:
    - Snapshot UUIDs (one per line)
    - JSONL: {"type": "Snapshot", "id": "...", "url": "..."}
    - JSONL: {"type": "ArchiveResult", "snapshot_id": "...", "plugin": "..."}

Output (JSONL):
    {"type": "ArchiveResult", "id": "...", "snapshot_id": "...", "plugin": "...", "status": "..."}

Examples:
    # Extract specific snapshot
    archivebox extract 01234567-89ab-cdef-0123-456789abcdef

    # Pipe from snapshot command
    archivebox snapshot https://example.com | archivebox extract

    # Run specific plugins only
    archivebox extract --plugins=screenshot,singlefile 01234567-89ab-cdef-0123-456789abcdef

    # Chain commands
    archivebox crawl https://example.com | archivebox snapshot | archivebox extract
"""

__package__ = "archivebox.cli"
__command__ = "archivebox extract"

import sys
from collections import defaultdict
from itertools import product

import rich_click as click


def process_archiveresult_by_id(archiveresult_id: str) -> int:
    """
    Re-run extraction for a single ArchiveResult by ID.

    ArchiveResults are projected status rows, not queued work items. Re-running
    a single result means resetting that row and queueing its parent snapshot
    through the shared crawl runner with the corresponding plugin selected.
    """
    from rich import print as rprint
    from django.utils import timezone
    from archivebox.core.models import ArchiveResult
    from archivebox.api.v1_core import _uuid_ref_query
    from archivebox.services.runner import run_crawl

    try:
        archiveresult = ArchiveResult.objects.get(_uuid_ref_query("id", archiveresult_id))
    except ArchiveResult.DoesNotExist:
        rprint(f"[red]ArchiveResult {archiveresult_id} not found[/red]", file=sys.stderr)
        return 1

    rprint(f"[blue]Extracting {archiveresult.plugin} for {archiveresult.snapshot.url}[/blue]", file=sys.stderr)

    try:
        was_paused = archiveresult.snapshot.is_paused
        archiveresult.reset_for_retry()
        snapshot = archiveresult.snapshot
        if not was_paused:
            snapshot.queue_for_extraction()
        else:
            # A paused snapshot may still accept explicit maintenance for one
            # ArchiveResult, but this path must not transition it back to
            # queued/startable work. Guard: only set retry_at while the row is
            # still paused — concurrent resume would otherwise see a stale
            # retry_at marker.
            snapshot.safe_update(
                {"retry_at": timezone.now()},
                refresh=False,
                extra_filter={"status": snapshot.StatusChoices.PAUSED},
            )
        crawl = snapshot.crawl
        if not crawl.claim_processing_lock(lock_seconds=10):
            rprint(
                f"[yellow]Crawl {crawl.id} is already owned by another runner[/yellow]",
                file=sys.stderr,
            )
            return 1

        try:
            run_crawl(str(snapshot.crawl_id), snapshot_ids=[str(snapshot.id)], selected_plugins=[archiveresult.plugin])
        finally:
            if was_paused:
                snapshot.restore_paused_scheduler_marker()
        archiveresult.refresh_from_db()

        if archiveresult.status == ArchiveResult.StatusChoices.SUCCEEDED:
            print(f"[green]Extraction succeeded: {archiveresult.output_str}[/green]")
            return 0
        elif archiveresult.status == ArchiveResult.StatusChoices.NORESULTS:
            print(f"[dim]Extraction completed with no results: {archiveresult.output_str}[/dim]")
            return 0
        elif archiveresult.status == ArchiveResult.StatusChoices.FAILED:
            print(f"[red]Extraction failed: {archiveresult.output_str}[/red]", file=sys.stderr)
            return 1
        else:
            # Still in progress or backoff - not a failure
            print(f"[yellow]Extraction status: {archiveresult.status}[/yellow]")
            return 0

    except Exception as e:
        print(f"[red]Extraction error: {type(e).__name__}: {e}[/red]", file=sys.stderr)
        return 1


def run_plugins(
    args: tuple,
    records: list[dict] | None = None,
    plugins: str = "",
    wait: bool = True,
    emit_results: bool = True,
    show_progress: bool = True,
    preserve_queued: bool = False,
) -> int:
    """
    Run plugins on Snapshots from input.

    Reads Snapshot IDs or JSONL from args/stdin, runs plugins, outputs JSONL.

    Exit codes:
        0: Success
        1: Failure
    """
    from rich import print as rprint
    from django.utils import timezone

    from archivebox.misc.jsonl import (
        read_args_or_stdin,
        write_record,
        TYPE_SNAPSHOT,
        TYPE_ARCHIVERESULT,
    )
    from archivebox.core.models import Snapshot
    from archivebox.core.models import ArchiveResult
    from archivebox.services.runner import run_crawl
    from abx_dl.models import discover_plugins

    is_tty = sys.stdout.isatty()

    # Parse comma-separated plugins list once (reused in creation and filtering)
    plugins_list = [p.strip() for p in plugins.split(",") if p.strip()] if plugins else []

    # Parse stdin/args exactly once per CLI invocation.
    # `main()` may already have consumed stdin to distinguish Snapshot input from
    # ArchiveResult IDs; if so, it must pass the parsed records through here
    # instead of asking this helper to reread an already-drained pipe.
    if records is None:
        records = list(read_args_or_stdin(args))

    if not records:
        rprint("[yellow]No snapshots provided. Pass snapshot IDs as arguments or via stdin.[/yellow]", file=sys.stderr)
        return 1

    # Gather snapshot IDs and optional plugin constraints to process
    snapshot_ids = set()
    requested_plugins_by_snapshot: dict[str, set[str]] = defaultdict(set)
    for record in records:
        record_type = record.get("type")

        if record_type == TYPE_SNAPSHOT:
            snapshot_id = record.get("id")
            if snapshot_id:
                snapshot_ids.add(str(snapshot_id))
            elif record.get("url"):
                # Look up by URL (get most recent if multiple exist)
                snap = Snapshot.objects.filter(url=record["url"]).order_by("-created_at").first()
                if snap:
                    snapshot_ids.add(str(snap.id))
                else:
                    rprint(f"[yellow]Snapshot not found for URL: {record['url']}[/yellow]", file=sys.stderr)

        elif record_type == TYPE_ARCHIVERESULT:
            snapshot_id = record.get("snapshot_id")
            if snapshot_id:
                snapshot_ids.add(str(snapshot_id))
                plugin_name = record.get("plugin")
                if plugin_name and not plugins_list:
                    requested_plugins_by_snapshot[str(snapshot_id)].add(str(plugin_name))

        elif "id" in record:
            # Assume it's a snapshot ID
            snapshot_ids.add(str(record["id"]))

    if not snapshot_ids:
        rprint("[red]No valid snapshot IDs found in input[/red]", file=sys.stderr)
        return 1

    existing_snapshots = list(Snapshot.objects.filter(id__in=snapshot_ids).values_list("id", "crawl_id"))
    existing_snapshot_ids = {str(snapshot_id) for snapshot_id, _crawl_id in existing_snapshots}
    existing_crawl_ids = {str(crawl_id) for _snapshot_id, crawl_id in existing_snapshots}
    missing_snapshot_ids = sorted(str(snapshot_id) for snapshot_id in snapshot_ids - existing_snapshot_ids)
    for snapshot_id in missing_snapshot_ids:
        rprint(f"[yellow]Snapshot {snapshot_id} not found[/yellow]", file=sys.stderr)

    # Queue only the target plugin rows. Bulk updates keep large reindex runs
    # from doing one SELECT+UPDATE per snapshot/plugin before hooks even start.
    requested_pairs: set[tuple[str, str]] = set()
    if plugins_list:
        requested_pairs.update((snapshot_id, plugin_name) for snapshot_id, plugin_name in product(existing_snapshot_ids, plugins_list))
    else:
        requested_pairs.update(
            (snapshot_id, plugin_name)
            for snapshot_id, plugin_names in requested_plugins_by_snapshot.items()
            if snapshot_id in existing_snapshot_ids
            for plugin_name in plugin_names
        )
    plugins_by_name = discover_plugins(runtime="archivebox")
    requested_rows: set[tuple[str, str, str]] = set()
    for snapshot_id, plugin_name in requested_pairs:
        plugin = plugins_by_name.get(plugin_name)
        hooks = plugin.filter_hooks("Snapshot") if plugin is not None else []
        if hooks:
            requested_rows.update((snapshot_id, plugin_name, hook.name) for hook in hooks)
        else:
            requested_rows.add((snapshot_id, plugin_name, ""))

    queued_rows: set[tuple[str, str, str]] = set()
    if preserve_queued and requested_rows:
        queued_rows = {
            (str(snapshot_id), plugin_name, hook_name)
            for snapshot_id, plugin_name, hook_name in ArchiveResult.objects.filter(
                snapshot_id__in=existing_snapshot_ids,
                plugin__in={plugin_name for _snapshot_id, plugin_name, _hook_name in requested_rows},
                status=ArchiveResult.StatusChoices.QUEUED,
            ).values_list("snapshot_id", "plugin", "hook_name")
        }
    rows_to_queue = requested_rows - queued_rows

    reset_fields = {
        "status": ArchiveResult.StatusChoices.QUEUED,
        "output_str": "",
        "output_json": None,
        "output_files": {},
        "output_size": 0,
        "output_mimetypes": "",
        "start_ts": None,
        "end_ts": None,
        "modified_at": timezone.now(),
    }
    if rows_to_queue and plugins_list:
        rows_to_reset_by_hook: dict[tuple[str, str], set[str]] = defaultdict(set)
        for snapshot_id, plugin_name, hook_name in rows_to_queue:
            rows_to_reset_by_hook[(plugin_name, hook_name)].add(snapshot_id)
        for (plugin_name, hook_name), plugin_snapshot_ids in rows_to_reset_by_hook.items():
            ArchiveResult.objects.filter(snapshot_id__in=plugin_snapshot_ids, plugin=plugin_name, hook_name=hook_name).update(
                **reset_fields,
            )
    elif rows_to_queue and requested_plugins_by_snapshot:
        snapshot_ids_by_hook: dict[tuple[str, str], set[str]] = defaultdict(set)
        for snapshot_id, plugin_name, hook_name in rows_to_queue:
            snapshot_ids_by_hook[(plugin_name, hook_name)].add(snapshot_id)
        for (plugin_name, hook_name), plugin_snapshot_ids in snapshot_ids_by_hook.items():
            ArchiveResult.objects.filter(snapshot_id__in=plugin_snapshot_ids, plugin=plugin_name, hook_name=hook_name).update(
                **reset_fields,
            )
    existing_rows = (
        {
            (str(snapshot_id), plugin_name, hook_name)
            for snapshot_id, plugin_name, hook_name in ArchiveResult.objects.filter(
                snapshot_id__in=existing_snapshot_ids,
                plugin__in={plugin_name for _snapshot_id, plugin_name, _hook_name in rows_to_queue},
            ).values_list("snapshot_id", "plugin", "hook_name")
        }
        if rows_to_queue
        else set()
    )
    missing_rows = rows_to_queue - existing_rows
    if missing_rows:
        ArchiveResult.objects.bulk_create(
            [
                ArchiveResult(
                    snapshot_id=snapshot_id,
                    plugin=plugin_name,
                    hook_name=hook_name,
                    status=ArchiveResult.StatusChoices.QUEUED,
                )
                for snapshot_id, plugin_name, hook_name in sorted(missing_rows)
            ],
            batch_size=500,
        )

    processed_count = len(existing_snapshot_ids)
    queue_at = timezone.now()
    if existing_snapshot_ids:
        if requested_rows:
            # Targeted ArchiveResult retries use retry_at as the scheduling
            # signal and keep sealed snapshots sealed so extractors are not
            # re-run outside the explicitly queued plugin rows. Paused snapshots
            # also keep status=paused here: `retry_at` only asks the orchestrator
            # to process the queued plugin rows, and run_due_snapshot restores
            # retry_at=MAX afterward instead of resuming the snapshot lifecycle.
            affected_snapshot_ids = {snapshot_id for snapshot_id, _plugin_name, _hook_name in rows_to_queue}
            if preserve_queued and queued_rows:
                queued_snapshot_ids = {snapshot_id for snapshot_id, _plugin_name, _hook_name in queued_rows}
                affected_snapshot_ids.update(
                    str(snapshot_id)
                    for snapshot_id in Snapshot.objects.filter(id__in=queued_snapshot_ids)
                    .filter(retry_at__gt=queue_at)
                    .values_list("id", flat=True)
                )
                affected_snapshot_ids.update(
                    str(snapshot_id)
                    for snapshot_id in Snapshot.objects.filter(id__in=queued_snapshot_ids, retry_at__isnull=True).values_list(
                        "id",
                        flat=True,
                    )
                )
            for snapshot in Snapshot.objects.filter(id__in=affected_snapshot_ids).only("id", "status", "modified_at"):
                # Guard the read-time status so we never bump retry_at on a
                # row that's been re-queued / started by a concurrent runner.
                snapshot.safe_update(
                    {"retry_at": queue_at, "modified_at": queue_at},
                    refresh=False,
                    extra_filter={"status": snapshot.status},
                )
        else:
            # No plugin rows were requested, so this is a full snapshot retry.
            for snapshot in Snapshot.objects.filter(id__in=existing_snapshot_ids).only("id", "status", "retry_at", "modified_at"):
                snapshot.safe_update(
                    {
                        "status": Snapshot.StatusChoices.QUEUED,
                        "retry_at": queue_at,
                        "current_step": 0,
                        "modified_at": queue_at,
                    },
                    refresh=False,
                    extra_filter={"status": snapshot.status},
                )
    if existing_crawl_ids and not requested_rows:
        from archivebox.crawls.models import Crawl

        for crawl in Crawl.objects.filter(id__in=existing_crawl_ids).only("id", "status", "retry_at", "modified_at"):
            update_fields = {
                "retry_at": queue_at,
                "modified_at": queue_at,
            }
            if crawl.status != Crawl.StatusChoices.STARTED:
                update_fields["status"] = Crawl.StatusChoices.QUEUED
            crawl.safe_update(
                update_fields,
                refresh=False,
                extra_filter={"status": crawl.status},
            )

    if processed_count == 0:
        rprint("[red]No snapshots to process[/red]", file=sys.stderr)
        return 1

    if show_progress:
        rprint(f"[blue]Queued {processed_count} snapshots for extraction[/blue]", file=sys.stderr)

    # Run orchestrator if --wait (default)
    if wait:
        if show_progress:
            rprint("[blue]Running plugins...[/blue]", file=sys.stderr)
        snapshot_ids_by_crawl: dict[str, set[str]] = defaultdict(set)
        for snapshot_id, crawl_id in existing_snapshots:
            snapshot_ids_by_crawl[str(crawl_id)].add(str(snapshot_id))

        for crawl_id, crawl_snapshot_ids in snapshot_ids_by_crawl.items():
            from archivebox.crawls.models import Crawl

            crawl = Crawl.objects.get(id=crawl_id)
            if not crawl.claim_processing_lock(lock_seconds=10):
                rprint(
                    f"[yellow]Crawl {crawl_id} is already owned by another runner[/yellow]",
                    file=sys.stderr,
                )
                return 1
            selected_plugins = (
                plugins_list
                or sorted(
                    {plugin for snapshot_id in crawl_snapshot_ids for plugin in requested_plugins_by_snapshot.get(str(snapshot_id), set())},
                )
                or None
            )
            run_crawl(
                crawl_id,
                snapshot_ids=sorted(crawl_snapshot_ids),
                selected_plugins=selected_plugins,
                show_progress=show_progress,
            )

    if not emit_results:
        return 0

    # Output results as JSONL (when piped) or human-readable (when TTY)
    for snapshot_id in snapshot_ids:
        try:
            snapshot = Snapshot.objects.get(id=snapshot_id)
            results = snapshot.archiveresult_set.all()
            if plugins_list:
                results = results.filter(plugin__in=plugins_list)

            for result in results:
                if is_tty:
                    status_color = {
                        "succeeded": "green",
                        "failed": "red",
                        "skipped": "yellow",
                    }.get(result.status, "dim")
                    rprint(
                        f"  [{status_color}]{result.status}[/{status_color}] {result.plugin} → {result.output_str or ''}",
                        file=sys.stderr,
                    )
                else:
                    write_record(result.to_json())
        except Snapshot.DoesNotExist:
            continue

    return 0


def is_archiveresult_id(value: str) -> bool:
    """Check if value resolves to an ArchiveResult ID."""
    from archivebox.core.models import ArchiveResult
    from archivebox.api.v1_core import _uuid_ref_query

    return ArchiveResult.objects.filter(_uuid_ref_query("id", value)).exists()


@click.command()
@click.option("--plugins", "--plugin", "-p", default="", help="Comma-separated list of plugins to run (e.g., screenshot,singlefile)")
@click.option("--wait/--no-wait", default=True, help="Wait for plugins to complete (default: wait)")
@click.argument("args", nargs=-1)
def main(plugins: str, wait: bool, args: tuple):
    """Run plugins on Snapshots, or process existing ArchiveResults by ID"""
    from archivebox.misc.jsonl import read_args_or_stdin

    # Read all input
    records = list(read_args_or_stdin(args))

    if not records:
        from rich import print as rprint

        rprint("[yellow]No Snapshot IDs or ArchiveResult IDs provided. Pass as arguments or via stdin.[/yellow]", file=sys.stderr)
        sys.exit(1)

    # Check if input looks like existing ArchiveResult IDs to process
    all_are_archiveresult_ids = all(is_archiveresult_id(r.get("id") or r.get("url", "")) for r in records)

    if all_are_archiveresult_ids:
        # Process existing ArchiveResults by ID
        from rich import print as rprint

        exit_code = 0
        for record in records:
            archiveresult_id = record.get("id") or record.get("url")
            if not isinstance(archiveresult_id, str):
                rprint(f"[red]Invalid ArchiveResult input: {record}[/red]", file=sys.stderr)
                exit_code = 1
                continue
            result = process_archiveresult_by_id(archiveresult_id)
            if result != 0:
                exit_code = result
        sys.exit(exit_code)
    else:
        # Default behavior: run plugins on Snapshots from input
        sys.exit(run_plugins(args, records=records, plugins=plugins, wait=wait))


if __name__ == "__main__":
    main()
