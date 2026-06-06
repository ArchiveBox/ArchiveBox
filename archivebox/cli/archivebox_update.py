#!/usr/bin/env python3
from __future__ import annotations

__package__ = "archivebox.cli"

import os
import asyncio
import shlex
import time

from typing import TYPE_CHECKING, Any
from collections.abc import Iterable
from pathlib import Path

import rich_click as click

from archivebox.misc.util import enforce_types, docstring
from archivebox.cli.archivebox_snapshot import snapshot_filter_options

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl


def _get_snapshot_crawl(snapshot: Snapshot) -> Crawl | None:
    from django.core.exceptions import ObjectDoesNotExist

    try:
        return snapshot.crawl
    except ObjectDoesNotExist:
        return None


def _get_search_indexing_plugins() -> list[str]:
    from archivebox.config.common import get_config
    from archivebox.plugins.hooks import discover_hooks
    from archivebox.plugins.discovery import get_search_backends

    available_backends = set(get_search_backends())
    return sorted(
        plugin_name
        for plugin_name in {
            hook.parent.name
            for hook in discover_hooks("Snapshot", config=get_config())
            if hook.parent.name.startswith("search_backend_") and "index" in hook.name.lower()
        }
        if plugin_name.startswith("search_backend_") and plugin_name.removeprefix("search_backend_") in available_backends
    )


def _build_filtered_snapshots_queryset(
    **kwargs,
):
    from archivebox.core.models import Snapshot
    from archivebox.cli.archivebox_snapshot import build_snapshot_queryset

    limit = kwargs.pop("limit", None)
    snapshots = build_snapshot_queryset(**kwargs)
    if kwargs.get("resume"):
        snapshots = snapshots.filter(timestamp__lte=kwargs["resume"])
    snapshots = snapshots.select_related("crawl")
    if limit is not None and limit > 0:
        snapshot_ids = list(snapshots.values_list("id", flat=True)[:limit])
        snapshots = Snapshot.objects.filter(id__in=snapshot_ids).select_related("crawl")

    return snapshots


def reindex_snapshots(
    snapshots: QuerySet[Snapshot, Snapshot],
    *,
    search_plugins: list[str],
    batch_size: int,
    collect_ids: bool = False,
    wait_for_turn=None,
) -> dict[str, Any]:
    from archivebox.cli.archivebox_extract import run_plugins
    from archivebox.core.models import ArchiveResult
    from abx_dl.models import discover_plugins

    stats: dict[str, Any] = {"processed": 0, "requested": 0, "queued": 0, "skipped_queued": 0, "reindexed": 0, "snapshot_ids": []}
    records: list[dict[str, str]] = []
    plugins_by_name = discover_plugins(runtime="archivebox")
    required_hooks_by_plugin = {
        plugin_name: frozenset(hook.name for hook in plugins_by_name[plugin_name].filter_hooks("Snapshot"))
        for plugin_name in search_plugins
        if plugin_name in plugins_by_name
    }

    total = snapshots.count()
    print(f"[*] Reindexing {total} snapshots with search plugins: {', '.join(search_plugins)}")

    def run_batch() -> None:
        if not records:
            return
        if wait_for_turn:
            wait_for_turn()
        batch_records = list(records)
        snapshot_ids = {record["snapshot_id"] for record in batch_records}
        plugin_names = {record["plugin"] for record in batch_records}
        queued_rows = {
            (str(snapshot_id), plugin_name, hook_name)
            for snapshot_id, plugin_name, hook_name in ArchiveResult.objects.filter(
                snapshot_id__in=snapshot_ids,
                plugin__in=plugin_names,
                status=ArchiveResult.StatusChoices.QUEUED,
            ).values_list("snapshot_id", "plugin", "hook_name")
        }
        records_to_queue = []
        for record in batch_records:
            snapshot_id = record["snapshot_id"]
            plugin_name = record["plugin"]
            required_hooks = required_hooks_by_plugin.get(plugin_name, frozenset())
            if required_hooks and all((snapshot_id, plugin_name, hook_name) in queued_rows for hook_name in required_hooks):
                stats["skipped_queued"] += 1
                continue
            records_to_queue.append(record)
        if not records_to_queue:
            print(
                f"    [{stats['processed']}/{total}] Already queued {len(batch_records)} index jobs",
            )
            records.clear()
            return
        # `archivebox update --index-only` intentionally breaks the usual
        # "runner discovers work" rule by inserting synthetic queued
        # ArchiveResult rows for search backends. run_plugins() keeps this as
        # statement-sized UPDATE/bulk_create work, then bumps Snapshot.retry_at
        # so the orchestrator owns actual hook execution. Paused snapshots stay
        # PAUSED; run_due_snapshot restores retry_at=MAX after targeted rows
        # finish.
        exit_code = run_plugins(
            args=(),
            records=records_to_queue,
            wait=False,
            emit_results=False,
            show_progress=False,
            preserve_queued=True,
        )
        if exit_code != 0:
            raise SystemExit(exit_code)
        stats["queued"] += len(records_to_queue)
        print(
            f"    [{stats['processed']}/{total}] Queued {len(records_to_queue)} index jobs for orchestrator",
        )
        records.clear()

    for snapshot in snapshots.select_related("crawl").paged_iterator(chunk_size=batch_size):
        try:
            stats["processed"] += 1

            if _get_snapshot_crawl(snapshot) is None:
                continue

            if collect_ids:
                stats["snapshot_ids"].append(str(snapshot.id))
            for plugin_name in search_plugins:
                records.append(
                    {
                        "type": "ArchiveResult",
                        "snapshot_id": str(snapshot.id),
                        "plugin": plugin_name,
                    },
                )
                stats["requested"] += 1
            if len(records) >= batch_size:
                run_batch()
        except KeyboardInterrupt as err:
            err.archivebox_resume = snapshot.timestamp
            raise

    run_batch()
    return stats


