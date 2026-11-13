"""Domain actions select native snapshots; exported files stay on the server."""

from copy import copy

from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from .scope import normalize_site_scope, site_snapshot_filters
from .views import clone_admin


@clone_admin
@require_POST
def site_actions(request):
    from archivebox.core.exports import ALL_EXPORT_FORMATS, snapshot_export_view

    domains = [request.POST["domain"]] if request.POST.get("domain") else request.POST.getlist("_selected_action")
    try:
        scopes = list(dict.fromkeys(normalize_site_scope(domain) for domain in domains))
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    if not scopes:
        messages.error(request, "Select at least one domain.")
        return redirect("domains:index")
    if request.POST.get("action") != "export" or request.POST.get("export_format") not in ALL_EXPORT_FORMATS:
        return HttpResponseBadRequest("Use the snapshot admin action for re-snapshot or deletion.")
    if len(scopes) > 1 and any("/" in scope for scope in scopes):
        return HttpResponseBadRequest("Select domains without path prefixes for a multi-domain export.")
    selected = copy(request)
    selected.GET = site_snapshot_filters(",".join(scopes))
    selected.path = reverse("admin:core_snapshot_export", args=[request.POST["export_format"]])
    selected.path_info = selected.path
    if request.POST["export_format"] in {"rss", "csv", "jsonl"}:
        selected.method = "GET"
    return snapshot_export_view(selected, format=request.POST["export_format"], session_authorized=True)
