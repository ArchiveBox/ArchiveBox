"""Domain actions select native snapshots; exported files stay on the server."""

from copy import copy

from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import resolve, reverse
from django.views.decorators.http import require_POST

from .scope import normalize_site_scope, site_snapshot_filters
from .views import clone_admin


@clone_admin
@require_POST
def site_actions(request):
    from archivebox.core.exports import ALL_EXPORT_FORMATS, snapshot_export_view

    # Django's native confirmation posts the exact snapshot IDs back to this
    # URL. They are snapshot selections now, not domain strings. Do not expand
    # them to a domain again: newly captured snapshots were not confirmed.
    if request.POST.get("action") == "delete_selected" and request.POST.get("post") == "yes":
        selected = copy(request)
        selected.POST = request.POST.copy()
        selected.POST["select_across"] = "0"
        selected.path = reverse("admin:core_snapshot_changelist")
        selected.path_info = selected.path
        return resolve(selected.path).func(selected)

    row_domain = request.POST.get("delete_domain") or request.POST.get("domain")
    domains = [row_domain] if row_domain else request.POST.getlist("_selected_action")
    try:
        scopes = list(dict.fromkeys(normalize_site_scope(domain) for domain in domains))
    except ValueError:
        return HttpResponseBadRequest("Invalid domain selection.")
    if not scopes:
        messages.error(request, "Select at least one domain.")
        return redirect("domains:index")
    if len(scopes) > 1 and any("/" in scope for scope in scopes):
        return HttpResponseBadRequest("Select domains without path prefixes for a multi-domain export.")
    action = "delete_selected" if request.POST.get("delete_domain") else request.POST.get("action")
    if action in {"resnapshot_snapshot", "update_snapshots", "overwrite_snapshots", "delete_selected"}:
        # Submit through the native admin action, including its permission checks
        # and deletion confirmation. Routing must not depend on a JS module
        # loading before the user clicks a form button.
        selected = copy(request)
        selected.GET = site_snapshot_filters(",".join(scopes))
        selected.POST = request.POST.copy()
        selected.POST["action"] = action
        selected.POST["index"] = "0"
        selected.POST["select_across"] = "1"
        selected.POST.setlist("_selected_action", scopes)
        selected.path = reverse("admin:core_snapshot_changelist")
        selected.path_info = selected.path
        selected.META = {**request.META, "QUERY_STRING": selected.GET.urlencode()}
        return resolve(selected.path).func(selected)
    if action != "export" or request.POST.get("export_format") not in ALL_EXPORT_FORMATS:
        messages.error(request, "Choose an action or export format.")
        return redirect("domains:index")
    selected = copy(request)
    selected.GET = site_snapshot_filters(",".join(scopes))
    selected.path = reverse("admin:core_snapshot_export", args=[request.POST["export_format"]])
    selected.path_info = selected.path
    if request.POST["export_format"] in {"rss", "csv", "jsonl"}:
        selected.method = "GET"
    return snapshot_export_view(selected, format=request.POST["export_format"], session_authorized=True)
