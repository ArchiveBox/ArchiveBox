from __future__ import annotations
import time
from django.utils import timezone
from archivebox.misc.db import run_db_analyze_batch
from archivebox.core.shutdown_util import raise_if_shutdown_requested

from .dispatch import run_due_binary
from .dispatch import run_due_crawl
from .dispatch import run_due_snapshot
from .maintenance import run_snapshot_maintenance


def ensure_background_runner() -> bool:
    from archivebox.machine.models import Machine, Process
    from archivebox.workers.supervisord_util import RUNNER_WORKER, get_existing_supervisord_process, get_worker, start_worker

    supervisor = get_existing_supervisord_process()
    runner_worker = get_worker(supervisor, "worker_runner") if supervisor else None
    if runner_worker and runner_worker.get("statename") in ("STARTING", "RUNNING"):
        return False
    if supervisor is not None:
        start_worker(supervisor, RUNNER_WORKER())
        return True

    machine = Machine.current()
    Process.cleanup_stale_running(machine=machine)
    running_orchestrators = Process.objects.filter(
        machine=machine,
        status=Process.StatusChoices.RUNNING,
        process_type=Process.TypeChoices.ORCHESTRATOR,
    )
    if any(proc.is_running for proc in running_orchestrators):
        return False

    return False


def _first_due_id(queryset):
    return queryset.order_by("retry_at", "created_at").values_list("id", flat=True).first()


def _run_due_crawl_status(status: str, *, crawl_id: str | None, lock_seconds: int, interactive_interrupts: bool) -> bool:
    from archivebox.crawls.models import Crawl

    due_crawls = Crawl.objects.filter(
        retry_at__lte=timezone.now(),
        status=status,
    )
    if crawl_id:
        due_crawls = due_crawls.filter(id=crawl_id)
    due_crawl_id = _first_due_id(due_crawls)
    if due_crawl_id is None:
        return False
    due_crawl = Crawl.objects.filter(id=due_crawl_id).first()
    if due_crawl is None:
        return True
    run_due_crawl(
        due_crawl,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
    )
    return True


def _run_due_snapshot_query(queryset, *, lock_seconds: int, interactive_interrupts: bool, runtime_config) -> bool:
    due_snapshot_id = _first_due_id(queryset)
    return _run_due_snapshot_id(
        due_snapshot_id,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
        runtime_config=runtime_config,
    )


def _run_due_snapshot_id(snapshot_id, *, lock_seconds: int, interactive_interrupts: bool, runtime_config) -> bool:
    from archivebox.core.models import Snapshot

    due_snapshot_id = snapshot_id
    if due_snapshot_id is None:
        return False
    due_snapshot = Snapshot.objects.filter(id=due_snapshot_id).first()
    if due_snapshot is None:
        return True
    run_due_snapshot(
        due_snapshot,
        lock_seconds=lock_seconds,
        interactive_interrupts=interactive_interrupts,
        runtime_config=runtime_config,
    )
    return True


def _run_due_binary() -> bool:
    from archivebox.machine.models import Binary

    due_binary_id = (
        Binary.objects.filter(retry_at__lte=timezone.now())
        .exclude(status=Binary.StatusChoices.INSTALLED)
        .order_by("retry_at", "created_at")
        .values_list("id", flat=True)
        .first()
    )
    if due_binary_id is None:
        return False
    due_binary = Binary.objects.filter(id=due_binary_id).first()
    if due_binary is None:
        return True
    run_due_binary(due_binary, lock_seconds=60)
    return True


def _run_scheduled_work(*, crawl_id, interactive_interrupts, runtime_config, crawl_lock_seconds) -> bool:
    """Try one work item in priority order; query each tier only when reached."""
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    # Active children run before parent bookkeeping. Cancellation and pause
    # cleanup come next, then the broad active fallback, and finally sealed
    # maintenance. Keep this ordering so a backfill cannot starve new work.
    priorities = (
        (Snapshot, {"crawl__status__in": Crawl.RUNNABLE_STATES, "status__in": Snapshot.RUNNABLE_STATES}),
        (Crawl, {"status": Crawl.StatusChoices.QUEUED}),
        (Crawl, {"status": Crawl.StatusChoices.STARTED}),
        (Snapshot, {"crawl__status": Crawl.StatusChoices.SEALED, "status": Snapshot.StatusChoices.STARTED}),
        (Snapshot, {"crawl__status": Crawl.StatusChoices.PAUSED, "status__in": Snapshot.RUNNABLE_STATES}),
        (Snapshot, {"status__in": Snapshot.OPEN_STATES}),
        (Snapshot, {"status": Snapshot.StatusChoices.SEALED}),
        (Crawl, {"status": Crawl.StatusChoices.SEALED}),
    )
    for model, filters in priorities:
        if model is Crawl:
            ran = _run_due_crawl_status(
                filters["status"],
                crawl_id=crawl_id,
                lock_seconds=crawl_lock_seconds,
                interactive_interrupts=interactive_interrupts,
            )
        else:
            queryset = Snapshot.objects.filter(retry_at__lte=timezone.now(), **filters)
            if crawl_id:
                queryset = queryset.filter(crawl_id=crawl_id)
            ran = _run_due_snapshot_query(
                queryset,
                lock_seconds=60,
                interactive_interrupts=interactive_interrupts,
                runtime_config=runtime_config,
            )
        if ran:
            return True
    return crawl_id is None and _run_due_binary()


