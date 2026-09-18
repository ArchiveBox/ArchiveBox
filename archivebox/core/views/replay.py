import posixpath
from pathlib import Path
from urllib.parse import quote, urlparse

from abx_plugins.plugins.archivewebpage import replay_preview as archivewebpage_replay
from django import template
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views import View

from archivebox.config.common import (
    get_request_config,
)
from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.permissions import (
    can_view_snapshot,
    direct_snapshots_queryset,
)
from archivebox.core.routes_util import (
    build_admin_url,
    build_snapshot_url,
    build_web_url,
    get_snapshot_host,
    host_matches,
)
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.misc.util import (
    base_url,
    filter_queryset_by_uuid_substring,
    without_fragment,
)
from archivebox.plugins.discovery import get_plugin_name, get_plugin_template
from archivebox.progressmonitor.views import live_progress_view

from .lookup import _files_index_target, _find_snapshot_by_ref
from .replay_auth import _has_replay_cookie, _private_snapshot_auth_redirect, _replay_auth_response


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
    # Trusted viewers live on the snapshot origin, but the collection UI lives
    # on web.* (and can be embedded by admin.*). Permit only those configured
    # origins, not arbitrary sites or other snapshots. This does not grant the
    # archived document access to the parent frame or its admin session cookies.
    viewer_origins = " ".join(dict.fromkeys((build_web_url(request=request), build_admin_url(request=request))))
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
        f"frame-ancestors 'self' {viewer_origins};"
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
