"""
Background task functions for queuing work to the background runner.

These functions queue Snapshots/Crawls for processing by setting their status
to QUEUED so `archivebox run --daemon` or `archivebox server` can pick them up.

NOTE: These functions do NOT start the runner. They assume it's already
running via `archivebox server` or will be run inline by the CLI.
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

    _, result = add(**add_kwargs)

    return len(result) if result else 0


def bg_archive_snapshots(snapshots, kwargs: dict | None = None) -> int:
    """
    Queue multiple snapshots for archiving via the shared runner loop.

    Returns the number of snapshots queued.
    """
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    kwargs = kwargs or {}

    # Queue snapshots by setting status to queued with immediate retry_at
    queued_count = 0
    for snapshot in snapshots:
        if hasattr(snapshot, 'id'):
            Snapshot.objects.filter(id=snapshot.id).update(
                status=Snapshot.StatusChoices.QUEUED,
                retry_at=timezone.now(),
                downloaded_at=None,
            )
            crawl_id = getattr(snapshot, 'crawl_id', None)
            if crawl_id:
                Crawl.objects.filter(id=crawl_id).update(
                    status=Crawl.StatusChoices.QUEUED,
                    retry_at=timezone.now(),
                )
            queued_count += 1

    return queued_count


def bg_archive_snapshot(snapshot, overwrite: bool = False, methods: list | None = None) -> int:
    """
    Queue a single snapshot for archiving via the shared runner loop.

    Returns 1 if queued, 0 otherwise.
    """
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    if hasattr(snapshot, 'id'):
        Snapshot.objects.filter(id=snapshot.id).update(
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
            downloaded_at=None,
        )
        crawl_id = getattr(snapshot, 'crawl_id', None)
        if crawl_id:
            Crawl.objects.filter(id=crawl_id).update(
                status=Crawl.StatusChoices.QUEUED,
                retry_at=timezone.now(),
            )
        return 1

    return 0
