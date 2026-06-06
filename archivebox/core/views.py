__package__ = "archivebox.core"

import json
import os
import posixpath
from glob import glob, escape
from django.utils import timezone
from typing import cast
from pathlib import Path
from urllib.parse import quote, urlparse

from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, Http404, HttpResponseForbidden, QueryDict
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views import View
from django.views.generic.list import ListView
from django.views.generic import FormView
from django.db.models import Q
from django.contrib import messages
from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.sessions.models import Session
from django.core import signing
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from admin_data_views.typing import TableContext, ItemContext, SectionData
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink

from abx_plugins.plugins.archivewebpage import replay_preview as archivewebpage_replay

from archivebox.config import CONSTANTS, CONSTANTS_CONFIG, VERSION
from archivebox.config.common import (
    SENSITIVE_CONFIG_VALUE_REDACTED,
    find_config_default,
    find_config_section,
    find_config_source,
    find_config_type,
    get_config,
    get_all_configs,
    get_request_config,
    _plugin_config_properties,
    redact_sensitive_config,
)
from archivebox.config.common import PLUGIN_CONFIG_SCHEMAS
from archivebox.config.configset import BaseConfigSet
from archivebox.misc.paginators import CountlessPaginator
from archivebox.misc.util import (
    base_url,
    filter_queryset_by_uuid_substring,
    htmlencode,
    ts_to_date_str,
    urldecode,
    without_fragment,
)
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.misc.logging_util import printable_filesize
from archivebox.search.config import (
    get_search_mode,
    get_search_mode_backend,
    get_search_mode_base,
    get_search_mode_options,
)
from archivebox.search.query import apply_snapshot_search

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.permissions import (
    PERMISSIONS_PUBLIC,
    can_view_snapshot,
    direct_snapshots_queryset,
    filter_personas_by_permissions,
    get_snapshot_permissions,
    is_admin_user,
    public_snapshots_queryset,
)
from archivebox.core.routes_util import (
    build_admin_url,
    build_snapshot_url,
    build_web_url,
    get_admin_host,
    get_snapshot_host,
    get_snapshot_lookup_key,
    get_web_host,
    host_matches,
)
from archivebox.core.forms import AddLinkForm
from archivebox.plugins.forms import get_plugin_config_binary_urls
from archivebox.crawls.models import Crawl
from archivebox.workers.models import RETRY_AT_MAX
from archivebox.plugins.discovery import discover_plugin_configs
from archivebox.plugins.views import get_config_definition_link
from archivebox.progressmonitor.views import live_progress_view, progress_endpoint


def _files_index_target(snapshot: Snapshot, archivefile: str | None) -> str:
    target = archivefile or ""
    if target == "index.html":
        target = ""
    fullpath = Path(snapshot.output_dir) / target
    if fullpath.is_file():
        target = str(Path(target).parent)
        if target == ".":
            target = ""
    return target


def _find_snapshot_by_ref(snapshot_ref: str) -> Snapshot | None:
    lookup = get_snapshot_lookup_key(snapshot_ref)
    if not lookup:
        return None

    if len(lookup) == 12 and "-" not in lookup:
        return Snapshot.objects.filter(id__endswith=lookup).order_by("-created_at", "-downloaded_at").first()

    try:
        return Snapshot.objects.get(pk=lookup)
    except Snapshot.DoesNotExist:
        try:
            return Snapshot.objects.get(id__startswith=lookup)
        except Snapshot.DoesNotExist:
            return None
        except Snapshot.MultipleObjectsReturned:
            return Snapshot.objects.filter(id__startswith=lookup).first()


def _admin_login_redirect_or_forbidden(request: HttpRequest):
    if get_request_config(request).CONTROL_PLANE_ENABLED:
        return redirect(f"/admin/login/?next={request.path}")
    return HttpResponseForbidden("ArchiveBox is running with the control plane disabled in this security mode.")


REPLAY_AUTH_SALT = "archivebox.private-snapshot-replay"
REPLAY_COOKIE_PREFIX = f"archivebox_replay_{CONSTANTS.COLLECTION_ID}_"
REPLAY_GRANT_MAX_AGE = 60


def _replay_cookie_name(snapshot: Snapshot) -> str:
    return f"{REPLAY_COOKIE_PREFIX}{str(snapshot.id).replace('-', '')[-12:]}"


def _clean_replay_next(path: str | None) -> str:
    """Only allow same-snap relative replay paths; grants must never redirect off-host."""
    path = f"/{(path or 'index.html').lstrip('/')}"
    parsed = urlparse(path)
    if parsed.scheme or parsed.netloc or path.startswith("//"):
        return "/index.html"
    return path


def _replay_payload_is_valid(payload: dict, snapshot: Snapshot) -> bool:
    """A replay cookie is not its own auth source; it must point at a live admin session.

    Replayed pages can execute hostile JS, so admin cookies stay host-only on admin.*.
    The snap host gets only this host-only HttpOnly cookie, and every request checks
    that the original Django session still exists and still belongs to an active staff user.
    Logout, session expiry, user deletion/deactivation, or password auth-hash rotation all
    make the replay cookie inert without needing admin.* to delete a cookie on snap-*.
    """
    if payload.get("snapshot_id") != str(snapshot.id):
        return False
    try:
        session = Session.objects.get(session_key=str(payload.get("session_key") or ""))
        session_data = session.get_decoded()
        user_id = str(session_data.get(SESSION_KEY) or "")
        auth_hash = str(session_data.get(HASH_SESSION_KEY) or "")
        user = get_user_model().objects.get(pk=user_id)
    except Exception:
        return False
    return (
        str(payload.get("user_id")) == user_id
        and str(payload.get("auth_hash") or "") == auth_hash
        and user.is_active
        and user.is_staff
        and auth_hash == user.get_session_auth_hash()
    )


def _has_replay_cookie(request: HttpRequest, snapshot: Snapshot) -> bool:
    value = request.COOKIES.get(_replay_cookie_name(snapshot))
    if not value:
        return False
    try:
        payload = signing.loads(value, salt=REPLAY_AUTH_SALT, max_age=settings.SESSION_COOKIE_AGE)
    except signing.BadSignature:
        return False
    return isinstance(payload, dict) and _replay_payload_is_valid(payload, snapshot)


def _private_snapshot_auth_redirect(request: HttpRequest, snapshot: Snapshot, path: str = "", *, preserve_query: bool = True):
    next_path = _clean_replay_next(path or "index.html")
    if preserve_query and request.META.get("QUERY_STRING"):
        next_path = f"{next_path}?{request.META['QUERY_STRING']}"
    target = build_admin_url(
        f"/admin/core/snapshot/replay-auth/?snapshot={snapshot.id}&next={quote(next_path, safe='')}",
        request=request,
    )
    return redirect(target)


def _replay_auth_response(request: HttpRequest, snapshot: Snapshot):
    try:
        payload = signing.loads(str(request.GET.get("grant") or ""), salt=REPLAY_AUTH_SALT, max_age=REPLAY_GRANT_MAX_AGE)
    except signing.BadSignature:
        return _private_snapshot_auth_redirect(request, snapshot, "index.html", preserve_query=False)

    if not isinstance(payload, dict) or not _replay_payload_is_valid(payload, snapshot):
        return _private_snapshot_auth_redirect(request, snapshot, "index.html", preserve_query=False)

    cookie_value = signing.dumps(payload, salt=REPLAY_AUTH_SALT)
    response = redirect(_clean_replay_next(request.GET.get("next")))
    response.set_cookie(
        _replay_cookie_name(snapshot),
        cookie_value,
        max_age=settings.SESSION_COOKIE_AGE,
        secure=request.is_secure(),
        httponly=True,
        samesite="Lax",
    )
    return response


class SnapshotReplayAuthView(View):
    """Admin-only handoff that lets a snap host mint its own replay cookie.

    admin.* cannot set a host-only cookie for snap-* (browsers forbid that), and
    widening the real Django session cookie to *.archivebox.localhost would let XSS
    in replayed pages hit the admin UI. Instead admin.* proves the user is logged in
    with a short URL grant, then snap-* validates it and sets a snap-host-only cookie.
    """

    def get(self, request: HttpRequest):
        if not is_admin_user(request):
            return redirect(f"{build_admin_url('/admin/login/', request=request)}?next={quote(request.get_full_path(), safe='')}")

        snapshot = _find_snapshot_by_ref(str(request.GET.get("snapshot") or ""))
        if not snapshot:
            raise Http404

        payload = {
            "snapshot_id": str(snapshot.id),
            "user_id": str(request.user.pk),
            "session_key": request.session.session_key,
            "auth_hash": request.user.get_session_auth_hash(),
        }
        grant = signing.dumps(payload, salt=REPLAY_AUTH_SALT)
        next_path = _clean_replay_next(request.GET.get("next"))
        target = build_snapshot_url(str(snapshot.id), "_auth", request=request, config=get_request_config(request))
        return redirect(f"{target}?grant={quote(grant, safe='')}&next={quote(next_path, safe='')}")