@enforce_types
def update(
    filter_patterns: Iterable[str] = (),
    filter_type: str = "exact",
    status: str | None = None,
    url__icontains: str | None = None,
    url__istartswith: str | None = None,
    tag: str | None = None,
    crawl_id: str | None = None,
    limit: int | None = None,
    sort: str | None = None,
    search: str | None = None,
    before: float | None = None,
    after: float | None = None,
    resume: str | None = None,
    batch_size: int = 500,
    continuous: bool = False,
    index_only: bool = False,
    migrate_only: bool = False,
    stop_daemon_stack: bool = True,
) -> None:
    """
    Update snapshots: migrate old dirs, reconcile DB, and re-queue for archiving.

    Three-phase operation (without filters):
    - Phase 1: Drain old archive/ dirs by moving to new fs location (0.8.x → 0.9.x)
    - Phase 2: O(n) scan over entire DB from most recent to least recent
    - No orphan scans needed (trust 1:1 mapping between DB and filesystem after phase 1)

    With filters: Only phase 2 (DB query), no filesystem operations.
    Without filters: All phases (full update).
    """

    from rich import print
    from archivebox.config import CONSTANTS
    from archivebox.config.django import setup_django

    setup_django()
    from archivebox.misc.checks import check_migrations

    # This must be the first database operation in `archivebox update`.
    # Old 0.7.x/0.8.x collections may not have current machine/process/crawl
    # tables yet, and even "harmless" runtime-stack bookkeeping uses current
    # ORM models. Apply Django migrations before creating Process rows, checking
    # runtime ownership, queuing retry_at maintenance ticks, or touching any
    # lazy Snapshot.save() filesystem migration path.
    print("[*] Checking for pending migrations...")
    check_migrations(auto_apply=True)

    from archivebox.machine.models import Process
    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals, raise_if_shutdown_requested
    from archivebox.core.takeover_util import (
        command_owns_foreground_runner,
        current_command,
        ensure_daemon_stack,
        standby_until_foreground_runner_needed,
    )
    from archivebox.workers.supervisord_util import run_runner_worker, stop_own_supervisord_process

    command = current_command(Process.TypeChoices.UPDATE, data_dir=CONSTANTS.DATA_DIR)

    def wait_for_turn() -> None:
        raise_if_shutdown_requested()
        standby_until_foreground_runner_needed(command, data_dir=CONSTANTS.DATA_DIR)
        raise_if_shutdown_requested()

    def run_scoped_runner(*args: str, ensure_daemon_reason: str | None = None) -> None:
        while True:
            wait_for_turn()
            if ensure_daemon_reason:
                ensure_daemon_stack(reason=ensure_daemon_reason)
            exit_code = run_runner_worker(list(args), name=f"worker_runner_update_{os.getpid()}")
            if exit_code == 0:
                return
            if not command_owns_foreground_runner(command, data_dir=CONSTANTS.DATA_DIR):
                continue
            raise SystemExit(exit_code)

    is_filtered_update = any(
        (
            filter_patterns,
            status,
            url__icontains,
            url__istartswith,
            tag,
            crawl_id,
            limit,
            sort,
            search,
            before,
            after,
        ),
    )
    touched_snapshot_ids: set[str] = set()
    exit_code = 0

    try:
        wait_for_turn()

        with foreground_shutdown_signals(), foreground_parent_watchdog():
            while True:
                do_migrate = migrate_only or not index_only
                do_index = index_only or not migrate_only
                do_run_until_idle = do_migrate or do_index
                ran_post_migrate_runner = False
                full_update_empty = False
                maintenance_work_queued = False
                runner_work_queued = False

                if do_migrate:
                    if (
                        filter_patterns
                        or status
                        or url__icontains
                        or url__istartswith
                        or tag
                        or crawl_id
                        or limit
                        or sort
                        or search
                        or before
                        or after
                    ):
                        print("[*] Processing filtered snapshots from database...")
                        stats = process_filtered_snapshots(
                            filter_patterns=filter_patterns,
                            filter_type=filter_type,
                            status=status,
                            url__icontains=url__icontains,
                            url__istartswith=url__istartswith,
                            tag=tag,
                            crawl_id=crawl_id,
                            limit=limit,
                            sort=sort,
                            search=search,
                            before=before,
                            after=after,
                            resume=resume,
                            batch_size=batch_size,
                            queue_for_archiving=do_run_until_idle,
                            wait_for_turn=wait_for_turn,
                        )
                        print_stats(stats)
                        touched_snapshot_ids.update(stats.get("snapshot_ids", []))
                        maintenance_work_queued = stats.get("queued", 0) > 0
                        runner_work_queued = runner_work_queued or maintenance_work_queued
                    else:
                        stats_combined = {"phase1": {}, "phase2": {}}

                        print("[*] Phase 1: Draining old archive/ directories (0.8.x → 0.9.x migration)...")
                        stats_combined["phase1"] = drain_old_archive_dirs(
                            resume_from=resume,
                            batch_size=batch_size,
                        )

                        print("[*] Phase 2: Processing all database snapshots (most recent first)...")
                        stats_combined["phase2"] = process_all_db_snapshots(
                            batch_size=batch_size,
                            resume=resume,
                            wait_for_turn=wait_for_turn,
                        )
                        print_combined_stats(stats_combined)
                        full_update_empty = (
                            stats_combined["phase1"].get("processed", 0) == 0 and stats_combined["phase2"].get("snapshots", 0) == 0
                        )
                        maintenance_work_queued = any(
                            (
                                stats_combined["phase1"].get("queued", 0),
                                stats_combined["phase2"].get("queued", 0),
                                stats_combined["phase2"].get("crawls_sealed", 0),
                            ),
                        )
                        runner_work_queued = runner_work_queued or maintenance_work_queued

                    if do_run_until_idle:
                        # Filesystem migration is maintenance on existing
                        # Snapshot rows: Snapshot.save() moves archive/<ts> to
                        # the current output_dir and preserves the lifecycle
                        # status. Drain those retry_at ticks before queuing
                        # search backfill below. Otherwise the sealed/paused
                        # runner branch correctly sees queued ArchiveResult
                        # rows first, runs the targeted plugins, and may leave
                        # the fs_version maintenance tick hidden behind that
                        # plugin work until another update pass.
                        if full_update_empty:
                            print("[*] No snapshots or legacy archive directories found; skipping filesystem maintenance runner.")
                        elif not maintenance_work_queued:
                            print("[*] No filesystem maintenance work queued; skipping filesystem maintenance runner.")
                        else:
                            print("[*] Phase 3: Running filesystem maintenance until idle...")
                        if full_update_empty:
                            pass
                        elif not maintenance_work_queued:
                            pass
                        elif is_filtered_update:
                            if not touched_snapshot_ids:
                                print("[*] No matching snapshots queued work for the runner.")
                            for snapshot_id in sorted(touched_snapshot_ids):
                                run_scoped_runner("--snapshot-id", snapshot_id)
                        else:
                            run_scoped_runner("--maintenance-only")
                        ran_post_migrate_runner = True

                if do_index:
                    if full_update_empty:
                        print("[*] No snapshots found; skipping search indexing backfill.")
                    else:
                        ensure_daemon_stack(reason="search indexing")
                        search_plugins = _get_search_indexing_plugins()
                        if not search_plugins:
                            print("[*] No search indexing plugins are available, nothing to backfill.")
                        else:
                            snapshots = _build_filtered_snapshots_queryset(
                                filter_patterns=filter_patterns,
                                filter_type=filter_type,
                                status=status,
                                url__icontains=url__icontains,
                                url__istartswith=url__istartswith,
                                tag=tag,
                                crawl_id=crawl_id,
                                limit=limit,
                                sort=sort,
                                search=search,
                                before=before,
                                after=after,
                                resume=resume,
                            )
                            from django.db.models import Exists, OuterRef, Q
                            from django.utils import timezone
                            from archivebox.core.models import ArchiveResult, Snapshot

                            scoped_snapshot_ids = snapshots.order_by().values("id") if is_filtered_update else None
                            queued_index_results = ArchiveResult.objects.filter(
                                status=ArchiveResult.StatusChoices.QUEUED,
                                plugin__in=search_plugins,
                            )
                            if scoped_snapshot_ids is not None:
                                queued_index_results = queued_index_results.filter(snapshot_id__in=scoped_snapshot_ids)

                            if queued_index_results.exists():
                                runner_work_queued = True
                                now = timezone.now()
                                queued_result_for_snapshot = queued_index_results.filter(snapshot_id=OuterRef("pk"))
                                snapshots_to_wake = (
                                    Snapshot.objects.filter(
                                        status__in=(Snapshot.StatusChoices.SEALED, Snapshot.StatusChoices.PAUSED),
                                    )
                                    .annotate(
                                        has_queued_index_result=Exists(queued_result_for_snapshot),
                                    )
                                    .filter(
                                        has_queued_index_result=True,
                                    )
                                    .filter(
                                        Q(retry_at__isnull=True) | Q(retry_at__gt=now),
                                    )
                                )
                                if scoped_snapshot_ids is not None:
                                    snapshots_to_wake = snapshots_to_wake.filter(id__in=scoped_snapshot_ids)
                                woken_count = snapshots_to_wake.update(
                                    retry_at=now,
                                    modified_at=now,
                                )
                                print(
                                    "[*] Existing queued search index jobs found; "
                                    f"skipping backfill scan and waking {woken_count} snapshot(s) for the runner.",
                                )
                            else:
                                stats = reindex_snapshots(
                                    snapshots,
                                    search_plugins=search_plugins,
                                    batch_size=batch_size,
                                    collect_ids=True,
                                    wait_for_turn=wait_for_turn,
                                )
                                print_index_stats(stats)
                                touched_snapshot_ids.update(stats.get("snapshot_ids", []))
                                runner_work_queued = runner_work_queued or stats["queued"] > 0

                if do_run_until_idle and (do_index or not ran_post_migrate_runner):
                    # Search/index backfill intentionally queues targeted
                    # ArchiveResult rows without reopening sealed/paused
                    # snapshots. This second runner pass drains those plugin
                    # rows after filesystem maintenance has had its own turn.
                    # For a normal unfiltered `archivebox update`, keep the
                    # historical final pass broad enough to resume genuinely
                    # queued/interrupted crawl work after maintenance is done.
                    if full_update_empty:
                        print("[*] No snapshots found; skipping queued/interrupted crawl runner.")
                    elif not runner_work_queued:
                        print("[*] No queued/interrupted crawl work found; skipping queued/interrupted crawl runner.")
                    else:
                        print("[*] Phase 3: Running queued/interrupted crawl work until idle...")
                    if full_update_empty:
                        pass
                    elif not runner_work_queued:
                        pass
                    elif touched_snapshot_ids:
                        if not touched_snapshot_ids:
                            print("[*] No matching snapshots queued work for the runner.")
                        for snapshot_id in sorted(touched_snapshot_ids):
                            run_scoped_runner("--snapshot-id", snapshot_id)
                    else:
                        run_scoped_runner(
                            *(["--maintenance-only"] if index_only or migrate_only else []),
                            ensure_daemon_reason="search indexing" if do_index else None,
                        )

                if not continuous:
                    break

                print("[yellow]Sleeping 60s before next pass...[/yellow]")
                time.sleep(60)
                resume = None
    except (KeyboardInterrupt, asyncio.CancelledError) as err:
        exit_code = 130
        exact_resume = err.__dict__.get("archivebox_resume")
        resume_cmd = ["archivebox", "update"]
        if migrate_only:
            resume_cmd.append("--migrate-only")
        if index_only:
            resume_cmd.append("--index-only")
        if batch_size != 500:
            resume_cmd.extend(["--batch-size", str(batch_size)])
        if exact_resume or resume:
            resume_cmd.extend(["--resume", str(exact_resume or resume)])
        if before is not None:
            resume_cmd.extend(["--before", str(before)])
        if after is not None:
            resume_cmd.extend(["--after", str(after)])
        if filter_type != "exact":
            resume_cmd.extend(["--filter-type", filter_type])
        if status:
            resume_cmd.extend(["--status", status])
        if url__icontains:
            resume_cmd.extend(["--url__icontains", url__icontains])
        if url__istartswith:
            resume_cmd.extend(["--url__istartswith", url__istartswith])
        if tag:
            resume_cmd.extend(["--tag", tag])
        if crawl_id:
            resume_cmd.extend(["--crawl-id", crawl_id])
        if limit:
            resume_cmd.extend(["--limit", str(limit)])
        if sort:
            resume_cmd.extend(["--sort", sort])
        if search:
            resume_cmd.extend(["--search", search])
        resume_cmd.extend(str(pattern) for pattern in filter_patterns)
        print("\n[red][X] archivebox update interrupted.[/red]")
        print("[yellow]Hint: resume this idempotent update with:[/yellow]")
        print(f"    [green]{shlex.join(resume_cmd)}[/green]")
        raise SystemExit(exit_code)
    except SystemExit as err:
        if isinstance(err.code, int):
            exit_code = err.code
        elif err.code:
            exit_code = 1
        raise
    finally:
        command.mark_exited(exit_code=exit_code)
        if stop_daemon_stack:
            stop_own_supervisord_process()


