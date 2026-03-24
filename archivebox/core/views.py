__package__ = "archivebox.core"

import json
import os
import posixpath
from glob import glob, escape
from django.utils import timezone
import inspect
from typing import cast, get_type_hints
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, urlparse

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpRequest, HttpResponse, Http404, HttpResponseForbidden
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views import View
from django.views.generic.list import ListView
from django.views.generic import FormView
from django.db.models import Q
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from admin_data_views.typing import TableContext, ItemContext, SectionData
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink

from archivebox.config import CONSTANTS, CONSTANTS_CONFIG, DATA_DIR, VERSION
from archivebox.config.common import SHELL_CONFIG, SERVER_CONFIG, SEARCH_BACKEND_CONFIG
from archivebox.config.configset import get_flat_config, get_config, get_all_configs
from archivebox.misc.util import base_url, htmlencode, ts_to_date_str, urldecode, without_fragment
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.misc.logging_util import printable_filesize
from archivebox.search import get_search_mode, prioritize_metadata_matches, query_search_index

from archivebox.core.models import Snapshot
from archivebox.core.host_utils import (
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
from archivebox.crawls.models import Crawl
from archivebox.hooks import (
    BUILTIN_PLUGINS_DIR,
    USER_PLUGINS_DIR,
    discover_plugin_configs,
    get_enabled_plugins,
    get_plugin_name,
    iter_plugin_dirs,
)


ABX_PLUGINS_GITHUB_BASE_URL = "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/"
LIVE_PLUGIN_BASE_URL = "/admin/environment/plugins/"


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
    if SERVER_CONFIG.CONTROL_PLANE_ENABLED:
        return redirect(f"/admin/login/?next={request.path}")
    return HttpResponseForbidden("ArchiveBox is running with the control plane disabled in this security mode.")


class HomepageView(View):
    def get(self, request):
        if request.user.is_authenticated and SERVER_CONFIG.CONTROL_PLANE_ENABLED:
            return redirect("/admin/core/snapshot/")

        if SERVER_CONFIG.PUBLIC_INDEX:
            return redirect("/public")

        return _admin_login_redirect_or_forbidden(request)


class SnapshotView(View):
    # render static html index from filesystem archive/<timestamp>/index.html

    @staticmethod
    def find_snapshots_for_url(path: str):
        """Return a queryset of snapshots matching a URL-ish path."""

        def _fragmentless_url_query(url: str) -> Q:
            canonical = without_fragment(url)
            return Q(url=canonical) | Q(url__startswith=f"{canonical}#")

        normalized = without_fragment(path)
        if path.startswith(("http://", "https://")):
            # try exact match on full url / ID first
            qs = Snapshot.objects.filter(_fragmentless_url_query(path) | Q(id__icontains=path) | Q(id__icontains=normalized))
            if qs.exists():
                return qs
            normalized = normalized.split("://", 1)[1]

        # try exact match on full url / ID (without scheme)
        qs = Snapshot.objects.filter(
            _fragmentless_url_query("http://" + normalized)
            | _fragmentless_url_query("https://" + normalized)
            | Q(id__icontains=normalized),
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
    def render_live_index(request, snapshot):
        TITLE_LOADING_MSG = "Not yet archived..."
        from archivebox.core.widgets import TagEditorWidget

        hidden_card_plugins = {"archivedotorg", "favicon", "title"}
        outputs = [
            out
            for out in snapshot.discover_outputs(include_filesystem_fallback=True)
            if (out.get("size") or 0) > 0 and out.get("name") not in hidden_card_plugins
        ]
        archiveresults = {out["name"]: out for out in outputs}
        hash_index = snapshot.hashes_index
        # Get available extractor plugins from hooks (sorted by numeric prefix for ordering)
        # Convert to base names for display ordering
        all_plugins = [get_plugin_name(e) for e in get_enabled_plugins()]
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
        preferred_types = tuple(preview_priority + [p for p in all_plugins if p not in preview_priority])
        all_types = preferred_types + tuple(result_type for result_type in archiveresults.keys() if result_type not in preferred_types)

        best_result = {"path": "about:blank", "result": None}
        for result_type in preferred_types:
            if result_type in archiveresults:
                best_result = archiveresults[result_type]
                break

        related_snapshots_qs = SnapshotView.find_snapshots_for_url(snapshot.url)
        related_snapshots = list(related_snapshots_qs.exclude(id=snapshot.id).order_by("-bookmarked_at", "-created_at", "-timestamp")[:25])
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
            key=lambda r: all_types.index(r["name"]) if r["name"] in all_types else -r["size"],
        )
        non_compact_outputs = [out for out in ordered_outputs if not out.get("is_compact") and not out.get("is_metadata")]
        compact_outputs = [out for out in ordered_outputs if out.get("is_compact") or out.get("is_metadata")]
        tag_widget = TagEditorWidget()
        output_size = sum(int(out.get("size") or 0) for out in ordered_outputs)
        is_archived = bool(ordered_outputs or snapshot.downloaded_at or snapshot.status == Snapshot.StatusChoices.SEALED)

        context = {
            "id": str(snapshot.id),
            "snapshot_id": str(snapshot.id),
            "url": snapshot.url,
            "archive_path": snapshot.archive_path_from_db,
            "title": htmlencode(snapshot.resolved_title or (snapshot.base_url if is_archived else TITLE_LOADING_MSG)),
            "extension": snapshot.extension or "html",
            "tags": snapshot.tags_str() or "untagged",
            "size": printable_filesize(output_size) if output_size else "pending",
            "status": "archived" if is_archived else "not yet archived",
            "status_color": "success" if is_archived else "danger",
            "bookmarked_date": snapshot.bookmarked_date,
            "downloaded_datestr": snapshot.downloaded_datestr,
            "num_outputs": snapshot.num_outputs,
            "num_failures": snapshot.num_failures,
            "oldest_archive_date": ts_to_date_str(snapshot.oldest_archive_date),
            "warc_path": warc_path,
            "PREVIEW_ORIGINALS": SERVER_CONFIG.PREVIEW_ORIGINALS,
            "archiveresults": [*non_compact_outputs, *compact_outputs],
            "best_result": best_result,
            "snapshot": snapshot,  # Pass the snapshot object for template tags
            "related_snapshots": related_snapshots,
            "related_years": related_years,
            "loose_items": loose_items,
            "failed_items": failed_items,
            "title_tags": [{"name": tag.name, "style": tag_widget._tag_style(tag.name)} for tag in snapshot.tags.all().order_by("name")],
        }
        return render(template_name="core/snapshot.html", request=request, context=context)

    def get(self, request, path):
        if not request.user.is_authenticated and not SERVER_CONFIG.PUBLIC_SNAPSHOTS:
            return _admin_login_redirect_or_forbidden(request)

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
                    for snap in Snapshot.objects.filter(timestamp__startswith=slug)
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

        # slug is a URL
        try:
            try:
                snapshot = SnapshotView.find_snapshots_for_url(path).get()
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
            snapshots = SnapshotView.find_snapshots_for_url(path)
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
        if not request.user.is_authenticated and not SERVER_CONFIG.PUBLIC_SNAPSHOTS:
            return _admin_login_redirect_or_forbidden(request)

        if username == "system":
            return redirect(request.path.replace("/system/", "/web/", 1))

        if date and domain and domain == date:
            raise Http404

        requested_url = url
        if not requested_url and domain and domain.startswith(("http://", "https://")):
            requested_url = domain

        snapshot = None
        if snapshot_id:
            try:
                snapshot = Snapshot.objects.get(pk=snapshot_id)
            except Snapshot.DoesNotExist:
                try:
                    snapshot = Snapshot.objects.get(id__startswith=snapshot_id)
                except Snapshot.DoesNotExist:
                    snapshot = None
                except Snapshot.MultipleObjectsReturned:
                    snapshot = Snapshot.objects.filter(id__startswith=snapshot_id).first()
        else:
            # fuzzy lookup by date + domain/url (most recent)
            username_lookup = "system" if username == "web" else username
            if requested_url:
                qs = SnapshotView.find_snapshots_for_url(requested_url).filter(crawl__created_by__username=username_lookup)
            else:
                qs = Snapshot.objects.filter(crawl__created_by__username=username_lookup)

            if date:
                try:
                    if len(date) == 4:
                        qs = qs.filter(created_at__year=int(date))
                    elif len(date) == 6:
                        qs = qs.filter(created_at__year=int(date[:4]), created_at__month=int(date[4:6]))
                    elif len(date) == 8:
                        qs = qs.filter(
                            created_at__year=int(date[:4]),
                            created_at__month=int(date[4:6]),
                            created_at__day=int(date[6:8]),
                        )
                except ValueError:
                    pass

            if requested_url:
                snapshot = qs.order_by("-created_at", "-bookmarked_at", "-timestamp").first()
            else:
                requested_domain = domain or ""
                if requested_domain.startswith(("http://", "https://")):
                    requested_domain = Snapshot.extract_domain_from_url(requested_domain)
                else:
                    requested_domain = Snapshot.extract_domain_from_url(f"https://{requested_domain}")

                # Prefer exact domain matches
                matches = [
                    s for s in qs.order_by("-created_at", "-bookmarked_at") if Snapshot.extract_domain_from_url(s.url) == requested_domain
                ]
                snapshot = matches[0] if matches else qs.order_by("-created_at", "-bookmarked_at", "-timestamp").first()

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


def _latest_response_match(domain: str, rel_path: str) -> tuple[Path, Path] | None:
    if not domain or not rel_path:
        return None
    domain = domain.split(":", 1)[0].lower()
    # TODO: optimize by querying output_files in DB instead of globbing filesystem
    data_root = DATA_DIR / "users"
    escaped_domain = escape(domain)
    escaped_path = escape(rel_path)
    pattern = str(data_root / "*" / "snapshots" / "*" / escaped_domain / "*" / "responses" / escaped_domain / escaped_path)
    matches = glob(pattern)
    if not matches:
        return None

    sort_cache: dict[str, float] = {}
    best = max(matches, key=lambda match_path: _snapshot_sort_key(match_path, sort_cache))
    best_path = Path(best)
    parts = best_path.parts
    try:
        responses_idx = parts.index("responses")
    except ValueError:
        return None
    responses_root = Path(*parts[: responses_idx + 1])
    rel_to_root = Path(*parts[responses_idx + 1 :])
    return responses_root, rel_to_root


def _latest_responses_root(domain: str) -> Path | None:
    if not domain:
        return None
    domain = domain.split(":", 1)[0].lower()
    data_root = DATA_DIR / "users"
    escaped_domain = escape(domain)
    pattern = str(data_root / "*" / "snapshots" / "*" / escaped_domain / "*" / "responses" / escaped_domain)
    matches = glob(pattern)
    if not matches:
        return None

    sort_cache: dict[str, float] = {}
    best = max(matches, key=lambda match_path: _snapshot_sort_key(match_path, sort_cache))
    return Path(best)


def _latest_snapshot_for_domain(domain: str) -> Snapshot | None:
    if not domain:
        return None

    requested_domain = domain.split(":", 1)[0].lower()
    snapshots = SnapshotView.find_snapshots_for_url(f"https://{requested_domain}").order_by("-created_at", "-bookmarked_at", "-timestamp")
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
    is_directory_request = bool(path) and path.endswith("/")
    show_indexes = bool(request.GET.get("files")) or (SERVER_CONFIG.USES_SUBDOMAIN_ROUTING and is_directory_request)
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
    requested_root_index = path in ("", "index.html") or path.endswith("/")
    rel_path = path or ""
    if not rel_path or rel_path.endswith("/"):
        rel_path = f"{rel_path}index.html"
    rel_path = _safe_archive_relpath(rel_path)
    if rel_path is None:
        raise Http404

    domain = domain.lower()
    match = _latest_response_match(domain, rel_path)
    if not match and "." not in Path(rel_path).name:
        index_path = f"{rel_path.rstrip('/')}/index.html"
        match = _latest_response_match(domain, index_path)
    if not match and "." not in Path(rel_path).name:
        html_path = f"{rel_path}.html"
        match = _latest_response_match(domain, html_path)

    show_indexes = bool(request.GET.get("files"))
    if match:
        responses_root, rel_to_root = match
        response = _serve_responses_path(request, responses_root, str(rel_to_root), show_indexes)
        if response is not None:
            return response

    responses_root = _latest_responses_root(domain)
    if responses_root:
        response = _serve_responses_path(request, responses_root, rel_path, show_indexes)
        if response is not None:
            return response

    if requested_root_index and not show_indexes:
        snapshot = _latest_snapshot_for_domain(domain)
        if snapshot:
            return SnapshotView.render_live_index(request, snapshot)

    if SERVER_CONFIG.PUBLIC_ADD_VIEW or request.user.is_authenticated:
        target_url = _original_request_url(domain, path, request.META.get("QUERY_STRING", ""))
        return redirect(build_web_url(f"/web/{quote(target_url, safe=':/')}"))

    raise Http404


class SnapshotHostView(View):
    """Serve snapshot directory contents on <snapshot-subdomain>.<listen_host>/<path>."""

    def get(self, request, snapshot_id: str, path: str = ""):
        if not request.user.is_authenticated and not SERVER_CONFIG.PUBLIC_SNAPSHOTS:
            return _admin_login_redirect_or_forbidden(request)
        snapshot = _find_snapshot_by_ref(snapshot_id)

        if not snapshot:
            raise Http404

        canonical_host = get_snapshot_host(str(snapshot.id))
        if not host_matches(request.get_host(), canonical_host):
            target = build_snapshot_url(str(snapshot.id), path, request=request)
            if request.META.get("QUERY_STRING"):
                target = f"{target}?{request.META['QUERY_STRING']}"
            return redirect(target)

        return _serve_snapshot_replay(request, snapshot, path)


class SnapshotReplayView(View):
    """Serve snapshot directory contents on a one-domain replay path."""

    def get(self, request, snapshot_id: str, path: str = ""):
        if not request.user.is_authenticated and not SERVER_CONFIG.PUBLIC_SNAPSHOTS:
            return _admin_login_redirect_or_forbidden(request)

        snapshot = _find_snapshot_by_ref(snapshot_id)
        if not snapshot:
            raise Http404

        return _serve_snapshot_replay(request, snapshot, path)


class OriginalDomainHostView(View):
    """Serve responses from the most recent snapshot when using <domain>.<listen_host>/<path>."""

    def get(self, request, domain: str, path: str = ""):
        if not request.user.is_authenticated and not SERVER_CONFIG.PUBLIC_SNAPSHOTS:
            return _admin_login_redirect_or_forbidden(request)
        return _serve_original_domain_replay(request, domain, path)


class OriginalDomainReplayView(View):
    """Serve original-domain replay content on a one-domain replay path."""

    def get(self, request, domain: str, path: str = ""):
        if not request.user.is_authenticated and not SERVER_CONFIG.PUBLIC_SNAPSHOTS:
            return _admin_login_redirect_or_forbidden(request)
        return _serve_original_domain_replay(request, domain, path)


class PublicIndexView(ListView):
    template_name = "public_index.html"
    model = Snapshot
    paginate_by = SERVER_CONFIG.SNAPSHOTS_PER_PAGE
    ordering = ["-bookmarked_at", "-created_at"]

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            "VERSION": VERSION,
            "COMMIT_HASH": SHELL_CONFIG.COMMIT_HASH,
            "FOOTER_INFO": SERVER_CONFIG.FOOTER_INFO,
            "search_mode": get_search_mode(self.request.GET.get("search_mode")),
        }

    def get_queryset(self, **kwargs):
        qs = super().get_queryset(**kwargs)
        query = self.request.GET.get("q", default="").strip()

        if not query:
            return qs.distinct()

        query_type = self.request.GET.get("query_type")
        search_mode = get_search_mode(self.request.GET.get("search_mode"))

        if not query_type or query_type == "all":
            metadata_qs = qs.filter(
                Q(title__icontains=query) | Q(url__icontains=query) | Q(timestamp__icontains=query) | Q(tags__name__icontains=query),
            )
            if search_mode == "meta":
                qs = metadata_qs
            else:
                try:
                    qs = prioritize_metadata_matches(
                        qs,
                        metadata_qs,
                        query_search_index(query, search_mode=search_mode),
                        ordering=self.ordering,
                    )
                except Exception as err:
                    print(f"[!] Error while using search backend: {err.__class__.__name__} {err}")
                    qs = metadata_qs
        elif query_type == "fulltext":
            if search_mode == "meta":
                qs = qs.none()
            else:
                try:
                    qs = query_search_index(query, search_mode=search_mode).filter(pk__in=qs.values("pk"))
                except Exception as err:
                    print(f"[!] Error while using search backend: {err.__class__.__name__} {err}")
                    qs = qs.none()
        elif query_type == "meta":
            qs = qs.filter(
                Q(title__icontains=query) | Q(url__icontains=query) | Q(timestamp__icontains=query) | Q(tags__name__icontains=query),
            )
        elif query_type == "url":
            qs = qs.filter(Q(url__icontains=query))
        elif query_type == "title":
            qs = qs.filter(Q(title__icontains=query))
        elif query_type == "timestamp":
            qs = qs.filter(Q(timestamp__icontains=query))
        elif query_type == "tags":
            qs = qs.filter(Q(tags__name__icontains=query))
        else:
            print(f'[!] Unknown value for query_type: "{query_type}"')

        return qs.distinct()

    def get(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return redirect("/admin/core/snapshot/")
        if SERVER_CONFIG.PUBLIC_INDEX:
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

    def test_func(self):
        return SERVER_CONFIG.PUBLIC_ADD_VIEW or self.request.user.is_authenticated

    def _can_override_crawl_config(self) -> bool:
        user = self.request.user
        return bool(user.is_authenticated and (getattr(user, "is_superuser", False) or getattr(user, "is_staff", False)))

    def _get_custom_config_overrides(self, form: AddLinkForm) -> dict:
        custom_config = form.cleaned_data.get("config") or {}

        if not isinstance(custom_config, dict):
            return {}

        if not self._can_override_crawl_config():
            return {}

        return custom_config

    def get_context_data(self, **kwargs):
        required_search_plugin = f"search_backend_{SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE}".strip()
        plugin_configs = discover_plugin_configs()
        plugin_dependency_map = {
            plugin_name: [
                str(required_plugin).strip() for required_plugin in (schema.get("required_plugins") or []) if str(required_plugin).strip()
            ]
            for plugin_name, schema in plugin_configs.items()
            if isinstance(schema.get("required_plugins"), list) and schema.get("required_plugins")
        }
        return {
            **super().get_context_data(**kwargs),
            "title": "Create Crawl",
            # We can't just call request.build_absolute_uri in the template, because it would include query parameters
            "absolute_add_path": self.request.build_absolute_uri(self.request.path),
            "VERSION": VERSION,
            "FOOTER_INFO": SERVER_CONFIG.FOOTER_INFO,
            "required_search_plugin": required_search_plugin,
            "plugin_dependency_map_json": json.dumps(plugin_dependency_map, sort_keys=True),
            "stdout": "",
        }

    def _create_crawl_from_form(self, form, *, created_by_id=None) -> Crawl:
        urls = form.cleaned_data["url"]
        print(f"[+] Adding URL: {urls}")

        # Extract all form fields
        tag = form.cleaned_data["tag"]
        depth = int(form.cleaned_data["depth"])
        max_urls = int(form.cleaned_data.get("max_urls") or 0)
        max_size = int(form.cleaned_data.get("max_size") or 0)
        plugins = ",".join(form.cleaned_data.get("plugins", []))
        schedule = form.cleaned_data.get("schedule", "").strip()
        persona = form.cleaned_data.get("persona")
        index_only = form.cleaned_data.get("index_only", False)
        notes = form.cleaned_data.get("notes", "")
        url_filters = form.cleaned_data.get("url_filters") or {}
        custom_config = self._get_custom_config_overrides(form)

        from archivebox.config.permissions import HOSTNAME

        if created_by_id is None:
            if self.request.user.is_authenticated:
                created_by_id = self.request.user.pk
            else:
                from archivebox.base_models.models import get_or_create_system_user_pk

                created_by_id = get_or_create_system_user_pk()

        created_by_name = getattr(self.request.user, "username", "web") if self.request.user.is_authenticated else "web"

        # 1. save the provided urls to sources/2024-11-05__23-59-59__web_ui_add_by_user_<user_pk>.txt
        sources_file = CONSTANTS.SOURCES_DIR / f"{timezone.now().strftime('%Y-%m-%d__%H-%M-%S')}__web_ui_add_by_user_{created_by_id}.txt"
        sources_file.parent.mkdir(parents=True, exist_ok=True)
        sources_file.write_text(urls if isinstance(urls, str) else "\n".join(urls))

        # 2. create a new Crawl with the URLs from the file
        timestamp = timezone.now().strftime("%Y-%m-%d__%H-%M-%S")
        urls_content = sources_file.read_text()
        # Build complete config
        config = {
            "INDEX_ONLY": index_only,
            "DEPTH": depth,
            "PLUGINS": plugins or "",
            "DEFAULT_PERSONA": (persona.name if persona else "Default"),
        }

        # Merge custom config overrides
        config.update(custom_config)
        if url_filters.get("allowlist"):
            config["URL_ALLOWLIST"] = url_filters["allowlist"]
        if url_filters.get("denylist"):
            config["URL_DENYLIST"] = url_filters["denylist"]

        crawl = Crawl.objects.create(
            urls=urls_content,
            max_depth=depth,
            max_urls=max_urls,
            max_size=max_size,
            tags_str=tag,
            notes=notes,
            label=f"{created_by_name}@{HOSTNAME}{self.request.path} {timestamp}",
            created_by_id=created_by_id,
            config=config,
        )

        # 3. create a CrawlSchedule if schedule is provided
        if schedule:
            from archivebox.crawls.models import CrawlSchedule

            crawl_schedule = CrawlSchedule.objects.create(
                template=crawl,
                schedule=schedule,
                is_enabled=True,
                label=crawl.label,
                notes=f"Auto-created from add page. {notes}".strip(),
                created_by_id=created_by_id,
            )
            crawl.schedule = crawl_schedule
            crawl.save(update_fields=["schedule"])

        crawl.create_snapshots_from_urls()
        from archivebox.services.runner import ensure_background_runner

        ensure_background_runner()

        # 4. start the Orchestrator & wait until it completes
        #    ... orchestrator will create the root Snapshot, which creates pending ArchiveResults, which gets run by the ArchiveResultActors ...
        # from archivebox.crawls.actors import CrawlActor
        # from archivebox.core.actors import SnapshotActor, ArchiveResultActor

        return crawl

    def form_valid(self, form):
        crawl = self._create_crawl_from_form(form)

        urls = form.cleaned_data["url"]
        schedule = form.cleaned_data.get("schedule", "").strip()
        rough_url_count = len([url for url in urls.splitlines() if url.strip()])

        # Build success message with schedule link if created
        schedule_msg = ""
        if schedule:
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
        return SnapshotView.find_snapshots_for_url(requested_url).order_by("-created_at", "-bookmarked_at", "-timestamp").first()

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

        if not self.test_func():
            request_host = (request.get_host() or "").lower()
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
        form_data = {
            "url": add_url,
            "depth": defaults_form.fields["depth"].initial or "0",
            "max_urls": defaults_form.fields["max_urls"].initial or 0,
            "max_size": defaults_form.fields["max_size"].initial or "0",
            "persona": defaults_form.fields["persona"].initial or "Default",
            "config": {},
        }
        if defaults_form.fields["index_only"].initial:
            form_data["index_only"] = "on"

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


def live_progress_view(request):
    """Simple JSON endpoint for live progress status - used by admin progress monitor."""
    try:
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot, ArchiveResult
        from archivebox.machine.models import Process, Machine

        def is_current_run_timestamp(event_ts, run_started_at) -> bool:
            if run_started_at is None:
                return True
            if event_ts is None:
                return False
            return event_ts >= run_started_at

        def archiveresult_matches_current_run(ar, run_started_at) -> bool:
            if run_started_at is None:
                return True
            if ar.status in (
                ArchiveResult.StatusChoices.QUEUED,
                ArchiveResult.StatusChoices.STARTED,
                ArchiveResult.StatusChoices.BACKOFF,
            ):
                return True
            event_ts = ar.end_ts or ar.start_ts or ar.modified_at or ar.created_at
            return is_current_run_timestamp(event_ts, run_started_at)

        def hook_details(hook_name: str, plugin: str = "setup") -> tuple[str, str, str, str]:
            normalized_hook_name = Path(hook_name).name if hook_name else ""
            if not normalized_hook_name:
                return (plugin, plugin, "unknown", "")

            phase = "unknown"
            if normalized_hook_name == "InstallEvent":
                phase = "install"
            elif normalized_hook_name.startswith("on_CrawlSetup__"):
                phase = "crawl"
            elif normalized_hook_name.startswith("on_Snapshot__"):
                phase = "snapshot"
            elif normalized_hook_name.startswith("on_BinaryRequest__"):
                phase = "binary"

            label = normalized_hook_name
            if "__" in normalized_hook_name:
                label = normalized_hook_name.split("__", 1)[1]
            label = label.rsplit(".", 1)[0]
            if len(label) > 3 and label[:2].isdigit() and label[2] == "_":
                label = label[3:]
            label = label.replace("_", " ").strip() or plugin

            return (plugin, label, phase, normalized_hook_name)

        def process_label(cmd: list[str] | None) -> tuple[str, str, str, str]:
            hook_path = ""
            if isinstance(cmd, list) and cmd:
                first = cmd[0]
                if isinstance(first, str):
                    hook_path = first

            if not hook_path:
                return ("", "setup", "unknown", "")

            return hook_details(Path(hook_path).name, plugin=Path(hook_path).parent.name or "setup")

        machine = Machine.current()
        Process.cleanup_stale_running(machine=machine)
        Process.cleanup_orphaned_workers()
        orchestrator_proc = (
            Process.objects.filter(
                machine=machine,
                process_type=Process.TypeChoices.ORCHESTRATOR,
                status=Process.StatusChoices.RUNNING,
            )
            .order_by("-started_at")
            .first()
        )
        orchestrator_running = orchestrator_proc is not None
        orchestrator_pid = orchestrator_proc.pid if orchestrator_proc else None
        # Get model counts by status
        crawls_pending = Crawl.objects.filter(status=Crawl.StatusChoices.QUEUED).count()
        crawls_started = Crawl.objects.filter(status=Crawl.StatusChoices.STARTED).count()

        # Get recent crawls (last 24 hours)
        from datetime import timedelta

        one_day_ago = timezone.now() - timedelta(days=1)
        crawls_recent = Crawl.objects.filter(created_at__gte=one_day_ago).count()

        snapshots_pending = Snapshot.objects.filter(status=Snapshot.StatusChoices.QUEUED).count()
        snapshots_started = Snapshot.objects.filter(status=Snapshot.StatusChoices.STARTED).count()

        archiveresults_pending = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.QUEUED).count()
        archiveresults_started = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.STARTED).count()
        archiveresults_succeeded = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.SUCCEEDED).count()
        archiveresults_failed = ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.FAILED).count()

        # Get recently completed ArchiveResults with thumbnails (last 20 succeeded results)
        recent_thumbnails = []
        recent_results = (
            ArchiveResult.objects.filter(
                status=ArchiveResult.StatusChoices.SUCCEEDED,
            )
            .select_related("snapshot")
            .order_by("-end_ts")[:20]
        )

        for ar in recent_results:
            embed = ar.embed_path()
            if embed:
                # Only include results with embeddable image/media files
                ext = embed.lower().split(".")[-1] if "." in embed else ""
                is_embeddable = ext in ("png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "pdf", "html")
                if is_embeddable or ar.plugin in ("screenshot", "favicon", "dom"):
                    archive_path = embed or ""
                    recent_thumbnails.append(
                        {
                            "id": str(ar.id),
                            "plugin": ar.plugin,
                            "snapshot_id": str(ar.snapshot_id),
                            "snapshot_url": ar.snapshot.url[:60] if ar.snapshot else "",
                            "embed_path": embed,
                            "archive_path": archive_path,
                            "archive_url": build_snapshot_url(str(ar.snapshot_id), archive_path, request=request) if archive_path else "",
                            "end_ts": ar.end_ts.isoformat() if ar.end_ts else None,
                        },
                    )

        # Build hierarchical active crawls with nested snapshots and archive results

        running_processes = Process.objects.filter(
            machine=machine,
            status=Process.StatusChoices.RUNNING,
            process_type__in=[
                Process.TypeChoices.HOOK,
                Process.TypeChoices.BINARY,
            ],
        )
        recent_processes = Process.objects.filter(
            machine=machine,
            process_type__in=[
                Process.TypeChoices.HOOK,
                Process.TypeChoices.BINARY,
            ],
            modified_at__gte=timezone.now() - timedelta(minutes=10),
        ).order_by("-modified_at")
        crawl_process_pids: dict[str, int] = {}
        snapshot_process_pids: dict[str, int] = {}
        process_records_by_crawl: dict[str, list[tuple[dict[str, object], object | None]]] = {}
        process_records_by_snapshot: dict[str, list[tuple[dict[str, object], object | None]]] = {}
        seen_process_records: set[str] = set()
        for proc in running_processes:
            env = proc.env or {}
            if not isinstance(env, dict):
                env = {}

            crawl_id = env.get("CRAWL_ID")
            snapshot_id = env.get("SNAPSHOT_ID")
            _plugin, _label, phase, _hook_name = process_label(proc.cmd)
            if crawl_id and proc.pid:
                crawl_process_pids.setdefault(str(crawl_id), proc.pid)
            if phase == "snapshot" and snapshot_id and proc.pid:
                snapshot_process_pids.setdefault(str(snapshot_id), proc.pid)

        for proc in recent_processes:
            env = proc.env or {}
            if not isinstance(env, dict):
                env = {}

            crawl_id = env.get("CRAWL_ID")
            snapshot_id = env.get("SNAPSHOT_ID")
            if not crawl_id and not snapshot_id:
                continue

            plugin, label, phase, hook_name = process_label(proc.cmd)

            record_scope = str(snapshot_id) if phase == "snapshot" and snapshot_id else str(crawl_id)
            proc_key = f"{record_scope}:{plugin}:{label}:{proc.status}:{proc.exit_code}"
            if proc_key in seen_process_records:
                continue
            seen_process_records.add(proc_key)

            status = (
                "started"
                if proc.status == Process.StatusChoices.RUNNING
                else ("failed" if proc.exit_code not in (None, 0) else "succeeded")
            )
            payload: dict[str, object] = {
                "id": str(proc.id),
                "plugin": plugin,
                "label": label,
                "hook_name": hook_name,
                "status": status,
                "phase": phase,
                "source": "process",
                "process_id": str(proc.id),
            }
            if status == "started" and proc.pid:
                payload["pid"] = proc.pid
            proc_started_at = proc.started_at or proc.modified_at
            if phase == "snapshot" and snapshot_id:
                process_records_by_snapshot.setdefault(str(snapshot_id), []).append((payload, proc_started_at))
            elif crawl_id:
                process_records_by_crawl.setdefault(str(crawl_id), []).append((payload, proc_started_at))

        active_crawls_qs = (
            Crawl.objects.filter(status__in=[Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED])
            .prefetch_related(
                "snapshot_set",
                "snapshot_set__archiveresult_set",
                "snapshot_set__archiveresult_set__process",
            )
            .distinct()
            .order_by("-modified_at")[:10]
        )

        active_crawls = []
        total_workers = 0
        for crawl in active_crawls_qs:
            # Get ALL snapshots for this crawl to count status (already prefetched)
            all_crawl_snapshots = list(crawl.snapshot_set.all())

            # Count snapshots by status from ALL snapshots
            total_snapshots = len(all_crawl_snapshots)
            completed_snapshots = sum(1 for s in all_crawl_snapshots if s.status == Snapshot.StatusChoices.SEALED)
            started_snapshots = sum(1 for s in all_crawl_snapshots if s.status == Snapshot.StatusChoices.STARTED)
            pending_snapshots = sum(1 for s in all_crawl_snapshots if s.status == Snapshot.StatusChoices.QUEUED)

            # Get only ACTIVE snapshots to display (limit to 5 most recent)
            active_crawl_snapshots = [
                s for s in all_crawl_snapshots if s.status in [Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED]
            ][:5]

            # Count URLs in the crawl (for when snapshots haven't been created yet)
            urls_count = 0
            if crawl.urls:
                urls_count = len([u for u in crawl.urls.split("\n") if u.strip() and not u.startswith("#")])

            # Calculate crawl progress
            crawl_progress = int((completed_snapshots / total_snapshots) * 100) if total_snapshots > 0 else 0
            crawl_run_started_at = crawl.created_at
            crawl_setup_plugins = [
                payload
                for payload, proc_started_at in process_records_by_crawl.get(str(crawl.id), [])
                if is_current_run_timestamp(proc_started_at, crawl_run_started_at)
            ]
            total_workers += sum(1 for item in crawl_setup_plugins if item.get("source") == "process" and item.get("status") == "started")
            crawl_setup_total = len(crawl_setup_plugins)
            crawl_setup_completed = sum(1 for item in crawl_setup_plugins if item.get("status") == "succeeded")
            crawl_setup_failed = sum(1 for item in crawl_setup_plugins if item.get("status") == "failed")
            crawl_setup_pending = sum(1 for item in crawl_setup_plugins if item.get("status") == "queued")

            # Get active snapshots for this crawl (already prefetched)
            active_snapshots_for_crawl = []
            for snapshot in active_crawl_snapshots:
                snapshot_run_started_at = snapshot.downloaded_at or snapshot.created_at
                # Get archive results for this snapshot (already prefetched)
                snapshot_results = [
                    ar for ar in snapshot.archiveresult_set.all() if archiveresult_matches_current_run(ar, snapshot_run_started_at)
                ]

                now = timezone.now()
                plugin_progress_values: list[int] = []
                all_plugins: list[dict[str, object]] = []
                seen_plugin_keys: set[str] = set()

                def plugin_sort_key(ar):
                    status_order = {
                        ArchiveResult.StatusChoices.STARTED: 0,
                        ArchiveResult.StatusChoices.QUEUED: 1,
                        ArchiveResult.StatusChoices.SUCCEEDED: 2,
                        ArchiveResult.StatusChoices.NORESULTS: 3,
                        ArchiveResult.StatusChoices.FAILED: 4,
                    }
                    return (status_order.get(ar.status, 5), ar.plugin, ar.hook_name or "")

                for ar in sorted(snapshot_results, key=plugin_sort_key):
                    status = ar.status
                    progress_value = 0
                    if status in (
                        ArchiveResult.StatusChoices.SUCCEEDED,
                        ArchiveResult.StatusChoices.FAILED,
                        ArchiveResult.StatusChoices.SKIPPED,
                        ArchiveResult.StatusChoices.NORESULTS,
                    ):
                        progress_value = 100
                    elif status == ArchiveResult.StatusChoices.STARTED:
                        started_at = ar.start_ts or (ar.process.started_at if ar.process_id and ar.process else None)
                        timeout = ar.timeout or 120
                        if started_at and timeout:
                            elapsed = max(0.0, (now - started_at).total_seconds())
                            progress_value = int(min(99, max(1, (elapsed / float(timeout)) * 100)))
                        else:
                            progress_value = 1
                    else:
                        progress_value = 0

                    plugin_progress_values.append(progress_value)
                    plugin, label, phase, hook_name = hook_details(ar.hook_name or ar.plugin, plugin=ar.plugin)

                    plugin_payload = {
                        "id": str(ar.id),
                        "plugin": ar.plugin,
                        "label": label,
                        "hook_name": hook_name,
                        "phase": phase,
                        "status": status,
                        "process_id": str(ar.process_id) if ar.process_id else None,
                    }
                    if status == ArchiveResult.StatusChoices.STARTED and ar.process_id and ar.process:
                        plugin_payload["pid"] = ar.process.pid
                    if status == ArchiveResult.StatusChoices.STARTED:
                        plugin_payload["progress"] = progress_value
                        plugin_payload["timeout"] = ar.timeout or 120
                    plugin_payload["source"] = "archiveresult"
                    all_plugins.append(plugin_payload)
                    seen_plugin_keys.add(str(ar.process_id) if ar.process_id else f"{ar.plugin}:{hook_name}")

                for proc_payload, proc_started_at in process_records_by_snapshot.get(str(snapshot.id), []):
                    if not is_current_run_timestamp(proc_started_at, snapshot_run_started_at):
                        continue
                    proc_key = str(proc_payload.get("process_id") or f"{proc_payload.get('plugin')}:{proc_payload.get('hook_name')}")
                    if proc_key in seen_plugin_keys:
                        continue
                    seen_plugin_keys.add(proc_key)
                    all_plugins.append(proc_payload)

                    proc_status = proc_payload.get("status")
                    if proc_status in ("succeeded", "failed", "skipped"):
                        plugin_progress_values.append(100)
                    elif proc_status == "started":
                        plugin_progress_values.append(1)
                        total_workers += 1
                    else:
                        plugin_progress_values.append(0)

                total_plugins = len(all_plugins)
                completed_plugins = sum(1 for item in all_plugins if item.get("status") == "succeeded")
                failed_plugins = sum(1 for item in all_plugins if item.get("status") == "failed")
                pending_plugins = sum(1 for item in all_plugins if item.get("status") == "queued")

                snapshot_progress = int(sum(plugin_progress_values) / len(plugin_progress_values)) if plugin_progress_values else 0

                active_snapshots_for_crawl.append(
                    {
                        "id": str(snapshot.id),
                        "url": snapshot.url[:80],
                        "status": snapshot.status,
                        "started": (snapshot.downloaded_at or snapshot.created_at).isoformat()
                        if (snapshot.downloaded_at or snapshot.created_at)
                        else None,
                        "progress": snapshot_progress,
                        "total_plugins": total_plugins,
                        "completed_plugins": completed_plugins,
                        "failed_plugins": failed_plugins,
                        "pending_plugins": pending_plugins,
                        "all_plugins": all_plugins,
                        "worker_pid": snapshot_process_pids.get(str(snapshot.id)),
                    },
                )

            # Check if crawl can start (for debugging stuck crawls)
            can_start = bool(crawl.urls)
            urls_preview = crawl.urls[:60] if crawl.urls else None

            # Check if retry_at is in the future (would prevent worker from claiming)
            retry_at_future = crawl.retry_at > timezone.now() if crawl.retry_at else False
            seconds_until_retry = int((crawl.retry_at - timezone.now()).total_seconds()) if crawl.retry_at and retry_at_future else 0

            active_crawls.append(
                {
                    "id": str(crawl.id),
                    "label": str(crawl)[:60],
                    "status": crawl.status,
                    "started": crawl.created_at.isoformat() if crawl.created_at else None,
                    "progress": crawl_progress,
                    "max_depth": crawl.max_depth,
                    "urls_count": urls_count,
                    "total_snapshots": total_snapshots,
                    "completed_snapshots": completed_snapshots,
                    "started_snapshots": started_snapshots,
                    "failed_snapshots": 0,
                    "pending_snapshots": pending_snapshots,
                    "setup_plugins": crawl_setup_plugins,
                    "setup_total_plugins": crawl_setup_total,
                    "setup_completed_plugins": crawl_setup_completed,
                    "setup_failed_plugins": crawl_setup_failed,
                    "setup_pending_plugins": crawl_setup_pending,
                    "active_snapshots": active_snapshots_for_crawl,
                    "can_start": can_start,
                    "urls_preview": urls_preview,
                    "retry_at_future": retry_at_future,
                    "seconds_until_retry": seconds_until_retry,
                    "worker_pid": crawl_process_pids.get(str(crawl.id)),
                },
            )

        return JsonResponse(
            {
                "orchestrator_running": orchestrator_running,
                "orchestrator_pid": orchestrator_pid,
                "total_workers": total_workers,
                "crawls_pending": crawls_pending,
                "crawls_started": crawls_started,
                "crawls_recent": crawls_recent,
                "snapshots_pending": snapshots_pending,
                "snapshots_started": snapshots_started,
                "archiveresults_pending": archiveresults_pending,
                "archiveresults_started": archiveresults_started,
                "archiveresults_succeeded": archiveresults_succeeded,
                "archiveresults_failed": archiveresults_failed,
                "active_crawls": active_crawls,
                "recent_thumbnails": recent_thumbnails,
                "server_time": timezone.now().isoformat(),
            },
        )
    except Exception as e:
        import traceback

        return JsonResponse(
            {
                "error": str(e),
                "traceback": traceback.format_exc(),
                "orchestrator_running": False,
                "total_workers": 0,
                "crawls_pending": 0,
                "crawls_started": 0,
                "crawls_recent": 0,
                "snapshots_pending": 0,
                "snapshots_started": 0,
                "archiveresults_pending": 0,
                "archiveresults_started": 0,
                "archiveresults_succeeded": 0,
                "archiveresults_failed": 0,
                "active_crawls": [],
                "recent_thumbnails": [],
                "server_time": timezone.now().isoformat(),
            },
            status=500,
        )


def find_config_section(key: str) -> str:
    CONFIGS = get_all_configs()

    if key in CONSTANTS_CONFIG:
        return "CONSTANT"
    matching_sections = [section_id for section_id, section in CONFIGS.items() if key in dict(section)]
    section = matching_sections[0] if matching_sections else "DYNAMIC"
    return section


def find_config_default(key: str) -> str:
    CONFIGS = get_all_configs()

    if key in CONSTANTS_CONFIG:
        return str(CONSTANTS_CONFIG[key])

    default_val = None

    for config in CONFIGS.values():
        if key in dict(config):
            default_field = getattr(config, "model_fields", dict(config))[key]
            default_val = default_field.default if hasattr(default_field, "default") else default_field
            break

    if isinstance(default_val, Callable):
        default_val = inspect.getsource(default_val).split("lambda", 1)[-1].split(":", 1)[-1].replace("\n", " ").strip()
        if default_val.count(")") > default_val.count("("):
            default_val = default_val[:-1]
    else:
        default_val = str(default_val)

    return default_val


def find_config_type(key: str) -> str:
    from typing import ClassVar

    CONFIGS = get_all_configs()

    for config in CONFIGS.values():
        if hasattr(config, key):
            # Try to get from pydantic model_fields first (more reliable)
            if hasattr(config, "model_fields") and key in config.model_fields:
                field = config.model_fields[key]
                if hasattr(field, "annotation") and field.annotation is not None:
                    try:
                        return str(field.annotation.__name__)
                    except AttributeError:
                        return str(field.annotation)

            # Fallback to get_type_hints with proper namespace
            try:
                import typing

                namespace = {
                    "ClassVar": ClassVar,
                    "Optional": typing.Optional,
                    "Union": typing.Union,
                    "List": list,
                    "Dict": dict,
                    "Path": Path,
                }
                type_hints = get_type_hints(config, globalns=namespace, localns=namespace)
                try:
                    return str(type_hints[key].__name__)
                except AttributeError:
                    return str(type_hints[key])
            except Exception:
                # If all else fails, return str
                pass
    return "str"


def key_is_safe(key: str) -> bool:
    for term in ("key", "password", "secret", "token"):
        if term in key.lower():
            return False
    return True


def find_config_source(key: str, merged_config: dict) -> str:
    """Determine where a config value comes from."""
    from archivebox.machine.models import Machine

    # Environment variables override all persistent config sources.
    if key in os.environ:
        return "Environment"

    # Machine.config overrides ArchiveBox.conf.
    try:
        machine = Machine.current()
        if machine.config and key in machine.config:
            return "Machine"
    except Exception:
        pass

    # Check if it's from archivebox.config.file
    from archivebox.config.configset import BaseConfigSet

    file_config = BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE)
    if key in file_config:
        return "Config File"

    # Otherwise it's using the default
    return "Default"


