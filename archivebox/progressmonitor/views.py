__package__ = "archivebox.progressmonitor"

import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from abx_dl.events import PROCESS_EXIT_SKIPPED
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import CharField, Count, Q
from django.db.models.functions import Cast
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from archivebox.core.permissions import can_view_snapshot, is_admin_user
from archivebox.core.routes_util import build_snapshot_detail_url, build_snapshot_url, get_api_base_url
from archivebox.misc.logging_util import printable_filesize
from archivebox.plugins.discovery import discover_plugin_configs, get_plugin_default_output_path, get_snapshot_role_result


def progress_endpoint(scope: Literal["crawl", "snapshot"] | None = None, object_id: object | None = None) -> str:
    """Return the canonical same-origin progress endpoint for monitor embeds."""
    if not scope or object_id is None:
        return "/progress.json"
    return f"/progress.json?{scope}_id={str(object_id).replace('-', '')}"


@lru_cache(maxsize=1)
def _live_progress_plugin_names() -> tuple[frozenset[str], frozenset[str]]:
    plugin_configs = discover_plugin_configs()
    indexing_plugin_names = frozenset(
        plugin_name
        for plugin_name, plugin_config in plugin_configs.items()
        if {"search", "flush"}.issubset(plugin_config.get("commands", {}))
    )
    download_plugin_names = frozenset(
        plugin_name
        for plugin_name, plugin_config in plugin_configs.items()
        if plugin_config.get("output_mimetypes") and plugin_name not in indexing_plugin_names
    )
    return download_plugin_names, indexing_plugin_names


# Hundreds of hook paths are labeled on every one-second poll: plain string
# splits, because building pathlib objects for each one cost ~45ms per request.
def _hook_details(hook_name: str, plugin: str = "setup") -> tuple[str, str, str, str]:
    normalized_hook_name = hook_name.rstrip("/").rpartition("/")[2] if hook_name else ""
    if not normalized_hook_name:
        return (plugin, plugin, "unknown", "")

    phase = "unknown"
    if normalized_hook_name == "InstallEvent":
        phase = "install"
    elif normalized_hook_name.startswith("on_CrawlSetup__"):
        phase = "crawl"
    elif normalized_hook_name.startswith("on_Snapshot__"):
        phase = "snapshot"

    label = normalized_hook_name
    if "__" in normalized_hook_name:
        label = normalized_hook_name.split("__", 1)[1]
    label = label.rsplit(".", 1)[0]
    # .finite/.daemon/.bg say how a hook runs, not what it is; keep them out of badges.
    label = ".".join(part for part in label.split(".") if part not in ("finite", "daemon", "bg"))
    if len(label) > 3 and label[:2].isdigit() and label[2] == "_":
        label = label[3:]
    label = label.replace("_", " ").strip() or plugin

    return (plugin, label, phase, normalized_hook_name)


def _process_label(cmd: list | None) -> tuple[str, str, str, str]:
    if not isinstance(cmd, list):
        return ("", "setup", "unknown", "")
    hook_path = next(
        (arg for arg in cmd if isinstance(arg, str) and (name := arg.rpartition("/")[2]).startswith("on_") and "__" in name),
        "",
    )
    if not hook_path and cmd and isinstance(cmd[0], str):
        hook_path = cmd[0]

    if not hook_path:
        return ("", "setup", "unknown", "")

    parent, _, name = hook_path.rstrip("/").rpartition("/")
    return _hook_details(name, plugin=parent.rpartition("/")[2] or "setup")