def drain_old_archive_dirs(resume_from: str | None = None, batch_size: int = 500) -> dict[str, int]:
    """
    Drain old archive/ directories (0.8.x → 0.9.x migration).

    Only processes real directories (skips symlinks - those are already migrated).
    For each old dir found in archive/:
      1. Load or create DB snapshot
      2. Trigger fs migration on save() to move to data/archive/users/{user}/...
      3. Leave symlink in archive/ pointing to new location

    After this drains, archive/ should only contain symlinks and we can trust
    1:1 mapping between DB and filesystem.
    """
    from archivebox.core.models import Snapshot
    from archivebox.config import CONSTANTS
    from archivebox.crawls.models import Crawl
    from django.utils import timezone

    stats = {"processed": 0, "migrated": 0, "queued": 0, "skipped": 0, "invalid": 0}
    crawl_url_lines: dict[str, list[str]] = {}
    crawl_url_sets: dict[str, set[str]] = {}
    dirty_crawl_ids: set[str] = set()

    archive_dir = CONSTANTS.ARCHIVE_DIR
    if not archive_dir.exists():
        return stats

    last_crawl_id = None
    while True:
        crawl_qs = Crawl.objects.filter(label__startswith="[migration] orphaned").order_by("id")
        if last_crawl_id is not None:
            crawl_qs = crawl_qs.filter(id__gt=last_crawl_id)
        crawl_batch = list(crawl_qs[:batch_size])
        if not crawl_batch:
            break
        for crawl in crawl_batch:
            last_crawl_id = crawl.id
            url_entries = crawl._iter_url_lines()
            existing_urls = {url for _raw_line, url in url_entries if url}
            lines = (crawl.urls or "").splitlines()
            changed = False
            for url in crawl.snapshot_set.order_by("timestamp").values_list("url", flat=True):
                if url not in existing_urls:
                    lines.append(url)
                    existing_urls.add(url)
                    changed = True
            if changed:
                Crawl.objects.filter(pk=crawl.pk).update(urls="\n".join(lines), modified_at=timezone.now())

    # Scan for real directories only (skip symlinks - they're already migrated)
    all_entries = list(os.scandir(archive_dir))
    entries = [
        (e.stat().st_mtime, e.path)
        for e in all_entries
        if e.is_dir(follow_symlinks=False) and Snapshot.is_legacy_archive_dir(Path(e.path))  # Skip symlinks and 0.9.x roots
    ]
    entries.sort(reverse=True)  # Newest first
    print(f"[*] Found {len(entries)} old directories to drain")

    for mtime, entry_path in entries:
        entry_path = Path(entry_path)

        # Resume from timestamp if specified
        if resume_from and entry_path.name > resume_from:
            continue

        stats["processed"] += 1

        # Try to load existing snapshot from DB
        snapshot = Snapshot.load_from_directory(entry_path)

        if not snapshot:
            # Not in DB - create new snapshot record
            snapshot = Snapshot.create_from_directory(entry_path)
            if not snapshot:
                # Invalid directory - move to invalid/
                Snapshot.move_directory_to_invalid(entry_path)
                stats["invalid"] += 1
                print(f"    [{stats['processed']}] Invalid: {entry_path.name}")
                continue

            try:
                snapshot.status = Snapshot.StatusChoices.SEALED
                snapshot.retry_at = timezone.now()
                # Snapshot.save() owns URL validation and filesystem/index side
                # effects. Do not use bulk_create() here; it bypasses save().
                snapshot.save()

                crawl = _get_snapshot_crawl(snapshot)
                if crawl is not None:
                    crawl_cache_key = str(crawl.id)
                    existing_urls = crawl_url_sets.get(crawl_cache_key)
                    if existing_urls is None:
                        url_entries = crawl._iter_url_lines()
                        existing_urls = {url for _raw_line, url in url_entries if url}
                        crawl_url_sets[crawl_cache_key] = existing_urls
                        crawl_url_lines[crawl_cache_key] = (crawl.urls or "").splitlines()
                    if snapshot.url not in existing_urls:
                        crawl_url_lines[crawl_cache_key].append(snapshot.url)
                        existing_urls.add(snapshot.url)
                        dirty_crawl_ids.add(crawl_cache_key)

                stats["queued"] += 1
                print(f"    [{stats['processed']}] Imported orphaned snapshot and queued migration: {entry_path.name}")
            except Exception as e:
                stats["skipped"] += 1
                print(f"    [{stats['processed']}] Skipped (error: {e}): {entry_path.name}")
            continue

        # Ensure snapshot has a valid crawl (migration 0024 may have failed)
        has_valid_crawl = _get_snapshot_crawl(snapshot) is not None

        if not has_valid_crawl:
            # Create a new crawl (created_by will default to system user)
            crawl = Crawl.objects.create(urls=snapshot.url)
            # Use safe_update() to avoid save() hooks and keep the SQLite
            # write to one statement while the migration loop does filesystem
            # work outside any transaction. The modified_at CAS prevents this
            # repair scan from overwriting a newer Snapshot edit.
            if not snapshot.safe_update(
                {"crawl": crawl},
                refresh=False,
                extra_filter={"modified_at": snapshot.modified_at},
            ):
                stats["skipped"] += 1
                print(f"    [{stats['processed']}] Skipped stale snapshot repair: {entry_path.name}")
                continue
            snapshot.crawl = crawl

        # Check if needs migration (0.8.x → 0.9.x)
        try:
            if snapshot.fs_migration_needed:
                if snapshot.safe_update(
                    {"retry_at": timezone.now(), "modified_at": timezone.now()},
                    refresh=False,
                    extra_filter={"modified_at": snapshot.modified_at},
                ):
                    stats["queued"] += 1
                    print(f"    [{stats['processed']}] Queued filesystem migration: {entry_path.name}")
                else:
                    stats["skipped"] += 1
                    print(f"    [{stats['processed']}] Skipped stale filesystem migration row: {entry_path.name}")
            else:
                stats["skipped"] += 1
        except Exception as e:
            stats["skipped"] += 1
            print(f"    [{stats['processed']}] Skipped (error: {e}): {entry_path.name}")

        if stats["processed"] % batch_size == 0:
            for crawl_id in tuple(dirty_crawl_ids):
                Crawl.objects.filter(pk=crawl_id).update(
                    urls="\n".join(crawl_url_lines[crawl_id]),
                    modified_at=timezone.now(),
                )
            dirty_crawl_ids.clear()

    for crawl_id in tuple(dirty_crawl_ids):
        Crawl.objects.filter(pk=crawl_id).update(
            urls="\n".join(crawl_url_lines[crawl_id]),
            modified_at=timezone.now(),
        )
    dirty_crawl_ids.clear()
    return stats


