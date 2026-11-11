from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from archivebox.core.admin_site import archivebox_admin
from archivebox.progressmonitor.views import progress_endpoint

from .forms import SiteCloneForm
from .models import SiteClone


def clone_admin(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Site cloning requires a superuser account.")
        return view(request, *args, **kwargs)

    return wrapped


@clone_admin
@require_http_methods(["GET", "POST"])
def index(request):
    form = SiteCloneForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        clone = form.save(request.user)
        messages.success(request, "Site crawl queued. The ArchiveBox worker will discover and save matching pages.")
        return redirect(clone)
    clones = Paginator(SiteClone.objects.select_related("crawl", "crawl__schedule").order_by("-crawl__created_at"), 20).get_page(
        request.GET.get("page"),
    )
    return render(
        request,
        "siteclones/index.html",
        {
            **archivebox_admin.each_context(request),
            "title": "Clone a site",
            "form": form,
            "clones": clones,
        },
    )


@clone_admin
@require_http_methods(["GET"])
def detail(request, clone_id):
    clone = get_object_or_404(SiteClone.objects.select_related("crawl", "crawl__persona", "crawl__schedule"), pk=clone_id)
    crawl = clone.crawl
    counts = dict(crawl.snapshot_set.values_list("status").annotate(count=Count("id")))
    snapshots = Paginator(
        crawl.snapshot_set.order_by("depth", "created_at").only("id", "url", "title", "status", "depth", "output_size"),
        50,
    ).get_page(request.GET.get("page"))
    return render(
        request,
        "siteclones/detail.html",
        {
            **archivebox_admin.each_context(request),
            "title": crawl.label or "Site clone",
            "clone": clone,
            "crawl": crawl,
            "snapshots": snapshots,
            "total": sum(counts.values()),
            "saved": crawl.snapshot_set.filter(output_size__gt=0).count(),
            "progress_endpoint": progress_endpoint("crawl", crawl.pk),
            "progress_scope": "crawl",
            "progress_auto_expand": True,
            "scheduled_runs": crawl.schedule.crawl_set.exclude(pk=crawl.pk).order_by("-created_at")[:5] if crawl.schedule_id else [],
        },
    )


@clone_admin
@require_POST
def action(request, clone_id, action):
    clone = get_object_or_404(SiteClone.objects.select_related("crawl"), pk=clone_id)
    if action == "pause":
        clone.crawl.pause()
        messages.success(request, "Crawl paused. Saved pages are retained.")
    elif action == "resume":
        clone.crawl.resume()
        messages.success(request, "Crawl queued to resume with its existing page queue and limits.")
    return redirect(clone)