class HomepageView(View):
    def get(self, request):
        request_config = get_request_config(request)
        if request.user.is_authenticated and request_config.CONTROL_PLANE_ENABLED:
            return redirect("/admin/core/snapshot/")

        if request_config.PUBLIC_INDEX:
            return redirect("/public")

        return _admin_login_redirect_or_forbidden(request)


class SnapshotView(View):
    # render static html index from filesystem archive/<timestamp>/index.html

    @staticmethod
    def find_snapshots_for_url(path: str):
        """Return a queryset of snapshots matching a URL-ish path. URL only — never tries ID matching.

        Use ``find_snapshots_for_id`` separately if you also want to match by snapshot UUID.
        """

        def _fragmentless_url_query(url: str) -> Q:
            # Use a range comparison (url >= 'canonical#' AND url < 'canonical#\U0010ffff')
            # instead of LIKE/__startswith — SQLite's case-insensitive LIKE bypasses the
            # url index and forces a full-table scan over ~1M rows (~250ms). The range
            # form lets SQLite use a MULTI-INDEX OR and stays under 1ms.
            canonical = without_fragment(url)
            return Q(url=canonical) | (Q(url__gte=f"{canonical}#") & Q(url__lt=f"{canonical}#\U0010ffff"))

        normalized = without_fragment(path)
        if path.startswith(("http://", "https://")):
            # exact url match (indexed) — fastest path
            qs = Snapshot.objects.filter(_fragmentless_url_query(path))
            if qs.exists():
                return qs
            normalized = normalized.split("://", 1)[1]

        # try exact match on full url (without scheme)
        qs = Snapshot.objects.filter(
            _fragmentless_url_query("http://" + normalized) | _fragmentless_url_query("https://" + normalized),
        )
        if qs.exists():
            return qs

        # fall back to match on exact base_url
        base = base_url(normalized)
        qs = Snapshot.objects.filter(
            _fragmentless_url_query("http://" + base) | _fragmentless_url_query("https://" + base),
        )
        if qs.exists():
            return qs

        # fall back to matching base_url as prefix
        return Snapshot.objects.filter(Q(url__startswith="http://" + base) | Q(url__startswith="https://" + base))

    @staticmethod
    def find_snapshots_for_id(slug: str):
        """Return a queryset of snapshots matching a (possibly truncated) UUID via prefix or suffix.

        Strips non-hex characters from ``slug`` (so input with or without hyphens both work).
        Requires at least 8 hex chars — shorter inputs return an empty queryset to avoid
        scanning the entire snapshots table on too-broad matches.
        """
        return filter_queryset_by_uuid_substring(Snapshot.objects.all(), slug)

    @staticmethod
    def render_live_index(request, snapshot):
        TITLE_LOADING_MSG = "Not yet archived..."
        from archivebox.core.widgets import TagEditorWidget

        # Reuse the middleware-attached config; never re-bootstrap from env + plugin
        # schemas just to render a snapshot page (that pays ~30ms for no reason).
        runtime_config = get_request_config(request)
        snapshot._runtime_config = runtime_config
        snapshot_permissions = get_snapshot_permissions(snapshot)
        hidden_card_plugins = {"archivedotorg", "favicon", "title"}
        outputs = [
            out
            for out in snapshot.discover_outputs(include_filesystem_fallback=True)
            if (out.get("size") or 0) > 0 and out.get("name") not in hidden_card_plugins
        ]
        archiveresults = {out["name"]: out for out in outputs}
        hash_index = snapshot.hashes_index
        accounted_entries: set[str] = set()
        for output in outputs:
            output_name = output.get("name") or ""
            if output_name:
                accounted_entries.add(output_name)
            output_path = output.get("path") or ""
            if not output_path:
                continue
            parts = Path(output_path).parts
            if parts:
                accounted_entries.add(parts[0])

        loose_items, failed_items = snapshot.get_detail_page_auxiliary_items(outputs, hidden_card_plugins=hidden_card_plugins)
        preview_priority = [
            "singlefile",
            "screenshot",
            "wget",
            "dom",
            "pdf",
            "readability",
        ]
        preferred_types = tuple(preview_priority)
        output_order = {result_type: index for index, result_type in enumerate(archiveresults.keys())}

        best_result = {"path": "about:blank", "result": None}
        for result_type in preferred_types:
            if result_type in archiveresults:
                best_result = archiveresults[result_type]
                break

        related_snapshots_qs = (
            SnapshotView.find_snapshots_for_url(snapshot.url)
            .select_related("crawl", "crawl__created_by")
            .annotate(
                num_outputs_cached=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.SUCCEEDED),
                num_failures_cached=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.FAILED),
            )
        )
        related_snapshots = list(
            related_snapshots_qs.exclude(id=snapshot.id).order_by("-bookmarked_at", "-created_at", "-timestamp")[:25],
        )
        related_years_map: dict[int, list[Snapshot]] = {}
        for snap in [snapshot, *related_snapshots]:
            snap_dt = snap.bookmarked_at or snap.created_at or snap.downloaded_at
            if not snap_dt:
                continue
            related_years_map.setdefault(snap_dt.year, []).append(snap)
        related_years = []
        for year, snaps in related_years_map.items():
            snaps_sorted = sorted(
                snaps,
                key=lambda s: s.bookmarked_at or s.created_at or s.downloaded_at or timezone.now(),
                reverse=True,
            )
            related_years.append(
                {
                    "year": year,
                    "latest": snaps_sorted[0],
                    "snapshots": snaps_sorted,
                },
            )
        related_years.sort(key=lambda item: item["year"], reverse=True)

        warc_path = next(
            (rel_path for rel_path in hash_index if rel_path.startswith("warc/") and ".warc" in Path(rel_path).name),
            "warc/",
        )

        ordered_outputs = sorted(
            archiveresults.values(),
            key=lambda r: (
                preferred_types.index(r["name"]) if r["name"] in preferred_types else len(preferred_types),
                output_order.get(r["name"], len(output_order)),
            ),
        )
        if best_result["path"] == "about:blank" and ordered_outputs:
            best_result = ordered_outputs[0]
        non_compact_outputs = [out for out in ordered_outputs if not out.get("is_compact") and not out.get("is_metadata")]
        compact_outputs = [out for out in ordered_outputs if out.get("is_compact") or out.get("is_metadata")]
        tag_widget = TagEditorWidget()
        output_size = sum(int(out.get("size") or 0) for out in ordered_outputs)
        has_outputs = bool(ordered_outputs)
        is_archived = has_outputs or snapshot.status == Snapshot.StatusChoices.SEALED
        snapshot_status = str(snapshot.status or "").lower()
        status_label_by_state = {
            "queued": ("queued", "info"),
            "started": ("running", "warning"),
            "paused": ("paused", "default"),
            "sealed": ("archived", "success"),
        }
        if has_outputs and not is_archived:
            status_label, status_color = ("partial", "warning")
        elif has_outputs:
            status_label, status_color = ("archived", "success")
        else:
            status_label, status_color = status_label_by_state.get(snapshot_status, ("not yet archived", "danger"))

        context = {
            "id": str(snapshot.id),
            "snapshot_id": str(snapshot.id),
            "progress_endpoint": progress_endpoint("snapshot", snapshot.id),
            "url": snapshot.url,
            "archive_path": snapshot.archive_path_from_db,
            "title": htmlencode(snapshot.resolved_title or (snapshot.base_url if is_archived else TITLE_LOADING_MSG)),
            "extension": snapshot.extension or "html",
            "tags": snapshot.tags_str() or "untagged",
            "size": printable_filesize(output_size) if output_size else "—",
            "status": status_label,
            "status_color": status_color,
            "snapshot_state": snapshot_status,
            "has_outputs": has_outputs,
            "snapshot_permissions": snapshot_permissions,
            "snapshot_permissions_icon": {
                "public": "👥",
                "unlisted": "🔗",
                "private": "🔒",
            }.get(snapshot_permissions, "👥"),
            "bookmarked_date": snapshot.bookmarked_date,
            "downloaded_datestr": snapshot.downloaded_datestr,
            "num_outputs": snapshot.num_outputs,
            "num_failures": snapshot.num_failures,
            "oldest_archive_date": ts_to_date_str(snapshot.oldest_archive_date),
            "warc_path": warc_path,
            "archiveresults": [*non_compact_outputs, *compact_outputs],
            "best_result": best_result,
            "snapshot": snapshot,  # Pass the snapshot object for template tags
            "CONFIG": runtime_config,
            "related_snapshots": related_snapshots,
            "related_years": related_years,
            "loose_items": loose_items,
            "failed_items": failed_items,
            "title_tags": [{"name": tag.name, "style": tag_widget._tag_style(tag.name)} for tag in snapshot.tags.all().order_by("name")],
        }
        return render(template_name="core/snapshot.html", request=request, context=context)

    def get(self, request, path):
        snapshot = None

        try:
            slug, archivefile = path.split("/", 1)
        except (IndexError, ValueError):
            slug, archivefile = path.split("/", 1)[0], "index.html"

        # slug is a timestamp
        if slug.replace(".", "").isdigit():
            # missing trailing slash -> redirect to index
            if "/" not in path:
                return redirect(f"{path}/index.html")

            try:
                try:
                    snapshot = Snapshot.objects.get(Q(timestamp=slug) | Q(id__startswith=slug))
                    if not can_view_snapshot(request, snapshot):
                        return _private_snapshot_auth_redirect(request, snapshot, archivefile or "index.html")
                    canonical_base = snapshot.url_path
                    if canonical_base != snapshot.legacy_archive_path:
                        target_path = f"/{canonical_base}/{archivefile or 'index.html'}"
                        query = request.META.get("QUERY_STRING")
                        if query:
                            target_path = f"{target_path}?{query}"
                        return redirect(target_path)

                    if request.GET.get("files"):
                        target_path = _files_index_target(snapshot, archivefile)
                        response = serve_static_with_byterange_support(
                            request,
                            target_path,
                            document_root=snapshot.output_dir,
                            show_indexes=True,
                            is_archive_replay=True,
                        )
                    elif archivefile == "index.html":
                        # if they requested snapshot index, serve live rendered template instead of static html
                        response = self.render_live_index(request, snapshot)
                    else:
                        target = build_snapshot_url(str(snapshot.id), archivefile, request=request)
                        query = request.META.get("QUERY_STRING")
                        if query:
                            target = f"{target}?{query}"
                        return redirect(target)
                    response["Link"] = f'<{snapshot.url}>; rel="canonical"'
                    return response
                except Snapshot.DoesNotExist:
                    if Snapshot.objects.filter(timestamp__startswith=slug).exists():
                        raise Snapshot.MultipleObjectsReturned
                    else:
                        raise
            except Snapshot.DoesNotExist:
                # Snapshot does not exist
                return HttpResponse(
                    format_html(
                        (
                            "<center><br/><br/><br/>"
                            "No Snapshot directories match the given timestamp/ID: <code>{}</code><br/><br/>"
                            'You can <a href="/add/" target="_top">add a new Snapshot</a>, or return to the <a href="/" target="_top">Main Index</a>'
                            "</center>"
                        ),
                        slug,
                        path,
                    ),
                    content_type="text/html",
                    status=404,
                )
            except Snapshot.MultipleObjectsReturned:
                snapshot_hrefs = mark_safe("<br/>").join(
                    format_html(
                        '{} <a href="/{}/index.html"><b><code>{}</code></b></a> {} <b>{}</b>',
                        snap.bookmarked_at.strftime("%Y-%m-%d %H:%M:%S"),
                        snap.archive_path,
                        snap.timestamp,
                        snap.url,
                        snap.title_stripped[:64] or "",
                    )
                    for snap in direct_snapshots_queryset(request, Snapshot.objects.filter(timestamp__startswith=slug))
                    .only("url", "timestamp", "title", "bookmarked_at")
                    .order_by("-bookmarked_at")
                )
                return HttpResponse(
                    format_html(
                        ("Multiple Snapshots match the given timestamp/ID <code>{}</code><br/><pre>"),
                        slug,
                    )
                    + snapshot_hrefs
                    + format_html('</pre><br/>Choose a Snapshot to proceed or go back to the <a href="/" target="_top">Main Index</a>'),
                    content_type="text/html",
                    status=404,
                )
            except Http404:
                assert snapshot  # (Snapshot.DoesNotExist is already handled above)

                # Snapshot dir exists but file within does not e.g. 124235.324234/screenshot.png
                return HttpResponse(
                    format_html(
                        (
                            "<html><head>"
                            "<title>Snapshot Not Found</title>"
                            #'<script>'
                            #'setTimeout(() => { window.location.reload(); }, 5000);'
                            #'</script>'
                            "</head><body>"
                            "<center><br/><br/><br/>"
                            f'Snapshot <a href="/{snapshot.archive_path}/index.html" target="_top"><b><code>[{snapshot.timestamp}]</code></b></a>: <a href="{snapshot.url}" target="_blank" rel="noreferrer">{snapshot.url}</a><br/>'
                            f"was queued on {str(snapshot.bookmarked_at).split('.')[0]}, "
                            f'but no files have been saved yet in:<br/><b><a href="/{snapshot.archive_path}/" target="_top"><code>{snapshot.timestamp}</code></a><code>/'
                            "{}"
                            f"</code></b><br/><br/>"
                            "It's possible {} "
                            f"during the last capture on {str(snapshot.bookmarked_at).split('.')[0]},<br/>or that the archiving process has not completed yet.<br/>"
                            f"<pre><code># run this cmd to finish/retry archiving this Snapshot</code><br/>"
                            f'<code style="user-select: all; color: #333">archivebox update -t timestamp {snapshot.timestamp}</code></pre><br/><br/>'
                            '<div class="text-align: left; width: 100%; max-width: 400px">'
                            "<i><b>Next steps:</i></b><br/>"
                            f'- list all the <a href="/{snapshot.archive_path}/" target="_top">Snapshot files <code>.*</code></a><br/>'
                            f'- view the <a href="/{snapshot.archive_path}/index.html" target="_top">Snapshot <code>./index.html</code></a><br/>'
                            f'- go to the <a href="/admin/core/snapshot/{snapshot.pk}/change/" target="_top">Snapshot admin</a> to edit<br/>'
                            f'- go to the <a href="/admin/core/snapshot/?id__exact={snapshot.id}" target="_top">Snapshot actions</a> to re-archive<br/>'
                            '- or return to <a href="/" target="_top">the main index...</a></div>'
                            "</center>"
                            "</body></html>"
                        ),
                        archivefile if str(archivefile) != "None" else "",
                        f"the {archivefile} resource could not be fetched"
                        if str(archivefile) != "None"
                        else "the original site was not available",
                    ),
                    content_type="text/html",
                    status=404,
                )

        # slug is either a URL or a (possibly truncated) snapshot UUID
        def _resolve_snapshots_for_slug(slug: str):
            # full URLs go straight to the url-only path (fast, indexed)
            if "://" in slug:
                return SnapshotView.find_snapshots_for_url(slug)
            # short uuid-shaped slugs (>=8 hex chars after stripping non-hex) try id matching first
            id_qs = SnapshotView.find_snapshots_for_id(slug)
            if id_qs.exists():
                return id_qs
            return SnapshotView.find_snapshots_for_url(slug)

        try:
            try:
                snapshot = direct_snapshots_queryset(request, _resolve_snapshots_for_slug(path)).get()
            except Snapshot.DoesNotExist:
                raise
        except Snapshot.DoesNotExist:
            return HttpResponse(
                format_html(
                    (
                        "<center><br/><br/><br/>"
                        "No Snapshots match the given url: <code>{}</code><br/><br/><br/>"
                        'Return to the <a href="/" target="_top">Main Index</a>, or:<br/><br/>'
                        '+ <i><a href="/add/?url={}" target="_top">Add a new Snapshot for <code>{}</code></a><br/><br/></i>'
                        "</center>"
                    ),
                    base_url(path),
                    path if "://" in path else f"https://{path}",
                    path,
                ),
                content_type="text/html",
                status=404,
            )
        except Snapshot.MultipleObjectsReturned:
            snapshots = direct_snapshots_queryset(request, _resolve_snapshots_for_slug(path))
            snapshot_hrefs = mark_safe("<br/>").join(
                format_html(
                    '{} <code style="font-size: 0.8em">{}</code> <a href="/{}/index.html"><b><code>{}</code></b></a> {} <b>{}</b>',
                    snap.bookmarked_at.strftime("%Y-%m-%d %H:%M:%S"),
                    str(snap.id)[:8],
                    snap.archive_path,
                    snap.timestamp,
                    snap.url,
                    snap.title_stripped[:64] or "",
                )
                for snap in snapshots.only("url", "timestamp", "title", "bookmarked_at").order_by("-bookmarked_at")
            )
            return HttpResponse(
                format_html(
                    ("Multiple Snapshots match the given URL <code>{}</code><br/><pre>"),
                    base_url(path),
                )
                + snapshot_hrefs
                + format_html('</pre><br/>Choose a Snapshot to proceed or go back to the <a href="/" target="_top">Main Index</a>'),
                content_type="text/html",
                status=404,
            )

        target_path = f"/{snapshot.archive_path}/index.html"
        query = request.META.get("QUERY_STRING")
        if query:
            target_path = f"{target_path}?{query}"
        return redirect(target_path)


