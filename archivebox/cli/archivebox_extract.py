#!/usr/bin/env python3

"""Run abx-dl snapshot hooks for existing ArchiveBox snapshots."""

__package__ = "archivebox.cli"
__command__ = "archivebox extract"

import sys
from collections import defaultdict
from contextlib import redirect_stdout

import rich_click as click


def _resolve_requests(records: list[dict], plugins: str) -> tuple[dict[str, set[str]], set[str]]:
    """Resolve CLI records to snapshot-level execution requests.

    ArchiveResult input is accepted as a convenient reference to its parent
    Snapshot and plugin. It is never reset or converted into queued work.
    """
    from archivebox.api.v1_core import _uuid_ref_query
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.misc.jsonl import TYPE_ARCHIVERESULT

    explicit_plugins = {name.strip() for name in plugins.split(",") if name.strip()}
    requested: dict[str, set[str]] = defaultdict(set)
    missing: set[str] = set()

    for record in records:
        record_type = record.get("type")
        record_id = str(record.get("id") or "")

        if record_type == TYPE_ARCHIVERESULT and record.get("snapshot_id"):
            requested[str(record["snapshot_id"])].update(explicit_plugins or {str(record.get("plugin") or "")})
            requested[str(record["snapshot_id"])].discard("")
            continue

        if record_type == TYPE_ARCHIVERESULT:
            result = ArchiveResult.objects.filter(_uuid_ref_query("id", record_id)).only("snapshot_id", "plugin").first()
            if result is not None:
                requested[str(result.snapshot_id)].update(explicit_plugins or {result.plugin})
                continue

        snapshot_id = str(record.get("snapshot_id") or record_id or "")
        snapshot = Snapshot.objects.filter(id=snapshot_id).only("id").first() if snapshot_id else None
        if snapshot is None and record.get("url"):
            snapshot = Snapshot.objects.filter(url=record["url"]).order_by("-created_at").only("id").first()
        # Bare UUID CLI arguments are parsed as Snapshot records because the
        # input layer cannot know which model owns them. Preserve the public
        # convenience of passing an ArchiveResult ID by trying that reference
        # only after the Snapshot lookup misses.
        if snapshot is None and record_id and not record.get("url"):
            result = ArchiveResult.objects.filter(_uuid_ref_query("id", record_id)).only("snapshot_id", "plugin").first()
            if result is not None:
                requested[str(result.snapshot_id)].update(explicit_plugins or {result.plugin})
                continue
        if snapshot is None:
            missing.add(snapshot_id or str(record.get("url") or ""))
            continue
        requested[str(snapshot.id)].update(explicit_plugins)

    return requested, missing


def _run_snapshot_requests(requested: dict[str, set[str]], *, wait: bool, show_progress: bool) -> int:
    from django.utils import timezone
    from rich import print as rprint

    from archivebox.core.models import Snapshot
    from archivebox.services.runner import run_crawl

    snapshots = {str(snapshot.id): snapshot for snapshot in Snapshot.objects.filter(id__in=requested).select_related("crawl")}
    if not snapshots:
        rprint("[red]No snapshots to process[/red]", file=sys.stderr)
        return 1

    from archivebox.config.common import get_config
    from archivebox.plugins.discovery import get_enabled_plugins

    for snapshot_id, plugin_names in requested.items():
        snapshot = snapshots.get(snapshot_id)
        if snapshot is not None and not plugin_names:
            plugin_names.update(get_enabled_plugins(config=get_config(crawl=snapshot.crawl, snapshot=snapshot)))

    if wait and any("search_backend_sonic" in plugin_names for plugin_names in requested.values()):
        from archivebox.core.takeover_util import ensure_daemon_stack

        with redirect_stdout(sys.stderr):
            ensure_daemon_stack(reason="Sonic snapshot indexing")

    # Explicit extraction resumes open/paused snapshots at the snapshot level.
    # Sealed snapshots stay sealed during targeted maintenance backfills.
    if wait:
        for snapshot in snapshots.values():
            if snapshot.status != Snapshot.StatusChoices.SEALED:
                snapshot.update_and_requeue(
                    status=Snapshot.StatusChoices.QUEUED,
                    retry_at=timezone.now(),
                )

    if not wait:
        for snapshot_id, plugin_names in requested.items():
            snapshot = snapshots.get(snapshot_id)
            if snapshot is None:
                continue
            if plugin_names:
                snapshot.schedule_plugin_run(plugin_names, when=timezone.now())
            elif snapshot.status == Snapshot.StatusChoices.SEALED:
                snapshot.update_and_requeue(retry_at=timezone.now())
            else:
                snapshot.update_and_requeue(
                    status=Snapshot.StatusChoices.QUEUED,
                    retry_at=timezone.now(),
                )
        if show_progress:
            rprint(f"[blue]Queued {len(snapshots)} snapshots for extraction[/blue]", file=sys.stderr)
        return 0

    grouped: dict[tuple[str, tuple[str, ...]], list[str]] = defaultdict(list)
    for snapshot_id, plugin_names in requested.items():
        snapshot = snapshots.get(snapshot_id)
        if snapshot is not None:
            grouped[(str(snapshot.crawl_id), tuple(sorted(plugin_names)))].append(snapshot_id)

    for (crawl_id, plugin_names), snapshot_ids in grouped.items():
        run_crawl(
            crawl_id,
            snapshot_ids=sorted(snapshot_ids),
            selected_plugins=list(plugin_names) or None,
            show_progress=show_progress,
        )
    return 0


