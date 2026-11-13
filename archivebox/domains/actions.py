"""Domain actions select native snapshots; exported files stay on the server."""

from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST
from urllib.parse import urlencode

from archivebox.config import CONSTANTS
from .export_service import FORMATS, launch_export
from .scope import normalize_site_scope
from .views import clone_admin


@clone_admin
@require_POST
def site_actions(request):
    domains = [request.POST["domain"]] if request.POST.get("domain") else request.POST.getlist("_selected_action")
    try:
        scopes = list(dict.fromkeys(normalize_site_scope(domain) for domain in domains))
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    if not scopes:
        messages.error(request, "Select at least one domain.")
        return redirect("domains:index")
    if request.POST.get("action") != "export" or request.POST.get("export_format") not in FORMATS:
        return HttpResponseBadRequest("Use the snapshot admin action for re-snapshot or deletion.")
    if len(scopes) > 1 and any("/" in scope for scope in scopes):
        return HttpResponseBadRequest("Select domains without path prefixes for a multi-domain export.")
    scope = ",".join(scopes)
    try:
        process = launch_export(
            scope=scope,
            directory=request.POST.get("directory") or str(CONSTANTS.DATA_DIR / "exports"),
            format=request.POST["export_format"],
            max_bytes=4 * 1024**3 if request.POST["export_format"] in {"html_zip", "wacz"} else None,
        )
    except (ValueError, OSError) as error:
        messages.error(request, str(error))
        return redirect("domains:index")
    destination = process.cmd[process.cmd.index("--destination") + 1]
    url = reverse("domains:site_export") + "?" + urlencode({"scope": scope})
    messages.success(request, format_html('<a href="{}">Export</a> · <code>{}</code>', url, destination))
    return redirect(url)