class SnapshotPathView(View):
    """Serve snapshots by the new URL scheme: /<username>/<YYYYMMDD>/<domain>/<uuid>/..."""

    def get(
        self,
        request,
        username: str,
        date: str | None = None,
        domain: str | None = None,
        snapshot_id: str | None = None,
        path: str = "",
        url: str | None = None,
    ):
        if username == "system":
            return redirect(request.path.replace("/system/", "/web/", 1))

        if date and domain and domain == date:
            raise Http404

        requested_url = url
        if not requested_url and domain and domain.startswith(("http://", "https://")):
            requested_url = domain

        snapshot = None
        snapshots_qs = direct_snapshots_queryset(request, Snapshot.objects.select_related("crawl", "crawl__created_by"))
        if snapshot_id:
            snapshot = _find_snapshot_by_ref(snapshot_id)
            if snapshot and not can_view_snapshot(request, snapshot):
                return _private_snapshot_auth_redirect(request, snapshot, path or "index.html")
        else:
            # fuzzy lookup by date + domain/url (most recent)
            username_lookup = "system" if username == "web" else username
            if requested_url:
                qs = (
                    SnapshotView.find_snapshots_for_url(requested_url)
                    .select_related("crawl", "crawl__created_by")
                    .filter(
                        crawl__created_by__username=username_lookup,
                    )
                )
            else:
                qs = snapshots_qs.filter(crawl__created_by__username=username_lookup)

            if date:
                try:
                    if len(date) == 4:
                        qs = qs.filter(bookmarked_at__year=int(date))
                    elif len(date) == 6:
                        qs = qs.filter(bookmarked_at__year=int(date[:4]), bookmarked_at__month=int(date[4:6]))
                    elif len(date) == 8:
                        qs = qs.filter(
                            bookmarked_at__year=int(date[:4]),
                            bookmarked_at__month=int(date[4:6]),
                            bookmarked_at__day=int(date[6:8]),
                        )
                except ValueError:
                    pass

            if requested_url:
                snapshot = qs.order_by("-bookmarked_at", "-created_at", "-timestamp").first()
            else:
                requested_domain = domain or ""
                if requested_domain.startswith(("http://", "https://")):
                    requested_domain = Snapshot.extract_domain_from_url(requested_domain)
                else:
                    requested_domain = Snapshot.extract_domain_from_url(f"https://{requested_domain}")

                # Prefer exact domain matches
                matches = [
                    s for s in qs.order_by("-bookmarked_at", "-created_at") if Snapshot.extract_domain_from_url(s.url) == requested_domain
                ]
                snapshot = matches[0] if matches else qs.order_by("-bookmarked_at", "-created_at", "-timestamp").first()

        if not snapshot:
            return HttpResponse(
                format_html(
                    (
                        "<center><br/><br/><br/>"
                        "No Snapshots match the given id or url: <code>{}</code><br/><br/><br/>"
                        'Return to the <a href="/" target="_top">Main Index</a>'
                        "</center>"
                    ),
                    snapshot_id or requested_url or domain,
                ),
                content_type="text/html",
                status=404,
            )

        canonical_base = snapshot.url_path
        if date:
            requested_base = f"{username}/{date}/{domain or url or ''}"
        else:
            requested_base = f"{username}/{domain or url or ''}"
        if snapshot_id:
            requested_base = f"{requested_base}/{snapshot_id}"
        if canonical_base != requested_base:
            target = f"/{canonical_base}/{path or 'index.html'}"
            query = request.META.get("QUERY_STRING")
            if query:
                target = f"{target}?{query}"
            return redirect(target)

        archivefile = path or "index.html"
        if archivefile != "index.html" and not request.GET.get("files"):
            target = build_snapshot_url(str(snapshot.id), archivefile, request=request)
            query = request.META.get("QUERY_STRING")
            if query:
                target = f"{target}?{query}"
            return redirect(target)

        if request.GET.get("files"):
            target_path = _files_index_target(snapshot, archivefile)
            return serve_static_with_byterange_support(
                request,
                target_path,
                document_root=snapshot.output_dir,
                show_indexes=True,
                is_archive_replay=True,
            )

        if archivefile == "index.html":
            return SnapshotView.render_live_index(request, snapshot)

        return serve_static_with_byterange_support(
            request,
            archivefile,
            document_root=snapshot.output_dir,
            show_indexes=True,
            is_archive_replay=True,
        )


