from __future__ import annotations
from datetime import timedelta
from django.utils import timezone
from archivebox.workers.models import ACTIVE_STATE_LEASE_SECONDS
from archivebox.crawls.locks import crawl_lifecycle_lock

from .maintenance import run_snapshot_maintenance
from .console import _runner_console_line
from .install import run_binary
from .crawl import run_crawl


def run_due_crawl(crawl, *, lock_seconds: int, interactive_interrupts: bool = False) -> bool:
    with crawl_lifecycle_lock(str(crawl.id)):
        return _run_due_crawl_locked(
            crawl,
            lock_seconds=lock_seconds,
            interactive_interrupts=interactive_interrupts,
        )


def _run_due_crawl_locked(crawl, *, lock_seconds: int, interactive_interrupts: bool = False) -> bool:
    try:
        crawl.refresh_from_db(fields=["status", "retry_at", "modified_at"])
    except type(crawl).DoesNotExist:
        return False

    if crawl.is_paused:
        _runner_console_line(crawl=crawl, status="PAUSED")
        return True
    if crawl.status in (crawl.StatusChoices.QUEUED, crawl.StatusChoices.STARTED):
        from archivebox.core.models import Snapshot

        now = timezone.now()
        snapshot_count = crawl.snapshot_set.count()
        due_active_snapshots = crawl.snapshot_set.filter(
            status__in=Snapshot.RUNNABLE_STATES,
            retry_at__lte=now,
        ).exists()
        if snapshot_count and due_active_snapshots:
            # Child Snapshot rows own active work. Do not rewrite the parent
            # row unless it is still the same STARTED row we selected; this
            # avoids hot-looping on the parent while child work is ready without
            # resurrecting a user cancellation that sealed the crawl after
            # selection.
            crawl.safe_update(
                {
                    "status": crawl.StatusChoices.STARTED,
                    "retry_at": now + timedelta(seconds=ACTIVE_STATE_LEASE_SECONDS),
                    "modified_at": now,
                },
                refresh=False,
                extra_filter={"status": crawl.StatusChoices.STARTED},
            )
            return True
        if snapshot_count and not due_active_snapshots:
            if crawl.is_finished():
                if not crawl.claim_processing_lock(lock_seconds=lock_seconds):
                    return False
                crawl.refresh_from_db()
                crawl.advance_lifecycle()
                return True

            # retry_at is the only queue/ownership signal the runner sees.
            # Clearing it on an unfinished crawl hides the row forever, so keep
            # future snapshots scheduled and repair NULL queued child locks here.
            unlocked_children = crawl.snapshot_set.filter(
                status=Snapshot.StatusChoices.QUEUED,
                retry_at__isnull=True,
            ).update(
                retry_at=now,
                modified_at=now,
            )
            if unlocked_children:
                crawl.update_and_requeue(status=crawl.StatusChoices.STARTED, retry_at=now)
                return True

            next_snapshot_retry = (
                crawl.snapshot_set.filter(
                    status__in=Snapshot.OPEN_STATES,
                    retry_at__gt=now,
                )
                .order_by("retry_at", "created_at")
                .values_list("retry_at", flat=True)
                .first()
            )
            crawl.update_and_requeue(
                status=crawl.StatusChoices.STARTED,
                retry_at=next_snapshot_retry or now + timedelta(seconds=10),
            )
            return True
        if not crawl.claim_processing_lock(lock_seconds=lock_seconds):
            return False
        crawl.refresh_from_db()
        if crawl.status == crawl.StatusChoices.STARTED and crawl.is_finished():
            crawl.advance_lifecycle()
            return True
        _runner_console_line(crawl=crawl)
        run_crawl(str(crawl.id), process_discovered_snapshots_inline=True, interactive_interrupts=interactive_interrupts)
        return True

    if crawl.status == crawl.StatusChoices.SEALED:
        if not type(crawl).claim_for_worker(crawl, lock_seconds=lock_seconds):
            return False
        _runner_console_line(crawl=crawl, status="SEALED")
        crawl.cleanup_runtime()
        crawl.update_and_requeue(retry_at=None)
        return True

    crawl.update_and_requeue(retry_at=None)
    return True


