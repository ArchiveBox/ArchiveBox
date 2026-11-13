import sys
import re
from functools import wraps
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib.auth.views import redirect_to_login
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Snapshot, ArchiveResult
from archivebox.machine.models import Process
from .service import filter_groups, group_extensions, group_selection_hash, launch, read_report


def audit_admin(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Storage audit requires a superuser account.")
        return view(request, *args, **kwargs)

    return wrapped


@audit_admin
@require_GET
def index(request):
    snapshots = Snapshot.objects.all()
    query = request.GET.get("q", "").strip()
    if query:
        snapshots = snapshots.filter(url__icontains=query)
    versions = list(
        snapshots.values("url")
        .annotate(captures=Count("pk"), bytes=Sum("output_size"))
        .filter(captures__gt=1)
        .order_by("-bytes", "url")[:100],
    )
    for version in versions:
        version["review_url"] = "/admin/core/snapshot/?" + urlencode({"url": version["url"]})
        version["outputs_url"] = "/admin/core/archiveresult/?" + urlencode({"snapshot__url": version["url"]})
    results = ArchiveResult.objects.filter(snapshot__in=snapshots).exclude(plugin="")
    runtime = ExpressionWrapper(
        Coalesce(F("process__ended_at") - F("process__started_at"), F("end_ts") - F("start_ts")),
        output_field=DurationField(),
    )
    slowest_plugins = list(
        results.annotate(hook_runtime=runtime)
        .filter(hook_runtime__gte=timedelta())
        .values("plugin")
        .annotate(count=Count("pk"), total_runtime=Sum("hook_runtime"), avg_runtime=Avg("hook_runtime"), max_runtime=Max("hook_runtime"))
        .order_by("-max_runtime", "plugin")[:10],
    )
    for row in slowest_plugins:
        for metric in ("total", "avg", "max"):
            row[f"{metric}_seconds"] = row.pop(f"{metric}_runtime").total_seconds()
    heaviest_plugins = list(
        results.values("plugin").annotate(bytes=Sum("output_size"), count=Count("pk")).order_by("-bytes", "plugin")[:10],
    )
    for row in [*slowest_plugins, *heaviest_plugins]:
        filters = {"plugin__exact": row["plugin"]}
        if query:
            filters["snapshot__url__icontains"] = query
        row["review_url"] = "/admin/core/archiveresult/?" + urlencode(filters)
    largest_snapshots = list(snapshots.order_by("-output_size", "pk").values("id", "title", "url", "output_size")[:10])
    output_counts = dict(
        ArchiveResult.objects.filter(snapshot_id__in=[row["id"] for row in largest_snapshots])
        .values("snapshot_id")
        .annotate(count=Count("pk"))
        .values_list("snapshot_id", "count"),
    )
    for row in largest_snapshots:
        row["bytes"] = row.pop("output_size")
        row["output_count"] = output_counts.get(row["id"], 0)
        row["title"] = row["title"] or row["url"]
        row["review_url"] = f"/admin/core/snapshot/{row['id']}/change/"
    runs = Process.objects.filter(worker_type="storage-audit").order_by("-created_at")
    run_id = request.GET.get("run", "")
    if run_id and not re.fullmatch("[0-9a-f]{32}", run_id):
        return HttpResponseBadRequest("Invalid audit process.")
    process = get_object_or_404(runs, pk=run_id) if run_id else runs.first()
    if process:
        process.poll()
    report = read_report(process) if process else {}
    groups = report.get("groups", []) if isinstance(report.get("groups", []), list) else []
    groups = filter_groups(groups, query)
    return render(
        request,
        "storageaudit/index.html",
        {
            **archivebox_admin.each_context(request),
            "title": "Storage audit",
            "versions": versions,
            "slowest_plugins": slowest_plugins,
            "heaviest_plugins": heaviest_plugins,
            "largest_snapshots": largest_snapshots,
            "extensions": group_extensions(groups)[:10],
            "snapshot_count": snapshots.count(),
            "snapshot_bytes": snapshots.aggregate(total=Sum("output_size"))["total"] or 0,
            "output_count": ArchiveResult.objects.filter(snapshot__in=snapshots).count(),
            "query": query,
            "process": process,
            "runs": runs[:10],
            "report": report,
            "cow_available": sys.platform == "linux",
        },
    )


@audit_admin
@require_POST
def scan(request):
    process = launch(user_id=request.user.pk)
    return redirect(f"/admin/storage-audit/?run={process.pk}")


def selected_groups(request):
    run_id = request.POST.get("run", "")
    if not re.fullmatch("[0-9a-f]{32}", run_id):
        raise ValueError("Invalid audit process.")
    process = get_object_or_404(Process, pk=run_id, worker_type="storage-audit", status=Process.StatusChoices.EXITED, exit_code=0)
    report = read_report(process)
    if "extension" in request.POST:
        if request.POST.getlist("groups") or not report.get("complete"):
            raise ValueError("Invalid extension selection.")
        extension = next(
            (
                row
                for row in group_extensions(filter_groups(report.get("groups", []), request.POST.get("q", "").strip()))
                if row["extension"] == request.POST["extension"]
            ),
            None,
        )
        if extension is None:
            raise ValueError("Select an extension from the completed audit.")
        return process, extension["groups"]
    selected = set(request.POST.getlist("groups"))
    groups = [group for group in report.get("groups", []) if group["id"] in selected]
    if not report.get("complete") or not selected or len(selected) > 100 or len(groups) != len(selected):
        raise ValueError("Select 1–100 existing groups from a completed audit.")
    return process, groups


@audit_admin
@require_POST
def preview(request):
    try:
        process, groups = selected_groups(request)
    except (ValueError, TypeError):
        return HttpResponseBadRequest("Invalid audit selection.")
    payload = {"run": str(process.pk), "groups": [group["id"] for group in groups]}
    if "extension" in request.POST:
        payload = {
            "run": str(process.pk),
            "extension": request.POST["extension"],
            "q": request.POST.get("q", "").strip(),
            "selection_hash": group_selection_hash(groups),
        }
    token = signing.dumps(payload, salt="storage-audit-cow")
    return render(
        request,
        "storageaudit/preview.html",
        {
            **archivebox_admin.each_context(request),
            "title": "Review copy-on-write deduplication",
            "groups": groups,
            "token": token,
            "cow_available": sys.platform == "linux",
            "potential_bytes": sum(group["potential_bytes"] for group in groups),
        },
    )


@audit_admin
@require_POST
def apply(request):
    try:
        payload = signing.loads(request.POST.get("preview", ""), salt="storage-audit-cow", max_age=3600)
        source = get_object_or_404(
            Process,
            pk=payload["run"],
            worker_type="storage-audit",
            status=Process.StatusChoices.EXITED,
            exit_code=0,
        )
        report = read_report(source)
        extension = payload.get("extension")
        if extension is not None:
            selected = next(
                (
                    row
                    for row in group_extensions(filter_groups(report.get("groups", []), payload.get("q", "")))
                    if row["extension"] == extension
                ),
                None,
            )
            if selected is None or group_selection_hash(selected["groups"]) != payload["selection_hash"]:
                raise ValueError("Selection changed.")
            groups = set()
        else:
            groups = set(payload["groups"])
            if not groups or not groups.issubset({group["id"] for group in report.get("groups", [])}):
                raise ValueError("Selection changed.")
        if not report.get("complete"):
            raise ValueError("Audit is incomplete.")
        if sys.platform != "linux":
            return HttpResponseBadRequest("Native copy-on-write currently requires Linux. No files changed.")
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return HttpResponseBadRequest("Preview expired or selection changed. Review the audit again.")
    process = launch(
        user_id=request.user.pk,
        source=source,
        group_ids=sorted(groups),
        extension=extension,
        selection_hash=payload.get("selection_hash"),
        query=payload.get("q", ""),
    )
    return redirect(f"/admin/storage-audit/?run={process.pk}")