def find_plugin_for_config_key(key: str) -> str | None:
    for plugin_name, schema in discover_plugin_configs().items():
        if key in (schema.get("properties") or {}):
            return plugin_name
    return None


def get_config_definition_link(key: str) -> tuple[str, str]:
    plugin_name = find_plugin_for_config_key(key)
    if not plugin_name:
        return (
            f"https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{quote(key)}&type=code",
            "archivebox/config",
        )

    plugin_dir = next((path.resolve() for path in iter_plugin_dirs() if path.name == plugin_name), None)
    if plugin_dir:
        builtin_root = BUILTIN_PLUGINS_DIR.resolve()
        if plugin_dir.is_relative_to(builtin_root):
            return (
                f"{ABX_PLUGINS_GITHUB_BASE_URL}{quote(plugin_name)}/config.json",
                f"abx_plugins/plugins/{plugin_name}/config.json",
            )

        user_root = USER_PLUGINS_DIR.resolve()
        if plugin_dir.is_relative_to(user_root):
            return (
                f"{LIVE_PLUGIN_BASE_URL}user.{quote(plugin_name)}/",
                f"data/custom_plugins/{plugin_name}/config.json",
            )

    return (
        f"{LIVE_PLUGIN_BASE_URL}builtin.{quote(plugin_name)}/",
        f"abx_plugins/plugins/{plugin_name}/config.json",
    )