def _safe_archive_relpath(path: str) -> str | None:
    if not path:
        return ""
    cleaned = posixpath.normpath(path)
    cleaned = cleaned.lstrip("/")
    if cleaned.startswith("..") or "/../" in f"/{cleaned}/":
        return None
    return cleaned


def _coerce_sort_timestamp(value: str | float | None) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _snapshot_sort_key(match_path: str, cache: dict[str, float]) -> tuple[float, str]:
    parts = Path(match_path).parts
    date_str = ""
    snapshot_id = ""
    try:
        idx = parts.index("snapshots")
        date_str = parts[idx + 1]
        snapshot_id = parts[idx + 3]
    except Exception:
        return (_coerce_sort_timestamp(date_str), match_path)

    if snapshot_id not in cache:
        snapshot = Snapshot.objects.filter(id=snapshot_id).only("bookmarked_at", "created_at", "downloaded_at", "timestamp").first()
        if snapshot:
            snap_dt = snapshot.bookmarked_at or snapshot.created_at or snapshot.downloaded_at
            cache[snapshot_id] = snap_dt.timestamp() if snap_dt else _coerce_sort_timestamp(snapshot.timestamp)
        else:
            cache[snapshot_id] = _coerce_sort_timestamp(date_str)

    return (cache[snapshot_id], match_path)


def _snapshot_id_from_replay_path(path: Path) -> str | None:
    parts = path.parts
    try:
        responses_idx = parts.index("responses")
    except ValueError:
        return None
    return parts[responses_idx - 1] if responses_idx > 0 else None


def _replay_path_visible(request: HttpRequest, path: Path) -> bool:
    snapshot_id = _snapshot_id_from_replay_path(path)
    if not snapshot_id:
        return False
    snapshot = Snapshot.objects.filter(id=snapshot_id).select_related("crawl", "crawl__created_by").first()
    if not snapshot or (not can_view_snapshot(request, snapshot) and not _has_replay_cookie(request, snapshot)):
        return False
    request.archivebox_config = get_request_config(request, resolve_plugins=False)
    return True


def _latest_response_match(request: HttpRequest, domain: str, rel_path: str, *, data_root: Path) -> tuple[Path, Path] | None:
    if not domain or not rel_path:
        return None
    domain = domain.split(":", 1)[0].lower()
    # TODO: optimize by querying output_files in DB instead of globbing filesystem
    escaped_domain = escape(domain)
    escaped_path = escape(rel_path)
    pattern = str(data_root / "*" / "snapshots" / "*" / escaped_domain / "*" / "responses" / escaped_domain / escaped_path)
    matches = glob(pattern)
    if not matches:
        return None

    sort_cache: dict[str, float] = {}
    best_paths = sorted(matches, key=lambda match_path: _snapshot_sort_key(match_path, sort_cache), reverse=True)
    best_path = next((Path(match_path) for match_path in best_paths if _replay_path_visible(request, Path(match_path))), None)
    if best_path is None:
        return None
    parts = best_path.parts
    try:
        responses_idx = parts.index("responses")
    except ValueError:
        return None
    responses_root = Path(*parts[: responses_idx + 1])
    rel_to_root = Path(*parts[responses_idx + 1 :])
    return responses_root, rel_to_root