def live_progress_view(request, *, authorized_snapshot=None):
    """Read-only live progress; keep the server-side request below 100 ms.

    Every caller, including snapshot replay, must use bounded DB reads and
    cached metadata only. Never walk, stat, open, or reconcile archive/persona
    files here, probe Supervisor, or perform network/subprocess work. Captures
    publish their state to the DB; file existence and freshness belong to the
    separate output/image request. Do not scan history or rebuild inventories
    in this one-second polling path; expensive totals belong off the request.
    """
    started = time.perf_counter()
    try:
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine, Process

        snapshot_id_filter = (request.GET.get("snapshot_id") or "").strip().replace("-", "")
        crawl_id_filter = (request.GET.get("crawl_id") or "").strip().replace("-", "")
        is_admin = is_admin_user(request)

        scoped_snapshot = None
        if snapshot_id_filter:
            import uuid as _uuid

            try:
                _uuid.UUID(snapshot_id_filter)
            except (TypeError, ValueError):
                return JsonResponse({"error": "Invalid snapshot_id"}, status=400)
            scoped_snapshot = Snapshot.objects.filter(id=snapshot_id_filter).select_related("crawl").first()
            authorized_snapshot_id = str(getattr(authorized_snapshot, "id", "")).replace("-", "")
            if scoped_snapshot is None or (
                authorized_snapshot_id != str(scoped_snapshot.id).replace("-", "") and not can_view_snapshot(request, scoped_snapshot)
            ):
                return JsonResponse({"error": "Permission denied"}, status=403)
        elif crawl_id_filter:
            # Crawl-only scope still requires staff: there's no per-crawl ACL helper,
            # and a crawl can mix snapshot permissions levels.
            if not is_admin:
                return JsonResponse({"error": "Permission denied"}, status=403)
        else:
            if not is_admin:
                return JsonResponse({"error": "Permission denied"}, status=403)

        request_config = request.archivebox_config
        now = timezone.now()
        crawl_scope = Crawl.objects.all()
        snapshot_scope = Snapshot.objects.all()
        archiveresult_scope = ArchiveResult.objects.all()
        if is_admin and not request.user.is_superuser:
            crawl_scope = crawl_scope.filter(created_by=request.user)
            snapshot_scope = snapshot_scope.filter(crawl__created_by=request.user)
            archiveresult_scope = archiveresult_scope.filter(snapshot__crawl__created_by=request.user)
        # Header badges (queued, active, workers, throughput) always describe the
        # admin's whole collection; only the tree below follows the page's scope.
        # Guests on a public snapshot page only ever see that snapshot.
        header_crawl_scope, header_snapshot_scope, header_archiveresult_scope = crawl_scope, snapshot_scope, archiveresult_scope
        if scoped_snapshot is not None:
            snapshot_scope = Snapshot.objects.filter(id=scoped_snapshot.id)
            crawl_scope = Crawl.objects.filter(id=scoped_snapshot.crawl_id)
            archiveresult_scope = ArchiveResult.objects.filter(snapshot_id=scoped_snapshot.id)
        elif crawl_id_filter:
            snapshot_scope = snapshot_scope.filter(crawl_id=crawl_id_filter)
            crawl_scope = crawl_scope.filter(id=crawl_id_filter)
            archiveresult_scope = archiveresult_scope.filter(snapshot__crawl_id=crawl_id_filter)
        if not is_admin:
            header_crawl_scope, header_snapshot_scope, header_archiveresult_scope = crawl_scope, snapshot_scope, archiveresult_scope

        def is_current_run_timestamp(event_ts, run_started_at) -> bool:
            if run_started_at is None:
                return True
            if event_ts is None:
                return False
            return event_ts >= run_started_at

        def archiveresult_matches_current_run(ar, run_started_at) -> bool:
            if run_started_at is None:
                return True
            if ar.status in (
                ArchiveResult.StatusChoices.QUEUED,
                ArchiveResult.StatusChoices.STARTED,
                ArchiveResult.StatusChoices.BACKOFF,
            ):
                return True
            event_ts = ar.end_ts or ar.start_ts or ar.modified_at or ar.created_at
            return is_current_run_timestamp(event_ts, run_started_at)

        def snapshot_output_url(snapshot, output_path: str) -> str:
            return build_snapshot_url(str(snapshot["id"]), output_path, request=request, config=request_config)

        def snapshot_archive_path(snapshot) -> str:
            crawl = crawls_by_id.get(str(snapshot["crawl_id"]))
            return Snapshot.archive_path_for_values(
                fs_version=snapshot["fs_version"],
                timestamp=snapshot["timestamp"],
                snapshot_id=snapshot["id"],
                url=snapshot["url"],
                username=crawl["created_by__username"] if crawl is not None and crawl["created_by_id"] else "web",
                bookmarked_at=snapshot["bookmarked_at"],
                created_at=snapshot["created_at"],
            )

        def snapshot_view_url(snapshot, output_path: str = "") -> str:
            return build_snapshot_detail_url(
                snapshot_archive_path(snapshot),
                output_path=output_path,
                request=request,
                config=request_config,
            )

        def snapshot_display_url(url: str) -> str:
            url = str(url or "")
            return url if len(url) <= 96 else f"{url[:93]}..."

        api_base = get_api_base_url(request=request, config=request_config) if scoped_snapshot is not None else ""

        running_screencasts = {}

        def screencast_frame_url(snapshot_id: str) -> str:
            started_at = running_screencasts.get(snapshot_id)
            if started_at is None:
                return ""
            # File existence/freshness belongs to the image request, never to
            # the one-second JSON poll (archive storage may be remote).
            rel = f"/api/v1/core/snapshot/{snapshot_id}/screencast.jpg?v={int(now.timestamp())}&after={started_at.timestamp()}"
            return f"{api_base}{rel}" if api_base else rel

        machine = Machine.current_readonly()
        machine_id = machine.id if machine is not None else None
        orchestrator_proc = (
            Process.objects.filter(
                machine_id=machine_id,
                process_type=Process.TypeChoices.ORCHESTRATOR,
                status=Process.StatusChoices.RUNNING,
            )
            .only("pid", "started_at", "machine_id", "env", "cmd", "status")
            .order_by("-started_at")
            .first()
            if machine_id is not None
            else None
        )
        # A stopped runner cannot reconcile its own stale row. Validate only
        # this one candidate using the existing PID/start-time/namespace guard;
        # leave historical process rows and remote namespace semantics intact.
        orchestrator_running = bool(orchestrator_proc and orchestrator_proc.is_running)
        orchestrator_pid = orchestrator_proc.pid if orchestrator_running else None

        # Get model counts by status
        crawl_status_counts = Crawl.status_counts(
            header_crawl_scope,
            (Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED),
        )
        crawls_queued = crawl_status_counts.get(Crawl.StatusChoices.QUEUED, 0)
        crawls_active = crawl_status_counts.get(Crawl.StatusChoices.STARTED, 0)

        # Get recent crawls (last 24 hours)
        from datetime import timedelta

        one_day_ago = now - timedelta(days=1)
        paused_crawl_cutoff = now - timedelta(hours=12)
        crawls_recent = header_crawl_scope.filter(created_at__gte=one_day_ago).count()

        # Active captures are counted from live hook processes below.
        snapshot_status_counts = Snapshot.status_counts(header_snapshot_scope, (Snapshot.StatusChoices.QUEUED,))
        snapshots_queued = snapshot_status_counts.get(Snapshot.StatusChoices.QUEUED, 0)
        snapshots_active = snapshot_status_counts.get(Snapshot.StatusChoices.STARTED, 0)

        download_plugin_names, indexing_plugin_names = _live_progress_plugin_names()
        result_statuses = (
            ArchiveResult.StatusChoices.QUEUED,
            ArchiveResult.StatusChoices.STARTED,
        )
        # Start from open results using the existing status index. Filtering by
        # plugin first scans historical runs, including all completed results.
        # Grouping by the owning snapshot/crawl status here (a primary-key join
        # per open result) replaces two COUNTs that filtered on those joined
        # statuses and cost ~40ms per poll on a large collection.
        result_counts = list(
            header_archiveresult_scope.filter(status__in=result_statuses)
            .order_by()
            .values("status", "plugin", "snapshot__status", "snapshot__crawl__status", "process__status")
            .annotate(count=Count("*")),
        )
        # Recovery preserves interrupted ArchiveResults until their next fresh
        # capture. Their exited Process rows are not active downloads/indexing.
        result_counts = [
            row
            for row in result_counts
            if row["status"] != ArchiveResult.StatusChoices.STARTED or row["process__status"] == Process.StatusChoices.RUNNING
        ]
        archiveresult_status_counts = {
            status: sum(row["count"] for row in result_counts if row["status"] == status) for status in result_statuses
        }
        # Leftover open results of a finished or cancelled capture are not downloads.
        download_status_counts = {
            status: sum(
                row["count"]
                for row in result_counts
                if row["status"] == status
                and row["plugin"] in download_plugin_names
                and row["snapshot__status"] in Snapshot.RUNNABLE_STATES
                and row["snapshot__crawl__status"] in Crawl.RUNNABLE_STATES
            )
            for status in result_statuses
        }
        indexing_status_counts = {
            status: sum(row["count"] for row in result_counts if row["status"] == status and row["plugin"] in indexing_plugin_names)
            for status in result_statuses
        }
        archiveresults_queued = archiveresult_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        archiveresults_active = archiveresult_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)

        downloads_queued = download_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        downloads_active = download_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)
        indexing_queued = indexing_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        indexing_active = indexing_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)

        # Build hierarchical active crawls with nested snapshots and archive results.
        # Show a small, active-first window; everything else is one "more" link
        # to the matching admin list. Rows cost per-second CPU in every viewer.
        max_displayed_crawls = 3
        max_displayed_snapshots = 20
        # A collapsed monitor shows only the header counts. Skip the tree.
        include_tree = request.GET.get("tree") != "0"
        owner_filter = f"&created_by__id__exact={request.user.pk}" if is_admin and not request.user.is_superuser else ""

        active_crawl_fields = (
            "id",
            "created_at",
            "created_by_id",
            "modified_at",
            "urls",
            "config",
            "max_depth",
            "tags_str",
            "persona_id",
            "status",
            "retry_at",
            "label",
            "created_by__id",
            "created_by__username",
        )
        # Start with runnable children, not every historical snapshot belonging
        # to a paused crawl. These uncorrelated subqueries run once per poll.
        due_paused_snapshots = (
            Snapshot.objects.filter(
                status__in=Snapshot.RUNNABLE_STATES,
                retry_at__lte=now,
            )
            .order_by()
            .values("crawl_id")
        )
        queued_paused_results = (
            ArchiveResult.objects.filter(
                status=ArchiveResult.StatusChoices.QUEUED,
            )
            .order_by()
            .values("snapshot__crawl_id")
        )
        crawl_sections = (
            (Crawl.StatusChoices.STARTED, crawl_scope.filter(status=Crawl.StatusChoices.STARTED), crawls_active),
            (
                Crawl.StatusChoices.PAUSED,
                crawl_scope.filter(status=Crawl.StatusChoices.PAUSED).filter(
                    Q(created_at__gte=paused_crawl_cutoff) | Q(id__in=due_paused_snapshots) | Q(id__in=queued_paused_results),
                ),
                None,
            ),
            (Crawl.StatusChoices.QUEUED, crawl_scope.filter(status=Crawl.StatusChoices.QUEUED), crawls_queued),
        )
        active_crawls_list = []
        hidden_crawls = []
        for status, section_scope, section_total in crawl_sections if include_tree else ():
            limit = max_displayed_crawls - len(active_crawls_list)
            rows = list(section_scope.values(*active_crawl_fields).order_by("-modified_at")[:limit]) if limit else []
            active_crawls_list.extend(rows)
            if len(rows) == limit:
                # Paused crawls have no stored count, and counting them scans every
                # due snapshot; the "N hidden" note may trail by a few seconds.
                if section_total is None:
                    scope_key = f"{request.user.pk}:{is_admin}:{crawl_id_filter}:{scoped_snapshot.pk if scoped_snapshot else ''}"
                    section_total = cache.get_or_set(f"progress-paused-crawls:{scope_key}", section_scope.count, timeout=10)
                hidden = section_total - len(rows)
                if hidden > 0:
                    hidden_crawls.append(
                        {"status": status, "count": hidden, "url": f"/admin/crawls/crawl/?status__exact={status}{owner_filter}"},
                    )
        for crawl in active_crawls_list:
            crawl["id"] = str(crawl["id"])
            if crawl["persona_id"]:
                crawl["persona_id"] = str(crawl["persona_id"])
        persona_details_by_id: dict[str, dict[str, str]] = {}
        persona_details_by_name: dict[str, dict[str, str]] = {}
        persona_ids = {crawl["persona_id"] for crawl in active_crawls_list if crawl["persona_id"]}
        persona_names = {"Default"} if any(not crawl["persona_id"] for crawl in active_crawls_list) else set()
        if persona_ids or persona_names:
            from archivebox.personas.models import Persona

            for persona in Persona.objects.filter(Q(id__in=persona_ids) | Q(name__in=persona_names)).only("id", "name"):
                persona_details = {
                    "name": persona.name,
                    "admin_url": f"/admin/personas/persona/{persona.pk}/change/",
                }
                persona_details_by_id[str(persona.id)] = persona_details
                persona_details_by_name[persona.name] = persona_details
        active_crawl_ids = [crawl["id"] for crawl in active_crawls_list]
        snapshot_counts_by_crawl: dict[str, dict[str, int]] = {str(crawl_id): {} for crawl_id in active_crawl_ids}
        hidden_snapshots_by_crawl: dict[str, list[dict[str, object]]] = {str(crawl_id): [] for crawl_id in active_crawl_ids}
        active_snapshot_scope = snapshot_scope.filter(crawl_id__in=active_crawl_ids)
        if active_crawl_ids:
            # The existing (crawl, status, modified_at) index covers these counts.
            # Byte totals and cancellation details require table reads, so sample
            # those separately and share cached values between viewer tabs.
            for row in active_snapshot_scope.order_by().values("crawl_id", "status").annotate(count=Count("*")):
                crawl_id = str(row["crawl_id"])
                snapshot_counts_by_crawl[crawl_id][row["status"]] = row["count"]

        crawl_process_pids: dict[str, int] = {}
        snapshot_process_pids: dict[str, int] = {}
        process_records_by_crawl: dict[str, list[tuple[dict[str, object], object | None]]] = {}
        process_records_by_snapshot: dict[str, list[tuple[dict[str, object], object | None]]] = {}
        seen_process_records: set[str] = set()
        crawls_by_id = {str(crawl["id"]): crawl for crawl in active_crawls_list}
        started_snapshot_fields = (
            "id_str",
            "created_at",
            "modified_at",
            "url",
            "timestamp",
            "bookmarked_at",
            "crawl_id_str",
            "title",
            "downloaded_at",
            "fs_version",
            "status",
            "retry_at",
        )
        queued_snapshot_fields = (
            "id_str",
            "url",
            "crawl_id_str",
            "title",
            "status",
            # A QUEUED row whose hooks already spawned (or ?all_plugins=1) gets
            # the full payload, whose view_url needs the archive path columns.
            "fs_version",
            "timestamp",
            "bookmarked_at",
            "created_at",
        )
        # One snapshot budget across displayed crawls: started rows first, then
        # queued. Each (crawl, status) query is a LIMITed walk of the existing
        # (crawl, status, modified_at) index.
        snapshots = []
        remaining_snapshots = max_displayed_snapshots
        for status, fields, order in (
            (Snapshot.StatusChoices.STARTED, started_snapshot_fields, "-modified_at"),
            (Snapshot.StatusChoices.QUEUED, queued_snapshot_fields, "modified_at"),
        ):
            for crawl_id in active_crawl_ids:
                status_total = snapshot_counts_by_crawl[str(crawl_id)].get(status, 0)
                rows = (
                    list(
                        active_snapshot_scope.filter(crawl_id=crawl_id, status=status)
                        .annotate(id_str=Cast("id", CharField()), crawl_id_str=Cast("crawl_id", CharField()))
                        .values(*fields)
                        .order_by(order)[:remaining_snapshots],
                    )
                    if remaining_snapshots and status_total
                    else []
                )
                # modified_at only picks the window: the runner heartbeats it on
                # every live capture, so displaying in that order swapped them
                # (and all their hook badges) between polls. Ids are time-ordered.
                rows.sort(key=lambda row: row["id_str"])
                remaining_snapshots -= len(rows)
                snapshots.extend(rows)
                if status_total > len(rows):
                    hidden_snapshots_by_crawl[str(crawl_id)].append(
                        {
                            "status": status,
                            "count": status_total - len(rows),
                            "url": f"/admin/core/snapshot/?crawl_id__exact={str(crawl_id).replace('-', '')}&snapshot_status={status}",
                        },
                    )

        for snapshot in snapshots:
            # Process.pwd points at Snapshot.output_dir, which uses CompactUUID
            # hex path components. Keep progress IDs compact too so process rows
            # can be matched without carrying dashed/undashed variants.
            snapshot["id"] = str(snapshot.pop("id_str")).replace("-", "")
            snapshot["crawl_id"] = str(snapshot.pop("crawl_id_str")).replace("-", "")
        snapshots_by_id = {str(snapshot["id"]): snapshot for snapshot in snapshots}
        displayed_snapshots_by_crawl: dict[str, list[Snapshot]] = {str(crawl_id): [] for crawl_id in active_crawl_ids}
        for snapshot in snapshots:
            crawl_snapshots = displayed_snapshots_by_crawl.setdefault(str(snapshot["crawl_id"]), [])
            crawl_snapshots.append(snapshot)
        displayed_snapshot_ids = [
            snapshot["id"] for crawl_snapshots in displayed_snapshots_by_crawl.values() for snapshot in crawl_snapshots
        ]
        detailed_snapshot_ids = [snapshot["id"] for snapshot in snapshots if snapshot["status"] != Snapshot.StatusChoices.QUEUED]
        # Worker counts and screencasts cover every started crawl/snapshot, not
        # just the displayed window (and still work when the tree is skipped).
        worker_snapshot_crawls = {
            str(snapshot_id).replace("-", ""): str(crawl_id).replace("-", "")
            for snapshot_id, crawl_id in header_snapshot_scope.filter(status=Snapshot.StatusChoices.STARTED).values_list("id", "crawl_id")
        }
        worker_snapshot_crawls.update({snapshot_id: snapshot["crawl_id"] for snapshot_id, snapshot in snapshots_by_id.items()})
        # The running crawl heartbeats modified_at, so it is always among the
        # displayed started crawls; no separate started-crawl query needed.
        worker_crawl_ids = set(worker_snapshot_crawls.values()) | set(crawls_by_id)
        process_value_fields = ("id", "process_type", "status", "pwd", "cmd", "pid", "exit_code", "started_at", "ended_at", "modified_at")

        def process_scope(ids):
            if not ids:
                return Process.objects.none()
            return Process.objects.filter(
                pwd__regex="|".join(dict.fromkeys(ids)),
                machine_id=machine_id,
                process_type__in=[
                    Process.TypeChoices.HOOK,
                    Process.TypeChoices.BINARY,
                ],
            )

        running_processes = (
            process_scope([*worker_crawl_ids, *worker_snapshot_crawls])
            .filter(status=Process.StatusChoices.RUNNING)
            .values(*process_value_fields)
        )
        recent_processes = (
            process_scope([*active_crawl_ids, *displayed_snapshot_ids])
            .filter(modified_at__gte=now - timedelta(minutes=10))
            .values(*process_value_fields)
            .order_by("-modified_at")
        )

        archiveresults_by_snapshot: dict[str, list[ArchiveResult]] = {str(snapshot_id): [] for snapshot_id in detailed_snapshot_ids}
        if detailed_snapshot_ids:
            displayed_archiveresults = (
                archiveresult_scope.filter(snapshot_id__in=detailed_snapshot_ids)
                .select_related("process")
                .only(
                    "id",
                    "snapshot_id",
                    "plugin",
                    "hook_name",
                    "status",
                    "output_str",
                    "output_files",
                    "output_size",
                    "start_ts",
                    "end_ts",
                    "created_at",
                    "modified_at",
                    "process_id",
                    "process__id",
                    "process__pid",
                    "process__started_at",
                    "process__timeout",
                )
                .order_by("snapshot_id", "start_ts", "created_at")
            )
            for archiveresult in displayed_archiveresults:
                archiveresults_by_snapshot.setdefault(str(archiveresult.snapshot_id), []).append(archiveresult)

        def find_snapshot_for_process(proc_pwd: Path) -> Snapshot | None:
            for path_part in reversed(proc_pwd.parts):
                snapshot = snapshots_by_id.get(path_part.replace("-", ""))
                if snapshot:
                    return snapshot
            return None

        def find_crawl_for_process(proc_pwd: Path) -> Crawl | None:
            for path_part in reversed(proc_pwd.parts):
                crawl = crawls_by_id.get(path_part.replace("-", ""))
                if crawl:
                    return crawl
            return None

        running_worker_ids: set[str] = set()
        running_snapshot_ids: set[str] = set()
        # The current capture attempt began when its earliest live hook did
        # (background hooks such as the chrome tab span the whole attempt).
        # Snapshot timestamps cannot say this: created_at predates any queue
        # wait and downloaded_at is only set once a capture completes.
        attempt_started_at_by_snapshot: dict[str, datetime] = {}
        for proc in running_processes:
            if not proc["pwd"]:
                continue
            path_parts = [path_part.replace("-", "") for path_part in reversed(Path(proc["pwd"]).parts)]
            snapshot_id = next((path_part for path_part in path_parts if path_part in worker_snapshot_crawls), "")
            crawl_id = (
                worker_snapshot_crawls[snapshot_id]
                if snapshot_id
                else next((path_part for path_part in path_parts if path_part in worker_crawl_ids), "")
            )
            if not crawl_id:
                continue
            running_worker_ids.add(str(proc["id"]))
            if snapshot_id:
                running_snapshot_ids.add(snapshot_id)
                if proc["started_at"]:
                    attempt_started_at_by_snapshot[snapshot_id] = min(
                        proc["started_at"],
                        attempt_started_at_by_snapshot.get(snapshot_id, proc["started_at"]),
                    )
            _plugin, _label, phase, _hook_name = _process_label(proc["cmd"])
            if _plugin == "chrome_screencast" and snapshot_id and proc["started_at"]:
                # CDP sends frames only when the page changes. Keep a still
                # frame visible for its live capture, never for a previous run.
                # This query already selects RUNNING rows; trust the runner's
                # recorded state instead of probing its PID during every poll.
                running_screencasts[snapshot_id] = max(proc["started_at"], running_screencasts.get(snapshot_id, proc["started_at"]))
            if crawl_id and proc["pid"]:
                crawl_process_pids.setdefault(crawl_id, proc["pid"])
            if phase == "snapshot" and snapshot_id and proc["pid"]:
                snapshot_process_pids.setdefault(snapshot_id, proc["pid"])

        for proc in recent_processes:
            if not proc["pwd"]:
                continue
            proc_pwd = Path(proc["pwd"])
            matched_snapshot = find_snapshot_for_process(proc_pwd)
            matched_crawl = (
                crawls_by_id.get(str(matched_snapshot["crawl_id"])) if matched_snapshot is not None else find_crawl_for_process(proc_pwd)
            )
            if matched_snapshot is None and matched_crawl is None:
                continue
            crawl_id = str(matched_snapshot["crawl_id"] if matched_snapshot is not None else matched_crawl["id"])
            snapshot_id = str(matched_snapshot["id"]) if matched_snapshot is not None else ""

            plugin, label, phase, hook_name = _process_label(proc["cmd"])

            record_scope = str(snapshot_id) if phase == "snapshot" and snapshot_id else str(crawl_id)
            # Newest attempt per hook only (rows arrive newest-first): a run
            # killed by a restart exits non-zero, and listing it beside its
            # successful rerun showed setup steps as failed that had passed.
            proc_key = f"{record_scope}:{plugin}:{label}"
            if proc_key in seen_process_records:
                continue
            seen_process_records.add(proc_key)

            status = (
                "started"
                if proc["status"] == Process.StatusChoices.RUNNING
                else (
                    "skipped"
                    if proc["exit_code"] == PROCESS_EXIT_SKIPPED or (phase == "binary" and proc["exit_code"] not in (None, 0))
                    else ("failed" if proc["exit_code"] not in (None, 0) else "succeeded")
                )
            )
            payload: dict[str, object] = {
                "id": str(proc["id"]),
                "plugin": plugin,
                "label": label,
                "hook_name": hook_name,
                "status": status,
                "phase": phase,
                "source": "process",
                "process_id": str(proc["id"]),
            }
            if status == "started" and proc["pid"]:
                payload["pid"] = proc["pid"]
            # Badge width encodes hook duration. Running hooks get their start
            # so the browser grows them between polls; finished ones a fixed span.
            if status == "started" and proc["started_at"]:
                payload["started_at"] = proc["started_at"].isoformat()
            elif proc["started_at"] and proc["ended_at"]:
                payload["elapsed"] = round(max(0.0, (proc["ended_at"] - proc["started_at"]).total_seconds()), 1)
            proc_started_at = proc["started_at"] or proc["modified_at"]
            proc_run_at = (
                proc_started_at
                if proc["status"] == Process.StatusChoices.RUNNING
                else (proc["ended_at"] or proc["modified_at"] or proc_started_at)
            )
            if phase == "snapshot" and snapshot_id:
                process_records_by_snapshot.setdefault(snapshot_id, []).append((payload, proc_run_at))
            elif crawl_id:
                process_records_by_crawl.setdefault(crawl_id, []).append((payload, proc_run_at))

        active_crawls = []
        total_workers = len(running_worker_ids)
        # The header's "active" means captures in progress. STARTED rows also
        # include captures interrupted by a restart that wait for their crawl's
        # next turn; counting those showed e.g. 5 active while 2 were running.
        snapshots_active = len(running_snapshot_ids)
        for crawl in active_crawls_list:
            crawl_id = str(crawl["id"])
            crawl_snapshot_counts = snapshot_counts_by_crawl.get(crawl_id, {})
            total_snapshots = sum(crawl_snapshot_counts.values())
            completed_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.SEALED, 0)
            started_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.STARTED, 0)
            pending_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.QUEUED, 0)
            from archivebox.progressmonitor.collection import crawl_summary

            totals = (
                crawl_summary(crawl_id, snapshot_id=scoped_snapshot.pk if scoped_snapshot is not None else None)
                if completed_snapshots
                else {"snapshots": 0, "cancelled": 0, "bytes": 0}
            )
            cancelled_snapshots = totals["cancelled"] if totals is not None else None

            # Count URLs in the crawl (for when snapshots haven't been created yet)
            urls_count = 0
            if crawl["urls"]:
                urls_count = len([u for u in crawl["urls"].split("\n") if u.strip() and not u.startswith("#")])

            # Calculate crawl progress
            crawl_progress = int((completed_snapshots / total_snapshots) * 100) if total_snapshots > 0 else 0
            crawl_run_started_at = crawl["created_at"]
            crawl_setup_plugins = [
                payload
                for payload, proc_started_at in process_records_by_crawl.get(crawl_id, [])
                if is_current_run_timestamp(proc_started_at, crawl_run_started_at)
            ]
            crawl_setup_total = len(crawl_setup_plugins)
            crawl_setup_completed = sum(1 for item in crawl_setup_plugins if item.get("status") == "succeeded")
            crawl_setup_failed = sum(1 for item in crawl_setup_plugins if item.get("status") == "failed")
            crawl_setup_pending = sum(1 for item in crawl_setup_plugins if item.get("status") == "queued")
            crawl_screencast_url = ""
            crawl_screencast_link = ""

            # Get active snapshots for this crawl (already prefetched)
            active_snapshots_for_crawl = []
            for snapshot in displayed_snapshots_by_crawl.get(crawl_id, []):
                snapshot_run_started_at = snapshot.get("downloaded_at") or snapshot.get("created_at")
                snapshot_process_started_at = snapshot.get("created_at")
                # Get archive results only for displayed active snapshots. Large crawls can
                # contain thousands of sealed snapshots, and prefetching all their results
                # makes the progress endpoint compete with the runner.
                snapshot_results = [
                    ar
                    for ar in archiveresults_by_snapshot.get(str(snapshot["id"]), [])
                    if archiveresult_matches_current_run(ar, snapshot_run_started_at)
                ]
                if snapshot["status"] == Snapshot.StatusChoices.QUEUED:
                    snapshot_results = []
                attempt_started_at = attempt_started_at_by_snapshot.get(str(snapshot["id"]))
                if attempt_started_at is not None:
                    # Every capture reruns all hooks from scratch. An unfinished
                    # row older than every live hook was left by an interrupted
                    # attempt and is superseded; finished rows keep showing the
                    # outputs on disk until this attempt overwrites them.
                    snapshot_results = [
                        ar
                        for ar in snapshot_results
                        if ar.status in ArchiveResult.FINAL_STATES or ar.start_ts is None or ar.start_ts >= attempt_started_at
                    ]

                # Share each path within this response; subsequent requests read
                # fresh rows, including partial saves that do not touch modified_at.
                # Error/no-results messages can contain dots without naming a
                # file. Only successful legacy rows may use the path fallback;
                # any status can still link files declared by the hook.
                output_paths = {
                    ar.id: ar.embed_path_db(output_file_map=ar.output_files)
                    if ar.output_files or ar.status == ArchiveResult.StatusChoices.SUCCEEDED
                    else None
                    for ar in snapshot_results
                }

                plugin_progress_values: list[int] = []
                all_plugins: list[dict[str, object]] = []
                seen_plugin_keys: set[str] = set()
                snapshot_title = (
                    str(snapshot["title"] or "")
                    if snapshot["status"] == Snapshot.StatusChoices.QUEUED
                    else Snapshot._normalize_title_candidate(snapshot["title"], snapshot_url=snapshot["url"])
                )
                snapshot_favicon_url = ""
                snapshot_preview_url = ""
                snapshot_preview_link = ""
                snapshot_screencast_url = ""
                snapshot_screencast_link = ""
                snapshot_fallback_urls: list[str] = []
                title_result = get_snapshot_role_result(snapshot_results, "title_source")
                if not snapshot_title and title_result is not None:
                    snapshot_title = Snapshot._normalize_title_candidate(title_result.output_str, snapshot_url=snapshot["url"])
                favicon_result = get_snapshot_role_result(snapshot_results, "list_icon")
                if favicon_result is not None:
                    favicon_path = output_paths[favicon_result.id] or get_plugin_default_output_path(favicon_result.plugin)
                    if favicon_path:
                        snapshot_favicon_url = snapshot_output_url(snapshot, favicon_path)
                screenshot_result = get_snapshot_role_result(snapshot_results, "primary_preview")
                if screenshot_result is not None:
                    snapshot_preview_link = snapshot_view_url(snapshot)
                    screenshot_path = output_paths[screenshot_result.id] or get_plugin_default_output_path(screenshot_result.plugin)
                    if screenshot_path:
                        snapshot_preview_url = snapshot_output_url(snapshot, screenshot_path)
                        snapshot_preview_link = snapshot_view_url(snapshot, screenshot_path)
                    if snapshot_favicon_url:
                        snapshot_fallback_urls.append(snapshot_favicon_url)
                elif snapshot_favicon_url:
                    snapshot_preview_url = snapshot_favicon_url

                if snapshot["status"] == Snapshot.StatusChoices.STARTED:
                    snapshot_screencast_url = screencast_frame_url(str(snapshot["id"]))
                    snapshot_screencast_link = snapshot_view_url(snapshot) if snapshot_screencast_url else ""
                    if snapshot_screencast_url and not crawl_screencast_url:
                        crawl_screencast_url = snapshot_screencast_url
                        crawl_screencast_link = snapshot_screencast_link

                def plugin_sort_key(ar):
                    status_order = {
                        ArchiveResult.StatusChoices.STARTED: 0,
                        ArchiveResult.StatusChoices.QUEUED: 1,
                        ArchiveResult.StatusChoices.SUCCEEDED: 2,
                        ArchiveResult.StatusChoices.NORESULTS: 3,
                        ArchiveResult.StatusChoices.FAILED: 4,
                    }
                    return (status_order.get(ar.status, 5), ar.plugin, ar.hook_name or "")

                for ar in sorted(snapshot_results, key=plugin_sort_key):
                    status = ar.status
                    process = ar.process_record
                    progress_value = 0
                    if status in (
                        ArchiveResult.StatusChoices.SUCCEEDED,
                        ArchiveResult.StatusChoices.FAILED,
                        ArchiveResult.StatusChoices.SKIPPED,
                        ArchiveResult.StatusChoices.NORESULTS,
                    ):
                        progress_value = 100
                    elif status == ArchiveResult.StatusChoices.STARTED:
                        started_at = ar.start_ts or (process.started_at if process else None)
                        timeout = process.timeout if process else 120
                        if started_at and timeout:
                            elapsed = max(0.0, (now - started_at).total_seconds())
                            progress_value = int(min(99, max(1, (elapsed / float(timeout)) * 100)))
                        else:
                            progress_value = 1
                    else:
                        progress_value = 0

                    plugin_progress_values.append(progress_value)
                    plugin, label, phase, hook_name = _hook_details(ar.hook_name or ar.plugin, plugin=ar.plugin)

                    plugin_payload = {
                        "id": str(ar.id),
                        "plugin": ar.plugin,
                        "label": label,
                        "hook_name": hook_name,
                        "phase": phase,
                        "status": status,
                        "process_id": str(process.id) if process else None,
                        "admin_url": f"/admin/core/archiveresult/{ar.id}/change/",
                    }
                    output_path = output_paths[ar.id]
                    if output_path:
                        plugin_payload["output_path"] = output_path
                        plugin_payload["output_url"] = snapshot_view_url(snapshot, output_path)
                    if status == ArchiveResult.StatusChoices.STARTED and process:
                        plugin_payload["pid"] = process.pid
                    if status == ArchiveResult.StatusChoices.STARTED:
                        plugin_payload["progress"] = progress_value
                        plugin_payload["timeout"] = process.timeout if process else 120
                        if started_at:
                            plugin_payload["started_at"] = started_at.isoformat()
                    elif ar.start_ts and ar.end_ts:
                        plugin_payload["elapsed"] = round(max(0.0, (ar.end_ts - ar.start_ts).total_seconds()), 1)
                    plugin_payload["source"] = "archiveresult"
                    all_plugins.append(plugin_payload)
                    seen_plugin_keys.add(str(process.id) if process else f"{ar.plugin}:{hook_name}")

                for proc_payload, proc_started_at in process_records_by_snapshot.get(str(snapshot["id"]), []):
                    if not is_current_run_timestamp(proc_started_at, snapshot_process_started_at):
                        continue
                    proc_key = str(proc_payload.get("process_id") or f"{proc_payload.get('plugin')}:{proc_payload.get('hook_name')}")
                    if proc_key in seen_plugin_keys:
                        continue
                    seen_plugin_keys.add(proc_key)
                    all_plugins.append(proc_payload)

                    proc_status = proc_payload.get("status")
                    if proc_status in ("succeeded", "failed", "skipped"):
                        plugin_progress_values.append(100)
                    elif proc_status == "started":
                        plugin_progress_values.append(1)
                    else:
                        plugin_progress_values.append(0)

                total_plugins = len(all_plugins)
                completed_plugins = sum(1 for item in all_plugins if item.get("status") == "succeeded")
                failed_plugins = sum(1 for item in all_plugins if item.get("status") == "failed")
                pending_plugins = sum(1 for item in all_plugins if item.get("status") == "queued")

                snapshot_progress = int(sum(plugin_progress_values) / len(plugin_progress_values)) if plugin_progress_values else 0
                worker_state = "running" if snapshot_process_pids.get(str(snapshot["id"])) else "waiting"
                if (
                    snapshot["status"] == Snapshot.StatusChoices.STARTED
                    and str(snapshot["id"]) not in running_snapshot_ids
                    and not (snapshot["retry_at"] and snapshot["retry_at"] > now)
                ):
                    # No live hook and no runner renewing its lease: the
                    # capture was interrupted and waits to be started over.
                    worker_state = "interrupted"
                    attempt_started_at = None

                if snapshot["status"] == Snapshot.StatusChoices.QUEUED and not snapshot_process_pids.get(str(snapshot["id"])):
                    compact_snapshot = [
                        str(snapshot["id"]),
                        snapshot_display_url(snapshot["url"]),
                    ]
                    if snapshot_title:
                        compact_snapshot.append(snapshot_title)
                    active_snapshots_for_crawl.append(compact_snapshot)
                    continue

                snapshot_payload = {
                    "id": str(snapshot["id"]),
                    "url": snapshot_display_url(snapshot["url"]),
                    "title": snapshot_title,
                    "status": snapshot["status"],
                    "worker_state": worker_state,
                }
                if snapshot["status"] != Snapshot.StatusChoices.QUEUED or all_plugins or snapshot_process_pids.get(str(snapshot["id"])):
                    snapshot_payload.update(
                        {
                            "view_url": snapshot_view_url(snapshot),
                            "started": attempt_started_at.isoformat() if attempt_started_at else None,
                            "progress": snapshot_progress,
                            "total_plugins": total_plugins,
                            "completed_plugins": completed_plugins,
                            "failed_plugins": failed_plugins,
                            "pending_plugins": pending_plugins,
                            "all_plugins": all_plugins,
                        },
                    )
                    if snapshot_favicon_url:
                        snapshot_payload["favicon_url"] = snapshot_favicon_url
                    if snapshot_preview_url:
                        snapshot_payload["preview_url"] = snapshot_preview_url
                        snapshot_payload["preview_link"] = snapshot_preview_link
                    if snapshot_screencast_url:
                        snapshot_payload["screencast_url"] = snapshot_screencast_url
                        snapshot_payload["screencast_link"] = snapshot_screencast_link
                    if snapshot_fallback_urls:
                        snapshot_payload["preview_fallbacks"] = snapshot_fallback_urls
                    if snapshot_process_pids.get(str(snapshot["id"])):
                        snapshot_payload["worker_pid"] = snapshot_process_pids[str(snapshot["id"])]

                active_snapshots_for_crawl.append(snapshot_payload)

            # Check if crawl can start (for debugging stuck crawls)
            can_start = bool(crawl["urls"])
            urls_preview = crawl["urls"][:60] if crawl["urls"] else None
            crawl_tags = [tag.strip() for tag in (crawl["tags_str"] or "").replace("\n", ",").split(",") if tag.strip()]
            persona_details = persona_details_by_id.get(str(crawl["persona_id"])) if crawl["persona_id"] else None
            persona_name = persona_details["name"] if persona_details else "Default"
            persona_details = persona_details or persona_details_by_name.get(persona_name)
            crawl_label = (next((line.strip() for line in (crawl["urls"] or "").splitlines() if line.strip()), "") or crawl_id)[:60]
            if not is_admin:
                # WHY: non-admins only reach this through one public/unlisted
                # snapshot (or its replay cookie on hostile snap-* JS). Its crawl
                # may be private: seed URLs, tags, and persona identity stay admin-only.
                crawl_label = str(scoped_snapshot.url)[:60] if scoped_snapshot is not None else ""
                urls_preview, crawl_tags, persona_name, persona_details = None, [], None, None
            crawl_output_size = totals["bytes"] if totals is not None else None
            avg_snapshot_size = int(totals["bytes"] / max(totals["snapshots"], 1)) if totals is not None else None
            # These crawl-scope limits are frozen in Crawl.config. Rendering
            # them must not resolve personas, probe binaries, or reread config.
            max_urls = int(crawl["config"].get("CRAWL_MAX_URLS", request_config.CRAWL_MAX_URLS) or 0)
            crawl_max_size = int(crawl["config"].get("CRAWL_MAX_SIZE", request_config.CRAWL_MAX_SIZE) or 0)
            crawl_timeout = int(crawl["config"].get("CRAWL_TIMEOUT", request_config.CRAWL_TIMEOUT) or 0)
            snapshot_max_size = int(crawl["config"].get("SNAPSHOT_MAX_SIZE", request_config.SNAPSHOT_MAX_SIZE) or 0)

            # Check if retry_at is in the future (would prevent worker from claiming)
            retry_at_future = crawl["retry_at"] > now if crawl["retry_at"] else False
            is_paused = crawl["status"] == Crawl.StatusChoices.PAUSED
            seconds_until_retry = (
                0 if is_paused else int((crawl["retry_at"] - now).total_seconds()) if crawl["retry_at"] and retry_at_future else 0
            )
            crawl_worker_state = (
                "running"
                if crawl_process_pids.get(crawl_id)
                or any(isinstance(snapshot, dict) and snapshot.get("worker_pid") for snapshot in active_snapshots_for_crawl)
                else "waiting"
            )
            if is_paused:
                crawl_worker_state = "paused"
            elif (
                crawl["status"] == Crawl.StatusChoices.STARTED
                and crawl_worker_state == "waiting"
                and (started_snapshots or pending_snapshots)
            ):
                crawl_worker_state = "waiting" if orchestrator_running else "crashed"

            active_crawls.append(
                {
                    "id": crawl_id,
                    "label": crawl_label,
                    "status": crawl["status"],
                    "is_paused": is_paused,
                    "started": crawl["created_at"].isoformat() if crawl["created_at"] else None,
                    "progress": crawl_progress,
                    "created_by": crawl["created_by__username"],
                    "persona": persona_name,
                    "persona_admin_url": persona_details["admin_url"] if persona_details else None,
                    "max_depth": crawl["max_depth"],
                    "max_urls": max_urls,
                    "max_crawl_size": crawl_max_size,
                    "crawl_timeout": crawl_timeout,
                    "max_snapshot_size": snapshot_max_size,
                    "max_crawl_size_display": printable_filesize(crawl_max_size) if crawl_max_size else "unlimited",
                    "crawl_timeout_display": f"{crawl_timeout}s" if crawl_timeout else "unlimited",
                    "max_snapshot_size_display": printable_filesize(snapshot_max_size) if snapshot_max_size else "unlimited",
                    "crawl_output_size": crawl_output_size,
                    "avg_snapshot_size": avg_snapshot_size,
                    "crawl_output_size_display": printable_filesize(crawl_output_size or 0) if totals is not None else "…",
                    "avg_snapshot_size_display": printable_filesize(avg_snapshot_size or 0) if totals is not None else "…",
                    "tags": crawl_tags,
                    "urls_count": urls_count,
                    "total_snapshots": total_snapshots,
                    "completed_snapshots": completed_snapshots,
                    "started_snapshots": started_snapshots,
                    "failed_snapshots": 0,
                    "pending_snapshots": pending_snapshots,
                    "cancelled_snapshots": cancelled_snapshots,
                    "setup_plugins": crawl_setup_plugins,
                    "setup_total_plugins": crawl_setup_total,
                    "setup_completed_plugins": crawl_setup_completed,
                    "setup_failed_plugins": crawl_setup_failed,
                    "setup_pending_plugins": crawl_setup_pending,
                    "screencast_url": crawl_screencast_url,
                    "screencast_link": crawl_screencast_link,
                    "active_snapshots": active_snapshots_for_crawl,
                    "hidden_snapshots": hidden_snapshots_by_crawl.get(crawl_id, []),
                    "can_start": can_start,
                    "urls_preview": urls_preview,
                    "retry_at_future": retry_at_future,
                    "seconds_until_retry": seconds_until_retry,
                    "worker_pid": crawl_process_pids.get(crawl_id),
                    "worker_state": crawl_worker_state,
                },
            )

        payload = {
            "is_admin": is_admin,
            "scope": {
                "snapshot_id": str(scoped_snapshot.id) if scoped_snapshot is not None else "",
                "snapshot_status": scoped_snapshot.status if scoped_snapshot is not None else "",
                "crawl_id": crawl_id_filter,
            },
            "orchestrator_running": orchestrator_running,
            "orchestrator_pid": orchestrator_pid,
            "total_workers": total_workers,
            "crawls_active": crawls_active,
            "crawls_queued": crawls_queued,
            "crawls_recent": crawls_recent,
            "snapshots_active": snapshots_active,
            "snapshots_queued": snapshots_queued,
            "archiveresults_active": archiveresults_active,
            "archiveresults_queued": archiveresults_queued,
            "downloads_active": downloads_active,
            "downloads_queued": downloads_queued,
            "indexing_active": indexing_active,
            "indexing_queued": indexing_queued,
            "server_time": timezone.now().isoformat(),
        }
        if include_tree:
            payload["active_crawls"] = active_crawls
            payload["hidden_crawls"] = hidden_crawls
        if is_admin and (request.GET.get("collection") == "1" or request.GET.get("metrics") == "1"):
            from archivebox.progressmonitor.collection import collection_summary

            payload["collection"] = collection_summary(request.user)
        if is_admin and request.GET.get("metrics") == "1":
            from archivebox.progressmonitor.metrics import progress_metrics

            payload["metrics"] = progress_metrics(request.user)
        try:
            import ujson

            response = HttpResponse(ujson.dumps(payload), content_type="application/json")
        except ImportError:
            response = JsonResponse(payload)
        # The view's own time per poll, readable in browser devtools on any deployment.
        response["Server-Timing"] = f"progress;dur={(time.perf_counter() - started) * 1000:.1f}"
        return response
    except (DatabaseError, OSError, RuntimeError, TypeError, ValueError) as e:
        error_payload = {
            "error": str(e),
            "orchestrator_running": False,
            "total_workers": 0,
            "crawls_active": 0,
            "crawls_queued": 0,
            "crawls_recent": 0,
            "snapshots_active": 0,
            "snapshots_queued": 0,
            "archiveresults_active": 0,
            "archiveresults_queued": 0,
            "downloads_active": 0,
            "downloads_queued": 0,
            "indexing_active": 0,
            "indexing_queued": 0,
            "active_crawls": [],
            "server_time": timezone.now().isoformat(),
        }
        if settings.DEBUG:
            import traceback

            error_payload["traceback"] = traceback.format_exc()
        return JsonResponse(error_payload, status=500)