def run_due_snapshot(snapshot, *, lock_seconds: int, interactive_interrupts: bool = False, runtime_config=None) -> bool:
    with crawl_lifecycle_lock(str(snapshot.crawl_id)):
        return _run_due_snapshot_locked(
            snapshot,
            lock_seconds=lock_seconds,
            interactive_interrupts=interactive_interrupts,
            runtime_config=runtime_config,
        )


def _run_due_snapshot_locked(snapshot, *, lock_seconds: int, interactive_interrupts: bool = False, runtime_config=None) -> bool:
    from archivebox.core.models import Snapshot

    try:
        snapshot = Snapshot.objects.get(pk=snapshot.pk)
    except Snapshot.DoesNotExist:
        return False
    parent_reconciled = snapshot.reconcile_parent_lifecycle(lock_seconds=lock_seconds)
    if parent_reconciled is not None:
        if parent_reconciled:
            snapshot.refresh_from_db()
            if snapshot.status == Snapshot.StatusChoices.SEALED and snapshot.fs_migration_needed:
                return run_snapshot_maintenance(str(snapshot.id))
        return parent_reconciled

    if snapshot.is_paused:
        # Paused work never executes out of band. ArchiveResult rows are
        # historical projections and are not rewritten as scheduler state.
        snapshot.restore_paused_scheduler_marker()
        return True
    if snapshot.status == Snapshot.StatusChoices.SEALED:
        if not Snapshot.claim_for_worker(snapshot, lock_seconds=lock_seconds):
            return False
        snapshot.refresh_from_db()
        owned_retry_at = snapshot.retry_at
        snapshot.finalize_completed_upload_results()
        if snapshot.fs_migration_needed:
            snapshot.migrate_filesystem_to_current_version()
        snapshot.refresh_from_db()
        if snapshot.status != Snapshot.StatusChoices.SEALED or snapshot.retry_at != owned_retry_at:
            return True
        retry_plugins = [str(name).strip() for name in (snapshot.config or {}).get("RETRY_PLUGINS", []) if str(name).strip()]
        if retry_plugins:
            _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
            run_crawl(
                str(snapshot.crawl_id),
                snapshot_ids=[str(snapshot.id)],
                selected_plugins=retry_plugins,
                process_discovered_snapshots_inline=False,
                interactive_interrupts=interactive_interrupts,
            )
            return True
        return run_snapshot_maintenance(str(snapshot.id))

    if not snapshot.claim_processing_lock(lock_seconds=lock_seconds):
        return False
    snapshot.refresh_from_db()
    if any(process.is_running for process in snapshot.process_set.filter(status="running").iterator()):
        # The Snapshot lease may have expired while an abx-dl hook process is
        # still alive. Preserve the snapshot-level ownership boundary and do
        # not launch a second sequence; ArchiveResult status is irrelevant.
        snapshot.update_and_requeue(retry_at=timezone.now() + timedelta(seconds=lock_seconds))
        return True
    if snapshot.fs_migration_needed:
        # Migrate before abx-dl writes new hook outputs. The claimed Snapshot
        # lease remains in place and the idempotent migration persists its
        # indexed fs_version marker only after copy/verification/cleanup.
        snapshot.migrate_filesystem_to_current_version()
        snapshot.refresh_from_db()
    if snapshot.status == Snapshot.StatusChoices.QUEUED:
        snapshot.start_processing()
        snapshot.refresh_from_db()
    if snapshot.status != Snapshot.StatusChoices.STARTED:
        return True
    _runner_console_line(crawl_id=snapshot.crawl_id, snapshot=snapshot)
    run_crawl(
        str(snapshot.crawl_id),
        snapshot_ids=[str(snapshot.id)],
        selected_plugins=None,
        process_discovered_snapshots_inline=True,
        interactive_interrupts=interactive_interrupts,
    )
    return True


def run_due_binary(binary, *, lock_seconds: int) -> bool:
    from archivebox.crawls.locks import binary_lifecycle_lock

    with binary_lifecycle_lock(str(binary.id)):
        binary.refresh_from_db()
        if binary.status == binary.StatusChoices.INSTALLED:
            return True
        if not binary.claim_processing_lock(lock_seconds=lock_seconds):
            return False
        run_binary(str(binary.id))
    return True