def run_pending_crawls(
    *,
    daemon: bool = False,
    crawl_id: str | None = None,
    maintenance_only: bool = False,
    interactive_interrupts: bool = False,
) -> int:
    from archivebox.config.common import get_config
    from archivebox.crawls.models import Crawl, CrawlSchedule
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Process

    crawl_claim_lock_seconds = 10
    runtime_config = get_config()
    last_recovery_at = 0.0
    last_retention_at = 0.0
    last_retention_repair_at = 0.0
    last_analyze_at = 0.0
    analyze_queue: list[str] | None = None
    analyze_sweep_started_at = 0.0
    orchestrator_started_at = time.monotonic()
    while True:
        raise_if_shutdown_requested()
        now_monotonic = time.monotonic()
        if crawl_id is None and now_monotonic - last_retention_at >= (60.0 if daemon else 1.0):
            for model in (ArchiveResult, Snapshot, Crawl, Process):
                # Keep the tight scheduler loop anchored on indexed delete_at
                # columns only. Backfilling missing delete_at values has to read
                # config JSON for models whose retention policy is scoped to a
                # Crawl/Snapshot/Process. That repair is still required for
                # correctness, but it belongs in the idle maintenance block
                # below, not ahead of every claim attempt.
                model.delete_expired(batch_size=100, backfill_missing=False)
            last_retention_at = now_monotonic

        if daemon and crawl_id is None:
            now = timezone.now()
            for schedule in CrawlSchedule.objects.filter(is_enabled=True).select_related("template", "template__created_by"):
                if schedule.is_due(now):
                    schedule.dispatch(queued_at=now)

        if maintenance_only:
            # Filesystem migration is independent of lifecycle status; do not
            # tick queued snapshots or start their extraction work here.
            filesystem_snapshot = (
                Snapshot.objects.filter(retry_at__lte=timezone.now())
                .exclude(fs_version=Snapshot._fs_current_version())
                .order_by("retry_at", "created_at")
                .first()
            )
            if filesystem_snapshot and Snapshot.claim_for_worker(filesystem_snapshot, lock_seconds=60):
                if run_snapshot_maintenance(str(filesystem_snapshot.id)):
                    continue

        if not maintenance_only and _run_scheduled_work(
            crawl_id=crawl_id,
            interactive_interrupts=interactive_interrupts,
            runtime_config=runtime_config,
            crawl_lock_seconds=crawl_claim_lock_seconds,
        ):
            continue

        now_monotonic = time.monotonic()
        if crawl_id is None and now_monotonic - last_retention_repair_at >= (60.0 if daemon else 0.0):
            for model in (ArchiveResult, Snapshot, Crawl, Process):
                # No runnable work was found on this scheduler pass. This is
                # the bounded repair point for missing retention deadlines,
                # including ArchiveResult rows intentionally saved without
                # delete_at in the plugin-result hot path. Running it here keeps
                # DELETE_AFTER resolution fresh without making every hook event
                # load parent Snapshot/Crawl config.
                model.delete_expired(batch_size=100, backfill_missing=True)
            last_retention_repair_at = now_monotonic

        if daemon:
            now_monotonic = time.monotonic()
            if now_monotonic - last_recovery_at >= 30.0:
                from archivebox.core.recovery_util import recover_orchestrator_state

                recover_orchestrator_state()
                last_recovery_at = now_monotonic
            # SQLite query plans degrade as the snapshot/archiveresult tables grow
            # past their last ANALYZE — stale stats make the optimizer start large
            # joins from auth_user/crawl instead of using the url index, blowing the
            # snapshot detail page out to ~500ms. Refresh stats at most once per
            # 24hr while the queue is idle, and only after the orchestrator has
            # been alive for at least an hour so short server boots / one-off work
            # never pay the cost. The sweep is batched one table per idle tick;
            # individual table ANALYZE statements abort after 2min (progress
            # handler) and the whole sweep is hard-capped at 5min so a
            # pathological table cannot wedge maintenance forever. Any failure
            # inside the maintenance hook is swallowed — orchestrator must never
            # be taken down by stats refresh.
            try:
                if (
                    analyze_queue is None
                    and now_monotonic - orchestrator_started_at >= 3600.0
                    and now_monotonic - last_analyze_at >= 86400.0
                ):
                    analyze_sweep_started_at = now_monotonic
                    analyze_queue = run_db_analyze_batch(None)
                elif analyze_queue and now_monotonic - analyze_sweep_started_at >= 300.0:
                    # Sweep blew past the 5min hard cap — abandon what's left
                    # and don't retry until the next 24hr window.
                    analyze_queue = None
                    last_analyze_at = now_monotonic
                elif analyze_queue:
                    analyze_queue = run_db_analyze_batch(analyze_queue)
                if analyze_queue is not None and not analyze_queue:
                    analyze_queue = None
                    last_analyze_at = now_monotonic
            except Exception:
                analyze_queue = None
                last_analyze_at = now_monotonic
            time.sleep(2.0)
            continue
        return 0
