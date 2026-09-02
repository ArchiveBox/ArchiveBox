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
    from archivebox.core.models import ArchiveResult, Snapshot
    from django.db.models import Exists, OuterRef

    # Search backfill is the one maintenance hook allowed to execute without
    # reopening a Snapshot. Restrict that exception to already-sealed rows;
    # every open lifecycle state remains owned by the normal runner lifecycle.
    snapshots = snapshots.filter(status=Snapshot.StatusChoices.SEALED)

    stats: dict[str, Any] = {"processed": 0, "requested": 0, "queued": 0, "reindexed": 0, "snapshot_ids": []}
    print(f"[*] Reindexing missing search indexes with: {', '.join(search_plugins)}")

    completed_statuses = [ArchiveResult.StatusChoices.SUCCEEDED, ArchiveResult.StatusChoices.NORESULTS]
    for plugin_name in search_plugins:
        completed_result = ArchiveResult.objects.filter(
            snapshot_id=OuterRef("pk"),
            plugin=plugin_name,
            status__in=completed_statuses,
        )
        candidates = snapshots.annotate(has_completed_index=Exists(completed_result)).filter(has_completed_index=False).order_by("id")
        after_id = None
        while True:
            if wait_for_turn:
                wait_for_turn()
            page = candidates.filter(id__gt=after_id) if after_id is not None else candidates
            batch = list(page.select_related(None).only("id", "timestamp")[:batch_size])
            if not batch:
                break
            after_id = batch[-1].id
            records = [{"type": "Snapshot", "id": str(snapshot.id)} for snapshot in batch]
            stats["processed"] += len(batch)
            stats["requested"] += len(batch)
            if collect_ids:
                stats["snapshot_ids"].extend(str(snapshot.id) for snapshot in batch)
            exit_code = run_plugins(
                args=(),
                records=records,
                plugins=plugin_name,
                wait=True,
                emit_results=False,
                show_progress=False,
            )
            if exit_code != 0:
                raise SystemExit(exit_code)
            stats["reindexed"] += len(batch)
            print(f"    [{plugin_name}] indexed {stats['reindexed']} missing snapshots")
    return stats


