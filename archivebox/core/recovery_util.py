from __future__ import annotations

from pathlib import Path

from django.utils import timezone
from rich.console import Console


def _is_signal_interrupted_exit(exit_code: int | None) -> bool:
    return exit_code is not None and (exit_code < 0 or exit_code >= 128)


def _canonical_hook_name(hook_name: str) -> str:
    hook_name = Path(hook_name).name
    return Path(hook_name).stem if Path(hook_name).suffix in {".py", ".js", ".sh"} else hook_name


def recover_orchestrator_state(*, include_chrome: bool = False, crawl_id: str | None = None) -> dict[str, int]:
    from archivebox.crawls.models import Crawl
    from archivebox.core.models import ArchiveResult, Snapshot
    from abx_dl.output_files import OutputManifest
    from archivebox.machine.models import Process
    from django.core.exceptions import ValidationError
    from django.db.models import Exists, OuterRef, Q, Subquery, Value
    from django.db.models.functions import Coalesce

    now = timezone.now()
    recovery_console = Console(stderr=True, highlight=False, soft_wrap=True)
    crawl_filter = {"id": crawl_id} if crawl_id else {}
    snapshot_filter = {"crawl_id": crawl_id} if crawl_id else {}
    result_filter = {"snapshot__crawl_id": crawl_id} if crawl_id else {}
    cleaned = {
        "processes_stale_running": 0 if crawl_id else Process.cleanup_stale_running(),
        "processes_orphaned_workers": 0 if crawl_id else Process.cleanup_orphaned_workers(),
        "chrome_processes_orphaned": Process.cleanup_orphaned_chrome() if include_chrome and not crawl_id else 0,
        "crawls_queued_without_retry_at": 0,
        "snapshots_queued_without_retry_at": 0,
        "snapshots_sealed_with_extension_uploads_only": 0,
        "archiveresults_interrupted_without_running_process": 0,
        "archiveresults_missing_for_orphaned_hook_processes": 0,
        "snapshots_started_without_running_results": 0,
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

    extension_upload_results = ArchiveResult.objects.filter(
        snapshot_id=OuterRef("pk"),
        hook_name=Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME,
    )
    server_results = ArchiveResult.objects.filter(snapshot_id=OuterRef("pk")).exclude(
        hook_name=Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME,
    )
    extension_only_snapshots = (
        Snapshot.objects.filter(
            status=Snapshot.StatusChoices.SEALED,
            crawl__status__in=[Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED],
            **snapshot_filter,
        )
        .annotate(
            has_extension_upload=Exists(extension_upload_results),
            has_server_result=Exists(server_results),
        )
        .filter(has_extension_upload=True, has_server_result=False)
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
    orphaned_results = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.STARTED, **result_filter).exclude(
        process__status=Process.StatusChoices.RUNNING,
    )
    # ArchiveResult rows are projections, never work items. Close interrupted
    # projections as failed and wake their parent Snapshot so abx-dl can replay
    # the snapshot-level sequence. Indexed subqueries keep this bounded.
    Snapshot.objects.filter(
        id__in=orphaned_results.values("snapshot_id"),
        status=Snapshot.StatusChoices.STARTED,
    ).update(retry_at=now, modified_at=now)
    cleaned["archiveresults_interrupted_without_running_process"] = orphaned_results.update(
        status=ArchiveResult.StatusChoices.FAILED,
        modified_at=now,
    )
    orphaned_hook_processes = Process.objects.filter(
        process_type=Process.TypeChoices.HOOK,
        archiveresult__isnull=True,
    ).exclude(status=Process.StatusChoices.RUNNING)
    crawl_snapshot_ids = (
        {str(snapshot_id) for snapshot_id in Snapshot.objects.filter(crawl_id=crawl_id).values_list("id", flat=True)} if crawl_id else None
    )
    if crawl_snapshot_ids is not None:
        # Targeted `archivebox run --crawl-id ...` is used by foreground add/update
        # commands and by resume of one existing crawl. It must still repair bad
        # hook state for that crawl, but it must not scan historical orphaned hook
        # rows from unrelated crawls before the first snapshot can run.
        if crawl_snapshot_ids:
            snapshot_pwd_filter = Q()
            for snapshot_id in crawl_snapshot_ids:
                snapshot_pwd_filter |= Q(pwd__contains=snapshot_id)
            orphaned_hook_processes = orphaned_hook_processes.filter(snapshot_pwd_filter)
        else:
            orphaned_hook_processes = orphaned_hook_processes.none()
    for process in orphaned_hook_processes.only(
        "id",
        "pwd",
        "cmd",
        "process_type",
        "status",
        "exit_code",
        "stdout",
        "stderr",
        "started_at",
        "ended_at",
    ).order_by("-started_at", "-id"):
        hook_script_name = process.hook_script_name
        if not hook_script_name or not process.pwd:
            continue
        plugin_dir = Path(process.pwd)
        hook_name = _canonical_hook_name(hook_script_name)
        if crawl_snapshot_ids is not None and plugin_dir.parent.name not in crawl_snapshot_ids:
            continue
        try:
            # Old or synthetic hook Process rows can point at arbitrary paths.
            # Only paths whose parent directory is a valid Snapshot id can be
            # reconstructed into ArchiveResult rows.
            snapshot = Snapshot.objects.filter(id=plugin_dir.parent.name, **snapshot_filter).first()
        except ValidationError:
            continue
        if snapshot is None:
            continue
        result, created = ArchiveResult.get_or_create_by_hook(
            snapshot,
            plugin_dir.name,
            hook_name,
            defaults={
                "status": ArchiveResult.StatusChoices.FAILED,
            },
        )
        process_is_newer = bool(process.started_at and (result.start_ts is None or process.started_at >= result.start_ts))
        if created or process_is_newer:
            requeue_snapshot = False
            # A runner can die after the hook Process exits but before the
            # ProcessCompletedEvent projector links/finalizes ArchiveResult.
            # Reconstruct only that exact hook row from the durable Process row.
            manifest = OutputManifest.scan(plugin_dir, containment_root=snapshot.output_dir)
            output_files = manifest.as_mapping()
            output_size = manifest.total_size
            output_mimetypes = ",".join(manifest.mimetypes)
            emitted_records = [
                record
                for record in Process.parse_records_from_text(process.stdout or "")
                if record.get("type") == "ArchiveResult"
                and (record.get("plugin") or plugin_dir.name) == plugin_dir.name
                and _canonical_hook_name(str(record.get("hook_name") or hook_name)) == hook_name
            ]
            emitted_result = emitted_records[-1] if emitted_records else {}
            result.process = process
            result.start_ts = process.started_at
            result.end_ts = process.ended_at
            if _is_signal_interrupted_exit(process.exit_code):
                # The Process is a durable fact; record the interruption as a
                # failure and wake the parent Snapshot for replay.
                result.output_files = {}
                result.output_size = 0
                result.output_mimetypes = ""
                result.output_str = ""
                result.output_json = None
                result.status = ArchiveResult.StatusChoices.FAILED
                requeue_snapshot = True
            else:
                result.output_files = output_files
                result.output_size = output_size
                result.output_mimetypes = output_mimetypes
                result.output_str = (
                    emitted_result.get("output_str")
                    or emitted_result.get("output")
                    or (process.stderr if process.exit_code not in (0, None) else "")
                )
                result.output_json = emitted_result.get("output_json") if isinstance(emitted_result.get("output_json"), dict) else None
                emitted_status = emitted_result.get("status")
                result.status = (
                    emitted_status
                    if emitted_status in ArchiveResult.StatusChoices.values
                    else (
                        ArchiveResult.StatusChoices.FAILED
                        if process.exit_code not in (0, None)
                        else (ArchiveResult.StatusChoices.SUCCEEDED if output_files else ArchiveResult.StatusChoices.NORESULTS)
                    )
                )
            result.save(
                update_fields=[
                    "process",
                    "start_ts",
                    "end_ts",
                    "output_files",
                    "output_size",
                    "output_mimetypes",
                    "output_str",
                    "output_json",
                    "status",
                    "modified_at",
                ],
            )
            if requeue_snapshot:
                Snapshot.objects.filter(id=snapshot.id).update(retry_at=now, modified_at=now)
        if created:
            cleaned["archiveresults_missing_for_orphaned_hook_processes"] += 1
    started_snapshots = Snapshot.objects.filter(status=Snapshot.StatusChoices.STARTED).filter(
        Q(retry_at__isnull=True) | Q(retry_at__gt=now),
        **snapshot_filter,
    )

    # Broken lock repair: STARTED + retry_at=NULL or retry_at in the future
    # means "owned by an active runner". Recovery only runs from the current
    # elected runner after Process cleanup has proven old owners are gone, so
    # STARTED rows with no live ArchiveResult process should not wait out the
    # previous runner's full lease before the new runner can resume them.
    # We only unlock scheduling; normal Snapshot runner code owns the next
    # transition and side effects.
    cleaned["snapshots_started_without_running_results"] = (
        started_snapshots.annotate(has_running_process=Exists(running_hook_processes))
        .filter(has_running_process=False)
        .update(
            retry_at=now,
            modified_at=now,
        )
    )

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
        "archiveresults_interrupted_without_running_process": (
            "Closing {count} interrupted extractor result projection(s) "
            "(their parent Snapshots are resumed through the normal snapshot-level runner)."
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
