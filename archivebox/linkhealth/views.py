from functools import wraps
import re

from django.contrib import messages
from django.contrib.admin.options import IncorrectLookupParameters
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.http import HttpResponseBadRequest, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.exports import get_export_queryset
from archivebox.core.models import Folder, Snapshot, SnapshotTag, Tag
from archivebox.machine.models import Process
from .service import launch_check, report


def health_admin(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Link checks require a superuser account.")
        return view(request, *args, **kwargs)

    return wrapped


def selection(request, query):
    params = QueryDict(query).copy()
    for key in ("run", "page", "p"):
        params.pop(key, None)
    snapshots = get_export_queryset(params, user=request.user, public_only=False, config=request.archivebox_config, request=request)
    return snapshots, params.urlencode()


@health_admin
@require_GET
def index(request):
    try:
        snapshots, query = selection(request, request.GET.urlencode())
    except (IncorrectLookupParameters, ValueError):
        return HttpResponseBadRequest("Invalid snapshot filters.")
    runs = Process.objects.filter(worker_type="link-check").order_by("-created_at")
    run_id = request.GET.get("run", "")
    if run_id and not re.fullmatch(r"[0-9a-f]{32}", run_id):
        return HttpResponseBadRequest("Invalid process ID.")
    process = get_object_or_404(runs, pk=run_id) if run_id else runs.first()
    if process:
        process.poll()
    snapshots = snapshots.annotate(is_offline=Exists(SnapshotTag.objects.filter(snapshot_id=OuterRef("pk"), tag__name__iexact="offline")))
    offline_tag = Tag.objects.filter(name__iexact="offline").first()
    return render(
        request,
        "linkhealth/index.html",
        {
            **archivebox_admin.each_context(request),
            "title": "Broken links",
            "snapshots": Paginator(snapshots.order_by("-created_at", "pk"), 50).get_page(request.GET.get("page")),
            "count": snapshots.count(),
            "query": query,
            "filters": QueryDict(query),
            "inherited_filters": [
                (key, value)
                for key, values in QueryDict(query).lists()
                if key not in {"q", "url__icontains", "tag", "folder"}
                for value in values
            ],
            "folders": Folder.tree(),
            "tags": Tag.objects.order_by("name"),
            "offline_count": Snapshot.objects.filter(tags__name__iexact="offline").count(),
            "offline_tag": offline_tag,
            "process": process,
            "runs": runs[:10],
            "report": report(process) if process else {},
        },
    )


@health_admin
@require_POST
def scan(request):
    try:
        snapshots, query = selection(request, request.POST.get("query", ""))
    except (IncorrectLookupParameters, ValueError):
        return HttpResponseBadRequest("Invalid snapshot filters.")
    selected = request.POST.getlist("snapshot_ids")
    if request.POST.get("scope") == "selected":
        if not selected or len(selected) > 50 or any(not re.fullmatch(r"[0-9a-f]{32}", pk) for pk in selected):
            return HttpResponseBadRequest("Select between 1 and 50 snapshots from this list.")
        if snapshots.filter(pk__in=selected).count() != len(set(selected)):
            return HttpResponseBadRequest("Selection does not match these filters.")
    else:
        selected = None
    process = launch_check(user_id=request.user.pk, query=query, snapshot_ids=selected)
    messages.success(request, "Checking original URLs. Confirmed missing pages receive the offline tag.")
    return redirect(f"/admin/link-health/?{query + '&' if query else ''}run={process.pk}")


@health_admin
@require_POST
def cancel(request, process_id):
    try:
        _, query = selection(request, request.POST.get("query", ""))
    except (IncorrectLookupParameters, ValueError):
        return HttpResponseBadRequest("Invalid snapshot filters.")
    process = get_object_or_404(Process, pk=process_id, worker_type="link-check")
    process.kill()
    messages.success(request, "Link check stopped. Tags already applied are preserved.")
    return redirect(f"/admin/link-health/?{query + '&' if query else ''}run={process.pk}")
