__package__ = "archivebox.core"

import json
import os
import posixpath
from pathlib import Path
from typing import ClassVar, cast
from urllib.parse import quote, urlparse

from abx_plugins.plugins.archivewebpage import replay_preview as archivewebpage_replay
from admin_data_views.typing import ItemContext, SectionData, TableContext
from admin_data_views.utils import ItemLink, render_with_item_view, render_with_table_view
from django import template
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.paginator import InvalidPage
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden, QueryDict
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.views import View
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.generic import FormView
from django.views.generic.list import ListView

from archivebox.config import CONSTANTS, CONSTANTS_CONFIG, VERSION
from archivebox.config.common import (
    PLUGIN_CONFIG_SCHEMAS,
    SENSITIVE_CONFIG_VALUE_REDACTED,
    _plugin_config_properties,
    find_config_default,
    find_config_section,
    find_config_source,
    find_config_type,
    get_all_configs,
    get_config,
    get_request_config,
    redact_sensitive_config,
)
from archivebox.config.configset import BaseConfigSet
from archivebox.core.forms import AddLinkForm
from archivebox.core.models import ArchiveResult, Snapshot, SnapshotTag
from archivebox.core.permissions import (
    PERMISSIONS_PRIVATE,
    PERMISSIONS_PUBLIC,
    PERMISSIONS_UNLISTED,
    can_view_snapshot,
    direct_snapshots_queryset,
    filter_personas_by_permissions,
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
from archivebox.crawls.models import Crawl
from archivebox.misc.paginators import AcceleratedPaginator
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.misc.util import (
    base_url,
    filter_queryset_by_uuid_substring,
    sanitize_html_text,
    urldecode,
    validate_url,
    without_fragment,
)
from archivebox.plugins.discovery import get_plugin_name, get_plugin_template
from archivebox.plugins.forms import get_plugin_config_binary_urls
from archivebox.plugins.views import get_config_definition_link
from archivebox.progressmonitor.views import live_progress_view
from archivebox.search.config import (
    get_search_mode,
    get_search_mode_backend,
    get_search_mode_base,
    get_search_mode_options,
)
from archivebox.search.views import get_cached_public_search_state


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

    snapshots = Snapshot.objects.select_related("crawl", "crawl__created_by")

    if len(lookup) == 12 and "-" not in lookup:
        return snapshots.filter(id__endswith=lookup).order_by("-created_at", "-downloaded_at").first()

    try:
        return snapshots.get(pk=lookup)
    except Snapshot.DoesNotExist:
        try:
            return snapshots.get(id__startswith=lookup)
        except Snapshot.DoesNotExist:
            return None
        except Snapshot.MultipleObjectsReturned:
            return snapshots.filter(id__startswith=lookup).first()


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
    except (Session.DoesNotExist, get_user_model().DoesNotExist, KeyError, TypeError, ValueError):
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
        if not request_config.BASE_URL:
            return _admin_login_redirect_or_forbidden(request)

        if request.user.is_authenticated and request_config.CONTROL_PLANE_ENABLED:
            return redirect("/admin/core/snapshot/")

        if request_config.PUBLIC_INDEX:
            return redirect("/public")

        return _admin_login_redirect_or_forbidden(request)


class SnapshotView(View):
    # render static html index from filesystem archive/<timestamp>/index.html

    @staticmethod
    def find_snapshots_for_url(path: str, *, allow_fallback: bool = True):
        """Return a queryset of snapshots matching a URL-ish path. URL only — never tries ID matching.

        Use ``find_snapshots_for_id`` separately if you also want to match by snapshot UUID.
        """

        def _fragmentless_url_query(url: str) -> Q:
            from archivebox.misc.db import is_postgres

            canonical = without_fragment(url)
            if not is_postgres():
                # Use a range comparison (url >= 'canonical#' AND url < 'canonical#\U0010ffff')
                # instead of LIKE/__startswith — SQLite's case-insensitive LIKE bypasses the
                # url index and forces a full-table scan over ~1M rows (~250ms). The range
                # form lets SQLite use a MULTI-INDEX OR and stays under 1ms.
                return Q(url=canonical) | (Q(url__gte=f"{canonical}#") & Q(url__lt=f"{canonical}#\U0010ffff"))
            # On postgres the range trick is unsafe: linguistic (ICU/libc) collations
            # don't compare '#'-suffixed strings bytewise, so the range can miss rows.
            # startswith compiles to LIKE 'prefix%' with wildcards escaped, which is
            # correct under any collation and uses the url pattern-ops index.
            return Q(url=canonical) | Q(url__startswith=f"{canonical}#")

        normalized = without_fragment(path)
        if path.startswith(("http://", "https://")):
            # exact url match (indexed) — fastest path
            qs = Snapshot.objects.filter(_fragmentless_url_query(path))
            if not allow_fallback or qs.exists():
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
        return render(
            template_name="core/snapshot.html",
            request=request,
            context=snapshot.get_html_details_context(request=request),
        )

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
                    + mark_safe('</pre><br/>Choose a Snapshot to proceed or go back to the <a href="/" target="_top">Main Index</a>'),
                    content_type="text/html",
                    status=404,
                )
            except Http404:
                assert snapshot  # (Snapshot.DoesNotExist is already handled above)

                # Snapshot dir exists but file within does not e.g. 124235.324234/screenshot.png
                return HttpResponse(
                    format_html(
                        """
                        <html><head>
                        <title>Snapshot Not Found</title>
                        </head><body>
                        <center><br/><br/><br/>
                        Snapshot <a href="/{}/index.html" target="_top"><b><code>[{}]</code></b></a>: <a href="{}" target="_blank" rel="noreferrer">{}</a><br/>
                        was queued on {}, but no files have been saved yet in:<br/><b><a href="/{}/" target="_top"><code>{}</code></a><code>/{}</code></b><br/><br/>
                        It's possible {} during the last capture on {},<br/>or that the archiving process has not completed yet.<br/>
                        <pre><code># run this cmd to finish/retry archiving this Snapshot</code><br/>
                        <code style="user-select: all; color: #333">archivebox update -t timestamp {}</code></pre><br/><br/>
                        <div class="text-align: left; width: 100%; max-width: 400px">
                        <i><b>Next steps:</i></b><br/>
                        - list all the <a href="/{}/" target="_top">Snapshot files <code>.*</code></a><br/>
                        - view the <a href="/{}/index.html" target="_top">Snapshot <code>./index.html</code></a><br/>
                        - go to the <a href="/admin/core/snapshot/{}/change/" target="_top">Snapshot admin</a> to edit<br/>
                        - go to the <a href="/admin/core/snapshot/?id__exact={}" target="_top">Snapshot actions</a> to re-archive<br/>
                        - or return to <a href="/" target="_top">the main index...</a></div>
                        </center>
                        </body></html>
                        """,
                        snapshot.archive_path,
                        snapshot.timestamp,
                        snapshot.url,
                        snapshot.url,
                        str(snapshot.bookmarked_at).split(".")[0],
                        snapshot.archive_path,
                        snapshot.timestamp,
                        archivefile if str(archivefile) != "None" else "",
                        f"the {archivefile} resource could not be fetched"
                        if str(archivefile) != "None"
                        else "the original site was not available",
                        str(snapshot.bookmarked_at).split(".")[0],
                        snapshot.timestamp,
                        snapshot.archive_path,
                        snapshot.archive_path,
                        snapshot.pk,
                        snapshot.id,
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

        snapshots = direct_snapshots_queryset(request, _resolve_snapshots_for_slug(path))
        try:
            if "://" in path:
                snapshot = snapshots.order_by("-bookmarked_at").first()
                if snapshot is None:
                    raise Snapshot.DoesNotExist
            else:
                snapshot = snapshots.get()
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
                + mark_safe('</pre><br/>Choose a Snapshot to proceed or go back to the <a href="/" target="_top">Main Index</a>'),
                content_type="text/html",
                status=404,
            )

        target_path = build_snapshot_url(str(snapshot.id), "index.html", request=request)
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
                qs = direct_snapshots_queryset(
                    request,
                    SnapshotView.find_snapshots_for_url(requested_url)
                    .select_related("crawl", "crawl__created_by")
                    .filter(
                        crawl__created_by__username=username_lookup,
                    ),
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


def _resolve_archiveresult_relpath(snapshot: Snapshot, rel_path: str) -> tuple[str, ArchiveResult | None]:
    """Resolve plugin-relative output paths through ArchiveResult.output_files."""
    parts = Path(rel_path).parts
    if len(parts) < 2:
        return rel_path, None

    plugin = parts[0]
    plugin_relpath = posixpath.join(*parts[1:])
    results = list(
        ArchiveResult.objects.filter(
            snapshot=snapshot,
            plugin=plugin,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        ).only("plugin", "output_files"),
    )
    if not results:
        return rel_path, None

    for result in results:
        output_files = result.output_files or {}
        for candidate in (plugin_relpath, rel_path):
            file_info = output_files.get(candidate)
            if not isinstance(file_info, dict):
                continue
            if file_info.get("root_relative"):
                return candidate, result
            return rel_path, result

    return rel_path, results[0]


def _plugin_full_preview_response(
    request: HttpRequest,
    snapshot: Snapshot,
    rel_path: str,
    result: ArchiveResult | None,
) -> HttpResponse | None:
    """Render an explicit plugin full template as a trusted preview wrapper."""
    if not request.GET.get("preview"):
        return None

    path_parts = Path(rel_path).parts
    plugin = get_plugin_name(result.plugin) if result else (path_parts[0] if len(path_parts) > 1 else "")
    if not plugin:
        return None

    # ReplayWeb.page needs plugin-owned WACZ inspection and service-worker
    # context, so it remains the one narrow preview exception below.
    if plugin == "archivewebpage" and archivewebpage_replay.is_replay_target(rel_path):
        return None

    template_str = get_plugin_template(plugin, "full", fallback=False)
    if not template_str:
        return None

    raw_query = request.GET.copy()
    raw_query.pop("preview", None)
    output_url = request.path
    if raw_query:
        output_url = f"{output_url}?{raw_query.urlencode()}"

    rendered = (
        template.Engine(debug=False)
        .from_string(template_str)
        .render(
            template.Context(
                {
                    "result": result,
                    "snapshot": snapshot,
                    "output_path": output_url,
                    "output_path_raw": rel_path,
                    "plugin": plugin,
                    "preview_base": f"{request.path.rsplit('/', 1)[0]}/",
                },
            ),
        )
    )
    response = HttpResponse(rendered, content_type="text/html; charset=utf-8")
    response.headers["Content-Disposition"] = f'inline; filename="{Path(rel_path).stem}.html"'
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-ArchiveBox-Security-Mode"] = request.archivebox_config.SERVER_SECURITY_MODE
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' data: blob:; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
        "style-src 'unsafe-inline' data: blob: 'self'; "
        "connect-src 'self' data: blob:; "
        "img-src 'self' data: blob:; "
        "media-src 'self' data: blob:; "
        "font-src 'self' data: blob:; "
        "frame-src 'self' data: blob:; "
        "worker-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'self';"
    )
    return response


def _visible_response_snapshots_for_domain(request: HttpRequest, domain: str) -> list[Snapshot]:
    if not domain:
        return []

    requested_domain = domain.split(":", 1)[0].lower()
    roots = (f"http://{requested_domain}", f"https://{requested_domain}")
    domain_query = Q(url__in=roots)

    from archivebox.misc.db import is_postgres

    postgres = is_postgres()
    for root in roots:
        for separator in ("/", "?", "#"):
            prefix = f"{root}{separator}"
            if postgres:
                domain_query |= Q(url__startswith=prefix)
            else:
                domain_query |= Q(url__gte=prefix, url__lt=f"{prefix}\U0010ffff")

    candidates = (
        Snapshot.objects.filter(domain_query)
        .select_related("crawl", "crawl__created_by")
        .order_by("-bookmarked_at", "-created_at", "-timestamp")
    )
    return [snapshot for snapshot in candidates if can_view_snapshot(request, snapshot) or _has_replay_cookie(request, snapshot)]


def _latest_response_match(
    snapshots: list[Snapshot],
    domain: str,
    rel_path: str,
) -> tuple[Snapshot, Path, Path] | None:
    if not domain or not rel_path:
        return None
    requested_domain = domain.split(":", 1)[0].lower()
    rel_to_root = Path(rel_path)
    for snapshot in snapshots:
        responses_root = Path(snapshot.output_dir) / "responses" / requested_domain
        if (responses_root / rel_to_root).exists():
            return snapshot, responses_root, rel_to_root
    return None


def _latest_responses_root(snapshots: list[Snapshot], domain: str) -> tuple[Snapshot, Path] | None:
    if not domain:
        return None
    requested_domain = domain.split(":", 1)[0].lower()
    for snapshot in snapshots:
        responses_root = Path(snapshot.output_dir) / "responses" / requested_domain
        if responses_root.is_dir():
            return snapshot, responses_root
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

    rel_path, archive_result = _resolve_archiveresult_relpath(snapshot, rel_path)

    plugin_preview = _plugin_full_preview_response(request, snapshot, rel_path, archive_result)
    if plugin_preview is not None:
        return plugin_preview

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

    domain = domain.split(":", 1)[0].lower()
    snapshots = _visible_response_snapshots_for_domain(request, domain)
    match = _latest_response_match(snapshots, domain, rel_path)
    if not match and "." not in Path(rel_path).name:
        index_path = f"{rel_path.rstrip('/')}/index.html"
        match = _latest_response_match(snapshots, domain, index_path)
    if not match and "." not in Path(rel_path).name:
        html_path = f"{rel_path}.html"
        match = _latest_response_match(snapshots, domain, html_path)

    root_match = (match[0], match[1]) if match else _latest_responses_root(snapshots, domain)
    responses_root = root_match[1] if root_match else None
    if request_config.USES_SUBDOMAIN_ROUTING:
        snapshot = root_match[0] if root_match else (snapshots[0] if requested_root_index and snapshots else None)
        if snapshot:
            snapshot_path = f"responses/{domain}/{match[2]}" if match else path
            target = build_snapshot_url(str(snapshot.id), snapshot_path, request=request, config=request_config)
            if request.META.get("QUERY_STRING"):
                target = f"{target}?{request.META['QUERY_STRING']}"
            return redirect(target)

    show_indexes = bool(request.GET.get("files"))
    if match:
        _snapshot, responses_root, rel_to_root = match
        response = _serve_responses_path(request, responses_root, str(rel_to_root), show_indexes)
        if response is not None:
            return response

    if responses_root:
        response = _serve_responses_path(request, responses_root, rel_path, show_indexes)
        if response is not None:
            return response

    if requested_root_index and not show_indexes:
        if snapshots:
            return SnapshotView.render_live_index(request, snapshots[0])

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
    ordering: ClassVar[list[str]] = ["-bookmarked_at", "-created_at"]
    paginator_class = AcceleratedPaginator
    public_page_scan_chunk_size = 50

    def get_paginate_by(self, queryset):
        runtime_config = self.__dict__.get("runtime_config")
        if runtime_config is None:
            self.runtime_config = runtime_config = get_request_config(self.request, resolve_plugins=False)
        return runtime_config.SNAPSHOTS_PER_PAGE

    def _base_public_snapshot_fields(self) -> tuple[str, ...]:
        return (
            "id",
            "created_at",
            "modified_at",
            "url",
            "timestamp",
            "bookmarked_at",
            "title",
            "downloaded_at",
            "status",
            "output_size",
            "permissions",
        )

    def _ordered_public_page_from_order_index(self, *, page_number: int, page_size: int) -> list[Snapshot] | None:
        target_count = page_number * page_size
        public_snapshots: list[Snapshot] = []
        scanned = 0
        chunk_size = max(self.public_page_scan_chunk_size, page_size)
        ordered_snapshots = Snapshot.objects.order_by(*self.ordering).only(*self._base_public_snapshot_fields())

        while len(public_snapshots) < target_count:
            chunk = list(ordered_snapshots[scanned : scanned + chunk_size])
            if not chunk:
                break
            scanned += len(chunk)
            public_snapshots.extend(snapshot for snapshot in chunk if snapshot.permissions == PERMISSIONS_PUBLIC)

        start = (page_number - 1) * page_size
        return public_snapshots[start:target_count]

    def paginate_queryset(self, queryset, page_size):
        if self.request.GET.get("q", default="").strip():
            return super().paginate_queryset(queryset, page_size)

        public_count = self.get_exact_public_snapshot_count()
        paginator = self.get_paginator(range(public_count), page_size)
        page_kwarg = self.kwargs.get(self.page_kwarg)
        page_query = self.request.GET.get(self.page_kwarg)
        page_number = page_kwarg or page_query or 1

        try:
            page = paginator.page(page_number)
        except InvalidPage as err:
            raise Http404(f"Invalid page ({page_number}): {err}") from err

        object_list = self._ordered_public_page_from_order_index(page_number=page.number, page_size=page_size)
        page.object_list = object_list
        return paginator, page, object_list, page.has_other_pages()

    def get_context_data(self, **kwargs):
        runtime_config = self.__dict__.get("runtime_config")
        if runtime_config is None:
            self.runtime_config = runtime_config = get_request_config(self.request, resolve_plugins=False)
        search_mode = get_search_mode(self.request.GET.get("search_mode"), config=runtime_config)
        search_mode_backend = get_search_mode_backend(search_mode, config=runtime_config)
        query = self.request.GET.get("q", default="").strip()
        public_search_state = self.__dict__.get("public_search_state")
        public_search_pending = bool(query and (public_search_state is None or not public_search_state.get("done")))
        context = {
            **super().get_context_data(**kwargs),
            "VERSION": VERSION,
            "CONFIG": runtime_config,
            "COMMIT_HASH": runtime_config.COMMIT_HASH,
            "FOOTER_INFO": runtime_config.FOOTER_INFO,
            "WEB_BASE_URL": build_web_url(request=self.request, config=runtime_config),
            "search_mode": search_mode,
            "search_mode_options": get_search_mode_options(config=runtime_config),
            "public_search_stream_pending": public_search_pending,
        }
        context["show_search_index_hint"] = bool(
            query
            and not public_search_pending
            and get_search_mode_base(search_mode, config=runtime_config) == "deep"
            and search_mode_backend
            and context["paginator"].count == 0,
        )
        snapshots = list(context.get("object_list") or ())
        icons_by_snapshot: dict[str, set[str]] = {str(snapshot.id): set() for snapshot in snapshots}
        tag_names_by_snapshot: dict[str, list[str]] = {str(snapshot.id): [] for snapshot in snapshots}
        preview_paths_by_snapshot: dict[str, list[tuple[int, int, str]]] = {str(snapshot.id): [] for snapshot in snapshots}
        favicon_paths_by_snapshot: dict[str, list[str]] = {str(snapshot.id): [] for snapshot in snapshots}
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
            for snapshot_id, tag_name in (
                SnapshotTag.objects.filter(snapshot_id__in=icons_by_snapshot.keys())
                .order_by("tag__name")
                .values_list("snapshot_id", "tag__name")
                .iterator(chunk_size=1000)
            ):
                tag_names_by_snapshot[str(snapshot_id)].append(tag_name)

            preview_plugin_order = {
                "screenshot": 0,
                "chrome_extension_screenshot": 1,
            }
            preview_candidates = {
                "screenshot": ("screenshot.png",),
                "chrome_extension_screenshot": ("screenshot-1.png", "screenshot.png"),
            }

            def result_output_path(result: ArchiveResult, filename: str) -> str | None:
                output_files = result.output_files or {}
                file_info = output_files.get(filename)
                if not isinstance(file_info, dict) or int(file_info.get("size") or 0) <= 0:
                    return None
                if file_info.get("root_relative"):
                    return filename
                return f"{result.plugin}/{filename}"

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

            for result in (
                ArchiveResult.objects.filter(
                    snapshot_id__in=icons_by_snapshot.keys(),
                    status=ArchiveResult.StatusChoices.SUCCEEDED,
                    plugin__in=(*preview_candidates, "favicon"),
                )
                .only("snapshot_id", "plugin", "output_files")
                .iterator(chunk_size=1000)
            ):
                snapshot_key = str(result.snapshot_id)
                if result.plugin in preview_candidates:
                    plugin_rank = preview_plugin_order[result.plugin]
                    for filename_rank, filename in enumerate(preview_candidates[result.plugin]):
                        output_path = result_output_path(result, filename)
                        if output_path:
                            preview_paths_by_snapshot[snapshot_key].append((plugin_rank, filename_rank, output_path))
                elif result.plugin == "favicon":
                    output_path = result_output_path(result, "favicon.ico")
                    if output_path:
                        favicon_paths_by_snapshot[snapshot_key].append(output_path)

        for snapshot in snapshots:
            snapshot._icons_compact = True
            snapshot._icons_archive_results = icons_by_snapshot.get(str(snapshot.id), set())
            snapshot._icons_progress_stats = progress_by_snapshot.get(str(snapshot.id), {})
            snapshot.num_outputs_cached = snapshot._icons_progress_stats.get("succeeded", 0)
            snapshot._tags_str_cached = ",".join(tag_names_by_snapshot.get(str(snapshot.id), []))
            snapshot._public_preview_paths = [
                output_path for _plugin_rank, _filename_rank, output_path in sorted(preview_paths_by_snapshot.get(str(snapshot.id), []))
            ]
            snapshot._public_favicon_paths = favicon_paths_by_snapshot.get(str(snapshot.id), [])
            snapshot._is_archived_cached = bool(snapshot.downloaded_at or snapshot.status == Snapshot.StatusChoices.SEALED)
        context["object_list"] = snapshots
        return context

    def get_exact_public_snapshot_count(self) -> int:
        hidden_count = Snapshot.objects.filter(permissions=PERMISSIONS_PRIVATE).count()
        hidden_count += Snapshot.objects.filter(permissions=PERMISSIONS_UNLISTED).count()
        return Snapshot.objects.count() - hidden_count

    def get_queryset(self, **kwargs):
        qs = public_snapshots_queryset(super().get_queryset(**kwargs)).only(*self._base_public_snapshot_fields())
        query = self.request.GET.get("q", default="").strip()

        if not query:
            return qs

        cached_state = get_cached_public_search_state(self.request)
        self.public_search_state = cached_state
        if cached_state is not None:
            cached_ids = cached_state.get("ids") or []
            if not cached_ids:
                return qs.none()
            search_rank = Case(
                *(When(pk=snapshot_id, then=Value(index)) for index, snapshot_id in enumerate(cached_ids)),
                output_field=IntegerField(),
            )
            return qs.filter(pk__in=cached_ids).annotate(search_rank=search_rank).order_by("search_rank", *self.ordering)

        return qs.none()

    def get(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return redirect("/admin/core/snapshot/")
        if get_request_config(self.request).PUBLIC_INDEX:
            response = super().get(*args, **kwargs)
            return response
        else:
            return _admin_login_redirect_or_forbidden(self.request)


# The public web host intentionally has no CSRF cookie. Authenticated POSTs are
# re-protected in post(); integrations should use the token-authenticated API.
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

    def post(self, request: HttpRequest, *args: object, **kwargs: object):
        if request.user.is_authenticated:
            return csrf_protect(super().post)(request, *args, **kwargs)
        return super().post(request, *args, **kwargs)

    def _can_override_crawl_config(self) -> bool:
        user = self.request.user
        return bool(user.is_authenticated and user.is_active and user.is_superuser)

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
            effective_config_redacted = redact_sensitive_config(effective_config.model_dump(mode="json"))
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
        return {
            **context,
            "title": "Create Crawl",
            # We can't just call request.build_absolute_uri in the template, because it would include query parameters
            "absolute_add_path": self.request.build_absolute_uri(self.request.path),
            "web_base_url": build_web_url("", request=self.request),
            "VERSION": VERSION,
            "FOOTER_INFO": request_config.FOOTER_INFO,
            "required_search_plugin": required_search_plugin,
            "persona_config_map_json": json.dumps(persona_config_map, sort_keys=True, default=str),
            "recent_personas": recent_personas,
            "can_override_crawl_config": can_override_crawl_config,
            "stdout": "",
        }

    def _create_crawl_from_form(self, form, *, created_by_id=None) -> Crawl:
        from archivebox.cli.archivebox_add import add

        urls_input = form.cleaned_data["url"]
        urls = urls_input
        submitted_lines = [line.strip() for line in urls_input.splitlines() if line.strip()]
        if len(submitted_lines) == 1:
            try:
                # A lone URL pasted into /add/ is the same user-facing input as
                # `archivebox add https://...`: queue that URL directly so a
                # narrow plugin selection like `wget` can archive it without
                # also needing parser plugins. Multi-line or formatted text
                # remains verbatim import content for the internal parser root.
                urls = [validate_url(submitted_lines[0])]
            except ValueError:
                pass
        print(f"[+] Adding URL: {urls_input}")

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

        if created_by_id is None:
            if self.request.user.is_authenticated:
                created_by_id = self.request.user.pk
            else:
                from archivebox.base_models.models import get_or_create_system_user_pk

                created_by_id = get_or_create_system_user_pk()

        config = {}
        effective_config = get_config(persona=persona) if persona else get_config()
        if delete_after != str(effective_config.DELETE_AFTER):
            config["DELETE_AFTER"] = delete_after
        if timeout is not None and int(timeout) != int(effective_config.TIMEOUT):
            config["TIMEOUT"] = int(timeout)
        if permissions:
            config["PERMISSIONS"] = permissions

        config.update(plugin_config)
        config.update(custom_config)
        if bool(url_filters.get("only_new")) != bool(effective_config.ONLY_NEW):
            config["ONLY_NEW"] = bool(url_filters.get("only_new"))
        crawl, _snapshots = add(
            urls=urls,
            depth=depth,
            max_urls=max_urls,
            crawl_max_size=crawl_max_size,
            crawl_timeout=crawl_timeout,
            snapshot_max_size=snapshot_max_size,
            crawl_max_concurrent_snapshots=crawl_max_concurrent_snapshots,
            tag=tag,
            url_allowlist=url_filters.get("allowlist") or "",
            url_denylist=url_filters.get("denylist") or "",
            plugins=plugins,
            persona=persona.name if persona else "Default",
            bg=True,
            created_by_id=created_by_id,
            config=config,
        )
        if notes:
            crawl.safe_update({"notes": sanitize_html_text(notes)}, refresh=False)
        if permissions and crawl.config.get("PERMISSIONS") != permissions:
            next_config = {**crawl.config, "PERMISSIONS": permissions}
            crawl.safe_update({"config": next_config}, refresh=True)
        if start_paused:
            crawl.pause()

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

        return crawl

    def form_valid(self, form):
        crawl = self._create_crawl_from_form(form)

        urls = form.cleaned_data["url"]
        schedule = form.cleaned_data.get("schedule", "").strip()
        rough_url_count = len([url for url in urls.splitlines() if url.strip()])

        schedule_msg = ""
        if schedule and crawl.schedule_id:
            schedule_msg = format_html(" and <a href='{}'>scheduled to repeat {}</a>", crawl.schedule.admin_change_url, schedule)

        messages.success(
            self.request,
            format_html(
                "Created crawl with {} starting URL(s){}. Snapshots will be created and archived in the background. <a href='{}'>View Crawl →</a>",
                rough_url_count,
                schedule_msg,
                crawl.admin_change_url,
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
        request_config = get_request_config(request)
        web_host = get_web_host(config=request_config, request=request)
        admin_host = get_admin_host(config=request_config, request=request)
        is_web_host = host_matches(request_host, web_host)
        is_admin_host = host_matches(request_host, admin_host)
        if request.user.is_authenticated and not request_config.PUBLIC_ADD_VIEW and is_web_host and not is_admin_host:
            return redirect(build_admin_url(request.get_full_path(), request=request))

        if not self.test_func():
            if is_web_host and not is_admin_host:
                return redirect(build_admin_url(request.get_full_path(), request=request))
            if is_admin_host:
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
        response = HttpResponse("OK", content_type="text/plain", status=200)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Expose-Headers"] = "X-ArchiveBox-Health"
        response["X-ArchiveBox-Health"] = "OK"
        return response


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
        for key in dict(section):
            rows["Section"].append(section_id)  # section.replace('_', ' ').title().replace(' Config', '')
            rows["Key"].append(ItemLink(key, key=key))
            rows["Type"].append(format_html("<code>{}</code>", find_config_type(key)))

            # Use merged config value (includes machine overrides)
            actual_value = merged_config.get(key, dict(section)[key])
            rows["Value"].append(format_html("<code>{}</code>", actual_value))

            # Show where the value comes from
            source = find_config_source(key, merged_config)
            source_colors = {"Machine": "purple", "Environment": "blue", "File": "green", "Plugin Default": "teal", "Default": "gray"}
            rows["Source"].append(format_html('<code style="color: {}">{}</code>', source_colors.get(source, "gray"), source))

            rows["Default"].append(
                format_html(
                    '<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{}&type=code"><code style="text-decoration: underline">{}</code></a>',
                    key,
                    find_config_default(key) or "See here...",
                ),
            )

    section = "CONSTANT"
    for key in CONSTANTS_CONFIG:
        rows["Section"].append(section)  # section.replace('_', ' ').title().replace(' Config', '')
        rows["Key"].append(ItemLink(key, key=key))
        rows["Type"].append(format_html("<code>{}</code>", type(CONSTANTS_CONFIG[key]).__name__))
        rows["Value"].append(format_html("<code>{}</code>", redact_sensitive_config(CONSTANTS_CONFIG).get(key)))
        rows["Source"].append(mark_safe('<code style="color: gray">Constant</code>'))
        rows["Default"].append(
            format_html(
                '<a href="https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{}&type=code"><code style="text-decoration: underline">{}</code></a>',
                key,
                find_config_default(key) or "See here...",
            ),
        )

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
    sources_html = format_html_join(
        mark_safe("<br/>"),
        '<b style="color: {}">{}:</b> <code>{}</code>',
        ((color, source, value) for source, value, color in sources_info),
    )

    aliases = []

    if key in CONSTANTS_CONFIG:
        section_header = format_html(
            '[CONSTANTS]   &nbsp; <b><code style="color: lightgray">{}</code></b> &nbsp; <small>(read-only, hardcoded by ArchiveBox)</small>',
            key,
        )
    elif key in merged_config:
        section_header = format_html(
            'data / ArchiveBox.conf &nbsp; [{}]  &nbsp; <b><code style="color: lightgray">{}</code></b>',
            find_config_section(key),
            key,
        )
    else:
        section_header = format_html(
            '[DYNAMIC CONFIG]   &nbsp; <b><code style="color: lightgray">{}</code></b> &nbsp; <small>(read-only, calculated at runtime)</small>',
            key,
        )

    definition_url, definition_label = get_config_definition_link(key)
    redacted_message = (
        mark_safe(
            '<b style="color: red">Value is redacted for your security. (Passwords, secrets, API tokens, etc. cannot be viewed in the Web UI)</b><br/><br/>',
        )
        if is_redacted
        else ""
    )
    default_command_value = val.strip("'") if (val := find_config_default(key)) else str(final_value).strip("'")
    machine_config_link = (
        format_html('<br/><a href="{}">→ Edit <code>{}</code> in Machine.config for this server</a>', machine_admin_url, key)
        if machine_admin_url
        else ""
    )
    machine_config_tip = (
        format_html(
            '<br/><b>Tip:</b> To override <code>{}</code> on this machine, <a href="{}">edit the Machine.config field</a> and add:<br/><code>{}</code>',
            key,
            machine_admin_url,
            f'{{"{key}": "your_value_here"}}',
        )
        if machine_admin_url and key not in CONSTANTS_CONFIG
        else ""
    )

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
                "Key": format_html(
                    """
                <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Configuration#{}">Documentation</a>  &nbsp;
                <span style="display: {}">
                    Aliases: {}
                </span>
            """,
                    key.lower(),
                    "inline" if aliases else "none",
                    ", ".join(aliases),
                ),
                "Type": format_html(
                    """
                <a href="{}" target="_blank" rel="noopener noreferrer">
                    See full definition in <code>{}</code>...
                </a>
            """,
                    definition_url,
                    definition_label,
                ),
                "Value": format_html(
                    """
                {}
                <br/><hr/><br/>
                <b>Configuration Sources (highest priority first):</b><br/><br/>
                {}
                <br/><br/>
                <p style="display: {}">
                    <i>To change this value, edit <code>data/ArchiveBox.conf</code> or run:</i>
                    <br/><br/>
                    <code>archivebox config --set {}="{}"</code>
                </p>
            """,
                    redacted_message,
                    sources_html,
                    "block" if key in merged_config and key not in CONSTANTS_CONFIG else "none",
                    key,
                    default_command_value,
                ),
                "Currently read from": format_html(
                    """
                The value shown in the "Value" field comes from the <b>{}</b> source.
                <br/><br/>
                Priority order (highest to lowest):
                <ol>
                    <li><b style="color: purple">Machine</b> - Machine-specific overrides
                        {}
                    </li>
                    <li><b style="color: blue">Environment</b> - process defaults from environment variables</li>
                    <li><b style="color: green">File</b> - data/ArchiveBox.conf</li>
                    <li><b style="color: gray">Plugin Default</b> - Default value from plugin config.json</li>
                    <li><b style="color: gray">Default</b> - Default value from code</li>
                </ol>
                {}
            """,
                    config_source,
                    machine_config_link,
                    machine_config_tip,
                ),
            },
        },
    )

    return ItemContext(
        slug=key,
        title=key,
        data=[section_data],
    )
