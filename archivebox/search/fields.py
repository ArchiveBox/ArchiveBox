"""Server-owned operator menu and permission-scoped value completion."""

from datetime import date, timedelta
from urllib.parse import urlsplit

from django.contrib.admin.options import IncorrectLookupParameters
from django.urls import reverse
from django.db.models import Case, Exists, OuterRef, When

from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from archivebox.config.common import get_request_config
from archivebox.core.domain_grouping import domain_authority_from_key
from archivebox.core.models import ArchiveResult, Folder, Snapshot
from archivebox.core.permissions import discoverable_snapshots_queryset, is_admin_user
from archivebox.search.language import ALIASES, literal_pattern, substring


def snapshot_plugin_choices():
    from archivebox.plugins.discovery import get_plugin_catalog

    return sorted(name for name, plugin in get_plugin_catalog().items() if plugin.filter_hooks("Snapshot"))


@never_cache
@require_GET
def field_page(request):
    if not is_admin_user(request) and not get_request_config(request, resolve_plugins=False).PUBLIC_INDEX:
        return HttpResponseForbidden()
    return render(request, "search/standalone.html", {"admin_target": request.GET.get("target") == "admin"})


@never_cache
@require_GET
def suggestions(request):
    if not is_admin_user(request) and not get_request_config(request, resolve_plugins=False).PUBLIC_INDEX:
        return HttpResponseForbidden()
    scope = discoverable_snapshots_queryset(request, Snapshot.objects.all()).order_by()
    list_url = request.GET.get("search_url", "")
    if list_url:
        from archivebox.core.admin_site import archivebox_admin
        from archivebox.search.views import snapshot_view_scope

        path = urlsplit(list_url).path
        if path == reverse("public-index"):
            scope = snapshot_view_scope(request, list_url)
        elif path in (reverse("admin:core_snapshot_changelist"), reverse("admin:grid")):
            model_admin = archivebox_admin.get_model_admin(Snapshot)
            if not is_admin_user(request) or not model_admin.has_view_or_change_permission(request):
                return HttpResponseForbidden()
            try:
                scope = snapshot_view_scope(request, list_url, model_admin=model_admin)
            except IncorrectLookupParameters:
                return JsonResponse({"values": []}, status=400)
        else:
            return JsonResponse({"values": []}, status=400)
    key = request.GET.get("operator", "")
    key = ALIASES.get(key, key)
    prefix = request.GET.get("prefix", "")[:256]

    def choices(qs, field):
        if prefix:
            qs = qs.filter(substring(field, prefix))
        return list(qs.exclude(**{field: ""}).order_by(field).values_list(field, flat=True).distinct()[:12])

    if key == "tags":
        values = choices(scope.filter(tags__isnull=False), "tags__name")
    elif key == "folder":
        if is_admin_user(request):
            values = [choice["name"] for choice in Folder.objects.matching_name(prefix).picker_page(limit=20)]
        else:
            folders = Folder.tree(public=True, path_pattern=literal_pattern(prefix))
            values = [folder.path_label for folder in folders[:20]]
    elif key == "plugins":
        names = [name for name in snapshot_plugin_choices() if literal_pattern(prefix).search(name)]
        if is_admin_user(request) and not list_url:
            values = names
        else:
            # Probe the plugin index and stop at the first visible success.
            # DISTINCT over all matching archive results delayed completions on
            # large collections. A low-cardinality status index can likewise
            # walk most of the collection before hitting a rare plugin.
            visible = ArchiveResult.objects.filter(
                Exists(scope.filter(pk=OuterRef("snapshot_id"))),
                Case(When(status="succeeded", then=True), default=False),
            )
            values = []
            for name in names:
                if visible.filter(plugin=name).exists():
                    values.append(name)
                    if len(values) == 12:
                        break
    elif key in ("owner", "title", "status", "permissions"):
        field = "crawl__created_by__username" if key == "owner" else key
        values = choices(scope.filter(**{field + "__isnull": False}), field)
    elif key == "domain":
        hosts = scope.exclude(reversed_domain="")
        if prefix:
            hosts = hosts.filter(hosts.domain_rule_q("icontains", prefix))
        keys = hosts.order_by("reversed_domain").values_list("reversed_domain", flat=True).distinct()[:12]
        values = [domain_authority_from_key(k) for k in keys]
    elif key in ("linksto", "linkedfrom"):
        values = choices(scope, "url")
    elif key in ("after", "before", "bookmarked"):
        today = date.today()
        values = [str(today), str(today - timedelta(days=1)), today.strftime("%Y-%m"), str(today.year), str(today.year - 1)]
    elif key == "filetype":
        values = ["html", "png", "pdf", "jpg", "mp4", "webp", "json", "txt", "warc", "gz"]
    else:
        values = []
    return JsonResponse({"values": [v for v in values if v and (key == "domain" or literal_pattern(prefix).search(v))]})