def process_all_db_snapshots(batch_size: int = 500, resume: str | None = None, wait_for_turn=None) -> dict[str, int]:
    """
    O(n) scan over entire DB from most recent to least recent.

    For each snapshot:
      1. Reconcile index.json with DB (merge titles, tags, archive results)
      2. Mark migrated snapshots sealed unless explicitly re-queued elsewhere

    No orphan detection needed - we trust 1:1 mapping between DB and filesystem
    after Phase 1 has drained all old archive/ directories.
    """
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from django.db.models import Q
    from django.utils import timezone

    stats = {
        "processed": 0,
        "scanned_dirs": 0,
        "updated_json": 0,
        "updated_db": 0,
        "queued": 0,
        "sealed": 0,
        "crawls_sealed": 0,
    }
    current_fs_version = Snapshot._fs_current_version()

    queryset = Snapshot.objects.all()
    if resume:
        queryset = queryset.filter(timestamp__lte=resume)
    total = queryset.count()
    stats["snapshots"] = total
    print(f"[*] Processing {total} snapshots from database (most recent first)...")

    def update_in_batches(rows, *, label: str, **updates) -> int:
        updated = 0
        checked = 0
        while True:
            if wait_for_turn:
                wait_for_turn()
            batch = list(rows.only("id", "modified_at").order_by("-timestamp")[:batch_size])
            if not batch:
                if updated:
                    print(f"    [{label}] complete: {updated} rows updated")
                return updated
            checked += len(batch)
            print(f"    [{label}] updating next {len(batch)} rows (seen {checked})...")
            for snapshot in batch:
                # This maintenance scan intentionally bypasses save(); it is
                # only normalizing scheduler fields, and Snapshot.save() may
                # do filesystem migration work that belongs in the runner.
                # Guard each single-row UPDATE with modified_at so stale scan
                # pages cannot overwrite newer runner/admin writes.
                updated += int(
                    snapshot.safe_update(
                        updates,
                        refresh=False,
                        extra_filter={"modified_at": snapshot.modified_at},
                    ),
                )
            print(f"    [{label}] updated {updated} rows so far")

    now = timezone.now()
    updated_rows = update_in_batches(
        queryset.exclude(
            status__in=[
                Snapshot.StatusChoices.QUEUED,
                Snapshot.StatusChoices.STARTED,
                Snapshot.StatusChoices.PAUSED,
                Snapshot.StatusChoices.SEALED,
            ],
        ),
        label="snapshot status normalization",
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
        modified_at=now,
    )
    stats["sealed"] += updated_rows
    stats["updated_db"] += updated_rows

    fs_version_rows = queryset.exclude(fs_version=current_fs_version).filter(Q(retry_at__isnull=True) | Q(retry_at__gt=now))
    stale_batch = []

    def queue_stale_fs_batch() -> None:
        if not stale_batch:
            return
        if wait_for_turn:
            wait_for_turn()
        now = timezone.now()
        # Do not bump fs_version here. The orchestrator calls Snapshot.save(),
        # which performs the idempotent filesystem migration and commits the new
        # fs_version in the same serialized worker path as normal crawls.
        updated = 0
        for snapshot in stale_batch:
            # Each row gets its own short autocommit UPDATE because this scan
            # can touch millions of snapshots while a server is also alive.
            # The modified_at predicate is the CAS guard: if the runner or
            # admin changed the snapshot after paged_iterator read it, skip it
            # and let the newer state decide whether migration is still due.
            updated += int(
                snapshot.safe_update(
                    {
                        "retry_at": now,
                        "modified_at": now,
                    },
                    refresh=False,
                    extra_filter={"fs_version": snapshot.fs_version},
                ),
            )
        stats["processed"] += len(stale_batch)
        stats["updated_db"] += updated
        stats["queued"] += updated
        print(f"    [{stats['processed']}/{total}] Queued {updated} filesystem migrations for orchestrator...")
        stale_batch.clear()

    for snapshot in (
        fs_version_rows.only("id", "crawl_id", "timestamp", "fs_version", "modified_at")
        .order_by("-timestamp")
        .paged_iterator(chunk_size=batch_size)
    ):
        try:
            stale_batch.append(snapshot)
            if len(stale_batch) >= batch_size:
                queue_stale_fs_batch()
        except KeyboardInterrupt as err:
            err.archivebox_resume = snapshot.timestamp
            raise
    queue_stale_fs_batch()

    now = timezone.now()
    # Crawls with no open child snapshots are already finished. Seal them here
    # instead of waking the foreground runner; otherwise migration/update can
    # accidentally re-enter full crawl execution for historical rows.
    stats["crawls_sealed"] = (
        Crawl.objects.filter(
            status__in=Crawl.RUNNABLE_STATES,
        )
        .exclude(
            snapshot_set__status__in=Snapshot.OPEN_STATES,
        )
        .update(
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
            modified_at=now,
        )
    )
    stats["updated_db"] += stats["crawls_sealed"]
    return stats