def _latest_responses_root(request: HttpRequest, domain: str, *, data_root: Path) -> Path | None:
    if not domain:
        return None
    domain = domain.split(":", 1)[0].lower()
    escaped_domain = escape(domain)
    pattern = str(data_root / "*" / "snapshots" / "*" / escaped_domain / "*" / "responses" / escaped_domain)
    matches = glob(pattern)
    if not matches:
        return None

    sort_cache: dict[str, float] = {}
    best_paths = sorted(matches, key=lambda match_path: _snapshot_sort_key(match_path, sort_cache), reverse=True)
    return next((Path(match_path) for match_path in best_paths if _replay_path_visible(request, Path(match_path))), None)


def _latest_snapshot_for_domain(request: HttpRequest, domain: str) -> Snapshot | None:
    if not domain:
        return None

    requested_domain = domain.split(":", 1)[0].lower()
    snapshots = direct_snapshots_queryset(
        request,
        SnapshotView.find_snapshots_for_url(f"https://{requested_domain}"),
    ).order_by("-bookmarked_at", "-created_at", "-timestamp")
    for snapshot in snapshots:
        if Snapshot.extract_domain_from_url(snapshot.url).lower() == requested_domain:
            return snapshot
    return None


def _original_request_url(domain: str, path: str = "", query_string: str = "") -> str:
    normalized_domain = (domain or "").split(":", 1)[0].lower()
    normalized_path = (path or "").lstrip("/")
    if normalized_path in ("", "index.html"):
        normalized_path = ""
    target = f"https://{normalized_domain}"
    if normalized_path:
        target = f"{target}/{normalized_path}"
    if query_string:
        target = f"{target}?{query_string}"
    return target


def _serve_responses_path(request, responses_root: Path, rel_path: str, show_indexes: bool):
    candidates: list[str] = []
    rel_path = rel_path or ""
    if rel_path.endswith("/"):
        rel_path = f"{rel_path}index.html"
    if "." not in Path(rel_path).name:
        candidates.append(f"{rel_path.rstrip('/')}/index.html")
    candidates.append(rel_path)

    for candidate in candidates:
        try:
            return serve_static_with_byterange_support(
                request,
                candidate,
                document_root=str(responses_root),
                show_indexes=show_indexes,
                is_archive_replay=True,
            )
        except Http404:
            pass

    if rel_path.endswith("index.html"):
        rel_dir = rel_path[: -len("index.html")]
        try:
            return serve_static_with_byterange_support(
                request,
                rel_dir,
                document_root=str(responses_root),
                show_indexes=True,
                is_archive_replay=True,
            )
        except Http404:
            return None
    return None


def _serve_snapshot_replay(request: HttpRequest, snapshot: Snapshot, path: str = ""):
    rel_path = path or ""
    request_config = get_request_config(
        request,
        resolve_plugins=rel_path.startswith("replay/") or rel_path == "replay",
    )
    request.archivebox_config = request_config
    request.archivebox_snapshot_url = snapshot.url
    snapshot._runtime_config = request_config

    if rel_path.startswith("replay/") or rel_path == "replay":
        response = archivewebpage_replay.serve_replay_asset_response(rel_path, request_config, HttpResponse)
        if response is not None:
            return response

    if rel_path == "progress.json":
        # Host routing forwards every snap-* path to SnapshotHostView, so we forward
        # /progress.json on through to the same view used everywhere else. The caller
        # passes snapshot_id explicitly in the query string — we don't read it from the
        # subdomain (this keeps the endpoint identical across all security modes).
        return live_progress_view(request)

    is_directory_request = bool(path) and path.endswith("/")
    show_indexes = bool(request.GET.get("files")) or (request_config.USES_SUBDOMAIN_ROUTING and is_directory_request)
    if not show_indexes and (not rel_path or rel_path == "index.html"):
        return SnapshotView.render_live_index(request, snapshot)

    if not rel_path or rel_path.endswith("/"):
        if show_indexes:
            rel_path = rel_path.rstrip("/")
        else:
            rel_path = f"{rel_path}index.html"
    rel_path = _safe_archive_relpath(rel_path)
    if rel_path is None:
        raise Http404

    try:
        return serve_static_with_byterange_support(
            request,
            rel_path,
            document_root=snapshot.output_dir,
            show_indexes=show_indexes,
            is_archive_replay=True,
        )
    except Http404:
        pass

    host = urlparse(snapshot.url).hostname or snapshot.domain
    responses_root = Path(snapshot.output_dir) / "responses" / host
    if responses_root.exists():
        response = _serve_responses_path(request, responses_root, rel_path, show_indexes)
        if response is not None:
            return response

    raise Http404


def _serve_original_domain_replay(request: HttpRequest, domain: str, path: str = ""):
    request_config = get_request_config(request, resolve_plugins=False)
    request.archivebox_config = request_config
    requested_root_index = path in ("", "index.html") or path.endswith("/")
    rel_path = path or ""
    if not rel_path or rel_path.endswith("/"):
        rel_path = f"{rel_path}index.html"
    rel_path = _safe_archive_relpath(rel_path)
    if rel_path is None:
        raise Http404

    domain = domain.lower()
    match = _latest_response_match(request, domain, rel_path, data_root=CONSTANTS.USERS_DIR)
    if not match and "." not in Path(rel_path).name:
        index_path = f"{rel_path.rstrip('/')}/index.html"
        match = _latest_response_match(request, domain, index_path, data_root=CONSTANTS.USERS_DIR)
    if not match and "." not in Path(rel_path).name:
        html_path = f"{rel_path}.html"
        match = _latest_response_match(request, domain, html_path, data_root=CONSTANTS.USERS_DIR)

    show_indexes = bool(request.GET.get("files"))
    if match:
        responses_root, rel_to_root = match
        response = _serve_responses_path(request, responses_root, str(rel_to_root), show_indexes)
        if response is not None:
            return response

    responses_root = _latest_responses_root(request, domain, data_root=CONSTANTS.USERS_DIR)
    if responses_root:
        response = _serve_responses_path(request, responses_root, rel_path, show_indexes)
        if response is not None:
            return response

    if requested_root_index and not show_indexes:
        snapshot = _latest_snapshot_for_domain(request, domain)
        if snapshot:
            return SnapshotView.render_live_index(request, snapshot)

    if request_config.PUBLIC_ADD_VIEW or request.user.is_authenticated:
        target_url = _original_request_url(domain, path, request.META.get("QUERY_STRING", ""))
        return redirect(build_web_url(f"/web/{quote(target_url, safe=':/')}"))

    raise Http404


class SnapshotHostView(View):
    """Serve snapshot directory contents on <snapshot-subdomain>.<listen_host>/<path>."""

    def get(self, request, snapshot_id: str, path: str = ""):
        request_config = get_request_config(request)
        snapshot = _find_snapshot_by_ref(snapshot_id)

        if not snapshot:
            raise Http404
        if path == "_auth":
            return _replay_auth_response(request, snapshot)
        if not can_view_snapshot(request, snapshot) and not _has_replay_cookie(request, snapshot):
            return _private_snapshot_auth_redirect(request, snapshot, path)

        canonical_host = get_snapshot_host(str(snapshot.id), config=request_config)
        if not host_matches(request.get_host(), canonical_host):
            target = build_snapshot_url(str(snapshot.id), path, request=request, config=request_config)
            if request.META.get("QUERY_STRING"):
                target = f"{target}?{request.META['QUERY_STRING']}"
            return redirect(target)

        return _serve_snapshot_replay(request, snapshot, path)


class SnapshotReplayView(View):
    """Serve snapshot directory contents on a one-domain replay path."""

    def get(self, request, snapshot_id: str, path: str = ""):
        snapshot = _find_snapshot_by_ref(snapshot_id)
        if not snapshot:
            raise Http404
        if path == "_auth":
            return _replay_auth_response(request, snapshot)
        if not can_view_snapshot(request, snapshot) and not _has_replay_cookie(request, snapshot):
            return _private_snapshot_auth_redirect(request, snapshot, path)

        return _serve_snapshot_replay(request, snapshot, path)


class OriginalDomainHostView(View):
    """Serve responses from the most recent snapshot when using <domain>.<listen_host>/<path>."""

    def get(self, request, domain: str, path: str = ""):
        return _serve_original_domain_replay(request, domain, path)


class OriginalDomainReplayView(View):
    """Serve original-domain replay content on a one-domain replay path."""

    def get(self, request, domain: str, path: str = ""):
        return _serve_original_domain_replay(request, domain, path)


