from functools import wraps
from heapq import nlargest, nsmallest
import logging
from operator import itemgetter
from threading import Thread
from urllib.parse import urlencode, urlsplit

from django.contrib import messages
from django.contrib.admin.helpers import ActionForm
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.cache import cache
from django.core.paginator import Paginator
from django.core import signing
from django.db import close_old_connections, connection, connections
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from archivebox.config import CONSTANTS
from archivebox.config.common import get_request_config
from archivebox.machine.models import Machine
from .scope import crawl_site_scope, normalize_site_scope
from archivebox.core.admin_site import archivebox_admin
from archivebox.core.list_results_util import favicon_results, snapshot_favicon_data
from archivebox.core.models import Snapshot
from archivebox.core.domain_grouping import domain_key_from_url
from archivebox.progressmonitor.collection import _refresh_lock
from archivebox.core.permissions import PERMISSIONS_PUBLIC, get_snapshot_permissions
from archivebox.core.routes_util import build_original_url, build_snapshot_detail_url, build_snapshot_export_urls, is_snapshot_subdomain
from archivebox.personas.models import Persona

from .forms import DomainCrawlForm
from archivebox.crawls.models import Crawl


# Django's local cache handles expiry and refresh throttling. Keep the rows
# directly so paginating does not deserialize the entire collection each time.
_domain_metadata = ("", ())


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


def _store_domain_rows(key, rows):
    global _domain_metadata
    _domain_metadata = (key, rows)
    cache.set(key, True, timeout=3600)


def _domain_rows():
    # Never publish uncommitted metadata to other requests or refresh it using
    # a second connection that cannot see this transaction's writes.
    if connection.in_atomic_block:
        return Snapshot.objects.domain_summary()
    key = f"domain-summary:{CONSTANTS.COLLECTION_ID}"
    cached_key, rows = _domain_metadata
    if cached_key != key or not cache.get(key):
        rows = Snapshot.objects.domain_summary()
        _store_domain_rows(key, rows)
        cache.set(f"{key}:refresh", True, timeout=60)
        return rows

    # Keep the last complete domain list while refreshing its display totals.
    # Use the shared nonblocking gate so statistics scans cannot pile up.
    if _refresh_lock.acquire(blocking=False):
        try:
            refresh_due = cache.add(f"{key}:refresh", True, timeout=60)
        except Exception:
            _refresh_lock.release()
            logging.getLogger(__name__).exception("Could not schedule domain metadata refresh")
            return rows
        if not refresh_due:
            _refresh_lock.release()
            return rows

        def refresh():
            try:
                close_old_connections()
                _store_domain_rows(key, Snapshot.objects.domain_summary())
            except Exception:
                logging.getLogger(__name__).exception("Could not refresh domain metadata")
            finally:
                connections.close_all()
                _refresh_lock.release()

        try:
            Thread(target=refresh, name="domain-summary", daemon=True).start()
        except RuntimeError:
            _refresh_lock.release()
            logging.getLogger(__name__).exception("Could not start domain metadata refresh")
    return rows


def _domain_index_page(request, query, ordering):
    # A page of names comes from the same index and grouping as the sidebar.
    # Sample only the displayed groups and leave the collection total unknown.
    descending = ordering.startswith("-")
    backwards, cursor = False, None
    if token := request.GET.get("cursor"):
        try:
            saved_query, saved_ordering, backwards, cursor = signing.loads(token, salt="archivebox-domain-page")
            if (saved_query, saved_ordering) != (query, ordering):
                raise ValueError
        except (ValueError, signing.BadSignature) as error:
            raise Http404("Invalid domain page cursor") from error

    snapshots = Snapshot.objects.all()
    choices, further = snapshots.domain_choices_page(query, 50, cursor, descending=descending != backwards)
    if backwards:
        choices = dict(reversed(choices.items()))

    def page_url(reverse, boundary):
        token = signing.dumps([query, ordering, reverse, boundary], salt="archivebox-domain-page", compress=True)
        return "?" + urlencode({"q": query, "o": ordering, "cursor": token})

    previous_url = next_url = None
    if choices:
        first = next(iter(choices.values()))[1]
        last = next(reversed(choices.values()))[1]
        if backwards:
            previous_url = page_url(True, further) if further is not None else None
            next_url = page_url(False, [last, []])
        else:
            previous_url = page_url(True, [first, []]) if cursor is not None else None
            next_url = page_url(False, further) if further is not None else None
    return snapshots.domain_page_summary(choices), previous_url, next_url


