from __future__ import annotations

from pathlib import Path

from django.utils import timezone
from rich.console import Console


def _is_signal_interrupted_exit(exit_code: int | None) -> bool:
    return exit_code is not None and (exit_code < 0 or exit_code >= 128)


def recover_orchestrator_state(*, include_chrome: bool = False) -> dict[str, int]:
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.services.archive_result_service import _collect_output_metadata
    from archivebox.machine.models import Process
    from django.core.exceptions import ValidationError
    from django.db.models import Exists, OuterRef, Q, Subquery, Value
    from django.db.models.functions import Coalesce

    now = timezone.now()
    recovery_console = Console(stderr=True, highlight=False, soft_wrap=True)
    cleaned = {
        "processes_stale_running": Process.cleanup_stale_running(),
        "processes_orphaned_workers": Process.cleanup_orphaned_workers(),
        "chrome_processes_orphaned": Process.cleanup_orphaned_chrome() if include_chrome else 0,
        "crawls_queued_without_retry_at": 0,
        "snapshots_queued_without_retry_at": 0,
        "archiveresults_backoff": 0,
        "snapshots_queued_plugin_rows_waiting_on_stale_lease": 0,
        "archiveresults_started_without_running_process": 0,
        "archiveresults_missing_for_orphaned_hook_processes": 0,
        "snapshots_started_without_running_results": 0,
        "crawls_started_with_due_snapshots": 0,
        "crawls_started_waiting_on_future_snapshots": 0,
        "crawls_started_without_active_snapshots": 0,
    }

    running_archiveresults = ArchiveResult.objects.filter(
        snapshot_id=OuterRef("pk"),
        status=ArchiveResult.StatusChoices.STARTED,
        process__status=Process.StatusChoices.RUNNING,
    )
    active_child_snapshots = Snapshot.objects.filter(
        crawl_id=OuterRef("pk"),
        status__in=Snapshot.OPEN_STATES,
    )
    due_child_snapshots = active_child_snapshots.exclude(status=Snapshot.StatusChoices.PAUSED).filter(
        Q(retry_at__isnull=True) | Q(retry_at__lte=now),
    )
    next_future_child_retry = Subquery(
        active_child_snapshots.filter(retry_at__gt=now).order_by("retry_at").values("retry_at")[:1],
    )

    # Broken lock repair: QUEUED rows with retry_at=NULL are invisible to the
    # queue. Set only the scheduling field so the runner owns the next tick.
    cleaned["crawls_queued_without_retry_at"] = Crawl.objects.filter(
        status=Crawl.StatusChoices.QUEUED,
        retry_at__isnull=True,
    ).update(retry_at=now, modified_at=now)
    cleaned["snapshots_queued_without_retry_at"] = Snapshot.objects.filter(
        status=Snapshot.StatusChoices.QUEUED,
        retry_at__isnull=True,
        crawl__status__in=Crawl.RUNNABLE_STATES,
    ).update(retry_at=now, modified_at=now)
    backoff_results = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.BACKOFF)
    orphaned_results = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.STARTED).exclude(
        process__status=Process.StatusChoices.RUNNING,
    )
    # ArchiveResult has no retry_at scheduler. Wake only the parent Snapshots
    # for result rows we are about to repair, then requeue those exact rows.
    # Using subqueries keeps million-row recovery in SQLite instead of building
    # Python ID lists or scanning all sealed snapshots.
    Snapshot.objects.filter(
        id__in=backoff_results.values("snapshot_id"),
        status__in=[Snapshot.StatusChoices.SEALED, Snapshot.StatusChoices.PAUSED],
        retry_at__isnull=True,
    ).update(retry_at=now, modified_at=now)
    Snapshot.objects.filter(
        id__in=orphaned_results.values("snapshot_id"),
        status__in=[Snapshot.StatusChoices.SEALED, Snapshot.StatusChoices.PAUSED],
        retry_at__isnull=True,
    ).update(retry_at=now, modified_at=now)
    cleaned["archiveresults_backoff"] = backoff_results.update(status=ArchiveResult.StatusChoices.QUEUED, modified_at=now)
    # Targeted plugin rows on final/paused Snapshots are scheduled through the
    # parent Snapshot.retry_at. retry_at=NULL is the normal idle marker for a
    # sealed Snapshot and must not be interpreted as queued work just because
    # old/synthetic ArchiveResult rows exist. If takeover kills the runner
    # after it leases the Snapshot but before queued ArchiveResult rows finish,
    # the rows remain QUEUED while retry_at sits in the future. Recovery runs
    # only after this runner has won the single-runner gate, so it can safely
    # unlock those stale plugin leases for immediate processing instead of
    # waiting out the previous owner's full lock timeout.
    queued_plugin_results = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.QUEUED)
    cleaned["snapshots_queued_plugin_rows_waiting_on_stale_lease"] = (
        Snapshot.objects.filter(
            id__in=queued_plugin_results.values("snapshot_id"),
            status__in=[Snapshot.StatusChoices.SEALED, Snapshot.StatusChoices.PAUSED],
        )
        .filter(retry_at__gt=now)
        .update(retry_at=now, modified_at=now)
    )
    # Impossible state repair: STARTED ArchiveResults without a live Process
    # have no owner left to emit completion. Requeue only the result row; the
    # snapshot/crawl schedulers will pick up normal retry processing.
    cleaned["archiveresults_started_without_running_process"] = orphaned_results.update(
        status=ArchiveResult.StatusChoices.QUEUED,
        process=None,
        modified_at=now,
    )
    orphaned_hook_processes = Process.objects.filter(
        process_type=Process.TypeChoices.HOOK,
        archiveresult__isnull=True,
    ).exclude(status=Process.StatusChoices.RUNNING)
    for process in orphaned_hook_processes.only("id", "pwd", "cmd", "process_type", "status"):
        hook_script_name = process.hook_script_name
        if not hook_script_name or not process.pwd:
            continue
        plugin_dir = Path(process.pwd)
        try:
            # Old or synthetic hook Process rows can point at arbitrary paths.
            # Only paths whose parent directory is a valid Snapshot id can be
            # reconstructed into ArchiveResult rows.
            snapshot = Snapshot.objects.filter(id=plugin_dir.parent.name).first()
        except ValidationError:
            continue
        if snapshot is None:
            continue
        result, created = ArchiveResult.objects.get_or_create(
            snapshot=snapshot,
            plugin=plugin_dir.name,
            hook_name=Path(hook_script_name).stem,
            defaults={
                "status": ArchiveResult.StatusChoices.QUEUED,
            },
        )
        if result.status == ArchiveResult.StatusChoices.QUEUED:
            requeue_snapshot = False
            # A runner can die after the hook Process exits but before the
            # ProcessCompletedEvent projector links/finalizes ArchiveResult.
            # Reconstruct only that exact hook row from the durable Process row.
            output_files, output_size, output_mimetypes = _collect_output_metadata(plugin_dir)
            result.process = process
            if _is_signal_interrupted_exit(process.exit_code):
                # The owning runner died or was asked to stop while the hook was
                # still active. Keep the work item queued so takeover retries the
                # same hook; treating an unknown signal exit as success would
                # silently skip unfinished side effects.
                result.output_files = {}
                result.output_size = 0
                result.output_mimetypes = ""
                result.output_str = ""
                result.status = ArchiveResult.StatusChoices.QUEUED
                requeue_snapshot = True
            else:
                result.output_files = output_files
                result.output_size = output_size
                result.output_mimetypes = output_mimetypes
                result.output_str = process.stderr if process.exit_code not in (0, None) else ""
                result.status = (
                    ArchiveResult.StatusChoices.FAILED
                    if process.exit_code not in (0, None)
                    else (ArchiveResult.StatusChoices.SUCCEEDED if output_files else ArchiveResult.StatusChoices.NORESULTS)
                )
            result.save(
                update_fields=[
                    "process",
                    "output_files",
                    "output_size",
                    "output_mimetypes",
                    "output_str",
                    "status",
                    "modified_at",
                ],
            )
            if requeue_snapshot:
                Snapshot.objects.filter(id=snapshot.id).update(retry_at=now, modified_at=now)
        if created:
            cleaned["archiveresults_missing_for_orphaned_hook_processes"] += 1
            Snapshot.objects.filter(id=snapshot.id).update(retry_at=now, modified_at=now)
    started_snapshots = Snapshot.objects.filter(status=Snapshot.StatusChoices.STARTED).filter(
        Q(retry_at__isnull=True) | Q(retry_at__gt=now),
    )

    # Broken lock repair: STARTED + retry_at=NULL or retry_at in the future
    # means "owned by an active runner". Recovery only runs from the current
    # elected runner after Process cleanup has proven old owners are gone, so
    # STARTED rows with no live ArchiveResult process should not wait out the
    # previous runner's full lease before the new runner can resume them.
    # We only unlock scheduling; normal Snapshot runner code owns the next
    # transition and side effects.
    cleaned["snapshots_started_without_running_results"] = (
        started_snapshots.annotate(has_running_results=Exists(running_archiveresults))
        .filter(has_running_results=False)
        .update(
            retry_at=now,
            modified_at=now,
        )
    )

    # Broken lock repair: STARTED + retry_at=NULL is an orphaned ownership
    # lease. Recovery only unlocks scheduling; the runner owns any subsequent
    # state-machine transition, including sealing rows whose children/results
    # are already final.
    recoverable_started_crawls = Crawl.objects.filter(status=Crawl.StatusChoices.STARTED).filter(
        Q(retry_at__isnull=True) | Q(retry_at__gt=now),
    )

    due_started_crawls = recoverable_started_crawls.annotate(has_due_child=Exists(due_child_snapshots)).filter(has_due_child=True)
    cleaned["crawls_started_with_due_snapshots"] = due_started_crawls.update(retry_at=now, modified_at=now)
    future_started_crawls = recoverable_started_crawls.annotate(
        has_active_child=Exists(active_child_snapshots),
        has_due_child=Exists(due_child_snapshots),
        next_child_retry=next_future_child_retry,
    ).filter(has_active_child=True, has_due_child=False)
    cleaned["crawls_started_waiting_on_future_snapshots"] = future_started_crawls.update(
        retry_at=Coalesce("next_child_retry", Value(now)),
        modified_at=now,
    )
    finished_started_crawls = recoverable_started_crawls.annotate(has_active_child=Exists(active_child_snapshots)).filter(
        has_active_child=False,
    )
    cleaned["crawls_started_without_active_snapshots"] = finished_started_crawls.update(retry_at=now, modified_at=now)

    repair_messages = {
        "processes_stale_running": (
            "Closing {count} interrupted process(es) "
            "(ArchiveBox may have been interrupted before it was able to record that they stopped; any affected work can now be retried)."
        ),
        "processes_orphaned_workers": (
            "Closing {count} interrupted extractor process(es) "
            "(ArchiveBox may have been interrupted before it was able to record their result; affected extractor results can now be retried)."
        ),
        "chrome_processes_orphaned": (
            "Stopping {count} leftover browser process(es) "
            "(ArchiveBox may have been interrupted before it was able to close them; this frees browser resources and avoids duplicate browser sessions)."
        ),
        "crawls_queued_without_retry_at": (
            "Starting {count} Crawl(s) that were queued but never started "
            "(ArchiveBox may have been interrupted before it was able to begin archiving them)."
        ),
        "snapshots_queued_without_retry_at": (
            "Starting {count} Snapshot(s) that were queued but never started "
            "(ArchiveBox may have been interrupted before it was able to archive those URLs)."
        ),
        "archiveresults_backoff": (
            "Retrying {count} extractor result(s) that were waiting to retry "
            "(ArchiveBox may have been interrupted before it was able to try them again; affected outputs will be retried)."
        ),
        "archiveresults_started_without_running_process": (
            "Retrying {count} extractor result(s) that were interrupted before finishing "
            "(ArchiveBox may have been interrupted before it was able to save their final status; partial files will be overwritten with fresh results upon retry)."
        ),
        "snapshots_started_without_running_results": (
            "Resuming {count} Snapshot(s) that were interrupted before finishing "
            "(ArchiveBox may have been interrupted before it was able to finish archiving them; missing outputs will be retried)."
        ),
        "crawls_started_with_due_snapshots": (
            "Resuming {count} Crawl(s) with pending URLs ready to archive "
            "(ArchiveBox may have been interrupted before it was able to archive the remaining URLs; pending URLs will continue)."
        ),
        "crawls_started_waiting_on_future_snapshots": (
            "Resuming {count} Crawl(s) with URLs waiting for a later retry "
            "(ArchiveBox may have been interrupted before it was able to retry delayed URLs; they will retry later)."
        ),
        "crawls_started_without_active_snapshots": (
            "Finalizing {count} Crawl(s) that finished URL processing but were not closed cleanly "
            "(ArchiveBox may have been interrupted before it was able to save the final crawl status; archived data is not changed)."
        ),
    }
    for key, message in repair_messages.items():
        if cleaned[key]:
            recovery_console.print(f"[yellow]⚠️ Repairing: {message.format(count=cleaned[key])}[/yellow]")

    return cleaned