class PublicIndexView(ListView):
    template_name = "public_index.html"
    model = Snapshot
    ordering = ["-bookmarked_at", "-created_at"]
    paginator_class = CountlessPaginator

    def get_paginate_by(self, queryset):
        runtime_config = self.__dict__.get("runtime_config")
        if runtime_config is None:
            self.runtime_config = runtime_config = get_request_config(self.request, resolve_plugins=False)
        return runtime_config.SNAPSHOTS_PER_PAGE

    def get_context_data(self, **kwargs):
        runtime_config = self.__dict__.get("runtime_config")
        if runtime_config is None:
            self.runtime_config = runtime_config = get_request_config(self.request, resolve_plugins=False)
        search_mode = get_search_mode(self.request.GET.get("search_mode"), config=runtime_config)
        search_mode_backend = get_search_mode_backend(search_mode, config=runtime_config)
        context = {
            **super().get_context_data(**kwargs),
            "VERSION": VERSION,
            "CONFIG": runtime_config,
            "COMMIT_HASH": runtime_config.COMMIT_HASH,
            "FOOTER_INFO": runtime_config.FOOTER_INFO,
            "WEB_BASE_URL": build_web_url(request=self.request, config=runtime_config),
            "search_mode": search_mode,
            "search_mode_options": get_search_mode_options(config=runtime_config),
        }
        context["show_search_index_hint"] = bool(
            self.request.GET.get("q")
            and get_search_mode_base(search_mode, config=runtime_config) == "deep"
            and search_mode_backend
            and context["paginator"].count == 0,
        )
        snapshots = list(context.get("object_list") or ())
        icons_by_snapshot: dict[str, set[str]] = {str(snapshot.id): set() for snapshot in snapshots}
        progress_by_snapshot: dict[str, dict[str, int]] = {
            str(snapshot.id): {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "running": 0,
                "skipped": 0,
                "noresults": 0,
            }
            for snapshot in snapshots
        }
        if icons_by_snapshot:
            for snapshot_id, plugin, status in (
                ArchiveResult.objects.filter(
                    snapshot_id__in=icons_by_snapshot.keys(),
                )
                .exclude(plugin="")
                .values_list("snapshot_id", "plugin", "status")
                .iterator(chunk_size=1000)
            ):
                snapshot_key = str(snapshot_id)
                progress = progress_by_snapshot[snapshot_key]
                progress["total"] += 1
                if status == ArchiveResult.StatusChoices.SUCCEEDED:
                    icons_by_snapshot[snapshot_key].add(plugin)
                    progress["succeeded"] += 1
                elif status == ArchiveResult.StatusChoices.FAILED:
                    progress["failed"] += 1
                elif status == ArchiveResult.StatusChoices.STARTED:
                    progress["running"] += 1
                elif status == ArchiveResult.StatusChoices.SKIPPED:
                    progress["skipped"] += 1
                elif status == ArchiveResult.StatusChoices.NORESULTS:
                    progress["noresults"] += 1

        for snapshot in snapshots:
            snapshot._icons_compact = True
            snapshot._icons_archive_results = icons_by_snapshot.get(str(snapshot.id), set())
            snapshot._icons_progress_stats = progress_by_snapshot.get(str(snapshot.id), {})
            snapshot._is_archived_cached = bool(snapshot.downloaded_at or snapshot.status == Snapshot.StatusChoices.SEALED)
        context["object_list"] = snapshots
        return context

    def get_queryset(self, **kwargs):
        qs = (
            public_snapshots_queryset(super().get_queryset(**kwargs))
            .select_related("crawl__created_by")
            .annotate(
                num_outputs_cached=ArchiveResult.snapshot_count_expr(status=ArchiveResult.StatusChoices.SUCCEEDED),
            )
            .prefetch_related(
                "tags",
            )
        )
        query = self.request.GET.get("q", default="").strip()

        if not query:
            return qs

        runtime_config = self.__dict__.get("runtime_config")
        search_mode = get_search_mode(self.request.GET.get("search_mode"), config=runtime_config)
        try:
            return apply_snapshot_search(
                qs,
                query,
                search_mode=search_mode,
                config=runtime_config,
                ordering=self.ordering,
            )
        except Exception as err:
            print(f"[!] Error while using search backend: {err.__class__.__name__} {err}")
            if get_search_mode_backend(search_mode, config=runtime_config):
                return qs.none()
            return apply_snapshot_search(qs, query, search_mode="meta", config=runtime_config)

    def get(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return redirect("/admin/core/snapshot/")
        if get_request_config(self.request).PUBLIC_INDEX:
            response = super().get(*args, **kwargs)
            return response
        else:
            return _admin_login_redirect_or_forbidden(self.request)


@method_decorator(csrf_exempt, name="dispatch")
class AddView(UserPassesTestMixin, FormView):
    template_name = "add.html"
    form_class = AddLinkForm

    def get_initial(self):
        """Prefill the AddLinkForm with the 'url' GET parameter"""
        if self.request.method == "GET":
            url = self.request.GET.get("url", None)
            if url:
                return {"url": url if "://" in url else f"https://{url}"}

        return super().get_initial()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def test_func(self):
        return get_request_config(self.request).PUBLIC_ADD_VIEW or self.request.user.is_authenticated

    def _can_override_crawl_config(self) -> bool:
        return is_admin_user(self.request)

    def _get_custom_config_overrides(self, form: AddLinkForm) -> dict:
        custom_config = form.cleaned_data.get("config") or {}

        if not isinstance(custom_config, dict):
            return {}

        if not self._can_override_crawl_config():
            return {}

        return {str(key): value for key, value in custom_config.items() if not str(key).endswith("_BINARY")}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request_config = get_request_config(self.request, resolve_plugins=True)
        required_search_plugin = f"search_backend_{request_config.SEARCH_BACKEND_ENGINE}".strip()
        can_override_crawl_config = self._can_override_crawl_config()
        plugin_configs = discover_plugin_configs() if can_override_crawl_config else {}
        public_persona_config_keys = {
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS",
            "DELETE_AFTER",
            "ONLY_NEW",
            "PERMISSIONS",
            "TIMEOUT",
        }
        persona_queryset = context["form"].fields["persona"].queryset
        if not can_override_crawl_config:
            persona_queryset = filter_personas_by_permissions(persona_queryset, {PERMISSIONS_PUBLIC})
        persona_config_map = {}
        for persona in persona_queryset.order_by("name"):
            effective_config = get_config(persona=persona)
            effective_config_redacted = get_config(persona=persona, redact_sensitive=True).model_dump(mode="json")
            if can_override_crawl_config:
                raw_config = redact_sensitive_config(persona.config or {})
                effective_config_json = effective_config_redacted
                binary_urls = get_plugin_config_binary_urls(effective_config)
            else:
                raw_config = {}
                effective_config_json = {key: effective_config_redacted.get(key) for key in public_persona_config_keys}
                binary_urls = {}
            persona_config_map[persona.name] = {
                "config": raw_config,
                "effective_config": effective_config_json,
                "binary_urls": binary_urls,
            }
        recent_personas = list(persona_queryset.order_by("-created_at", "name")[:5])
        plugin_dependency_map = {}
        if can_override_crawl_config:
            plugin_dependency_map = {
                plugin_name: [
                    str(required_plugin).strip()
                    for required_plugin in (schema.get("required_plugins") or [])
                    if str(required_plugin).strip()
                ]
                for plugin_name, schema in plugin_configs.items()
                if isinstance(schema.get("required_plugins"), list) and schema.get("required_plugins")
            }
        return {
            **context,
            "title": "Create Crawl",
            # We can't just call request.build_absolute_uri in the template, because it would include query parameters
            "absolute_add_path": self.request.build_absolute_uri(self.request.path),
            "web_base_url": build_web_url("", request=self.request),
            "VERSION": VERSION,
            "FOOTER_INFO": request_config.FOOTER_INFO,
            "required_search_plugin": required_search_plugin,
            "plugin_dependency_map_json": json.dumps(plugin_dependency_map, sort_keys=True),
            "persona_config_map_json": json.dumps(persona_config_map, sort_keys=True, default=str),
            "recent_personas": recent_personas,
            "can_override_crawl_config": can_override_crawl_config,
            "stdout": "",
        }

    def _create_crawl_from_form(self, form, *, created_by_id=None) -> Crawl:
        urls = form.cleaned_data["url"]
        print(f"[+] Adding URL: {urls}")

        # Extract all form fields
        tag = form.cleaned_data["tag"]
        depth = int(form.cleaned_data["depth"])
        max_urls = int(form.cleaned_data.get("max_urls") or 0)
        crawl_max_size = int(form.cleaned_data.get("crawl_max_size") or 0)
        crawl_timeout = int(form.cleaned_data.get("crawl_timeout") or 0)
        timeout = form.cleaned_data.get("timeout")
        snapshot_max_size = int(form.cleaned_data.get("snapshot_max_size") or 0)
        delete_after = str(form.cleaned_data.get("delete_after") or "0").strip() or "0"
        crawl_max_concurrent_snapshots = int(form.cleaned_data["crawl_max_concurrent_snapshots"])
        permissions = str(form.cleaned_data.get("permissions") or "public").strip().lower()
        can_override_crawl_config = self._can_override_crawl_config()
        plugins = ",".join(form.cleaned_data.get("plugins", [])) if can_override_crawl_config else ""
        schedule = form.cleaned_data.get("schedule", "").strip() if can_override_crawl_config else ""
        persona = form.cleaned_data.get("persona")
        start_paused = form.cleaned_data.get("start_paused", False) if can_override_crawl_config else False
        notes = form.cleaned_data.get("notes", "")
        url_filters = form.cleaned_data.get("url_filters") or {}
        plugin_config = form.cleaned_data.get("plugin_config") or {}
        if not isinstance(plugin_config, dict):
            plugin_config = {}
        if not can_override_crawl_config:
            plugin_config = {}
        custom_config = self._get_custom_config_overrides(form)
        custom_config.pop("DEFAULT_PERSONA", None)
        custom_config.pop("PERMISSIONS", None)
        if persona:
            persona.ensure_dirs()

        from archivebox.config.permissions import HOSTNAME

        if created_by_id is None:
            if self.request.user.is_authenticated:
                created_by_id = self.request.user.pk
            else:
                from archivebox.base_models.models import get_or_create_system_user_pk

                created_by_id = get_or_create_system_user_pk()

        created_by_name = self.request.user.username if self.request.user.is_authenticated else "web"

        # 1. save the provided urls to sources/2024-11-05__23-59-59__web_ui_add_by_user_<user_pk>.txt
        sources_file = CONSTANTS.SOURCES_DIR / f"{timezone.now().strftime('%Y-%m-%d__%H-%M-%S')}__web_ui_add_by_user_{created_by_id}.txt"
        sources_file.parent.mkdir(parents=True, exist_ok=True)
        sources_file.write_text(urls if isinstance(urls, str) else "\n".join(urls))

        # 2. create a new Crawl with the URLs from the file
        timestamp = timezone.now().strftime("%Y-%m-%d__%H-%M-%S")
        urls_content = sources_file.read_text()
        # Store explicit crawl-scoped overrides; Crawl.save() freezes them
        # over the resolved persona/user/machine defaults at creation time.
        config = {}
        if plugins:
            config["PLUGINS"] = plugins
        effective_config = get_config(persona=persona) if persona else get_config()
        if crawl_max_concurrent_snapshots != int(effective_config.CRAWL_MAX_CONCURRENT_SNAPSHOTS):
            config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] = crawl_max_concurrent_snapshots
        if delete_after != str(effective_config.DELETE_AFTER):
            config["DELETE_AFTER"] = delete_after
        config["PERMISSIONS"] = permissions
        if max_urls:
            config["CRAWL_MAX_URLS"] = max_urls
        if crawl_max_size:
            config["CRAWL_MAX_SIZE"] = crawl_max_size
        if crawl_timeout:
            config["CRAWL_TIMEOUT"] = crawl_timeout
        if timeout is not None and int(timeout) != int(effective_config.TIMEOUT):
            config["TIMEOUT"] = int(timeout)
        if snapshot_max_size:
            config["SNAPSHOT_MAX_SIZE"] = snapshot_max_size

        # Merge custom config overrides
        config.update(plugin_config)
        config.update(custom_config)
        if bool(url_filters.get("only_new")) != bool(effective_config.ONLY_NEW):
            config["ONLY_NEW"] = bool(url_filters.get("only_new"))
        if url_filters.get("allowlist"):
            config["URL_ALLOWLIST"] = url_filters["allowlist"]
        if url_filters.get("denylist"):
            config["URL_DENYLIST"] = url_filters["denylist"]

        crawl = Crawl.create_scheduler_row(
            urls=urls_content,
            max_depth=depth,
            tags_str=tag,
            notes=notes,
            label=f"{created_by_name}@{HOSTNAME}{self.request.path} {timestamp}",
            created_by_id=created_by_id,
            config=config,
            persona_id=persona.id if persona else None,
            status=Crawl.StatusChoices.PAUSED if start_paused else Crawl.StatusChoices.QUEUED,
            retry_at=RETRY_AT_MAX if start_paused else timezone.now(),
        )

        # 3. create a CrawlSchedule if schedule is provided
        if schedule:
            from archivebox.crawls.models import CrawlSchedule

            crawl_schedule = CrawlSchedule.objects.create(
                template=crawl,
                schedule=schedule,
                is_enabled=True,
                config=config,
                label=crawl.label,
                notes=f"Auto-created from add page. {notes}".strip(),
                created_by_id=created_by_id,
            )
            crawl.schedule = crawl_schedule
            crawl.safe_update({"schedule": crawl_schedule}, refresh=False)

        if not start_paused:
            from archivebox.services.runner import ensure_background_runner

            ensure_background_runner()

        return crawl

    def form_valid(self, form):
        crawl = self._create_crawl_from_form(form)

        urls = form.cleaned_data["url"]
        schedule = form.cleaned_data.get("schedule", "").strip()
        rough_url_count = len([url for url in urls.splitlines() if url.strip()])

        # Build success message with schedule link if created
        schedule_msg = ""
        if schedule and crawl.schedule_id:
            schedule_msg = f" and <a href='{crawl.schedule.admin_change_url}'>scheduled to repeat {schedule}</a>"

        messages.success(
            self.request,
            mark_safe(
                f"Created crawl with {rough_url_count} starting URL(s){schedule_msg}. Snapshots will be created and archived in the background. <a href='{crawl.admin_change_url}'>View Crawl →</a>",
            ),
        )

        # Orchestrator (managed by supervisord) will pick up the queued crawl
        return redirect(crawl.admin_change_url)


