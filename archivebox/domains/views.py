from copy import copy
from functools import wraps
from urllib.parse import urlencode, urlsplit

from django.contrib import messages
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from archivebox.config import CONSTANTS
from archivebox.config.common import get_request_config
from archivebox.machine.models import Machine, Process
from .scope import crawl_site_scope, normalize_site_scope, site_snapshot_filters
from archivebox.core.admin_site import archivebox_admin
from archivebox.core.models import Snapshot
from archivebox.core.permissions import PERMISSIONS_PUBLIC, get_snapshot_permissions
from archivebox.core.routes_util import build_admin_url, build_original_url, build_snapshot_detail_url, is_snapshot_subdomain

from .forms import DomainCrawlForm
from archivebox.crawls.models import Crawl


def clone_admin(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Domain management requires a superuser account.")
        return view(request, *args, **kwargs)

    return wrapped


@clone_admin
@require_http_methods(["GET", "POST"])
def index(request):
    from archivebox.core.exports import ALL_EXPORT_FORMATS

    form = DomainCrawlForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        crawl = form.save(request.user)
        messages.success(request, "Crawl queued.")
        return redirect(crawl.admin_change_url)
    rows = Snapshot.objects.domain_summary()
    query = str(request.GET.get("q", "")).strip()
    if query:
        rows = [row for row in rows if query.casefold() in row["domain"].casefold()]
    ordering = request.GET.get("o", "domain")
    fields = {
        "domain": "domain",
        "count": "snapshot_count",
        "size": "total_size",
        "personas": "persona_count",
        "oldest": "oldest_at",
        "newest": "newest_at",
    }
    if ordering.lstrip("-") not in fields:
        ordering = "domain"
    rows.sort(
        key=lambda row: (row[fields[ordering.lstrip("-")]] is not None, row[fields[ordering.lstrip("-")]], row["domain"]),
        reverse=ordering.startswith("-"),
    )
    domains = Paginator(rows, 50).get_page(request.GET.get("page"))
    ids = {row[key] for row in domains for key in ("oldest_id", "newest_id", "root_id") if row[key]}
    captures = {
        str(snapshot.pk): snapshot
        for snapshot in Snapshot.objects.filter(pk__in=ids)
        .select_related("crawl", "crawl__created_by")
        .prefetch_related("archiveresult_set")
    }
    snapshot_admin = copy(archivebox_admin._registry[Snapshot])
    snapshot_admin.request = request
    config = get_request_config(request)
    for row in domains:
        latest = captures[str(row["newest_id"])]
        earliest = captures[str(row["oldest_id"])]
        root = captures[str(row["root_id"])]
        original = urlsplit(root.url)
        domain_url = build_snapshot_detail_url(root.archive_path_from_db, request=request) + "?header=collapsed"
        # Original-domain replay already rewrites saved links without changing
        # capture bytes. Private captures keep the trusted detail-page auth flow.
        if (
            config.USES_SUBDOMAIN_ROUTING
            and get_snapshot_permissions(root) == PERMISSIONS_PUBLIC
            and original.hostname
            and ":" not in original.hostname
            and original.hostname not in {"admin", "web", "api"}
            and not is_snapshot_subdomain(original.hostname)
            and original.port is None
        ):
            domain_url = build_original_url(
                original.hostname,
                original.path + ("?" + original.query if original.query else ""),
                request=request,
            )
        row.update(
            {
                "domain_url": domain_url,
                "snapshot_url": reverse("admin:core_snapshot_changelist") + "?" + urlencode({"domain": row["scope"]}),
                "persona_url": reverse("admin:personas_persona_changelist") + "?" + urlencode({"snapshot__domain": row["scope"]}),
                "site_url": reverse("domains:site_export") + "?" + urlencode({"scope": row["scope"]}),
                "oldest_url": build_snapshot_detail_url(earliest.archive_path_from_db, request=request),
                "newest_url": build_snapshot_detail_url(latest.archive_path_from_db, request=request),
                "favicon_html": snapshot_admin.url_favicon(root),
                "replay_url": build_admin_url(
                    "/admin/core/snapshot/replay-auth/?"
                    + urlencode(
                        {
                            "snapshot": str(root.pk),
                            "original_domain": original.hostname,
                            "next": original.path + ("?" + original.query if original.query else ""),
                        },
                    ),
                    request=request,
                ),
            },
        )
    headers = []
    for key, label in (
        ("domain", "Domain"),
        ("count", "Snapshots"),
        ("size", "Size"),
        ("personas", "Personas"),
        ("newest", "Latest"),
        ("oldest", "Oldest"),
    ):
        params = request.GET.copy()
        params.pop("page", None)
        params["o"] = "-" + key if ordering == key else key
        headers.append(
            {
                "key": key,
                "label": label,
                "url": "?" + params.urlencode(),
                "active": ordering.lstrip("-") == key,
                "descending": ordering.startswith("-"),
            },
        )
    action_form = ActionForm(initial={"select_across": False})
    action_form.fields["action"].choices = [
        ("", "---------"),
        ("resnapshot_snapshot", "Re-Snapshot"),
        ("update_snapshots", "Retry failed"),
        ("overwrite_snapshots", "Reset and retry"),
        ("delete_selected", "Delete"),
    ]
    return render(
        request,
        "domains/index.html",
        {
            **archivebox_admin.each_context(request),
            "title": "Domains",
            "form": form,
            "domains": domains,
            "domain_scopes": [row["scope"] for row in rows],
            "export_formats": ALL_EXPORT_FORMATS.items(),
            "export_directory": str(CONSTANTS.DATA_DIR / "exports"),
            "domain_headers": headers,
            "domain_query": query,
            "action_form": action_form,
            "actions_selection_counter": True,
            "cl": {
                "result_list": domains.object_list,
                "result_count": len(rows),
                "full_result_count": len(rows),
                "search_fields": ["domain"],
                "query": query,
                "params": request.GET.dict(),
                "opts": {"model_name": "site_domain", "verbose_name_plural": "domains"},
                "model_admin": {"show_search_mode_selector": False},
                "has_filters": False,
            },
            "selection_note": f"0 of {len(domains.object_list)} selected",
            "selection_note_all": f"All {len(rows)} domains selected",
            "module_name": "domains",
            "page_query": urlencode({"q": query, "o": ordering}),
        },
    )


def _site_context(request, clone_id=None):
    crawl = get_object_or_404(Crawl.objects.select_related("persona", "schedule"), pk=clone_id) if clone_id else None
    try:
        scope = crawl_site_scope(crawl) if crawl else normalize_site_scope(request.POST.get("scope") or request.GET.get("scope"))
    except ValueError as error:
        raise Http404(str(error)) from error
    return crawl, scope


def _site_url(name, crawl, scope, **kwargs):
    if crawl:
        return reverse(f"domains:{name}", kwargs={"clone_id": crawl.pk, **kwargs})
    return reverse(f"domains:site_{name}", kwargs=kwargs) + "?" + urlencode({"scope": scope})


@clone_admin
@require_http_methods(["GET"])
def detail(request, clone_id=None):
    _crawl, scope = _site_context(request, clone_id)
    domains = []
    for part in scope.split(","):
        authority = part.split("/", 1)[0]
        domains.append(authority if authority.startswith(("*.", "[")) else "*." + authority)
    return redirect(reverse("admin:core_snapshot_changelist") + "?" + urlencode({"domain": ",".join(domains)}))


@clone_admin
@require_POST
def action(request, clone_id, action):
    crawl = get_object_or_404(Crawl, pk=clone_id, tags_str__regex=r"(^|,)site-clone(,|$)")
    if action == "pause":
        if crawl.pause():
            messages.success(request, "Crawl paused. Saved pages are retained.")
        else:
            messages.info(request, "Crawl cannot be paused in its current state.")
    elif action == "resume":
        if crawl.resume():
            messages.success(request, "Crawl queued to resume with its existing page queue and limits.")
        else:
            messages.info(request, "Crawl cannot be resumed in its current state.")
    return redirect(crawl.admin_change_url)


@clone_admin
@require_http_methods(["GET", "POST"])
def export(request, clone_id=None):
    from archivebox.core.exports import snapshot_export_view

    crawl, scope = _site_context(request, clone_id)
    format = request.POST.get("format") or request.GET.get("format") or "html_zip"
    selected = copy(request)
    selected.GET = site_snapshot_filters(scope)
    selected.path = reverse("admin:core_snapshot_export", args=[format])
    selected.path_info = selected.path
    if format in {"rss", "csv", "jsonl"}:
        selected.method = "GET"
    return snapshot_export_view(
        selected,
        format=format,
        session_authorized=True,
    )


@clone_admin
@require_POST
def replay_settings(request, clone_id=None):
    crawl, scope = _site_context(request, clone_id)
    machine = Machine.current()
    machine.refresh_from_db(fields=["config"])
    machine.config = {**machine.config, "REWRITE_ARCHIVED_LINKS": request.POST.get("rewrite_archived_links") == "on"}
    machine.save(update_fields=["config"])
    return redirect("domains:index")


@clone_admin
@require_POST
def cancel_export(request, process_id, clone_id=None):
    from archivebox.core.exports import snapshot_export_job_view
    from .export_service import export_log_prefix

    _crawl, scope = _site_context(request, clone_id)
    get_object_or_404(
        Process,
        pk=process_id,
        worker_type="site-export",
        pwd__startswith=export_log_prefix(query=site_snapshot_filters(scope), user=request.user),
    )
    return snapshot_export_job_view(request, process_id, action="cancel")
