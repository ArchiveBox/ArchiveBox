#!/usr/bin/env python3

__package__ = "archivebox.cli"
__command__ = "archivebox remove"

import time
from pathlib import Path
from collections.abc import Iterable

import rich_click as click

from django.db.models import QuerySet

from archivebox.config import CONSTANTS
from archivebox.config.django import setup_django
from archivebox.misc.util import enforce_types, docstring
from archivebox.misc.checks import check_data_folder
from archivebox.misc.logging_util import (
    log_list_started,
    log_list_finished,
    log_removal_started,
    log_removal_finished,
    TimedProgress,
)
from archivebox.cli.archivebox_snapshot import snapshot_filter_options


@enforce_types
def remove(
    filter_patterns: Iterable[str] = (),
    filter_type: str = "exact",
    snapshots: QuerySet | None = None,
    after: float | None = None,
    before: float | None = None,
    yes: bool = False,
    delete: bool = False,
    out_dir: Path = CONSTANTS.DATA_DIR,
    timeout: float | None = None,
    **kwargs,
) -> dict[str, object]:
    """Remove the specified URLs from the archive"""

    setup_django()
    check_data_folder()
    timeout = float(timeout) if timeout is not None else None

    from archivebox.core.models import Snapshot

    filter_kwargs = {
        **kwargs,
        "filter_patterns": filter_patterns,
        "filter_type": filter_type,
        "after": after,
        "before": before,
    }
    pattern_list = list(filter_patterns)

    log_list_started(pattern_list or None, filter_type)
    timer = TimedProgress(360, prefix="      ")
    try:
        if snapshots is None:
            snapshots = Snapshot.objects.order_by("-created_at").search(**filter_kwargs)
        # Freeze the target set up-front so a concurrent daemon writing new
        # snapshots can't extend the deletion under us, and so the cursor isn't
        # held open across the per-row deletes below.
        snapshot_pks = list(snapshots.values_list("pk", flat=True))
    finally:
        timer.end()

    if not snapshot_pks:
        log_removal_finished(0, 0)
        raise SystemExit(1)

    if not yes:
        log_list_finished(snapshots)
        log_removal_started(snapshots, yes=False)

    from archivebox.search.query import flush_search_index

    started_at = time.monotonic()
    deadline = started_at + timeout if timeout is not None else None

    # Search-index flush touches a separate backend (FTS / sonic), not the
    # main index.sqlite3 writer lock, so it's safe to do once up front.
    flush_search_index(snapshots=snapshots)

    # Delete one snapshot at a time. Each ``.delete()`` is its own short
    # Django-atomic block, so the writer lock is released between rows and
    # an in-flight daemon transaction can interleave instead of deadlocking.
    # Filesystem cleanup for each row is scheduled via ``transaction.on_commit``
    # in ``base_models/models.py`` and runs AFTER its row's tx commits — so
    # rmtree doesn't hold the lock either.
    #
    deleted_snapshot_pks = []
    timed_out = False
    timeout_error = ""
    for index, pk in enumerate(snapshot_pks):
        if deadline is not None and time.monotonic() >= deadline:
            timed_out = True
            timeout_error = f"Remove timed out after {timeout:g}s with {len(snapshot_pks) - index} snapshots remaining."
            break
        deleted_count, _ = Snapshot.objects.filter(pk=pk).delete()
        if deleted_count:
            deleted_snapshot_pks.append(pk)

    all_snapshots = Snapshot.objects.all()
    remaining_count = all_snapshots.count()
    deleted_snapshot_id_set = set(deleted_snapshot_pks)
    remaining_snapshot_pks = [snapshot_id for snapshot_id in snapshot_pks if snapshot_id not in deleted_snapshot_id_set]
    log_removal_finished(remaining_count, len(deleted_snapshot_pks))

    return {
        "removed_count": len(deleted_snapshot_pks),
        "removed_snapshot_ids": [str(snapshot_id) for snapshot_id in deleted_snapshot_pks],
        "not_removed_count": len(remaining_snapshot_pks),
        "not_removed_snapshot_ids": [str(snapshot_id) for snapshot_id in remaining_snapshot_pks],
        "success": not timed_out,
        "error": timeout_error,
        "timeout": timeout,
    }


@click.command()
@click.option("--yes", is_flag=True, help="Remove links instantly without prompting to confirm")
@click.option("--delete", is_flag=True, help="Compatibility no-op; archived content is deleted automatically")
@click.option("--timeout", type=float, default=None, help="Maximum seconds to spend deleting snapshots")
@snapshot_filter_options(default_filter_type="exact")
@docstring(remove.__doc__)
def main(**kwargs):
    """Remove the specified URLs from the archive"""
    result = remove(**kwargs)
    if not result["success"]:
        raise SystemExit(124)


if __name__ == "__main__":
    main()