@render_with_table_view
def live_config_list_view(request: HttpRequest, **kwargs) -> TableContext:
    CONFIGS = get_all_configs()

    assert getattr(request.user, "is_superuser", False), "Must be a superuser to view configuration settings."

    # Get merged config that includes Machine.config overrides
    try:
        from archivebox.machine.models import Machine

        Machine.current()
        merged_config = get_config()
    except Exception:
        # Fallback if Machine model not available
        merged_config = get_config()

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
            actual_value = merged_config.get(key, getattr(section, key, None))
            rows["Value"].append(mark_safe(f"<code>{actual_value}</code>") if key_is_safe(key) else "******** (redacted)")

            # Show where the value comes from
            source = find_config_source(key, merged_config)
            source_colors = {"Machine": "purple", "Environment": "blue", "Config File": "green", "Default": "gray"}
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
        rows["Type"].append(format_html("<code>{}</code>", getattr(type(CONSTANTS_CONFIG[key]), "__name__", str(CONSTANTS_CONFIG[key]))))
        rows["Value"].append(format_html("<code>{}</code>", CONSTANTS_CONFIG[key]) if key_is_safe(key) else "******** (redacted)")
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
    from archivebox.config.configset import BaseConfigSet

    CONFIGS = get_all_configs()
    FLAT_CONFIG = get_flat_config()

    assert getattr(request.user, "is_superuser", False), "Must be a superuser to view configuration settings."

    # Get merged config
    merged_config = get_config()

    # Determine all sources for this config value
    sources_info = []

    # Environment variable
    if key in os.environ:
        sources_info.append(("Environment", os.environ[key] if key_is_safe(key) else "********", "blue"))

    # Machine config
    machine = None
    machine_admin_url = None
    try:
        machine = Machine.current()
        machine_admin_url = f"/admin/machine/machine/{machine.id}/change/"
        if machine.config and key in machine.config:
            sources_info.append(("Machine", machine.config[key] if key_is_safe(key) else "********", "purple"))
    except Exception:
        pass

    # Config file value
    if CONSTANTS.CONFIG_FILE.exists():
        file_config = BaseConfigSet.load_from_file(CONSTANTS.CONFIG_FILE)
        if key in file_config:
            sources_info.append(("Config File", file_config[key], "green"))

    # Default value
    default_val = find_config_default(key)
    if default_val:
        sources_info.append(("Default", default_val, "gray"))

    # Final computed value
    final_value = merged_config.get(key, FLAT_CONFIG.get(key, CONFIGS.get(key, None)))
    if not key_is_safe(key):
        final_value = "********"

    # Build sources display
    sources_html = "<br/>".join([f'<b style="color: {color}">{source}:</b> <code>{value}</code>' for source, value, color in sources_info])

    # aliases = USER_CONFIG.get(key, {}).get("aliases", [])
    aliases = []

    if key in CONSTANTS_CONFIG:
        section_header = mark_safe(
            f'[CONSTANTS]   &nbsp; <b><code style="color: lightgray">{key}</code></b> &nbsp; <small>(read-only, hardcoded by ArchiveBox)</small>',
        )
    elif key in FLAT_CONFIG:
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
                "Currently read from": find_config_source(key, merged_config),
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
                    if not key_is_safe(key)
                    else ""
                }
                <br/><hr/><br/>
                <b>Configuration Sources (highest priority first):</b><br/><br/>
                {sources_html}
                <br/><br/>
                <p style="display: {"block" if key in FLAT_CONFIG and key not in CONSTANTS_CONFIG else "none"}">
                    <i>To change this value, edit <code>data/ArchiveBox.conf</code> or run:</i>
                    <br/><br/>
                    <code>archivebox config --set {key}="{
                    val.strip("'")
                    if (val := find_config_default(key))
                    else (str(FLAT_CONFIG[key] if key_is_safe(key) else "********")).strip("'")
                }"</code>
                </p>
            '''),
                "Currently read from": mark_safe(f"""
                The value shown in the "Value" field comes from the <b>{find_config_source(key, merged_config)}</b> source.
                <br/><br/>
                Priority order (highest to lowest):
                <ol>
                    <li><b style="color: blue">Environment</b> - Environment variables</li>
                    <li><b style="color: purple">Machine</b> - Machine-specific overrides
                        {f'<br/><a href="{machine_admin_url}">→ Edit <code>{key}</code> in Machine.config for this server</a>' if machine_admin_url else ""}
                    </li>
                    <li><b style="color: green">Config File</b> - data/ArchiveBox.conf</li>
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