@clone_admin
@require_http_methods(["GET", "POST"])
def index(request):
    from archivebox.core.exports import ALL_EXPORT_FORMATS

    form = DomainCrawlForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        crawl = form.save(request.user)
        messages.success(request, "Crawl queued.")
        return redirect(crawl.admin_change_url)
    query = request.GET.get("q", "").strip()[:253]
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
    field = fields[ordering.lstrip("-")]
    descending = ordering.startswith("-")
    fragment = request.GET.get("table") == "1"
    loading = not fragment
    domain_total = domain_page = previous_url = next_url = None
    if loading:
        domains = ()
    elif field == "domain":
        domains, previous_url, next_url = _domain_index_page(request, query, ordering)
    else:
        rows = Snapshot.objects.filter_by_domain_search(query).domain_summary() if query else _domain_rows()
        page = Paginator(rows, 50).get_page(request.GET.get("page"))
        domain_total, domain_page = page.paginator.count, page.number
        start, end = max(page.start_index() - 1, 0), page.end_index()
        sort_key = itemgetter(field, "domain")
        if end * 4 < len(rows):
            earliest = nlargest if descending else nsmallest
            domains = earliest(end, rows, key=sort_key)[start:]
        else:
            domains = sorted(rows, key=sort_key, reverse=descending)[start:end]

        def page_url(number):
            return "?" + urlencode({"q": query, "o": ordering, "page": number})

        previous_url = page_url(page.previous_page_number()) if page.has_previous() else None
        next_url = page_url(page.next_page_number()) if page.has_next() else None
    if domains:
        ids = {row[key] for row in domains for key in ("oldest_id", "newest_id", "root_id") if row[key]}
        captures = {
            str(snapshot.pk): snapshot
            for snapshot in Snapshot.objects.filter(pk__in=ids)
            .select_related("crawl", "crawl__created_by")
            .only("id", "url", "timestamp", "fs_version", "permissions", "bookmarked_at", "created_at", "crawl__created_by__username")
            .prefetch_related(
                Prefetch(
                    "archiveresult_set",
                    queryset=favicon_results().filter(snapshot_id__in={row["root_id"] for row in domains}),
                    to_attr="favicon_results",
                ),
            )
        }
        # Captures may have been deleted since the metadata refresh. Their stale
        # display totals are harmless, but must not turn the next page into a 500.
        domains = [row.copy() for row in domains if all(str(row[key]) in captures for key in ("oldest_id", "newest_id", "root_id"))]
        persona_ids = {pk for row in domains for pk in row.get("persona_ids", ())}
        personas = {
            pk: {"name": name, "url": reverse("admin:personas_persona_change", args=[pk])}
            for pk, name in Persona.objects.filter(pk__in=persona_ids).values_list("pk", "name")
        }
        config = get_request_config(request)
        for row in domains:
            latest = captures[str(row["newest_id"])]
            earliest = captures[str(row["oldest_id"])]
            root = captures[str(row["root_id"])]
            try:
                matches = Snapshot.objects.filter_by_domain(row["scope"])
            except ValueError:
                # Match the legacy-host fallback used by domain_page_summary.
                matches = Snapshot.objects.filter(reversed_domain=domain_key_from_url(root.url))
            # Counts use the domain index even when other metadata is sampled
            # or cached. Keep the number identical to the linked snapshot scope.
            row["snapshot_count"] = matches.count()
            snapshot_url = reverse("admin:core_snapshot_changelist") + "?" + urlencode({"domain": row["scope"]})
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
                    "snapshot_url": snapshot_url,
                    "delete_snapshots_url": snapshot_url + "#delete-snapshots",
                    "personas": sorted(
                        (personas[pk] for pk in row.get("persona_ids", ()) if pk in personas),
                        key=lambda item: item["name"].casefold(),
                    ),
                    "oldest_url": build_snapshot_detail_url(earliest.archive_path_from_db, request=request),
                    "newest_url": build_snapshot_detail_url(latest.archive_path_from_db, request=request),
                    "favicon": snapshot_favicon_data(root.pk, root.favicon_results, request=request),
                },
            )
    headers = []
    for key, label in (
        ("domain", "Domain"),
        ("count", "Snapshots"),
        ("size", "Total Size"),
        ("personas", "Personas"),
        ("newest", "Newest Snapshot"),
        ("oldest", "Oldest Snapshot"),
    ):
        params = request.GET.copy()
        for parameter in ("page", "cursor", "table"):
            params.pop(parameter, None)
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
    table_params = {"q": query, "o": ordering, "page": request.GET.get("page"), "cursor": request.GET.get("cursor"), "table": "1"}
    return render(
        request,
        "domains/table.html" if fragment else "domains/index.html",
        {
            **archivebox_admin.each_context(request),
            "title": "Domains",
            "form": form,
            "domains": domains,
            "domain_table_loading": loading,
            "domain_table_url": "?" + urlencode({key: value for key, value in table_params.items() if value}),
            "domain_total": domain_total,
            "domain_page": domain_page,
            "domain_previous_url": previous_url,
            "domain_next_url": next_url,
            "export_formats": ALL_EXPORT_FORMATS.items(),
            "domain_export_urls": build_snapshot_export_urls({}, request=request),
            "export_directory": str(CONSTANTS.DATA_DIR / "exports"),
            "domain_headers": headers,
            "domain_query": query,
            "action_form": action_form,
            "actions_selection_counter": True,
            "cl": {
                "result_list": domains,
                "result_count": domain_total if domain_total is not None else len(domains),
                "display_result_count": domain_total if domain_total is not None else len(domains),
                "result_count_exact": domain_total is not None,
                "full_result_count": domain_total,
                "search_fields": ["domain"],
                "query": query,
                "params": {"q": query, "o": ordering},
                "opts": {"model_name": "site_domain", "verbose_name_plural": "domains"},
                "model_admin": {"show_search_mode_selector": False},
                "has_filters": False,
            },
            "selection_note": f"0 of {len(domains)} selected",
            "selection_note_all": "All matching domains selected",
            "module_name": "domains",
        },
    )


def _site_context(request, clone_id=None):
    crawl = get_object_or_404(Crawl.objects.select_related("persona", "schedule"), pk=clone_id) if clone_id else None
    try:
        scope = crawl_site_scope(crawl) if crawl else normalize_site_scope(request.POST.get("scope") or request.GET.get("scope"))
    except ValueError as error:
        raise Http404(str(error)) from error
    return crawl, scope


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
@require_POST
def replay_settings(request, clone_id=None):
    crawl, scope = _site_context(request, clone_id)
    machine = Machine.current()
    machine.refresh_from_db(fields=["config"])
    machine.config = {**machine.config, "REWRITE_ARCHIVED_LINKS": request.POST.get("rewrite_archived_links") == "on"}
    machine.save(update_fields=["config"])
    return redirect("domains:index")
