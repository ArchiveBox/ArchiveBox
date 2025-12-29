"""
Background task functions for queuing work to the orchestrator.

These functions queue Snapshots/Crawls for processing by setting their status
to QUEUED, which the orchestrator workers will pick up and process.

NOTE: These functions do NOT start the orchestrator - they assume it's already
running via `archivebox server` (supervisord) or will be run inline by the CLI.
"""

__package__ = 'archivebox.workers'

from django.utils import timezone


def bg_add(add_kwargs: dict) -> int:
    """
    Add URLs and queue them for archiving.

    Returns the number of snapshots created.
    """
    from archivebox.cli.archivebox_add import add

    assert add_kwargs and add_kwargs.get("urls")

    # When called as background task, always run in background mode
    add_kwargs = add_kwargs.copy()
    add_kwargs['bg'] = True

    result = add(**add_kwargs)

    return len(result) if result else 0


def bg_archive_snapshots(snapshots, kwargs: dict | None = None) -> int:
    """
    Queue multiple snapshots for archiving via the state machine system.

    This sets snapshots to 'queued' status so the orchestrator workers pick them up.
    The actual archiving happens through the worker's process_item() method.

    Returns the number of snapshots queued.
    """
    from archivebox.core.models import Snapshot

    kwargs = kwargs or {}

    # Queue snapshots by setting status to queued with immediate retry_at
    queued_count = 0
    for snapshot in snapshots:
        if hasattr(snapshot, 'id'):
            # Update snapshot to queued state so workers pick it up
            Snapshot.objects.filter(id=snapshot.id).update(
                status=Snapshot.StatusChoices.QUEUED,
                retry_at=timezone.now(),
            )
            queued_count += 1

    return queued_count


def bg_archive_snapshot(snapshot, overwrite: bool = False, methods: list | None = None) -> int:
    """
    Queue a single snapshot for archiving via the state machine system.

    This sets the snapshot to 'queued' status so the orchestrator workers pick it up.
    The actual archiving happens through the worker's process_item() method.

    Returns 1 if queued, 0 otherwise.
    """
    from archivebox.core.models import Snapshot

    # Queue the snapshot by setting status to queued
    if hasattr(snapshot, 'id'):
        Snapshot.objects.filter(id=snapshot.id).update(
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        return 1

    return 0