class WebAddView(AddView):
    def _latest_snapshot_for_url(self, requested_url: str):
        return (
            direct_snapshots_queryset(
                self.request,
                SnapshotView.find_snapshots_for_url(requested_url),
            )
            .order_by("-bookmarked_at", "-created_at", "-timestamp")
            .first()
        )

    def _normalize_add_url(self, requested_url: str) -> str:
        if requested_url.startswith(("http://", "https://")):
            return requested_url
        return f"https://{requested_url}"

    def dispatch(self, request, *args, **kwargs):
        requested_url = urldecode(kwargs.get("url", "") or "")
        if requested_url:
            snapshot = self._latest_snapshot_for_url(requested_url)
            if snapshot:
                return redirect(f"/{snapshot.url_path}")

        request_host = (request.get_host() or "").lower()
        if request.user.is_authenticated and not get_request_config(request).PUBLIC_ADD_VIEW and host_matches(request_host, get_web_host()):
            return redirect(build_admin_url(request.get_full_path(), request=request))

        if not self.test_func():
            if host_matches(request_host, get_web_host()):
                return redirect(build_admin_url(request.get_full_path(), request=request))
            if host_matches(request_host, get_admin_host()):
                next_url = quote(request.get_full_path(), safe="/:?=&")
                return redirect(f"{build_admin_url('/admin/login/', request=request)}?next={next_url}")
            return HttpResponse(
                format_html(
                    (
                        "<center><br/><br/><br/>"
                        "No Snapshots match the given url: <code>{}</code><br/><br/><br/>"
                        'Return to the <a href="/" target="_top">Main Index</a>'
                        "</center>"
                    ),
                    requested_url or "",
                ),
                content_type="text/html",
                status=404,
            )

        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, *args: object, **kwargs: object):
        requested_url = urldecode(str(kwargs.get("url") or (args[0] if args else "")))
        if not requested_url:
            raise Http404

        snapshot = self._latest_snapshot_for_url(requested_url)
        if snapshot:
            return redirect(f"/{snapshot.url_path}")

        add_url = self._normalize_add_url(requested_url)
        assert self.form_class is not None
        defaults_form = self.form_class()
        form_data = QueryDict(mutable=True)
        form_data.update(
            {
                "url": add_url,
                "depth": defaults_form.fields["depth"].initial or "0",
                "max_urls": defaults_form.fields["max_urls"].initial or 0,
                "crawl_max_size": defaults_form.fields["crawl_max_size"].initial or "0",
                "crawl_timeout": defaults_form.fields["crawl_timeout"].initial or 0,
                "timeout": defaults_form.fields["timeout"].initial or 0,
                "snapshot_max_size": defaults_form.fields["snapshot_max_size"].initial or "0",
                "delete_after": defaults_form.fields["delete_after"].initial or "0",
                "crawl_max_concurrent_snapshots": defaults_form.fields["crawl_max_concurrent_snapshots"].initial,
                "persona": defaults_form.fields["persona"].initial or "Default",
                "permissions": defaults_form.fields["permissions"].initial or "public",
                "config": "{}",
            },
        )
        if defaults_form.fields["start_paused"].initial:
            form_data["start_paused"] = "on"

        form = self.form_class(data=form_data)
        if not form.is_valid():
            return self.form_invalid(form)

        crawl = self._create_crawl_from_form(form)
        snapshot = Snapshot.from_json({"url": add_url, "tags": form.cleaned_data.get("tag", "")}, overrides={"crawl": crawl})
        assert snapshot is not None
        return redirect(f"/{snapshot.url_path}")