def run_plugins(
    args: tuple,
    records: list[dict] | None = None,
    plugins: str = "",
    wait: bool = True,
    emit_results: bool = True,
    show_progress: bool = True,
) -> int:
    """Execute selected plugins through the snapshot-level runner."""
    from rich import print as rprint

    from archivebox.core.models import Snapshot
    from archivebox.misc.jsonl import read_args_or_stdin, write_record

    if records is None:
        records = list(read_args_or_stdin(args))
    if not records:
        rprint("[yellow]No snapshots provided. Pass snapshot IDs as arguments or via stdin.[/yellow]", file=sys.stderr)
        return 1

    requested, missing = _resolve_requests(records, plugins)
    for value in sorted(missing):
        rprint(f"[yellow]Snapshot or ArchiveResult not found: {value}[/yellow]", file=sys.stderr)
    if not requested:
        return 1

    exit_code = _run_snapshot_requests(requested, wait=wait, show_progress=show_progress)
    if exit_code or not emit_results:
        return exit_code

    is_tty = sys.stdout.isatty()
    for snapshot in Snapshot.objects.filter(id__in=requested):
        results = snapshot.archiveresult_set.all()
        requested_plugins = requested[str(snapshot.id)]
        if requested_plugins:
            results = results.filter(plugin__in=requested_plugins)
        for result in results:
            if is_tty:
                color = {"succeeded": "green", "failed": "red", "skipped": "yellow"}.get(result.status, "dim")
                rprint(f"  [{color}]{result.status}[/{color}] {result.plugin} → {result.output_str or ''}", file=sys.stderr)
            else:
                write_record(result.to_json())
    return 0


def process_archiveresult_by_id(archiveresult_id: str) -> int:
    """Re-run the parent Snapshot plugin referenced by an ArchiveResult."""
    return run_plugins((), records=[{"id": archiveresult_id}], wait=True)


@click.command()
@click.option("--plugins", "--plugin", "-p", default="", help="Comma-separated list of plugins to run")
@click.option("--wait/--no-wait", default=True, help="Wait for plugins to complete (default: wait)")
@click.argument("args", nargs=-1)
def main(plugins: str, wait: bool, args: tuple):
    """Run plugins on Snapshots; ArchiveResult IDs select their parent plugin."""
    from archivebox.misc.jsonl import read_args_or_stdin

    records = list(read_args_or_stdin(args))
    if not records:
        from rich import print as rprint

        rprint("[yellow]No Snapshot IDs or ArchiveResult IDs provided. Pass as arguments or via stdin.[/yellow]", file=sys.stderr)
        sys.exit(1)
    sys.exit(run_plugins(args, records=records, plugins=plugins, wait=wait))


if __name__ == "__main__":
    main()