def process_filtered_snapshots(
    filter_patterns: Iterable[str],
    filter_type: str,
    status: str | None,
    url__icontains: str | None,
    url__istartswith: str | None,
    tag: str | None,
    crawl_id: str | None,
    limit: int | None,
    sort: str | None,
    search: str | None,
    before: float | None,
    after: float | None,
    resume: str | None,
    batch_size: int,
    queue_for_archiving: bool = True,
    wait_for_turn=None,
) -> dict[str, Any]:
    """Process snapshots matching filters (DB query only)."""
    from archivebox.core.models import Snapshot
    from django.utils import timezone

    stats: dict[str, Any] = {"processed": 0, "updated_json": 0, "updated_db": 0, "queued": 0, "snapshot_ids": []}

    snapshots = _build_filtered_snapshots_queryset(
        filter_patterns=filter_patterns,
        filter_type=filter_type,
        status=status,
        url__icontains=url__icontains,
        url__istartswith=url__istartswith,
        tag=tag,
        crawl_id=crawl_id,
        limit=limit,
        sort=sort,
        search=search,
        before=before,
        after=after,
        resume=resume,
    )

    total = snapshots.count()
    print(f"[*] Found {total} matching snapshots")

    for snapshot in snapshots.select_related("crawl").paged_iterator(chunk_size=batch_size):
        if wait_for_turn and stats["processed"] % batch_size == 0:
            wait_for_turn()
        stats["processed"] += 1

        # Skip snapshots with missing crawl references
        if _get_snapshot_crawl(snapshot) is None:
            continue

        try:
            stats["snapshot_ids"].append(str(snapshot.id))
            update_values = {}
            updated = 0
            if not isinstance(snapshot.current_step, int):
                update_values["current_step"] = 0
            if queue_for_archiving:
                update_values.update(
                    {
                        "status": Snapshot.StatusChoices.QUEUED,
                        "retry_at": timezone.now(),
                        "modified_at": timezone.now(),
                    },
                )
            if update_values:
                # update() is intentionally used instead of save(); save()
                # runs output-dir hooks, which must not happen while SQLite
                # is holding the write lock for this state change. Index-only
                # maintenance goes through reindex_snapshots/run_plugins instead
                # so paused snapshots keep status=paused while only their
                # targeted search ArchiveResult rows run. Since this loop reads
                # with paged_iterator() and writes later, modified_at is the CAS
                # guard that prevents stale CLI scans from overwriting a newer
                # runner/admin update to the same snapshot.
                updated = int(
                    snapshot.safe_update(
                        update_values,
                        refresh=False,
                        extra_filter={"modified_at": snapshot.modified_at},
                    ),
                )
                stats["updated_db"] += updated

            stats["queued"] += updated if queue_for_archiving else 0
        except KeyboardInterrupt as err:
            err.archivebox_resume = snapshot.timestamp
            raise
        except Exception as e:
            # Skip snapshots that can't be processed
            print(f"    [!] Skipping snapshot {snapshot.id}: {e}")
            continue

        if stats["processed"] % batch_size == 0:
            print(f"    [{stats['processed']}/{total}] Processed...")

    return stats