class HealthCheckView(View):
    """
    A Django view that renders plain text "OK" for service discovery tools
    """

    def get(self, request):
        """
        Handle a GET request
        """
        return HttpResponse("OK", content_type="text/plain", status=200)


@render_with_table_view
def live_config_list_view(request: HttpRequest, **kwargs) -> TableContext:
    CONFIGS = get_all_configs()

    assert request.user.is_superuser, "Must be a superuser to view configuration settings."

    merged_config = get_config(redact_sensitive=True)

    rows = {
        "Section": [],
        "Key": [],
        "Type": [],
        "Value": [],
        "Source": [],
        "Default": [],
        # "Documentation": [],
        # "Aliases": [],
    }

    for section_id, section in reversed(list(CONFIGS.items())):
        for key in dict(section).keys():
            rows["Section"].append(section_id)  # section.replace('_', ' ').title().replace(' Config', '')
            rows["Key"].append(ItemLink(key, key=key))
            rows["Type"].append(format_html("<code>{}</code>", find_config_type(key)))

            # Use merged config value (includes machine overrides)
            actual_value = merged_config.get(key, dict(section)[key])
            rows["Value"].append(mark_safe(f"<code>{actual_value}</code>"))

            # Show where the value comes from
            source = find_config_source(key, merged_config)
            source_colors = {"Machine": "purple", "Environment": "blue", "File": "green", "Plugin Default": "teal", "Default": "gray"}
            rows["Source"].append(format_html('<code style="color: {}">{}</code>', source_colors.get(source, "gray"), source))

            rows["Default"].append(
                mark_safe(
                    f'<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{key}&type=code"><code style="text-decoration: underline">{find_config_default(key) or "See here..."}</code></a>',
                ),
            )
            # rows['Documentation'].append(mark_safe(f'Wiki: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">{key}</a>'))
            # rows['Aliases'].append(', '.join(find_config_aliases(key)))

    section = "CONSTANT"
    for key in CONSTANTS_CONFIG.keys():
        rows["Section"].append(section)  # section.replace('_', ' ').title().replace(' Config', '')
        rows["Key"].append(ItemLink(key, key=key))
        rows["Type"].append(format_html("<code>{}</code>", type(CONSTANTS_CONFIG[key]).__name__))
        rows["Value"].append(format_html("<code>{}</code>", redact_sensitive_config(CONSTANTS_CONFIG).get(key)))
        rows["Source"].append(mark_safe('<code style="color: gray">Constant</code>'))
        rows["Default"].append(
            mark_safe(
                f'<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{key}&type=code"><code style="text-decoration: underline">{find_config_default(key) or "See here..."}</code></a>',
            ),
        )
        # rows['Documentation'].append(mark_safe(f'Wiki: <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">{key}</a>'))
        # rows['Aliases'].append('')

    return TableContext(
        title="Computed Configuration Values",
        table=rows,
    )


@render_with_item_view
def live_config_value_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    from archivebox.machine.models import Machine

    CONFIGS = get_all_configs()

    assert request.user.is_superuser, "Must be a superuser to view configuration settings."

    merged_config = get_config(redact_sensitive=True)

    # Determine all sources for this config value
    sources_info = []

    # Machine config
    machine = Machine.current()
    machine_admin_url = machine.admin_change_url
    if machine.config and key in machine.config:
        sources_info.append(("Machine", redact_sensitive_config(machine.config).get(key), "purple"))

    # Environment variable
    if key in os.environ:
        sources_info.append(("Environment", redact_sensitive_config(os.environ).get(key), "blue"))

    # Config file value
    if CONSTANTS.CONFIG_FILE.exists():
        file_config = BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE)
        if key in file_config:
            sources_info.append(("File", redact_sensitive_config(file_config).get(key), "green"))

    # Default value
    default_val = find_config_default(key)
    if key in _plugin_config_properties(PLUGIN_CONFIG_SCHEMAS):
        sources_info.append(("Plugin Default", default_val, "gray"))
    elif default_val:
        sources_info.append(("Default", default_val, "gray"))

    # Final computed value
    config_source = find_config_source(key, merged_config)
    final_value = merged_config.get(key, CONFIGS.get(key, None))
    is_redacted = final_value == SENSITIVE_CONFIG_VALUE_REDACTED

    # Build sources display
    sources_html = "<br/>".join([f'<b style="color: {color}">{source}:</b> <code>{value}</code>' for source, value, color in sources_info])

    # aliases = USER_CONFIG.get(key, {}).get("aliases", [])
    aliases = []

    if key in CONSTANTS_CONFIG:
        section_header = mark_safe(
            f'[CONSTANTS]   &nbsp; <b><code style="color: lightgray">{key}</code></b> &nbsp; <small>(read-only, hardcoded by ArchiveBox)</small>',
        )
    elif key in merged_config:
        section_header = mark_safe(
            f'data / ArchiveBox.conf &nbsp; [{find_config_section(key)}]  &nbsp; <b><code style="color: lightgray">{key}</code></b>',
        )
    else:
        section_header = mark_safe(
            f'[DYNAMIC CONFIG]   &nbsp; <b><code style="color: lightgray">{key}</code></b> &nbsp; <small>(read-only, calculated at runtime)</small>',
        )

    definition_url, definition_label = get_config_definition_link(key)

    section_data = cast(
        SectionData,
        {
            "name": section_header,
            "description": None,
            "fields": {
                "Key": key,
                "Type": find_config_type(key),
                "Value": final_value,
                "Currently read from": config_source,
            },
            "help_texts": {
                "Key": mark_safe(f"""
                <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{key.lower()}">Documentation</a>  &nbsp;
                <span style="display: {"inline" if aliases else "none"}">
                    Aliases: {", ".join(aliases)}
                </span>
            """),
                "Type": mark_safe(f'''
                <a href="{definition_url}" target="_blank" rel="noopener noreferrer">
                    See full definition in <code>{definition_label}</code>...
                </a>
            '''),
                "Value": mark_safe(f'''
                {
                    '<b style="color: red">Value is redacted for your security. (Passwords, secrets, API tokens, etc. cannot be viewed in the Web UI)</b><br/><br/>'
                    if is_redacted
                    else ""
                }
                <br/><hr/><br/>
                <b>Configuration Sources (highest priority first):</b><br/><br/>
                {sources_html}
                <br/><br/>
                <p style="display: {"block" if key in merged_config and key not in CONSTANTS_CONFIG else "none"}">
                    <i>To change this value, edit <code>data/ArchiveBox.conf</code> or run:</i>
                    <br/><br/>
                    <code>archivebox config --set {key}="{
                    val.strip("'") if (val := find_config_default(key)) else str(final_value).strip("'")
                }"</code>
                </p>
            '''),
                "Currently read from": mark_safe(f"""
                The value shown in the "Value" field comes from the <b>{config_source}</b> source.
                <br/><br/>
                Priority order (highest to lowest):
                <ol>
                    <li><b style="color: purple">Machine</b> - Machine-specific overrides
                        {f'<br/><a href="{machine_admin_url}">→ Edit <code>{key}</code> in Machine.config for this server</a>' if machine_admin_url else ""}
                    </li>
                    <li><b style="color: blue">Environment</b> - process defaults from environment variables</li>
                    <li><b style="color: green">File</b> - data/ArchiveBox.conf</li>
                    <li><b style="color: gray">Plugin Default</b> - Default value from plugin config.json</li>
                    <li><b style="color: gray">Default</b> - Default value from code</li>
                </ol>
                {f'<br/><b>Tip:</b> To override <code>{key}</code> on this machine, <a href="{machine_admin_url}">edit the Machine.config field</a> and add:<br/><code>{{"\\"{key}\\": "your_value_here"}}</code>' if machine_admin_url and key not in CONSTANTS_CONFIG else ""}
            """),
            },
        },
    )

    return ItemContext(
        slug=key,
        title=key,
        data=[section_data],
    )
