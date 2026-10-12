from __future__ import annotations

import os

from django.utils import timezone
from rich.console import Console


def recover_orchestrator_state(*, include_chrome: bool = False, crawl_id: str | None = None) -> dict[str, int]:
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process
    from django.db.models import Exists, OuterRef, Q, Subquery, Value
    from django.db.models.functions import Coalesce

    now = timezone.now()
    recovery_console = Console(stderr=True, highlight=False, soft_wrap=True)
    crawl_filter = {"id": crawl_id} if crawl_id else {}
    snapshot_filter = {"crawl_id": crawl_id} if crawl_id else {}
    cleaned = {
        "processes_stale_running": 0 if crawl_id else Process.cleanup_stale_running(),
        "processes_orphaned_workers": 0 if crawl_id else Process.cleanup_orphaned_workers(),
        "chrome_processes_orphaned": Process.cleanup_orphaned_chrome() if include_chrome and not crawl_id else 0,
        "crawls_queued_without_retry_at": 0,
        "snapshots_queued_without_retry_at": 0,
        "snapshots_sealed_with_extension_uploads_only": 0,
        "snapshots_started_without_running_results": 0,
        "snapshots_interrupted_after_restart": 0,
        "crawls_started_with_due_snapshots": 0,
        "crawls_started_waiting_on_future_snapshots": 0,
        "crawls_started_without_active_snapshots": 0,
    }

    running_hook_processes = Process.objects.filter(
        archiveresult__snapshot_id=OuterRef("pk"),
        process_type=Process.TypeChoices.HOOK,
        status=Process.StatusChoices.RUNNING,
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
        **crawl_filter,
    ).update(retry_at=now, modified_at=now)
    cleaned["snapshots_queued_without_retry_at"] = Snapshot.objects.filter(
        status=Snapshot.StatusChoices.QUEUED,
        retry_at__isnull=True,
        crawl__status__in=Crawl.RUNNABLE_STATES,
        **snapshot_filter,
    ).update(retry_at=now, modified_at=now)

    # Find rare uploads through hook_name's index before checking their parents;
    # a correlated upload probe otherwise visits every sealed snapshot.
    extension_upload_results = ArchiveResult.objects.filter(
        hook_name=Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME,
    )
    server_results = ArchiveResult.objects.filter(snapshot_id=OuterRef("pk")).exclude(
        hook_name=Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME,
    )
    extension_only_snapshots = (
        Snapshot.objects.filter(
            id__in=extension_upload_results.values("snapshot_id"),
            status=Snapshot.StatusChoices.SEALED,
            crawl__status__in=[Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED],
            **snapshot_filter,
        )
        .annotate(
            has_server_result=Exists(server_results),
        )
        .filter(has_server_result=False)
    )
    # Older browser-extension uploads could win a race with runner startup:
    # their successful external rows made the fresh Snapshot look finished
    # before its configured server-hook workset was materialized. Reopen only
    # that exact, recognizable state so the normal runner adds the missing
    # server rows to the same Snapshot and preserves the uploaded outputs.
    Crawl.objects.filter(
        id__in=Subquery(extension_only_snapshots.values("crawl_id")),
        status=Crawl.StatusChoices.SEALED,
    ).update(status=Crawl.StatusChoices.STARTED, retry_at=now, modified_at=now)
    cleaned["snapshots_sealed_with_extension_uploads_only"] = extension_only_snapshots.update(
        status=Snapshot.StatusChoices.QUEUED,
        retry_at=now,
        modified_at=now,
    )
    # ArchiveResults belong to the live hook lifecycle. Do not infer outcomes
    # from interrupted processes or reconstruct old stdout here. A new run
    # overwrites its own result and files as it executes (abx-plugins contract).
    interrupted_snapshots = Snapshot.objects.filter(status=Snapshot.StatusChoices.STARTED, **snapshot_filter).annotate(
        has_running_process=Exists(running_hook_processes),
    )

    # A capture is never resumed: plugins overwrite their outputs in place, so
    # an interrupted Snapshot starts over as a fresh queued capture that reruns
    # every hook. Recovery only runs from the elected runner after Process
    # cleanup proved old owners gone, so the dead owner's lease is irrelevant:
    # one that expired before the restart leaves retry_at in the past, and
    # skipping those left captures STARTED (shown as running) for days.
    # Materialize first: no read cursor may stay open across these writes.
    restartable = list(
        interrupted_snapshots.filter(has_running_process=False, crawl__status__in=Crawl.RUNNABLE_STATES).select_related(
            "crawl",
            "crawl__created_by",
        ),
    )
    for snapshot in restartable:
        if _restarted_from_scratch_before(snapshot):
            # Bounded give-up: one fresh restart already failed to finish, so a
            # capture that kills its runner cannot crash-loop the collection.
            if snapshot.seal():
                cleaned["snapshots_interrupted_after_restart"] += 1
        elif Snapshot.objects.filter(pk=snapshot.pk, status=Snapshot.StatusChoices.STARTED, retry_at=snapshot.retry_at).update(
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=now,
            modified_at=now,
        ):
            cleaned["snapshots_started_without_running_results"] += 1

    # Paused/cancelled crawls own their children's next transition; only make
    # an orphaned lease due so the runner's pause/seal pass can apply it.
    cleaned["snapshots_started_without_running_results"] += Snapshot.objects.filter(
        id__in=interrupted_snapshots.filter(has_running_process=False)
        .exclude(crawl__status__in=Crawl.RUNNABLE_STATES)
        .filter(Q(retry_at__isnull=True) | Q(retry_at__gt=now))
        .values("id"),
    ).update(retry_at=now, modified_at=now)

    # Broken lock repair: STARTED + retry_at=NULL is an orphaned ownership
    # lease. Recovery only unlocks scheduling; the runner owns any subsequent
    # lifecycle transition, including sealing rows whose children/results
    # are already final.
    recoverable_started_crawls = Crawl.objects.filter(status=Crawl.StatusChoices.STARTED).filter(
        Q(retry_at__isnull=True) | Q(retry_at__gt=now),
        **crawl_filter,
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
        "snapshots_sealed_with_extension_uploads_only": (
            "Finishing {count} browser-extension Snapshot(s) that received uploaded files before server extractors started "
            "(uploaded and server-created results will remain together on the same Snapshot)."
        ),
        "snapshots_started_without_running_results": (
            "Recovering {count} Snapshot(s) that were interrupted before finishing "
            "(ArchiveBox may have been interrupted before it was able to finish archiving them; unfinished captures start over from scratch)."
        ),
        "snapshots_interrupted_after_restart": (
            "Finishing {count} Snapshot(s) that were interrupted again after already being restarted from scratch "
            "(their outputs so far are kept; failed extractors can be retried manually)."
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


def _restarted_from_scratch_before(snapshot) -> bool:
    from archivebox.machine.models import Process
    from archivebox.services.runner import resolve_snapshot_attempt_timeout
    from django.db.models import Max, Min

    # Hook Process rows are never overwritten, unlike ArchiveResults, so they
    # are the only existing record of earlier attempts. The runner aborts an
    # attempt at its ceiling, so hook starts spread wider than one ceiling
    # came from at least two attempts of this capture. Range on pwd (not
    # LIKE) so SQLite can use the (process_type, worker_type, pwd) index.
    snapshot_dir = f"{snapshot.output_dir}{os.sep}"
    hook_runs = Process.objects.filter(
        process_type=Process.TypeChoices.HOOK,
        worker_type="",
        pwd__gte=snapshot_dir,
        pwd__lt=f"{snapshot_dir}\U0010ffff",
    )
    if snapshot.downloaded_at:
        # Earlier completed captures are not attempts of this one.
        hook_runs = hook_runs.filter(started_at__gt=snapshot.downloaded_at)
    span = hook_runs.aggregate(first=Min("started_at"), last=Max("started_at"))
    if span["first"] is None:
        return False
    return (span["last"] - span["first"]).total_seconds() > resolve_snapshot_attempt_timeout(snapshot)