def print_stats(stats: dict):
    """Print statistics for filtered mode."""
    from rich import print

    print(f"""
[green]Update Complete[/green]
  Scanned rows:     {stats["processed"]}
  Updated JSON:     {stats.get("updated_json", 0)}
  Updated DB rows:  {stats.get("updated_db", 0)}
  Queued snapshots: {stats["queued"]}
""")


def print_combined_stats(stats_combined: dict):
    """Print statistics for full mode."""
    from rich import print

    s1 = stats_combined["phase1"]
    s2 = stats_combined["phase2"]

    print(f"""
[green]Archive Update Complete[/green]

Phase 1 (Drain Old Dirs):
  Scanned dirs:     {s1.get("processed", 0)}
  Moved files:      {s1.get("migrated", 0)}
  Skipped dirs:     {s1.get("skipped", 0)}
  Invalid dirs:     {s1.get("invalid", 0)}

Phase 2 (Process DB):
  Scanned dirs:     {s2.get("scanned_dirs", 0)}
  Updated JSON:     {s2.get("updated_json", 0)}
  Updated DB rows:  {s2.get("updated_db", 0)}
  Sealed snapshots: {s2.get("sealed", 0)}
  Sealed crawls:    {s2.get("crawls_sealed", 0)}
""")


def print_index_stats(stats: dict[str, Any]) -> None:
    from rich import print

    print(f"""
[green]Search Reindex Complete[/green]
  Scanned rows:      {stats["processed"]}
  Requested jobs:    {stats.get("requested", stats["queued"])}
  Queued index jobs: {stats["queued"]}
  Already queued:    {stats.get("skipped_queued", 0)}
""")


@click.command()
@click.option("--resume", type=str, help="Resume from timestamp")
@click.option("--batch-size", type=int, default=500, help="Commit every N records")
@click.option("--continuous", is_flag=True, help="Run continuously as background worker")
@click.option("--index-only", is_flag=True, help="Backfill available search indexes from existing archived content")
@click.option("--migrate-only", is_flag=True, help="Only migrate filesystem and update database/index state")
@snapshot_filter_options(default_filter_type="exact")
@docstring(update.__doc__)
def main(**kwargs):
    from archivebox.core.shutdown_util import foreground_parent_watchdog, foreground_shutdown_signals

    try:
        with foreground_shutdown_signals(), foreground_parent_watchdog():
            update(**kwargs)
    except ValueError as err:
        raise click.BadParameter(str(err), param_hint="--status") from err
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
