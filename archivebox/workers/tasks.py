"""
Background task functions for queuing work to the orchestrator.

These functions queue Snapshots/Crawls for processing by setting their status
to QUEUED, which the orchestrator workers will pick up and process.
"""

__package__ = 'archivebox.workers'

from django.utils import timezone


def ensure_orchestrator_running():
    """Ensure the orchestrator is running to process queued items."""
    from .orchestrator import Orchestrator

    if not Orchestrator.is_running():
        # Start orchestrator in background
        orchestrator = Orchestrator(exit_on_idle=True)
        orchestrator.start()


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

    # Ensure orchestrator is running to process the new snapshots
    ensure_orchestrator_running()

    return len(result) if result else 0


def bg_archive_snapshots(snapshots, kwargs: dict | None = None) -> int:
    """
    Queue multiple snapshots for archiving via the state machine system.

    This sets snapshots to 'queued' status so the orchestrator workers pick them up.
    The actual archiving happens through the worker's process_item() method.

    Returns the number of snapshots queued.
    """
    from core.models import Snapshot

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

    # Ensure orchestrator is running to process the queued snapshots
    if queued_count > 0:
        ensure_orchestrator_running()

    return queued_count


def bg_archive_snapshot(snapshot, overwrite: bool = False, methods: list | None = None) -> int:
    """
    Queue a single snapshot for archiving via the state machine system.

    This sets the snapshot to 'queued' status so the orchestrator workers pick it up.
    The actual archiving happens through the worker's process_item() method.

    Returns 1 if queued, 0 otherwise.
    """
    from core.models import Snapshot

    # Queue the snapshot by setting status to queued
    if hasattr(snapshot, 'id'):
        Snapshot.objects.filter(id=snapshot.id).update(
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )

        # Ensure orchestrator is running to process the queued snapshot
        ensure_orchestrator_running()
        return 1

    return 0
