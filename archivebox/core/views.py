__package__ = "archivebox.core"

import json
import os
import posixpath
from glob import glob, escape
from django.utils import timezone
import inspect
from typing import cast
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlparse

from django.shortcuts import render, redirect
from django.http import JsonResponse, HttpRequest, HttpResponse, Http404, HttpResponseForbidden, QueryDict
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views import View
from django.views.generic.list import ListView
from django.views.generic import FormView
from django.db.models import CharField, Count, Q, Prefetch, Sum
from django.db.models.functions import Cast
from django.contrib import messages
from django.contrib.auth.mixins import UserPassesTestMixin
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.gzip import gzip_page
from django.utils.decorators import method_decorator

from admin_data_views.typing import TableContext, ItemContext, SectionData
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink

from abx_dl.events import PROCESS_EXIT_SKIPPED

from archivebox.config import CONSTANTS, CONSTANTS_CONFIG, VERSION
from archivebox.config.common import get_config, get_all_configs
from archivebox.config.configset import BaseConfigSet
from archivebox.misc.paginators import CountlessPaginator
from archivebox.misc.util import base_url, htmlencode, ts_to_date_str, urldecode, without_fragment
from archivebox.misc.serve_static import serve_static_with_byterange_support
from archivebox.misc.logging_util import printable_filesize
from archivebox.search import (
    get_search_backend_display_name,
    get_search_mode,
    get_search_mode_backend,
    get_search_mode_base,
    get_search_mode_options,
    prioritize_metadata_matches,
    query_search_index,
)

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.permissions import (
    PERMISSIONS_PUBLIC,
    can_view_snapshot,
    direct_snapshots_queryset,
    filter_personas_by_permissions,
    is_admin_user,
    public_snapshots_queryset,
)
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
from archivebox.core.forms import AddLinkForm, get_plugin_config_binary_urls
from archivebox.crawls.models import Crawl
from archivebox.workers.models import RETRY_AT_MAX
from archivebox.hooks import (
    BUILTIN_PLUGINS_DIR,
    USER_PLUGINS_DIR,
    discover_plugin_configs,
    iter_plugin_dirs,
)


ABX_PLUGINS_GITHUB_BASE_URL = "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/"
LIVE_PLUGIN_BASE_URL = "/admin/environment/plugins/"


@lru_cache(maxsize=1)
def _live_progress_plugin_names() -> tuple[frozenset[str], frozenset[str]]:
    plugin_configs = discover_plugin_configs()
    download_plugin_names = frozenset(
        plugin_name
        for plugin_name, plugin_config in plugin_configs.items()
        if plugin_config.get("output_mimetypes") and not plugin_name.startswith("search_backend_")
    )
    indexing_plugin_names = frozenset(plugin_name for plugin_name in plugin_configs if plugin_name.startswith("search_backend_"))
    return download_plugin_names, indexing_plugin_names


def _get_request_config(request: HttpRequest, *, resolve_plugins: bool = False):
    request_config = getattr(request, "archivebox_config", None)
    request_config_resolves_plugins = bool(getattr(request, "_archivebox_config_resolves_plugins", False))
    if request_config is None or (resolve_plugins and not request_config_resolves_plugins):
        request_config = get_config(resolve_plugins=resolve_plugins)
        request.archivebox_config = request_config
        request._archivebox_config_resolves_plugins = resolve_plugins
    return request_config


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
    if _get_request_config(request).CONTROL_PLANE_ENABLED:
        return redirect(f"/admin/login/?next={request.path}")
    return HttpResponseForbidden("ArchiveBox is running with the control plane disabled in this security mode.")


