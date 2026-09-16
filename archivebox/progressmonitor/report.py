"""Assemble one live-progress report from scoped, bounded database queries."""

from functools import lru_cache
from typing import Any
from pathlib import Path

from abx_dl.events import PROCESS_EXIT_SKIPPED
from django.db.models import CharField, Count, Q, Sum
from django.db.models.functions import Cast
from django.utils import timezone

from archivebox.core.routes_util import get_api_base_url
from archivebox.plugins.discovery import discover_plugin_configs


from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Machine, Process

from .presentation import render_crawl, process_label
from datetime import timedelta


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


class ProgressReport:
    """Per-request query results shared by status, process, and preview rendering."""

    def __init__(self, request, *, scoped_snapshot, crawl_id_filter, is_admin):
        self.request = request
        self.scoped_snapshot = scoped_snapshot
        self.crawl_id_filter = crawl_id_filter
        self.is_admin = is_admin
        self.request_config = self.request.archivebox_config
        self.now = timezone.now()
        self.crawl_scope = Crawl.objects.all()
        self.snapshot_scope = Snapshot.objects.all()
        self.archiveresult_scope = ArchiveResult.objects.all()
        if self.is_admin and not self.request.user.is_superuser:
            self.crawl_scope = self.crawl_scope.filter(created_by=self.request.user)
            self.snapshot_scope = self.snapshot_scope.filter(crawl__created_by=self.request.user)
            self.archiveresult_scope = self.archiveresult_scope.filter(snapshot__crawl__created_by=self.request.user)
        if self.scoped_snapshot is not None:
            self.snapshot_scope = Snapshot.objects.filter(id=self.scoped_snapshot.id)
            self.crawl_scope = Crawl.objects.filter(id=self.scoped_snapshot.crawl_id)
            self.archiveresult_scope = ArchiveResult.objects.filter(snapshot_id=self.scoped_snapshot.id)
        elif self.crawl_id_filter:
            self.snapshot_scope = self.snapshot_scope.filter(crawl_id=self.crawl_id_filter)
            self.crawl_scope = self.crawl_scope.filter(id=self.crawl_id_filter)
            self.archiveresult_scope = self.archiveresult_scope.filter(snapshot__crawl_id=self.crawl_id_filter)

        self.api_base = get_api_base_url(request=self.request, config=self.request_config) if self.scoped_snapshot is not None else ""

    def load_orchestrator(self):
        self.machine_id = Machine.current().id
        orchestrator_proc = (
            Process.objects.filter(
                machine_id=self.machine_id,
                process_type=Process.TypeChoices.ORCHESTRATOR,
                status=Process.StatusChoices.RUNNING,
            )
            .only("id", "pid", "started_at", "machine_id", "process_type", "status")
            .order_by("-started_at")
            .first()
            if self.machine_id is not None
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
        self.orchestrator_running = orchestrator_proc_running or runner_worker_running
        self.orchestrator_pid = orchestrator_proc.pid if orchestrator_proc_running and orchestrator_proc else runner_worker_pid

    def load_counts(self):
        downloads, indexing = _live_progress_plugin_names()
        download_scope = self.archiveresult_scope.filter(
            plugin__in=downloads,
            snapshot__status__in=Snapshot.RUNNABLE_STATES,
            snapshot__crawl__status__in=Crawl.RUNNABLE_STATES,
        )
        self.counts = {}
        for label, model, scope in (
            ("crawls", Crawl, self.crawl_scope),
            ("snapshots", Snapshot, self.snapshot_scope),
            ("archiveresults", ArchiveResult, self.archiveresult_scope),
            ("downloads", ArchiveResult, download_scope),
            ("indexing", ArchiveResult, self.archiveresult_scope.filter(plugin__in=indexing)),
        ):
            counts = model.status_counts(scope, ("queued", "started"))
            self.counts[f"{label}_queued"] = counts.get("queued", 0)
            self.counts[f"{label}_active"] = counts.get("started", 0)
        self.counts["crawls_recent"] = self.crawl_scope.filter(created_at__gte=self.now - timedelta(days=1)).count()

    def load_crawls(self):
        # Build hierarchical active crawls with nested snapshots and archive results
        max_active_crawls = 10
        max_queued_crawls = 10
        self.max_started_snapshots_per_crawl = 50
        self.max_queued_snapshots_per_crawl = 50

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
            self.crawl_scope.filter(status=Crawl.StatusChoices.STARTED)
            .values(*active_crawl_fields)
            .order_by("-modified_at")[:max_active_crawls],
        )
        paused_crawls = list(
            self.crawl_scope.filter(
                Q(status=Crawl.StatusChoices.PAUSED, created_at__gte=self.now - timedelta(hours=12))
                | Q(
                    status=Crawl.StatusChoices.PAUSED,
                    snapshot_set__status__in=Snapshot.RUNNABLE_STATES,
                    snapshot_set__retry_at__lte=self.now,
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
            self.crawl_scope.filter(status=Crawl.StatusChoices.QUEUED)
            .values(*active_crawl_fields)
            .order_by("-modified_at")[:max_queued_crawls],
        )
        self.queued_crawls_hidden = max(self.counts["crawls_queued"] - len(queued_crawls), 0)
        self.active_crawls_list = started_crawls + paused_crawls + queued_crawls
        for crawl in self.active_crawls_list:
            crawl["id"] = str(crawl["id"])
            if crawl["persona_id"]:
                crawl["persona_id"] = str(crawl["persona_id"])
        self.persona_details_by_id: dict[str, dict[str, str]] = {}
        self.persona_details_by_name: dict[str, dict[str, str]] = {}
        persona_ids = {crawl["persona_id"] for crawl in self.active_crawls_list if crawl["persona_id"]}
        persona_names = {"Default"} if any(not crawl["persona_id"] for crawl in self.active_crawls_list) else set()
        if persona_ids or persona_names:
            from archivebox.personas.models import Persona

            for persona in Persona.objects.filter(Q(id__in=persona_ids) | Q(name__in=persona_names)).only("id", "name", "config"):
                persona_details = {
                    "name": persona.name,
                    "admin_url": f"/admin/personas/persona/{persona.pk}/change/",
                }
                self.persona_details_by_id[str(persona.id)] = persona_details
                self.persona_details_by_name[persona.name] = persona_details
        self.active_crawl_ids = [crawl["id"] for crawl in self.active_crawls_list]
        self.active_crawl_objects = {}
        if self.active_crawl_ids:
            for crawl_obj in Crawl.objects.filter(id__in=self.active_crawl_ids).select_related("created_by", "persona"):
                crawl_obj._runtime_config = self.request_config
                self.active_crawl_objects[str(crawl_obj.id)] = crawl_obj
        self.snapshot_counts_by_crawl: dict[str, dict[str, int]] = {str(crawl_id): {} for crawl_id in self.active_crawl_ids}
        self.cancelled_snapshot_counts_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in self.active_crawl_ids}
        self.crawl_output_sizes_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in self.active_crawl_ids}
        self.queued_snapshot_overflow_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in self.active_crawl_ids}
        self.active_snapshot_scope = self.snapshot_scope.filter(crawl_id__in=self.active_crawl_ids)
        if self.active_crawl_ids:
            for row in self.active_snapshot_scope.values("crawl_id", "status").annotate(count=Count("id")):
                self.snapshot_counts_by_crawl.setdefault(str(row["crawl_id"]), {})[row["status"]] = row["count"]

            for row in (
                self.active_snapshot_scope.filter(status=Snapshot.StatusChoices.SEALED, downloaded_at__isnull=True)
                .values("crawl_id")
                .annotate(count=Count("id"))
            ):
                self.cancelled_snapshot_counts_by_crawl[str(row["crawl_id"])] = row["count"]

            for row in (
                self.active_snapshot_scope.filter(
                    status=Snapshot.StatusChoices.SEALED,
                )
                .values("crawl_id")
                .annotate(size=Sum("output_size"))
            ):
                self.crawl_output_sizes_by_crawl[str(row["crawl_id"])] = int(row["size"] or 0)

    def load_snapshots(self):
        self.crawl_process_pids: dict[str, int] = {}
        self.snapshot_process_pids: dict[str, int] = {}
        self.process_records_by_crawl: dict[str, list[tuple[dict[str, object], object | None]]] = {}
        self.process_records_by_snapshot: dict[str, list[tuple[dict[str, object], object | None]]] = {}
        self.seen_process_records: set[str] = set()
        self.crawls_by_id = {str(crawl["id"]): crawl for crawl in self.active_crawls_list}
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
        for crawl_id in self.active_crawl_ids:
            crawl_snapshot_scope = self.active_snapshot_scope.filter(crawl_id=crawl_id)
            snapshots.extend(
                crawl_snapshot_scope.filter(status=Snapshot.StatusChoices.STARTED)
                .annotate(id_str=Cast("id", CharField()), crawl_id_str=Cast("crawl_id", CharField()))
                .values(*started_snapshot_fields)
                .order_by("-modified_at")[: self.max_started_snapshots_per_crawl],
            )
            queued_snapshots = list(
                crawl_snapshot_scope.filter(status=Snapshot.StatusChoices.QUEUED)
                .annotate(id_str=Cast("id", CharField()), crawl_id_str=Cast("crawl_id", CharField()))
                .values(
                    *queued_snapshot_fields,
                )
                .order_by("modified_at")[: self.max_queued_snapshots_per_crawl],
            )
            self.queued_snapshot_overflow_by_crawl[str(crawl_id)] = max(
                self.snapshot_counts_by_crawl.get(str(crawl_id), {}).get(Snapshot.StatusChoices.QUEUED, 0) - len(queued_snapshots),
                0,
            )
            snapshots.extend(queued_snapshots)

        for snapshot in snapshots:
            # Process.pwd points at Snapshot.output_dir, which uses CompactUUID
            # hex path components. Keep progress IDs compact too so process rows
            # can be matched without carrying dashed/undashed variants.
            snapshot["id"] = str(snapshot.pop("id_str")).replace("-", "")
            snapshot["crawl_id"] = str(snapshot.pop("crawl_id_str")).replace("-", "")
        self.snapshots_by_id = {str(snapshot["id"]): snapshot for snapshot in snapshots}
        self.displayed_snapshots_by_crawl: dict[str, list[dict[str, Any]]] = {str(crawl_id): [] for crawl_id in self.active_crawl_ids}
        for snapshot in snapshots:
            crawl_snapshots = self.displayed_snapshots_by_crawl.setdefault(str(snapshot["crawl_id"]), [])
            crawl_snapshots.append(snapshot)
        displayed_snapshot_ids = [
            snapshot["id"] for crawl_snapshots in self.displayed_snapshots_by_crawl.values() for snapshot in crawl_snapshots
        ]
        detailed_snapshot_ids = [snapshot["id"] for snapshot in snapshots if snapshot["status"] != Snapshot.StatusChoices.QUEUED]
        process_value_fields = ("id", "process_type", "status", "pwd", "cmd", "pid", "exit_code", "started_at", "ended_at", "modified_at")
        if self.active_crawl_ids or displayed_snapshot_ids:
            process_scope = Process.objects.filter(
                machine_id=self.machine_id,
                process_type__in=[
                    Process.TypeChoices.HOOK,
                    Process.TypeChoices.BINARY,
                ],
            )
            self.running_processes = process_scope.filter(status=Process.StatusChoices.RUNNING).values(*process_value_fields)
            self.recent_processes = (
                process_scope.filter(modified_at__gte=self.now - timedelta(minutes=10))
                .values(*process_value_fields)
                .order_by("-modified_at")
            )
        else:
            self.running_processes = Process.objects.none().values(*process_value_fields)
            self.recent_processes = Process.objects.none().values(*process_value_fields)

        self.archiveresults_by_snapshot: dict[str, list[ArchiveResult]] = {str(snapshot_id): [] for snapshot_id in detailed_snapshot_ids}
        if detailed_snapshot_ids:
            displayed_archiveresults = (
                self.archiveresult_scope.filter(snapshot_id__in=detailed_snapshot_ids)
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
                self.archiveresults_by_snapshot.setdefault(str(archiveresult.snapshot_id), []).append(archiveresult)

    def load_processes(self):
        self.running_worker_ids: set[str] = set()
        for proc in self.running_processes:
            if not proc["pwd"]:
                continue
            scope = self.process_scope_ids(Path(proc["pwd"]))
            if scope is None:
                continue
            crawl_id, snapshot_id = scope
            self.running_worker_ids.add(str(proc["id"]))
            _plugin, _label, phase, _hook_name = process_label(proc["cmd"])
            if crawl_id and proc["pid"]:
                self.crawl_process_pids.setdefault(crawl_id, proc["pid"])
            if phase == "snapshot" and snapshot_id and proc["pid"]:
                self.snapshot_process_pids.setdefault(snapshot_id, proc["pid"])

        for proc in self.recent_processes:
            if not proc["pwd"]:
                continue
            scope = self.process_scope_ids(Path(proc["pwd"]))
            if scope is None:
                continue
            crawl_id, snapshot_id = scope

            plugin, label, phase, hook_name = process_label(proc["cmd"])

            record_scope = str(snapshot_id) if phase == "snapshot" and snapshot_id else str(crawl_id)
            proc_key = f"{record_scope}:{plugin}:{label}:{proc['status']}:{proc['exit_code']}"
            if proc_key in self.seen_process_records:
                continue
            self.seen_process_records.add(proc_key)

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
                self.process_records_by_snapshot.setdefault(snapshot_id, []).append((payload, proc_run_at))
            elif crawl_id:
                self.process_records_by_crawl.setdefault(crawl_id, []).append((payload, proc_run_at))

    def payload(self):
        self.load_orchestrator()
        self.load_counts()
        self.load_crawls()
        self.load_snapshots()
        self.load_processes()
        return {
            "is_admin": self.is_admin,
            "scope": {
                "snapshot_id": str(self.scoped_snapshot.id) if self.scoped_snapshot is not None else "",
                "crawl_id": self.crawl_id_filter,
            },
            "orchestrator_running": self.orchestrator_running,
            "orchestrator_pid": self.orchestrator_pid,
            "total_workers": len(self.running_worker_ids),
            **self.counts,
            "active_crawls": [render_crawl(self, crawl) for crawl in self.active_crawls_list],
            "queued_crawls_hidden": self.queued_crawls_hidden,
            "server_time": timezone.now().isoformat(),
        }

    def process_scope_ids(self, proc_pwd: Path) -> tuple[str, str] | None:
        """Match a process directory to the displayed snapshot or crawl IDs."""
        parts = [part.replace("-", "") for part in reversed(proc_pwd.parts)]
        for part in parts:
            if snapshot := self.snapshots_by_id.get(part):
                return str(snapshot["crawl_id"]), str(snapshot["id"])
        for part in parts:
            if crawl := self.crawls_by_id.get(part):
                return str(crawl["id"]), ""
        return None
