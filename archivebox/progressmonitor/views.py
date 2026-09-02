__package__ = "archivebox.progressmonitor"

from functools import lru_cache
from pathlib import Path
from typing import Literal

from abx_dl.events import PROCESS_EXIT_SKIPPED
from django.conf import settings
from django.db import DatabaseError
from django.db.models import CharField, Count, Q, Sum
from django.db.models.functions import Cast
from django.http import HttpResponse, JsonResponse
from django.utils import timezone

from archivebox.config import CONSTANTS
from archivebox.config.common import get_config
from archivebox.core.permissions import can_view_snapshot, is_admin_user
from archivebox.core.routes_util import build_snapshot_url, build_web_url, get_api_base_url
from archivebox.misc.logging_util import printable_filesize
from archivebox.plugins.discovery import discover_plugin_configs


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


def live_progress_view(request):
    """Simple JSON endpoint for live progress status - used by admin progress monitor."""
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
            if scoped_snapshot is None or not can_view_snapshot(request, scoped_snapshot):
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
        if scoped_snapshot is not None:
            snapshot_scope = Snapshot.objects.filter(id=scoped_snapshot.id)
            crawl_scope = Crawl.objects.filter(id=scoped_snapshot.crawl_id)
            archiveresult_scope = ArchiveResult.objects.filter(snapshot_id=scoped_snapshot.id)
        elif crawl_id_filter:
            snapshot_scope = snapshot_scope.filter(crawl_id=crawl_id_filter)
            crawl_scope = crawl_scope.filter(id=crawl_id_filter)
            archiveresult_scope = archiveresult_scope.filter(snapshot__crawl_id=crawl_id_filter)

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

        def hook_details(hook_name: str, plugin: str = "setup") -> tuple[str, str, str, str]:
            normalized_hook_name = Path(hook_name).name if hook_name else ""
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
            if len(label) > 3 and label[:2].isdigit() and label[2] == "_":
                label = label[3:]
            label = label.replace("_", " ").strip() or plugin

            return (plugin, label, phase, normalized_hook_name)

        def process_label(cmd: list[str] | None) -> tuple[str, str, str, str]:
            hook_path = ""
            if isinstance(cmd, list) and cmd:
                hook_path = next(
                    (arg for arg in cmd if isinstance(arg, str) and Path(arg).name.startswith("on_") and "__" in Path(arg).name),
                    "",
                )
                if not hook_path and isinstance(cmd[0], str):
                    hook_path = cmd[0]

            if not hook_path:
                return ("", "setup", "unknown", "")

            return hook_details(Path(hook_path).name, plugin=Path(hook_path).parent.name or "setup")

        def archiveresult_output_path(ar) -> str | None:
            output_file_map = ar.output_files if isinstance(ar.output_files, dict) else {}

            def is_root_relative(path: str) -> bool:
                metadata = output_file_map.get(path) or {}
                return bool(isinstance(metadata, dict) and metadata.get("root_relative"))

            if ar.output_str:
                raw_output = str(ar.output_str).strip()
                if ar._looks_like_output_path(raw_output, ar.plugin):
                    output_path = Path(raw_output)
                    if output_path.is_absolute():
                        return None

                    if raw_output.startswith(f"{ar.plugin}/"):
                        candidates = [raw_output]
                    elif len(output_path.parts) == 1:
                        candidates = [f"{ar.plugin}/{raw_output}", raw_output]
                    else:
                        candidates = [raw_output]

                    if raw_output in output_file_map and is_root_relative(raw_output):
                        return raw_output

                    for relative_path in candidates:
                        plugin_relative = relative_path.removeprefix(f"{ar.plugin}/")
                        if relative_path in output_file_map:
                            return f"{ar.plugin}/{relative_path}" if not relative_path.startswith(f"{ar.plugin}/") else relative_path
                        if plugin_relative in output_file_map:
                            return f"{ar.plugin}/{plugin_relative}"

            output_file_paths = list(output_file_map.keys())
            if output_file_paths:
                fallback_path = ArchiveResult._fallback_output_file_path(output_file_paths, ar.plugin, output_file_map)
                if fallback_path:
                    if is_root_relative(fallback_path):
                        return fallback_path
                    return f"{ar.plugin}/{fallback_path}"

            return None

        def snapshot_output_url(snapshot, output_path: str) -> str:
            return build_snapshot_url(str(snapshot["id"]), output_path, request=request, config=request_config)

        def snapshot_archive_path(snapshot) -> str:
            if snapshot["fs_version"] in ("0.7.0", "0.8.0"):
                return f"{CONSTANTS.ARCHIVE_DIR_NAME}/{snapshot['timestamp']}"
            crawl = crawls_by_id.get(str(snapshot["crawl_id"]))
            username = "web"
            if crawl is not None and crawl["created_by_id"]:
                username = crawl["created_by__username"]
            if username == "system":
                username = "web"
            date_base = snapshot["bookmarked_at"] or snapshot["created_at"]
            date_str = date_base.strftime("%Y%m%d") if date_base else "unknown"
            domain = Snapshot.extract_domain_from_url(snapshot["url"])
            return f"{username}/{date_str}/{domain}/{snapshot['id']}"

        def snapshot_view_url(snapshot, output_path: str = "") -> str:
            anchor = f"#{output_path}" if output_path else ""
            return build_web_url(
                f"/{snapshot_archive_path(snapshot)}/index.html{anchor}",
                request=request,
                config=request_config,
            )

        def snapshot_display_url(url: str) -> str:
            url = str(url or "")
            return url if len(url) <= 96 else f"{url[:93]}..."

        api_base = get_api_base_url(request=request, config=request_config) if scoped_snapshot is not None else ""

        def screencast_frame_url(crawl_id: str, crawl_dir: Path) -> str:
            frame_path = crawl_dir / "chrome_screencast" / "latest.jpg"
            try:
                frame_stat = frame_path.stat()
            except OSError:
                return ""
            if frame_stat.st_size <= 0:
                return ""
            if now.timestamp() - frame_stat.st_mtime > 15:
                return ""
            rel = f"/api/v1/crawls/crawl/{crawl_id}/files/chrome_screencast/latest.jpg?v={frame_stat.st_mtime_ns}"
            return f"{api_base}{rel}" if api_base else rel

        machine_id = Machine.current().id
        orchestrator_proc = (
            Process.objects.filter(
                machine_id=machine_id,
                process_type=Process.TypeChoices.ORCHESTRATOR,
                status=Process.StatusChoices.RUNNING,
            )
            .only("id", "pid", "started_at", "machine_id", "process_type", "status")
            .order_by("-started_at")
            .first()
            if machine_id is not None
            else None
        )
        runner_worker = None
        orchestrator_proc_running = bool(orchestrator_proc and orchestrator_proc.is_running)
        if not orchestrator_proc_running:
            try:
                from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker

                supervisor = get_existing_supervisord_process(quiet=True)
                runner_worker = get_worker(supervisor, "worker_runner") if supervisor else None
            except (OSError, RuntimeError, TimeoutError):
                runner_worker = None

        runner_worker_running = bool(runner_worker and runner_worker.get("statename") in ("STARTING", "RUNNING"))
        runner_worker_pid = runner_worker.get("pid") if runner_worker else None
        orchestrator_running = orchestrator_proc_running or runner_worker_running
        orchestrator_pid = orchestrator_proc.pid if orchestrator_proc_running and orchestrator_proc else runner_worker_pid

        # Get model counts by status
        crawl_status_counts = Crawl.status_counts(
            crawl_scope,
            (Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED, Crawl.StatusChoices.PAUSED),
        )
        crawls_queued = crawl_status_counts.get(Crawl.StatusChoices.QUEUED, 0)
        crawls_active = crawl_status_counts.get(Crawl.StatusChoices.STARTED, 0)

        # Get recent crawls (last 24 hours)
        from datetime import timedelta

        one_day_ago = now - timedelta(days=1)
        paused_crawl_cutoff = now - timedelta(hours=12)
        crawls_recent = crawl_scope.filter(created_at__gte=one_day_ago).count()

        snapshot_status_counts = Snapshot.status_counts(
            snapshot_scope,
            Snapshot.OPEN_STATES,
        )
        snapshots_queued = snapshot_status_counts.get(Snapshot.StatusChoices.QUEUED, 0)
        snapshots_active = snapshot_status_counts.get(Snapshot.StatusChoices.STARTED, 0)

        download_plugin_names, indexing_plugin_names = _live_progress_plugin_names()
        result_statuses = (
            ArchiveResult.StatusChoices.QUEUED,
            ArchiveResult.StatusChoices.STARTED,
        )
        archiveresult_status_counts = ArchiveResult.status_counts(archiveresult_scope, result_statuses)
        download_scope = archiveresult_scope.filter(
            plugin__in=download_plugin_names,
            snapshot__status__in=Snapshot.RUNNABLE_STATES,
            snapshot__crawl__status__in=Crawl.RUNNABLE_STATES,
        )
        indexing_scope = archiveresult_scope.filter(plugin__in=indexing_plugin_names)
        download_status_counts = ArchiveResult.status_counts(download_scope, result_statuses)
        indexing_status_counts = ArchiveResult.status_counts(indexing_scope, result_statuses)
        archiveresults_queued = archiveresult_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        archiveresults_active = archiveresult_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)

        downloads_queued = download_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        downloads_active = download_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)
        indexing_queued = indexing_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        indexing_active = indexing_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)

        # Build hierarchical active crawls with nested snapshots and archive results
        max_active_crawls = 10
        max_queued_crawls = 10
        max_started_snapshots_per_crawl = 50
        max_queued_snapshots_per_crawl = 50

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
        started_crawls = list(
            crawl_scope.filter(status=Crawl.StatusChoices.STARTED)
            .values(*active_crawl_fields)
            .order_by("-modified_at")[:max_active_crawls],
        )
        paused_crawls = list(
            crawl_scope.filter(
                Q(status=Crawl.StatusChoices.PAUSED, created_at__gte=paused_crawl_cutoff)
                | Q(
                    status=Crawl.StatusChoices.PAUSED,
                    snapshot_set__status__in=Snapshot.RUNNABLE_STATES,
                    snapshot_set__retry_at__lte=now,
                )
                | Q(
                    status=Crawl.StatusChoices.PAUSED,
                    snapshot_set__archiveresult__status=ArchiveResult.StatusChoices.QUEUED,
                ),
            )
            .values(*active_crawl_fields)
            .distinct()
            .order_by("-modified_at")[:max_active_crawls],
        )
        queued_crawls = list(
            crawl_scope.filter(status=Crawl.StatusChoices.QUEUED).values(*active_crawl_fields).order_by("-modified_at")[:max_queued_crawls],
        )
        queued_crawls_hidden = max(crawls_queued - len(queued_crawls), 0)
        active_crawls_list = started_crawls + paused_crawls + queued_crawls
        for crawl in active_crawls_list:
            crawl["id"] = str(crawl["id"])
            if crawl["persona_id"]:
                crawl["persona_id"] = str(crawl["persona_id"])
        persona_details_by_id: dict[str, dict[str, str]] = {}
        persona_details_by_name: dict[str, dict[str, str]] = {}
        persona_objects_by_id = {}
        persona_objects_by_name = {}
        persona_ids = {crawl["persona_id"] for crawl in active_crawls_list if crawl["persona_id"]}
        persona_names = {"Default"} if any(not crawl["persona_id"] for crawl in active_crawls_list) else set()
        if persona_ids or persona_names:
            from archivebox.personas.models import Persona

            for persona in Persona.objects.filter(Q(id__in=persona_ids) | Q(name__in=persona_names)).only("id", "name", "config"):
                persona_details = {
                    "name": persona.name,
                    "admin_url": f"/admin/personas/persona/{persona.pk}/change/",
                }
                persona_details_by_id[str(persona.id)] = persona_details
                persona_details_by_name[persona.name] = persona_details
                persona_objects_by_id[str(persona.id)] = persona
                persona_objects_by_name[persona.name] = persona
        active_crawl_ids = [crawl["id"] for crawl in active_crawls_list]
        active_crawl_objects = {}
        if active_crawl_ids:
            for crawl_obj in Crawl.objects.filter(id__in=active_crawl_ids).select_related("created_by", "persona"):
                crawl_obj._runtime_config = request_config
                active_crawl_objects[str(crawl_obj.id)] = crawl_obj
        snapshot_counts_by_crawl: dict[str, dict[str, int]] = {str(crawl_id): {} for crawl_id in active_crawl_ids}
        cancelled_snapshot_counts_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in active_crawl_ids}
        crawl_output_sizes_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in active_crawl_ids}
        queued_snapshot_overflow_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in active_crawl_ids}
        active_snapshot_scope = snapshot_scope.filter(crawl_id__in=active_crawl_ids)
        if active_crawl_ids:
            for row in active_snapshot_scope.values("crawl_id", "status").annotate(count=Count("id")):
                snapshot_counts_by_crawl.setdefault(str(row["crawl_id"]), {})[row["status"]] = row["count"]

            for row in (
                active_snapshot_scope.filter(status=Snapshot.StatusChoices.SEALED, downloaded_at__isnull=True)
                .values("crawl_id")
                .annotate(count=Count("id"))
            ):
                cancelled_snapshot_counts_by_crawl[str(row["crawl_id"])] = row["count"]

            for row in (
                active_snapshot_scope.filter(
                    status=Snapshot.StatusChoices.SEALED,
                )
                .values("crawl_id")
                .annotate(size=Sum("output_size"))
            ):
                crawl_output_sizes_by_crawl[str(row["crawl_id"])] = int(row["size"] or 0)

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
        )
        queued_snapshot_fields = (
            "id_str",
            "url",
            "crawl_id_str",
            "title",
            "status",
        )
        snapshots = []
        for crawl_id in active_crawl_ids:
            crawl_snapshot_scope = active_snapshot_scope.filter(crawl_id=crawl_id)
            snapshots.extend(
                crawl_snapshot_scope.filter(status=Snapshot.StatusChoices.STARTED)
                .annotate(id_str=Cast("id", CharField()), crawl_id_str=Cast("crawl_id", CharField()))
                .values(*started_snapshot_fields)
                .order_by("-modified_at")[:max_started_snapshots_per_crawl],
            )
            queued_snapshots = list(
                crawl_snapshot_scope.filter(status=Snapshot.StatusChoices.QUEUED)
                .annotate(id_str=Cast("id", CharField()), crawl_id_str=Cast("crawl_id", CharField()))
                .values(
                    *queued_snapshot_fields,
                )
                .order_by("modified_at")[:max_queued_snapshots_per_crawl],
            )
            queued_snapshot_overflow_by_crawl[str(crawl_id)] = max(
                snapshot_counts_by_crawl.get(str(crawl_id), {}).get(Snapshot.StatusChoices.QUEUED, 0) - len(queued_snapshots),
                0,
            )
            snapshots.extend(queued_snapshots)

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
        process_value_fields = ("id", "process_type", "status", "pwd", "cmd", "pid", "exit_code", "started_at", "ended_at", "modified_at")
        if active_crawl_ids or displayed_snapshot_ids:
            process_scope = Process.objects.filter(
                machine_id=machine_id,
                process_type__in=[
                    Process.TypeChoices.HOOK,
                    Process.TypeChoices.BINARY,
                ],
            )
            running_processes = process_scope.filter(status=Process.StatusChoices.RUNNING).values(*process_value_fields)
            recent_processes = (
                process_scope.filter(modified_at__gte=now - timedelta(minutes=10)).values(*process_value_fields).order_by("-modified_at")
            )
        else:
            running_processes = Process.objects.none()
            recent_processes = Process.objects.none()

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
        for proc in running_processes:
            if not proc["pwd"]:
                continue
            proc_pwd = Path(proc["pwd"])
            matched_snapshot = find_snapshot_for_process(proc_pwd)
            matched_crawl = (
                crawls_by_id.get(str(matched_snapshot["crawl_id"])) if matched_snapshot is not None else find_crawl_for_process(proc_pwd)
            )
            if matched_snapshot is None:
                if matched_crawl is None:
                    continue
                crawl_id = str(matched_crawl["id"])
                snapshot_id = ""
            else:
                crawl_id = str(matched_snapshot["crawl_id"])
                snapshot_id = str(matched_snapshot["id"])
            running_worker_ids.add(str(proc["id"]))
            _plugin, _label, phase, _hook_name = process_label(proc["cmd"])
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

            plugin, label, phase, hook_name = process_label(proc["cmd"])

            record_scope = str(snapshot_id) if phase == "snapshot" and snapshot_id else str(crawl_id)
            proc_key = f"{record_scope}:{plugin}:{label}:{proc['status']}:{proc['exit_code']}"
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
        for crawl in active_crawls_list:
            crawl_id = str(crawl["id"])
            crawl_snapshot_counts = snapshot_counts_by_crawl.get(crawl_id, {})
            total_snapshots = sum(crawl_snapshot_counts.values())
            completed_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.SEALED, 0)
            started_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.STARTED, 0)
            pending_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.QUEUED, 0)
            cancelled_snapshots = cancelled_snapshot_counts_by_crawl.get(crawl_id, 0)

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
            crawl_screencast_url = screencast_frame_url(crawl_id, active_crawl_objects[crawl_id].output_dir)
            crawl_screencast_link = f"/admin/crawls/crawl/{crawl_id.replace('-', '')}/change/" if crawl_screencast_url else ""

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
                result_by_plugin = {result.plugin: result for result in snapshot_results}
                title_result = result_by_plugin.get("title")
                if not snapshot_title and title_result is not None and title_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
                    snapshot_title = Snapshot._normalize_title_candidate(title_result.output_str, snapshot_url=snapshot["url"])
                favicon_result = result_by_plugin.get("favicon")
                if favicon_result is not None and favicon_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
                    favicon_path = archiveresult_output_path(favicon_result) or "favicon/favicon.ico"
                    snapshot_favicon_url = snapshot_output_url(snapshot, favicon_path)
                screenshot_result = result_by_plugin.get("screenshot")
                if screenshot_result is not None and screenshot_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
                    snapshot_preview_link = snapshot_view_url(snapshot)
                    screenshot_path = archiveresult_output_path(screenshot_result) or "screenshot/screenshot.png"
                    snapshot_preview_url = snapshot_output_url(snapshot, screenshot_path)
                    snapshot_preview_link = snapshot_view_url(snapshot, screenshot_path)
                    if snapshot_favicon_url:
                        snapshot_fallback_urls.append(snapshot_favicon_url)
                elif snapshot_favicon_url:
                    snapshot_preview_url = snapshot_favicon_url

                if snapshot["status"] == Snapshot.StatusChoices.STARTED:
                    snapshot_screencast_url = screencast_frame_url(crawl_id, active_crawl_objects[crawl_id].output_dir)
                    snapshot_screencast_link = snapshot_view_url(snapshot) if snapshot_screencast_url else ""

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
                    plugin, label, phase, hook_name = hook_details(ar.hook_name or ar.plugin, plugin=ar.plugin)

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
                    output_path = archiveresult_output_path(ar)
                    if output_path:
                        plugin_payload["output_path"] = output_path
                        plugin_payload["output_url"] = snapshot_view_url(snapshot, output_path)
                    if status == ArchiveResult.StatusChoices.STARTED and process:
                        plugin_payload["pid"] = process.pid
                    if status == ArchiveResult.StatusChoices.STARTED:
                        plugin_payload["progress"] = progress_value
                        plugin_payload["timeout"] = process.timeout if process else 120
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
                    and worker_state == "waiting"
                    and not all_plugins
                    and snapshot["modified_at"]
                    and (now - snapshot["modified_at"]).total_seconds() > 30
                ):
                    worker_state = "waiting" if orchestrator_running else "crashed"

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
                            "started": (snapshot["downloaded_at"] or snapshot["created_at"]).isoformat()
                            if (snapshot["downloaded_at"] or snapshot["created_at"])
                            else None,
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
            crawl_output_size = crawl_output_sizes_by_crawl.get(crawl_id, 0)
            avg_snapshot_size = int(crawl_output_size / completed_snapshots) if completed_snapshots else 0
            crawl_obj = active_crawl_objects[crawl_id]
            effective_crawl_config = get_config(crawl=crawl_obj, resolve_plugins=False)
            max_urls = int(effective_crawl_config.CRAWL_MAX_URLS or 0)
            crawl_max_size = int(effective_crawl_config.CRAWL_MAX_SIZE or 0)
            crawl_timeout = int(effective_crawl_config.CRAWL_TIMEOUT or 0)
            snapshot_max_size = int(effective_crawl_config.SNAPSHOT_MAX_SIZE or 0)

            # Check if retry_at is in the future (would prevent worker from claiming)
            retry_at_future = crawl["retry_at"] > now if crawl["retry_at"] else False
            is_paused = crawl_obj.is_paused
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
                    "label": (next((line.strip() for line in (crawl["urls"] or "").splitlines() if line.strip()), "") or crawl_id)[:60],
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
                    "crawl_output_size_display": printable_filesize(crawl_output_size) if crawl_output_size else "0 B",
                    "avg_snapshot_size_display": printable_filesize(avg_snapshot_size) if avg_snapshot_size else "0 B",
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
                    "queued_snapshots_hidden": queued_snapshot_overflow_by_crawl.get(crawl_id, 0),
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
            "active_crawls": active_crawls,
            "queued_crawls_hidden": queued_crawls_hidden,
            "server_time": timezone.now().isoformat(),
        }
        try:
            import ujson

            return HttpResponse(ujson.dumps(payload), content_type="application/json")
        except ImportError:
            return JsonResponse(payload)
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