class HomepageView(View):
    def get(self, request):
        request_config = _get_request_config(request)
        if request.user.is_authenticated and request_config.CONTROL_PLANE_ENABLED:
            return redirect("/admin/core/snapshot/")

        if request_config.PUBLIC_INDEX:
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

        crawl = getattr(snapshot, "crawl", None)
        runtime_config = getattr(request, "archivebox_config", None)
        page_config_keys = {
            "PREVIEW_ORIGINALS",
            "BIND_ADDR",
            "USES_SUBDOMAIN_ROUTING",
            "BASE_URL",
            "PERMISSIONS",
            "SERVER_SECURITY_MODE",
        }
        scoped_config_keys = set((getattr(snapshot, "config", None) or {}).keys())
        scoped_config_keys.update((getattr(crawl, "config", None) or {}).keys())
        needs_scoped_config = bool(scoped_config_keys & page_config_keys)
        if runtime_config is None or needs_scoped_config:
            runtime_config = get_config(snapshot=snapshot, resolve_plugins=False)
            request.archivebox_config = runtime_config
        snapshot._runtime_config = runtime_config
        hidden_card_plugins = {"archivedotorg", "favicon", "title"}
        outputs = [
            out
            for out in snapshot.discover_outputs(include_filesystem_fallback=False)
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
            "snapshot_permissions": str(runtime_config.PERMISSIONS).strip().lower(),
            "snapshot_permissions_icon": {
                "public": "👥",
                "unlisted": "🔗",
                "private": "🔒",
            }[str(runtime_config.PERMISSIONS).strip().lower()],
            "bookmarked_date": snapshot.bookmarked_date,
            "downloaded_datestr": snapshot.downloaded_datestr,
            "num_outputs": snapshot.num_outputs,
            "num_failures": snapshot.num_failures,
            "oldest_archive_date": ts_to_date_str(snapshot.oldest_archive_date),
            "warc_path": warc_path,
            "PREVIEW_ORIGINALS": runtime_config.PREVIEW_ORIGINALS,
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
                        return _admin_login_redirect_or_forbidden(request)
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

        # slug is a URL
        try:
            try:
                snapshot = direct_snapshots_queryset(request, SnapshotView.find_snapshots_for_url(path)).get()
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
            snapshots = direct_snapshots_queryset(request, SnapshotView.find_snapshots_for_url(path))
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
            try:
                snapshot = snapshots_qs.get(pk=snapshot_id)
            except Snapshot.DoesNotExist:
                try:
                    snapshot = snapshots_qs.get(id__startswith=snapshot_id)
                except Snapshot.DoesNotExist:
                    snapshot = None
                except Snapshot.MultipleObjectsReturned:
                    snapshot = snapshots_qs.filter(id__startswith=snapshot_id).first()
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
    if not snapshot or not can_view_snapshot(request, snapshot):
        return False
    request.archivebox_config = get_config(snapshot=snapshot, resolve_plugins=False)
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
    request_config = get_config(snapshot=snapshot, resolve_plugins=False)
    request.archivebox_config = request_config
    snapshot._runtime_config = request_config
    rel_path = path or ""
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
    request_config = _get_request_config(request)
    requested_root_index = path in ("", "index.html") or path.endswith("/")
    rel_path = path or ""
    if not rel_path or rel_path.endswith("/"):
        rel_path = f"{rel_path}index.html"
    rel_path = _safe_archive_relpath(rel_path)
    if rel_path is None:
        raise Http404

    domain = domain.lower()
    match = _latest_response_match(request, domain, rel_path, data_root=request_config.USERS_DIR)
    if not match and "." not in Path(rel_path).name:
        index_path = f"{rel_path.rstrip('/')}/index.html"
        match = _latest_response_match(request, domain, index_path, data_root=request_config.USERS_DIR)
    if not match and "." not in Path(rel_path).name:
        html_path = f"{rel_path}.html"
        match = _latest_response_match(request, domain, html_path, data_root=request_config.USERS_DIR)

    show_indexes = bool(request.GET.get("files"))
    if match:
        responses_root, rel_to_root = match
        response = _serve_responses_path(request, responses_root, str(rel_to_root), show_indexes)
        if response is not None:
            return response

    responses_root = _latest_responses_root(request, domain, data_root=request_config.USERS_DIR)
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
        request_config = _get_request_config(request)
        snapshot = _find_snapshot_by_ref(snapshot_id)

        if not snapshot:
            raise Http404
        if not can_view_snapshot(request, snapshot):
            return _admin_login_redirect_or_forbidden(request)

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
        if not can_view_snapshot(request, snapshot):
            return _admin_login_redirect_or_forbidden(request)

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
        runtime_config = getattr(self, "runtime_config", None)
        if runtime_config is None:
            self.runtime_config = runtime_config = _get_request_config(self.request, resolve_plugins=True)
        return runtime_config.SNAPSHOTS_PER_PAGE

    def get_context_data(self, **kwargs):
        runtime_config = getattr(self, "runtime_config", None)
        if runtime_config is None:
            self.runtime_config = runtime_config = _get_request_config(self.request, resolve_plugins=True)
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
            "search_backend_label": get_search_backend_display_name(search_mode_backend) if search_mode_backend else "",
        }
        context["show_search_index_hint"] = bool(
            self.request.GET.get("q")
            and get_search_mode_base(search_mode, config=runtime_config) == "deep"
            and search_mode_backend
            and getattr(context.get("paginator"), "count", 0) == 0,
        )
        for snapshot in context.get("object_list") or ():
            snapshot._icons_compact = True
            snapshot._is_archived_cached = bool(snapshot.downloaded_at or snapshot.status == Snapshot.StatusChoices.SEALED)
            results = getattr(snapshot, "_prefetched_objects_cache", {}).get("archiveresult_set")
            if results is not None:
                snapshot.num_outputs_cached = len(results)
        return context

    def get_queryset(self, **kwargs):
        qs = public_snapshots_queryset(super().get_queryset(**kwargs)).prefetch_related(
            "tags",
            Prefetch(
                "archiveresult_set",
                queryset=ArchiveResult.objects.filter(status=ArchiveResult.StatusChoices.SUCCEEDED).only(
                    "id",
                    "snapshot_id",
                    "plugin",
                    "status",
                    "output_size",
                ),
            ),
        )
        query = self.request.GET.get("q", default="").strip()

        if not query:
            return qs

        search_mode = get_search_mode(self.request.GET.get("search_mode"), config=getattr(self, "runtime_config", None))

        metadata_qs = qs.filter(
            Q(title__icontains=query) | Q(url__icontains=query) | Q(timestamp__icontains=query) | Q(tags__name__icontains=query),
        )
        search_mode_base = get_search_mode_base(search_mode, config=getattr(self, "runtime_config", None))
        search_mode_backend = get_search_mode_backend(search_mode, config=getattr(self, "runtime_config", None))
        if search_mode_base == "meta":
            qs = metadata_qs
        else:
            try:
                backend_qs = query_search_index(query, search_mode=search_mode)
                if search_mode_backend:
                    qs = qs.filter(pk__in=backend_qs.values("pk"))
                else:
                    qs = prioritize_metadata_matches(
                        qs,
                        metadata_qs,
                        backend_qs,
                        ordering=self.ordering,
                    )
            except Exception as err:
                print(f"[!] Error while using search backend: {err.__class__.__name__} {err}")
                qs = qs.none() if search_mode_backend else metadata_qs

        return qs.distinct()

    def get(self, *args, **kwargs):
        if self.request.user.is_authenticated:
            return redirect("/admin/core/snapshot/")
        if _get_request_config(self.request).PUBLIC_INDEX:
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
        return _get_request_config(self.request).PUBLIC_ADD_VIEW or self.request.user.is_authenticated

    def _can_override_crawl_config(self) -> bool:
        return is_admin_user(self.request)

    def _get_custom_config_overrides(self, form: AddLinkForm) -> dict:
        custom_config = form.cleaned_data.get("config") or {}

        if not isinstance(custom_config, dict):
            return {}

        if not self._can_override_crawl_config():
            return {}

        return custom_config

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request_config = _get_request_config(self.request, resolve_plugins=True)
        required_search_plugin = f"search_backend_{request_config.SEARCH_BACKEND_ENGINE}".strip()
        can_override_crawl_config = self._can_override_crawl_config()
        plugin_configs = discover_plugin_configs() if can_override_crawl_config else {}
        sensitive_keys = {
            str(config_key)
            for schema in plugin_configs.values()
            for config_key, prop_schema in (schema.get("properties") or {}).items()
            if isinstance(prop_schema, dict) and prop_schema.get("x-sensitive")
        }
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
            if can_override_crawl_config:
                raw_config = {str(key): value for key, value in (persona.config or {}).items() if str(key) not in sensitive_keys}
                effective_config_json = {str(key): value for key, value in effective_config.items() if str(key) not in sensitive_keys}
                binary_urls = get_plugin_config_binary_urls(effective_config)
            else:
                raw_config = {}
                effective_config_json = {key: effective_config.get(key) for key in public_persona_config_keys}
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
            "VERSION": VERSION,
            "FOOTER_INFO": request_config.FOOTER_INFO,
            "required_search_plugin": required_search_plugin,
            "plugin_dependency_map_json": json.dumps(plugin_dependency_map, sort_keys=True),
            "persona_config_map_json": json.dumps(persona_config_map, sort_keys=True, default=str),
            "recent_personas": recent_personas,
            "can_override_crawl_config": can_override_crawl_config,
            "can_select_permissions": self.request.user.is_authenticated,
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
        if not can_override_crawl_config:
            # Authenticated non-staff users may only choose public/unlisted; anonymous users
            # are always forced to public. Never honor a non-staff request for private.
            if not self.request.user.is_authenticated or permissions not in {"public", "unlisted"}:
                permissions = "public"
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

        created_by_name = getattr(self.request.user, "username", "web") if self.request.user.is_authenticated else "web"

        # 1. save the provided urls to sources/2024-11-05__23-59-59__web_ui_add_by_user_<user_pk>.txt
        sources_file = CONSTANTS.SOURCES_DIR / f"{timezone.now().strftime('%Y-%m-%d__%H-%M-%S')}__web_ui_add_by_user_{created_by_id}.txt"
        sources_file.parent.mkdir(parents=True, exist_ok=True)
        sources_file.write_text(urls if isinstance(urls, str) else "\n".join(urls))

        # 2. create a new Crawl with the URLs from the file
        timestamp = timezone.now().strftime("%Y-%m-%d__%H-%M-%S")
        urls_content = sources_file.read_text()
        # Store only explicit crawl-scoped overrides. Persona/machine/plugin
        # defaults are resolved at hook runtime via get_config(...).
        config = {}
        if plugins:
            config["PLUGINS"] = plugins
        effective_config = get_config(persona=persona, user=self.request.user) if persona else get_config(user=self.request.user)
        if can_override_crawl_config:
            # Resource limits are crawl config and are only honored for staff. Non-staff
            # users inherit these from the (public) persona / server defaults at hook runtime.
            if crawl_max_concurrent_snapshots != int(effective_config.CRAWL_MAX_CONCURRENT_SNAPSHOTS):
                config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] = crawl_max_concurrent_snapshots
            if delete_after != str(effective_config.DELETE_AFTER):
                config["DELETE_AFTER"] = delete_after
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
        config["PERMISSIONS"] = permissions

        # Merge custom config overrides
        config.update(plugin_config)
        config.update(custom_config)
        if bool(url_filters.get("only_new")) != bool(effective_config.ONLY_NEW):
            config["ONLY_NEW"] = bool(url_filters.get("only_new"))
        if url_filters.get("allowlist"):
            config["URL_ALLOWLIST"] = url_filters["allowlist"]
        if url_filters.get("denylist"):
            config["URL_DENYLIST"] = url_filters["denylist"]

        crawl = Crawl.objects.create(
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


@gzip_page
def live_progress_view(request):
    """Simple JSON endpoint for live progress status - used by admin progress monitor."""
    try:
        from archivebox.crawls.models import Crawl
        from archivebox.core.models import Snapshot, ArchiveResult
        from archivebox.machine.models import Process, Machine

        if not request.user.is_authenticated or not request.user.is_active or not request.user.is_staff:
            return JsonResponse({"error": "Permission denied"}, status=403)

        request_config = request.archivebox_config
        now = timezone.now()
        crawl_scope = Crawl.objects.all()
        snapshot_scope = Snapshot.objects.all()
        archiveresult_scope = ArchiveResult.objects.all()
        if not request.user.is_superuser:
            crawl_scope = crawl_scope.filter(created_by=request.user)
            snapshot_scope = snapshot_scope.filter(crawl__created_by=request.user)
            archiveresult_scope = archiveresult_scope.filter(snapshot__crawl__created_by=request.user)

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

        def archiveresult_output_path(ar) -> str | None:
            output_file_map = ar.output_files if isinstance(ar.output_files, dict) else {}

            def is_root_relative(path: str) -> bool:
                metadata = output_file_map.get(path) or {}
                return bool(isinstance(metadata, dict) and metadata.get("root_relative"))

            if ar.output_str:
                raw_output = str(ar.output_str).strip()
                if ar._looks_like_output_path(raw_output, ar.plugin):
                    output_path = Path(raw_output)
                    if output_path.is_absolute():
                        return None

                    if raw_output.startswith(f"{ar.plugin}/"):
                        candidates = [raw_output]
                    elif len(output_path.parts) == 1:
                        candidates = [f"{ar.plugin}/{raw_output}", raw_output]
                    else:
                        candidates = [raw_output]

                    if raw_output in output_file_map and is_root_relative(raw_output):
                        return raw_output

                    for relative_path in candidates:
                        plugin_relative = relative_path.removeprefix(f"{ar.plugin}/")
                        if relative_path in output_file_map:
                            return f"{ar.plugin}/{relative_path}" if not relative_path.startswith(f"{ar.plugin}/") else relative_path
                        if plugin_relative in output_file_map:
                            return f"{ar.plugin}/{plugin_relative}"

            output_file_paths = list(output_file_map.keys())
            if output_file_paths:
                fallback_path = ArchiveResult._fallback_output_file_path(output_file_paths, ar.plugin, output_file_map)
                if fallback_path:
                    if is_root_relative(fallback_path):
                        return fallback_path
                    return f"{ar.plugin}/{fallback_path}"

            return None

        def snapshot_output_url(snapshot, output_path: str) -> str:
            return build_snapshot_url(str(snapshot["id"]), output_path, request=request, config=request_config)

        def snapshot_archive_path(snapshot) -> str:
            if snapshot["fs_version"] in ("0.7.0", "0.8.0"):
                return f"{CONSTANTS.ARCHIVE_DIR_NAME}/{snapshot['timestamp']}"
            crawl = crawls_by_id.get(str(snapshot["crawl_id"]))
            username = "web"
            if crawl is not None and crawl["created_by_id"]:
                username = crawl["created_by__username"]
            if username == "system":
                username = "web"
            date_base = snapshot["bookmarked_at"] or snapshot["created_at"]
            date_str = date_base.strftime("%Y%m%d") if date_base else "unknown"
            domain = Snapshot.extract_domain_from_url(snapshot["url"])
            return f"{username}/{date_str}/{domain}/{snapshot['id']}"

        def snapshot_view_url(snapshot, output_path: str = "") -> str:
            anchor = f"#{output_path}" if output_path else ""
            return build_web_url(
                f"/{snapshot_archive_path(snapshot)}/index.html{anchor}",
                request=request,
                config=request_config,
            )

        def snapshot_display_url(url: str) -> str:
            url = str(url or "")
            return url if len(url) <= 96 else f"{url[:93]}..."

        def screencast_frame_url(crawl_id: str, crawl_dir: Path) -> str:
            frame_path = crawl_dir / "chrome_screencast" / "latest.jpg"
            try:
                frame_stat = frame_path.stat()
            except OSError:
                return ""
            if frame_stat.st_size <= 0:
                return ""
            if now.timestamp() - frame_stat.st_mtime > 15:
                return ""
            return f"/api/v1/crawls/crawl/{crawl_id}/files/chrome_screencast/latest.jpg?v={frame_stat.st_mtime_ns}"

        machine_id = Machine.current().id
        orchestrator_proc = (
            Process.objects.filter(
                machine_id=machine_id,
                process_type=Process.TypeChoices.ORCHESTRATOR,
                status=Process.StatusChoices.RUNNING,
            )
            .only("id", "pid", "started_at", "machine_id", "process_type", "status")
            .order_by("-started_at")
            .first()
            if machine_id is not None
            else None
        )
        runner_worker = None
        orchestrator_proc_running = bool(orchestrator_proc and orchestrator_proc.is_running)
        if not orchestrator_proc_running:
            try:
                from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker

                supervisor = get_existing_supervisord_process(quiet=True)
                runner_worker = get_worker(supervisor, "worker_runner") if supervisor else None
            except Exception:
                runner_worker = None

        runner_worker_running = bool(runner_worker and runner_worker.get("statename") in ("STARTING", "RUNNING"))
        runner_worker_pid = runner_worker.get("pid") if runner_worker else None
        orchestrator_running = orchestrator_proc_running or runner_worker_running
        orchestrator_pid = orchestrator_proc.pid if orchestrator_proc_running and orchestrator_proc else runner_worker_pid

        def count_statuses(queryset, statuses) -> dict[str, int]:
            # Keep these as individual indexed COUNTs instead of GROUP BY over
            # every matching row. On large SQLite data dirs, GROUP BY can scan
            # and sort far more of the status index than the live-progress
            # header needs before the runner gets CPU again.
            return {status: queryset.filter(status=status).count() for status in statuses}

        # Get model counts by status
        crawl_status_counts = count_statuses(
            crawl_scope,
            (Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED, Crawl.StatusChoices.PAUSED),
        )
        crawls_pending = crawl_status_counts.get(Crawl.StatusChoices.QUEUED, 0)
        crawls_started = crawl_status_counts.get(Crawl.StatusChoices.STARTED, 0)
        crawls_paused = crawl_status_counts.get(Crawl.StatusChoices.PAUSED, 0)

        # Get recent crawls (last 24 hours)
        from datetime import timedelta

        one_day_ago = now - timedelta(days=1)
        paused_crawl_cutoff = now - timedelta(hours=12)
        crawls_recent = crawl_scope.filter(created_at__gte=one_day_ago).count()

        snapshot_status_counts = count_statuses(
            snapshot_scope,
            (Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.PAUSED),
        )
        snapshots_pending = snapshot_status_counts.get(Snapshot.StatusChoices.QUEUED, 0)
        snapshots_started = snapshot_status_counts.get(Snapshot.StatusChoices.STARTED, 0)
        snapshots_paused = snapshot_status_counts.get(Snapshot.StatusChoices.PAUSED, 0)

        download_plugin_names, indexing_plugin_names = _live_progress_plugin_names()
        result_statuses = (
            ArchiveResult.StatusChoices.QUEUED,
            ArchiveResult.StatusChoices.STARTED,
            ArchiveResult.StatusChoices.PAUSED,
        )
        archiveresult_status_counts = count_statuses(archiveresult_scope, result_statuses)
        download_scope = archiveresult_scope.filter(
            plugin__in=download_plugin_names,
            snapshot__status__in=(Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED),
            snapshot__crawl__status__in=(Crawl.StatusChoices.QUEUED, Crawl.StatusChoices.STARTED),
        )
        indexing_scope = archiveresult_scope.filter(plugin__in=indexing_plugin_names)
        download_status_counts = count_statuses(download_scope, result_statuses)
        indexing_status_counts = count_statuses(indexing_scope, result_statuses)
        archiveresults_pending = archiveresult_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        archiveresults_started = archiveresult_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)
        archiveresults_paused = archiveresult_status_counts.get(ArchiveResult.StatusChoices.PAUSED, 0)
        archiveresults_succeeded = 0
        archiveresults_failed = 0

        downloads_pending = download_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        downloads_started = download_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)
        indexing_pending = indexing_status_counts.get(ArchiveResult.StatusChoices.QUEUED, 0)
        indexing_started = indexing_status_counts.get(ArchiveResult.StatusChoices.STARTED, 0)

        # Build hierarchical active crawls with nested snapshots and archive results
        max_active_crawls = 10
        max_queued_crawls = 10
        max_started_snapshots_per_crawl = 50
        max_queued_snapshots_per_crawl = 50

        active_crawl_fields = (
            "id",
            "created_at",
            "created_by_id",
            "modified_at",
            "urls",
            "config",
            "max_depth",
            "tags_str",
            "persona_id",
            "status",
            "retry_at",
            "label",
            "created_by__id",
            "created_by__username",
        )
        started_crawls = list(
            crawl_scope.filter(status=Crawl.StatusChoices.STARTED)
            .values(*active_crawl_fields)
            .order_by("-modified_at")[:max_active_crawls],
        )
        paused_crawls = list(
            crawl_scope.filter(status=Crawl.StatusChoices.PAUSED, created_at__gte=paused_crawl_cutoff)
            .values(*active_crawl_fields)
            .order_by("-modified_at")[:max_active_crawls],
        )
        queued_crawls = list(
            crawl_scope.filter(status=Crawl.StatusChoices.QUEUED).values(*active_crawl_fields).order_by("-modified_at")[:max_queued_crawls],
        )
        queued_crawls_hidden = max(crawls_pending - len(queued_crawls), 0)
        active_crawls_list = started_crawls + paused_crawls + queued_crawls
        for crawl in active_crawls_list:
            crawl["id"] = str(crawl["id"])
            if crawl["persona_id"]:
                crawl["persona_id"] = str(crawl["persona_id"])
        persona_details_by_id: dict[str, dict[str, str]] = {}
        persona_details_by_name: dict[str, dict[str, str]] = {}
        persona_objects_by_id = {}
        persona_objects_by_name = {}
        persona_ids = {crawl["persona_id"] for crawl in active_crawls_list if crawl["persona_id"]}
        persona_names = {
            str((crawl["config"] or {}).get("DEFAULT_PERSONA") or "Default") for crawl in active_crawls_list if not crawl["persona_id"]
        }
        if persona_ids or persona_names:
            from archivebox.personas.models import Persona

            for persona in Persona.objects.filter(Q(id__in=persona_ids) | Q(name__in=persona_names)).only("id", "name", "config"):
                persona_details = {
                    "name": persona.name,
                    "admin_url": f"/admin/personas/persona/{persona.pk}/change/",
                }
                persona_details_by_id[str(persona.id)] = persona_details
                persona_details_by_name[persona.name] = persona_details
                persona_objects_by_id[str(persona.id)] = persona
                persona_objects_by_name[persona.name] = persona
        active_crawl_ids = [crawl["id"] for crawl in active_crawls_list]
        active_crawl_objects = {}
        if active_crawl_ids:
            for crawl_obj in Crawl.objects.filter(id__in=active_crawl_ids).select_related("created_by", "persona"):
                crawl_obj._runtime_config = request_config
                active_crawl_objects[str(crawl_obj.id)] = crawl_obj
        snapshot_counts_by_crawl: dict[str, dict[str, int]] = {str(crawl_id): {} for crawl_id in active_crawl_ids}
        cancelled_snapshot_counts_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in active_crawl_ids}
        crawl_output_sizes_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in active_crawl_ids}
        queued_snapshot_overflow_by_crawl: dict[str, int] = {str(crawl_id): 0 for crawl_id in active_crawl_ids}
        active_snapshot_scope = snapshot_scope.filter(crawl_id__in=active_crawl_ids)
        if active_crawl_ids:
            for row in active_snapshot_scope.values("crawl_id", "status").annotate(count=Count("id")):
                snapshot_counts_by_crawl.setdefault(str(row["crawl_id"]), {})[row["status"]] = row["count"]

            for row in (
                active_snapshot_scope.filter(status=Snapshot.StatusChoices.SEALED, downloaded_at__isnull=True)
                .values("crawl_id")
                .annotate(count=Count("id"))
            ):
                cancelled_snapshot_counts_by_crawl[str(row["crawl_id"])] = row["count"]

            for row in (
                archiveresult_scope.filter(
                    snapshot__crawl_id__in=active_crawl_ids,
                    snapshot__status=Snapshot.StatusChoices.SEALED,
                )
                .values("snapshot__crawl_id")
                .annotate(size=Sum("output_size"))
            ):
                crawl_output_sizes_by_crawl[str(row["snapshot__crawl_id"])] = int(row["size"] or 0)

        crawl_process_pids: dict[str, int] = {}
        snapshot_process_pids: dict[str, int] = {}
        process_records_by_crawl: dict[str, list[tuple[dict[str, object], object | None]]] = {}
        process_records_by_snapshot: dict[str, list[tuple[dict[str, object], object | None]]] = {}
        seen_process_records: set[str] = set()
        crawls_by_id = {str(crawl["id"]): crawl for crawl in active_crawls_list}
        started_snapshot_fields = (
            "id_str",
            "created_at",
            "modified_at",
            "url",
            "timestamp",
            "bookmarked_at",
            "crawl_id_str",
            "title",
            "downloaded_at",
            "fs_version",
            "status",
        )
        queued_snapshot_fields = (
            "id_str",
            "url",
            "crawl_id_str",
            "title",
            "status",
        )
        snapshots = []
        for crawl_id in active_crawl_ids:
            crawl_snapshot_scope = active_snapshot_scope.filter(crawl_id=crawl_id)
            snapshots.extend(
                crawl_snapshot_scope.filter(status=Snapshot.StatusChoices.STARTED)
                .annotate(id_str=Cast("id", CharField()), crawl_id_str=Cast("crawl_id", CharField()))
                .values(*started_snapshot_fields)
                .order_by("-modified_at")[:max_started_snapshots_per_crawl],
            )
            queued_snapshots = list(
                crawl_snapshot_scope.filter(status=Snapshot.StatusChoices.QUEUED)
                .annotate(id_str=Cast("id", CharField()), crawl_id_str=Cast("crawl_id", CharField()))
                .values(
                    *queued_snapshot_fields,
                )
                .order_by("modified_at")[:max_queued_snapshots_per_crawl],
            )
            queued_snapshot_overflow_by_crawl[str(crawl_id)] = max(
                snapshot_counts_by_crawl.get(str(crawl_id), {}).get(Snapshot.StatusChoices.QUEUED, 0) - len(queued_snapshots),
                0,
            )
            snapshots.extend(queued_snapshots)

        def dashed_uuid(value: str) -> str:
            value = str(value)
            if len(value) == 32:
                return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"
            return value

        for snapshot in snapshots:
            snapshot["id"] = (
                snapshot.pop("id_str") if snapshot["status"] == Snapshot.StatusChoices.QUEUED else dashed_uuid(snapshot.pop("id_str"))
            )
            snapshot["crawl_id"] = dashed_uuid(snapshot.pop("crawl_id_str"))
        snapshots_by_id = {str(snapshot["id"]): snapshot for snapshot in snapshots}
        displayed_snapshots_by_crawl: dict[str, list[Snapshot]] = {str(crawl_id): [] for crawl_id in active_crawl_ids}
        for snapshot in snapshots:
            crawl_snapshots = displayed_snapshots_by_crawl.setdefault(str(snapshot["crawl_id"]), [])
            crawl_snapshots.append(snapshot)
        displayed_snapshot_ids = [
            snapshot["id"] for crawl_snapshots in displayed_snapshots_by_crawl.values() for snapshot in crawl_snapshots
        ]
        detailed_snapshot_ids = [snapshot["id"] for snapshot in snapshots if snapshot["status"] != Snapshot.StatusChoices.QUEUED]
        process_value_fields = ("id", "process_type", "status", "pwd", "cmd", "pid", "exit_code", "started_at", "modified_at")
        if active_crawl_ids or displayed_snapshot_ids:
            process_scope = Process.objects.filter(
                machine_id=machine_id,
                process_type__in=[
                    Process.TypeChoices.HOOK,
                    Process.TypeChoices.BINARY,
                ],
            )
            running_processes = process_scope.filter(status=Process.StatusChoices.RUNNING).values(*process_value_fields)
            recent_processes = (
                process_scope.filter(modified_at__gte=now - timedelta(minutes=10)).values(*process_value_fields).order_by("-modified_at")
            )
        else:
            running_processes = Process.objects.none()
            recent_processes = Process.objects.none()

        archiveresults_by_snapshot: dict[str, list[ArchiveResult]] = {str(snapshot_id): [] for snapshot_id in detailed_snapshot_ids}
        if detailed_snapshot_ids:
            displayed_archiveresults = (
                archiveresult_scope.filter(snapshot_id__in=detailed_snapshot_ids)
                .select_related("process")
                .only(
                    "id",
                    "snapshot_id",
                    "plugin",
                    "hook_name",
                    "status",
                    "output_str",
                    "output_files",
                    "output_size",
                    "start_ts",
                    "end_ts",
                    "created_at",
                    "modified_at",
                    "process_id",
                    "process__id",
                    "process__pid",
                    "process__started_at",
                    "process__timeout",
                )
                .order_by("snapshot_id", "start_ts", "created_at")
            )
            for archiveresult in displayed_archiveresults:
                archiveresults_by_snapshot.setdefault(str(archiveresult.snapshot_id), []).append(archiveresult)
                if archiveresult.status == ArchiveResult.StatusChoices.SUCCEEDED:
                    archiveresults_succeeded += 1
                elif archiveresult.status == ArchiveResult.StatusChoices.FAILED:
                    archiveresults_failed += 1

        def find_snapshot_for_process(proc_pwd: Path) -> Snapshot | None:
            for path_part in reversed(proc_pwd.parts):
                snapshot = snapshots_by_id.get(path_part)
                if snapshot:
                    return snapshot
            return None

        def find_crawl_for_process(proc_pwd: Path) -> Crawl | None:
            for path_part in reversed(proc_pwd.parts):
                crawl = crawls_by_id.get(path_part)
                if crawl:
                    return crawl
            return None

        running_worker_ids: set[str] = set()
        for proc in running_processes:
            if not proc["pwd"]:
                continue
            proc_pwd = Path(proc["pwd"])
            matched_snapshot = find_snapshot_for_process(proc_pwd)
            matched_crawl = (
                crawls_by_id.get(str(matched_snapshot["crawl_id"])) if matched_snapshot is not None else find_crawl_for_process(proc_pwd)
            )
            if matched_snapshot is None:
                if matched_crawl is None:
                    continue
                crawl_id = str(matched_crawl["id"])
                snapshot_id = ""
            else:
                crawl_id = str(matched_snapshot["crawl_id"])
                snapshot_id = str(matched_snapshot["id"])
            running_worker_ids.add(str(proc["id"]))
            _plugin, _label, phase, _hook_name = process_label(proc["cmd"])
            if crawl_id and proc["pid"]:
                crawl_process_pids.setdefault(crawl_id, proc["pid"])
            if phase == "snapshot" and snapshot_id and proc["pid"]:
                snapshot_process_pids.setdefault(snapshot_id, proc["pid"])

        for proc in recent_processes:
            if not proc["pwd"]:
                continue
            proc_pwd = Path(proc["pwd"])
            matched_snapshot = find_snapshot_for_process(proc_pwd)
            matched_crawl = (
                crawls_by_id.get(str(matched_snapshot["crawl_id"])) if matched_snapshot is not None else find_crawl_for_process(proc_pwd)
            )
            if matched_snapshot is None and matched_crawl is None:
                continue
            crawl_id = str(matched_snapshot["crawl_id"] if matched_snapshot is not None else matched_crawl["id"])
            snapshot_id = str(matched_snapshot["id"]) if matched_snapshot is not None else ""

            plugin, label, phase, hook_name = process_label(proc["cmd"])

            record_scope = str(snapshot_id) if phase == "snapshot" and snapshot_id else str(crawl_id)
            proc_key = f"{record_scope}:{plugin}:{label}:{proc['status']}:{proc['exit_code']}"
            if proc_key in seen_process_records:
                continue
            seen_process_records.add(proc_key)

            status = (
                "started"
                if proc["status"] == Process.StatusChoices.RUNNING
                else (
                    "skipped"
                    if proc["exit_code"] == PROCESS_EXIT_SKIPPED or (phase == "binary" and proc["exit_code"] not in (None, 0))
                    else ("failed" if proc["exit_code"] not in (None, 0) else "succeeded")
                )
            )
            payload: dict[str, object] = {
                "id": str(proc["id"]),
                "plugin": plugin,
                "label": label,
                "hook_name": hook_name,
                "status": status,
                "phase": phase,
                "source": "process",
                "process_id": str(proc["id"]),
            }
            if status == "started" and proc["pid"]:
                payload["pid"] = proc["pid"]
            proc_started_at = proc["started_at"] or proc["modified_at"]
            if phase == "snapshot" and snapshot_id:
                process_records_by_snapshot.setdefault(snapshot_id, []).append((payload, proc_started_at))
            elif crawl_id:
                process_records_by_crawl.setdefault(crawl_id, []).append((payload, proc_started_at))

        active_crawls = []
        total_workers = len(running_worker_ids)
        for crawl in active_crawls_list:
            crawl_id = str(crawl["id"])
            crawl_snapshot_counts = snapshot_counts_by_crawl.get(crawl_id, {})
            total_snapshots = sum(crawl_snapshot_counts.values())
            completed_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.SEALED, 0)
            started_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.STARTED, 0)
            pending_snapshots = crawl_snapshot_counts.get(Snapshot.StatusChoices.QUEUED, 0)
            cancelled_snapshots = cancelled_snapshot_counts_by_crawl.get(crawl_id, 0)

            # Count URLs in the crawl (for when snapshots haven't been created yet)
            urls_count = 0
            if crawl["urls"]:
                urls_count = len([u for u in crawl["urls"].split("\n") if u.strip() and not u.startswith("#")])

            # Calculate crawl progress
            crawl_progress = int((completed_snapshots / total_snapshots) * 100) if total_snapshots > 0 else 0
            crawl_run_started_at = crawl["created_at"]
            crawl_setup_plugins = [
                payload
                for payload, proc_started_at in process_records_by_crawl.get(crawl_id, [])
                if is_current_run_timestamp(proc_started_at, crawl_run_started_at)
            ]
            crawl_setup_total = len(crawl_setup_plugins)
            crawl_setup_completed = sum(1 for item in crawl_setup_plugins if item.get("status") == "succeeded")
            crawl_setup_failed = sum(1 for item in crawl_setup_plugins if item.get("status") == "failed")
            crawl_setup_pending = sum(1 for item in crawl_setup_plugins if item.get("status") == "queued")
            crawl_screencast_url = screencast_frame_url(crawl_id, active_crawl_objects[crawl_id].output_dir)
            crawl_screencast_link = f"/admin/crawls/crawl/{crawl_id}/change/" if crawl_screencast_url else ""

            # Get active snapshots for this crawl (already prefetched)
            active_snapshots_for_crawl = []
            for snapshot in displayed_snapshots_by_crawl.get(crawl_id, []):
                snapshot_run_started_at = snapshot.get("downloaded_at") or snapshot.get("created_at")
                # Get archive results only for displayed active snapshots. Large crawls can
                # contain thousands of sealed snapshots, and prefetching all their results
                # makes the progress endpoint compete with the runner.
                snapshot_results = [
                    ar
                    for ar in archiveresults_by_snapshot.get(str(snapshot["id"]), [])
                    if archiveresult_matches_current_run(ar, snapshot_run_started_at)
                ]
                if snapshot["status"] == Snapshot.StatusChoices.QUEUED:
                    snapshot_results = []

                plugin_progress_values: list[int] = []
                all_plugins: list[dict[str, object]] = []
                seen_plugin_keys: set[str] = set()
                snapshot_title = (
                    str(snapshot["title"] or "")
                    if snapshot["status"] == Snapshot.StatusChoices.QUEUED
                    else Snapshot._normalize_title_candidate(snapshot["title"], snapshot_url=snapshot["url"])
                )
                snapshot_favicon_url = ""
                snapshot_preview_url = ""
                snapshot_preview_link = ""
                snapshot_screencast_url = ""
                snapshot_screencast_link = ""
                snapshot_fallback_urls: list[str] = []
                result_by_plugin = {result.plugin: result for result in snapshot_results}
                title_result = result_by_plugin.get("title")
                if not snapshot_title and title_result is not None and title_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
                    snapshot_title = Snapshot._normalize_title_candidate(title_result.output_str, snapshot_url=snapshot["url"])
                favicon_result = result_by_plugin.get("favicon")
                if favicon_result is not None and favicon_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
                    favicon_path = archiveresult_output_path(favicon_result) or "favicon/favicon.ico"
                    snapshot_favicon_url = snapshot_output_url(snapshot, favicon_path)
                screenshot_result = result_by_plugin.get("screenshot")
                if screenshot_result is not None and screenshot_result.status == ArchiveResult.StatusChoices.SUCCEEDED:
                    snapshot_preview_link = snapshot_view_url(snapshot)
                    screenshot_path = archiveresult_output_path(screenshot_result) or "screenshot/screenshot.png"
                    snapshot_preview_url = snapshot_output_url(snapshot, screenshot_path)
                    snapshot_preview_link = snapshot_view_url(snapshot, screenshot_path)
                    if snapshot_favicon_url:
                        snapshot_fallback_urls.append(snapshot_favicon_url)
                elif snapshot_favicon_url:
                    snapshot_preview_url = snapshot_favicon_url

                if snapshot["status"] == Snapshot.StatusChoices.STARTED:
                    snapshot_screencast_url = screencast_frame_url(crawl_id, active_crawl_objects[crawl_id].output_dir)
                    snapshot_screencast_link = snapshot_view_url(snapshot) if snapshot_screencast_url else ""

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
                    process = ar.process_record
                    progress_value = 0
                    if status in (
                        ArchiveResult.StatusChoices.SUCCEEDED,
                        ArchiveResult.StatusChoices.FAILED,
                        ArchiveResult.StatusChoices.SKIPPED,
                        ArchiveResult.StatusChoices.NORESULTS,
                    ):
                        progress_value = 100
                    elif status == ArchiveResult.StatusChoices.STARTED:
                        started_at = ar.start_ts or (process.started_at if process else None)
                        timeout = process.timeout if process else 120
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
                        "process_id": str(process.id) if process else None,
                        "admin_url": f"/admin/core/archiveresult/{ar.id}/change/",
                    }
                    output_path = archiveresult_output_path(ar)
                    if output_path:
                        plugin_payload["output_path"] = output_path
                        plugin_payload["output_url"] = snapshot_view_url(snapshot, output_path)
                    if status == ArchiveResult.StatusChoices.STARTED and process:
                        plugin_payload["pid"] = process.pid
                    if status == ArchiveResult.StatusChoices.STARTED:
                        plugin_payload["progress"] = progress_value
                        plugin_payload["timeout"] = process.timeout if process else 120
                    plugin_payload["source"] = "archiveresult"
                    all_plugins.append(plugin_payload)
                    seen_plugin_keys.add(str(process.id) if process else f"{ar.plugin}:{hook_name}")

                for proc_payload, proc_started_at in process_records_by_snapshot.get(str(snapshot["id"]), []):
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
                    else:
                        plugin_progress_values.append(0)

                total_plugins = len(all_plugins)
                completed_plugins = sum(1 for item in all_plugins if item.get("status") == "succeeded")
                failed_plugins = sum(1 for item in all_plugins if item.get("status") == "failed")
                pending_plugins = sum(1 for item in all_plugins if item.get("status") == "queued")

                snapshot_progress = int(sum(plugin_progress_values) / len(plugin_progress_values)) if plugin_progress_values else 0
                worker_state = "running" if snapshot_process_pids.get(str(snapshot["id"])) else "waiting"
                if (
                    snapshot["status"] == Snapshot.StatusChoices.STARTED
                    and worker_state == "waiting"
                    and not all_plugins
                    and snapshot["modified_at"]
                    and (now - snapshot["modified_at"]).total_seconds() > 30
                ):
                    worker_state = "waiting" if orchestrator_running else "crashed"

                if snapshot["status"] == Snapshot.StatusChoices.QUEUED and not snapshot_process_pids.get(str(snapshot["id"])):
                    compact_snapshot = [
                        str(snapshot["id"]),
                        snapshot_display_url(snapshot["url"]),
                    ]
                    if snapshot_title:
                        compact_snapshot.append(snapshot_title)
                    active_snapshots_for_crawl.append(compact_snapshot)
                    continue

                snapshot_payload = {
                    "id": str(snapshot["id"]),
                    "url": snapshot_display_url(snapshot["url"]),
                    "title": snapshot_title,
                    "status": snapshot["status"],
                    "worker_state": worker_state,
                }
                if snapshot["status"] != Snapshot.StatusChoices.QUEUED or all_plugins or snapshot_process_pids.get(str(snapshot["id"])):
                    snapshot_payload.update(
                        {
                            "view_url": snapshot_view_url(snapshot),
                            "started": (snapshot["downloaded_at"] or snapshot["created_at"]).isoformat()
                            if (snapshot["downloaded_at"] or snapshot["created_at"])
                            else None,
                            "progress": snapshot_progress,
                            "total_plugins": total_plugins,
                            "completed_plugins": completed_plugins,
                            "failed_plugins": failed_plugins,
                            "pending_plugins": pending_plugins,
                            "all_plugins": all_plugins,
                        },
                    )
                    if snapshot_favicon_url:
                        snapshot_payload["favicon_url"] = snapshot_favicon_url
                    if snapshot_preview_url:
                        snapshot_payload["preview_url"] = snapshot_preview_url
                        snapshot_payload["preview_link"] = snapshot_preview_link
                    if snapshot_screencast_url:
                        snapshot_payload["screencast_url"] = snapshot_screencast_url
                        snapshot_payload["screencast_link"] = snapshot_screencast_link
                    if snapshot_fallback_urls:
                        snapshot_payload["preview_fallbacks"] = snapshot_fallback_urls
                    if snapshot_process_pids.get(str(snapshot["id"])):
                        snapshot_payload["worker_pid"] = snapshot_process_pids[str(snapshot["id"])]

                active_snapshots_for_crawl.append(snapshot_payload)

            # Check if crawl can start (for debugging stuck crawls)
            can_start = bool(crawl["urls"])
            urls_preview = crawl["urls"][:60] if crawl["urls"] else None
            crawl_tags = [tag.strip() for tag in (crawl["tags_str"] or "").replace("\n", ",").split(",") if tag.strip()]
            persona_details = persona_details_by_id.get(str(crawl["persona_id"])) if crawl["persona_id"] else None
            persona_name = persona_details["name"] if persona_details else str((crawl["config"] or {}).get("DEFAULT_PERSONA") or "Default")
            persona_details = persona_details or persona_details_by_name.get(persona_name)
            crawl_output_size = crawl_output_sizes_by_crawl.get(crawl_id, 0)
            avg_snapshot_size = int(crawl_output_size / completed_snapshots) if completed_snapshots else 0
            crawl_obj = active_crawl_objects[crawl_id]
            persona_obj = (
                persona_objects_by_id.get(str(crawl["persona_id"])) if crawl["persona_id"] else persona_objects_by_name.get(persona_name)
            )
            effective_crawl_config = get_config(
                base_config=request_config,
                user=crawl_obj.created_by,
                persona=persona_obj,
                crawl=crawl_obj,
                resolve_plugins=False,
            )
            max_urls = int(effective_crawl_config.CRAWL_MAX_URLS or 0)
            crawl_max_size = int(effective_crawl_config.CRAWL_MAX_SIZE or 0)
            crawl_timeout = int(effective_crawl_config.CRAWL_TIMEOUT or 0)
            snapshot_max_size = int(effective_crawl_config.SNAPSHOT_MAX_SIZE or 0)

            # Check if retry_at is in the future (would prevent worker from claiming)
            retry_at_future = crawl["retry_at"] > now if crawl["retry_at"] else False
            is_paused = crawl_obj.is_paused
            seconds_until_retry = (
                0 if is_paused else int((crawl["retry_at"] - now).total_seconds()) if crawl["retry_at"] and retry_at_future else 0
            )
            crawl_worker_state = (
                "running"
                if crawl_process_pids.get(crawl_id)
                or any(isinstance(snapshot, dict) and snapshot.get("worker_pid") for snapshot in active_snapshots_for_crawl)
                else "waiting"
            )
            if is_paused:
                crawl_worker_state = "paused"
            elif (
                crawl["status"] == Crawl.StatusChoices.STARTED
                and crawl_worker_state == "waiting"
                and (started_snapshots or pending_snapshots)
            ):
                crawl_worker_state = "waiting" if orchestrator_running else "crashed"

            active_crawls.append(
                {
                    "id": crawl_id,
                    "label": (next((line.strip() for line in (crawl["urls"] or "").splitlines() if line.strip()), "") or crawl_id)[:60],
                    "status": crawl["status"],
                    "is_paused": is_paused,
                    "started": crawl["created_at"].isoformat() if crawl["created_at"] else None,
                    "progress": crawl_progress,
                    "created_by": crawl["created_by__username"],
                    "persona": persona_name,
                    "persona_admin_url": persona_details["admin_url"] if persona_details else None,
                    "max_depth": crawl["max_depth"],
                    "max_urls": max_urls,
                    "max_crawl_size": crawl_max_size,
                    "crawl_timeout": crawl_timeout,
                    "max_snapshot_size": snapshot_max_size,
                    "max_crawl_size_display": printable_filesize(crawl_max_size) if crawl_max_size else "unlimited",
                    "crawl_timeout_display": f"{crawl_timeout}s" if crawl_timeout else "unlimited",
                    "max_snapshot_size_display": printable_filesize(snapshot_max_size) if snapshot_max_size else "unlimited",
                    "crawl_output_size": crawl_output_size,
                    "avg_snapshot_size": avg_snapshot_size,
                    "crawl_output_size_display": printable_filesize(crawl_output_size) if crawl_output_size else "0 B",
                    "avg_snapshot_size_display": printable_filesize(avg_snapshot_size) if avg_snapshot_size else "0 B",
                    "tags": crawl_tags,
                    "urls_count": urls_count,
                    "total_snapshots": total_snapshots,
                    "completed_snapshots": completed_snapshots,
                    "started_snapshots": started_snapshots,
                    "failed_snapshots": 0,
                    "pending_snapshots": pending_snapshots,
                    "cancelled_snapshots": cancelled_snapshots,
                    "setup_plugins": crawl_setup_plugins,
                    "setup_total_plugins": crawl_setup_total,
                    "setup_completed_plugins": crawl_setup_completed,
                    "setup_failed_plugins": crawl_setup_failed,
                    "setup_pending_plugins": crawl_setup_pending,
                    "screencast_url": crawl_screencast_url,
                    "screencast_link": crawl_screencast_link,
                    "active_snapshots": active_snapshots_for_crawl,
                    "queued_snapshots_hidden": queued_snapshot_overflow_by_crawl.get(crawl_id, 0),
                    "can_start": can_start,
                    "urls_preview": urls_preview,
                    "retry_at_future": retry_at_future,
                    "seconds_until_retry": seconds_until_retry,
                    "worker_pid": crawl_process_pids.get(crawl_id),
                    "worker_state": crawl_worker_state,
                },
            )

        payload = {
            "orchestrator_running": orchestrator_running,
            "orchestrator_pid": orchestrator_pid,
            "total_workers": total_workers,
            "crawls_pending": crawls_pending,
            "crawls_started": crawls_started,
            "crawls_active": crawls_started,
            "crawls_queued": crawls_pending,
            "crawls_paused": crawls_paused,
            "crawls_recent": crawls_recent,
            "snapshots_pending": snapshots_pending,
            "snapshots_started": snapshots_started,
            "snapshots_active": snapshots_started,
            "snapshots_queued": snapshots_pending,
            "snapshots_paused": snapshots_paused,
            "archiveresults_pending": archiveresults_pending,
            "archiveresults_started": archiveresults_started,
            "archiveresults_paused": archiveresults_paused,
            "archiveresults_succeeded": archiveresults_succeeded,
            "archiveresults_failed": archiveresults_failed,
            "downloads_pending": downloads_pending,
            "downloads_started": downloads_started,
            "downloads_active": downloads_started,
            "downloads_queued": downloads_pending,
            "indexing_pending": indexing_pending,
            "indexing_started": indexing_started,
            "indexing_active": indexing_started,
            "indexing_queued": indexing_pending,
            "active_crawls": active_crawls,
            "queued_crawls_hidden": queued_crawls_hidden,
            "recent_thumbnails": [],
            "server_time": timezone.now().isoformat(),
        }
        try:
            import ujson

            return HttpResponse(ujson.dumps(payload), content_type="application/json")
        except ImportError:
            return JsonResponse(payload)
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
                "crawls_active": 0,
                "crawls_queued": 0,
                "crawls_paused": 0,
                "crawls_recent": 0,
                "snapshots_pending": 0,
                "snapshots_started": 0,
                "snapshots_active": 0,
                "snapshots_queued": 0,
                "snapshots_paused": 0,
                "archiveresults_pending": 0,
                "archiveresults_started": 0,
                "archiveresults_paused": 0,
                "archiveresults_succeeded": 0,
                "archiveresults_failed": 0,
                "downloads_pending": 0,
                "downloads_started": 0,
                "downloads_active": 0,
                "downloads_queued": 0,
                "indexing_pending": 0,
                "indexing_started": 0,
                "indexing_active": 0,
                "indexing_queued": 0,
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
            default_val = type(config).model_fields[key].default
            break

    if isinstance(default_val, Callable):
        default_val = inspect.getsource(default_val).split("lambda", 1)[-1].split(":", 1)[-1].replace("\n", " ").strip()
        if default_val.count(")") > default_val.count("("):
            default_val = default_val[:-1]
    else:
        default_val = str(default_val)

    return default_val


def find_config_type(key: str) -> str:
    CONFIGS = get_all_configs()

    for config in CONFIGS.values():
        if key in type(config).model_fields:
            annotation = type(config).model_fields[key].annotation
            return getattr(annotation, "__name__", str(annotation))
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

    CONFIGS = get_all_configs()

    assert getattr(request.user, "is_superuser", False), "Must be a superuser to view configuration settings."

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
    final_value = merged_config.get(key, CONFIGS.get(key, None))
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
                <p style="display: {"block" if key in merged_config and key not in CONSTANTS_CONFIG else "none"}">
                    <i>To change this value, edit <code>data/ArchiveBox.conf</code> or run:</i>
                    <br/><br/>
                    <code>archivebox config --set {key}="{
                    val.strip("'")
                    if (val := find_config_default(key))
                    else (str(final_value if key_is_safe(key) else "********")).strip("'")
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
