from copy import copy

from django.contrib import messages
from django.contrib.admin.options import IncorrectLookupParameters
from django.db.models import Prefetch
from django.http import HttpResponseBadRequest, QueryDict
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Snapshot
from archivebox.core.permissions import public_snapshots_queryset
from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.importers.views import importer_admin, page
from archivebox.search.query import apply_snapshot_search
from .forms import ExportForm, SubscribeForm
from .models import SavedFeed


def list_queryset(request):
    """Reuse real admin filters, resolving search without the browser's async cache."""
    model_admin = copy(archivebox_admin._registry[Snapshot])
    model_admin.request = request

    def search(_request, queryset, term):
        if term:
            queryset = apply_snapshot_search(
                queryset,
                term,
                search_mode=request.GET.get("search_mode", "meta"),
                config=request.archivebox_config,
            )
        return queryset, True

    model_admin.get_search_results = search
    return model_admin.get_changelist_instance(request).queryset


@importer_admin
@require_http_methods(["GET", "POST"])
def index(request):
    form = SubscribeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        schedule = form.cleaned_data["schedule"]
        source = ImporterSource.objects.create(
            name=form.cleaned_data["name"],
            created_by=request.user,
            plugin="importer_rss",
            feed="feed",
            settings={
                "IMPORTER_RSS_URL": form.feed_url,
                **({"IMPORTER_RSS_IMPORT_TAGS": True} if form.cleaned_data["import_tags"] else {}),
            },
            tags=form.cleaned_data["tags"],
            schedule=schedule,
            next_run_at=form.next_run_at,
        )
        messages.success(request, "Feed saved. Preview the articles or start importing now.")
        return redirect(source)
    return page(
        request,
        "feeds/index.html",
        {
            "title": "Feeds",
            "form": form,
            "sources": ImporterSource.objects.filter(plugin="importer_rss")
            .order_by("name")
            .prefetch_related(
                Prefetch(
                    "runs",
                    queryset=ImporterRun.objects.only("id", "source_id", "status", "created_at").order_by("-created_at", "-id")[:1],
                    to_attr="latest_runs",
                ),
            ),
            "feeds": SavedFeed.objects.filter(enabled=True).order_by("name"),
        },
    )


@importer_admin
@require_http_methods(["GET", "POST"])
def export(request):
    form = ExportForm(request.POST if request.method == "POST" else None, initial={"name": "ArchiveBox reading list"})
    try:
        count = list_queryset(request).count()
    except (IncorrectLookupParameters, ValueError):
        return HttpResponseBadRequest("Invalid snapshot filters.")
    if request.method == "POST" and form.is_valid():
        feed = form.save(commit=False)
        feed.created_by = request.user
        filters = request.GET.copy()
        for key in ("p", "api_key", "token", "password", "_popup", "_to_field"):
            filters.pop(key, None)
        feed.filters = dict(filters.lists())
        feed.save()
        messages.success(request, "RSS link created. Copy it into your feed reader.")
        return redirect("feeds:index")
    return page(request, "feeds/export.html", {"title": "Export this list as RSS", "form": form, "count": count})


@require_GET
def rss(request, token):
    from archivebox.api.v1_core import _snapshots_rss_response

    feed = get_object_or_404(
        SavedFeed.objects.select_related("created_by"),
        token=token,
        enabled=True,
        created_by__is_active=True,
        created_by__is_superuser=True,
    )
    query_request = copy(request)
    query_request.GET = QueryDict(mutable=True)
    for key, values in feed.filters.items():
        query_request.GET.setlist(key, values)
    query_request.user = feed.created_by
    try:
        queryset = list_queryset(query_request)
    except (IncorrectLookupParameters, ValueError):
        return HttpResponseBadRequest("The saved list contains filters that are no longer supported.")
    if not feed.include_private:
        queryset = public_snapshots_queryset(queryset)
    response = _snapshots_rss_response(
        request,
        snapshots=queryset.select_related("crawl__created_by").prefetch_related("tags")[:500],
        title=feed.name,
    )
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


@importer_admin
@require_POST
def revoke(request, feed_id):
    get_object_or_404(SavedFeed, pk=feed_id).delete()
    messages.success(request, "RSS link revoked.")
    return redirect("feeds:index")