def run_scheduled_maintenance(*, batch_size: int = 500) -> dict[str, Any]:
    """Queue stale filesystem rows and backfill missing search facts."""
    from archivebox.core.models import Snapshot

    filesystem_stats = process_all_db_snapshots(batch_size=batch_size)
    search_plugins = _get_search_indexing_plugins()
    search_stats = (
        reindex_snapshots(
            Snapshot.objects.filter(fs_version=Snapshot._fs_current_version()),
            search_plugins=search_plugins,
            batch_size=batch_size,
        )
        if search_plugins
        else {"processed": 0, "requested": 0, "queued": 0, "reindexed": 0, "snapshot_ids": []}
    )
    return {"filesystem": filesystem_stats, "search": search_stats}


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
    - Phase 1: Drain legacy archive/ directories into the current layout
    - Phase 2: Select only stale fs_version rows through the indexed column
    - Phase 3: Run queued snapshot-level filesystem maintenance until idle

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
        standby_until_foreground_runner_needed,
    )
    from archivebox.workers.supervisord_util import run_runner_worker, stop_own_supervisord_process

    command = current_command(Process.TypeChoices.UPDATE, data_dir=CONSTANTS.DATA_DIR)

    def still_owns_foreground_runner() -> bool:
        from django.db import connections

        try:
            return command_owns_foreground_runner(command, data_dir=CONSTANTS.DATA_DIR)
        finally:
            connections.close_all()

    def wait_for_turn() -> None:
        raise_if_shutdown_requested()
        standby_until_foreground_runner_needed(command, data_dir=CONSTANTS.DATA_DIR)
        raise_if_shutdown_requested()

    def run_scoped_runner(*args: str) -> None:
        while True:
            wait_for_turn()
            exit_code = run_runner_worker(
                list(args),
                name=f"worker_runner_update_{os.getpid()}",
                keep_running=still_owns_foreground_runner,
            )
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
                            queue_for_archiving=True,
                            wait_for_turn=wait_for_turn,
                        )
                        print_stats(stats)
                        touched_snapshot_ids.update(stats.get("snapshot_ids", []))
                    else:
                        stats_combined = {"phase1": {}, "phase2": {}}

                        print("[*] Phase 1: Draining old archive/ directories (0.8.x → 0.9.x migration)...")
                        stats_combined["phase1"] = drain_old_archive_dirs(
                            resume_from=resume,
                            batch_size=batch_size,
                        )

                        print("[*] Phase 2: Selecting database snapshots with stale filesystem versions...")
                        stats_combined["phase2"] = process_all_db_snapshots(
                            batch_size=batch_size,
                            resume=resume,
                            wait_for_turn=wait_for_turn,
                        )
                        print_combined_stats(stats_combined)
                    # The due selectors are indexed and cheap when empty, so
                    # always drain them instead of preceding the runner with
                    # whole-table counts merely to decide whether to call it.
                    print("[*] Phase 3: Running filesystem maintenance until idle...")
                    if is_filtered_update:
                        for snapshot_id in sorted(touched_snapshot_ids):
                            run_scoped_runner("--snapshot-id", snapshot_id)
                    elif migrate_only:
                        run_scoped_runner("--maintenance-only")
                    else:
                        run_scoped_runner()

                if do_index:
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
                        stats = reindex_snapshots(
                            snapshots,
                            search_plugins=search_plugins,
                            batch_size=batch_size,
                            collect_ids=is_filtered_update,
                            wait_for_turn=wait_for_turn,
                        )
                        print_index_stats(stats)
                        touched_snapshot_ids.update(stats.get("snapshot_ids", []))

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

    Removes obsolete timestamp symlinks and processes real legacy directories.
    For each old dir found in archive/:
      1. Load or create DB snapshot
      2. Trigger fs migration on save() to move to data/archive/users/{user}/...
      3. Remove the old timestamp path after the verified migration commits

    After this drains, current snapshot data exists only under archive/users/.
    """
    from archivebox.core.models import Snapshot
    from archivebox.config import CONSTANTS
    from archivebox.crawls.models import Crawl
    from django.utils import timezone

    stats = {"processed": 0, "migrated": 0, "queued": 0, "skipped": 0, "invalid": 0, "removed_symlinks": 0}
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

    # Compatibility timestamp projections are harmful in portable exports and
    # duplicate the obsolete 0.7.x-looking namespace without containing data.
    all_entries = list(os.scandir(archive_dir))
    for entry in all_entries:
        entry_path = Path(entry.path)
        if entry.is_symlink() and Snapshot.is_legacy_archive_dir(entry_path):
            try:
                target_path = entry_path.resolve(strict=True)
                points_into_current_layout = target_path.is_relative_to(CONSTANTS.USERS_DIR.resolve(strict=True))
            except OSError:
                points_into_current_layout = False

            if points_into_current_layout:
                entry_path.unlink(missing_ok=True)
                stats["removed_symlinks"] += 1

    # Scan real legacy directories only; these still contain data to migrate.
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
    """Queue only snapshots whose indexed filesystem version is stale."""
    from archivebox.core.models import Snapshot
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
    queryset = Snapshot.objects.filter(fs_version__in=Snapshot._FS_VERSION_MIGRATION_PATHS)
    if resume:
        queryset = queryset.filter(timestamp__lte=resume)
    initial_now = timezone.now()
    rows_to_wake = queryset.filter(Q(retry_at__isnull=True) | Q(retry_at__gt=initial_now))
    after_id = None
    while True:
        if wait_for_turn:
            wait_for_turn()
        page = rows_to_wake.filter(id__gt=after_id) if after_id is not None else rows_to_wake
        batch = list(page.only("id", "fs_version", "modified_at").order_by("id")[:batch_size])
        if not batch:
            break
        after_id = batch[-1].id
        now = timezone.now()
        updated = 0
        for snapshot in batch:
            updated += int(
                snapshot.safe_update(
                    {"retry_at": now, "modified_at": now},
                    refresh=False,
                    extra_filter={"fs_version": snapshot.fs_version},
                ),
            )
        stats["processed"] += len(batch)
        stats["updated_db"] += updated
        stats["queued"] += updated
        print(f"    Queued {stats['queued']} stale filesystem snapshots so far...")
    stats["snapshots"] = stats["processed"]
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
  Missing index runs: {stats["processed"]}
  Requested runs:    {stats.get("requested", 0)}
  Indexed snapshots: {stats.get("reindexed", 0)}
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
