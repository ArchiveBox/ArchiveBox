"""Read-only Memento negotiation: https://www.rfc-editor.org/rfc/rfc7089.html#section-3

The original URL (URI-R) identifies the page; canonical snapshots (URI-M) identify
captures. Existing /archive/<url> and snapshot?format=link routes provide the
TimeGate (URI-G) and TimeMap (URI-T), without capture hooks or new archive steps.
"""

from datetime import UTC, datetime
from urllib.parse import quote

from django.db.models import Prefetch
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date, parse_http_date_safe

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.permissions import discoverable_snapshots_queryset
from archivebox.core.routes_util import build_snapshot_detail_url, build_snapshot_url, build_web_url
from archivebox.misc.util import equivalent_urls, iri_to_uri

ARCHIVE_TYPES = {".wacz": "application/wacz", ".warc.gz": "application/gzip", ".warc": "application/warc"}


def _captures(request, url):
    # Exact identity matters; public discovery must not reveal unlisted captures.
    # The IRI and URI spellings (/über, /%C3%BCber) are one identity: the
    # lookup URL is a decoded path plus a raw query, rarely the stored form.
    snapshots = Snapshot.objects.filter(url__in=equivalent_urls(url), downloaded_at__isnull=False, output_size__gt=0).select_related(
        "crawl__created_by",
    )
    return discoverable_snapshots_queryset(request, snapshots).order_by("downloaded_at", "id")


def _links(request, snapshot, relation="timemap"):
    # Link headers are ASCII: send the original as a URI (IDNA host, UTF-8 escapes).
    original = iri_to_uri(snapshot.url)
    # Encode nested query/fragment delimiters so the lookup keeps the original URL.
    gate = build_web_url("/archive/" + quote(snapshot.url, safe=":/"), request=request)
    timemap = build_snapshot_detail_url(snapshot.archive_path_from_db, request=request) + "?format=link"
    return [
        f'<{original}>; rel="original"',
        f'<{gate}>; rel="timegate"',
        f'<{timemap}>; rel="{relation}"; type="application/link-format"',
        f'<{original}>; rel="canonical"',
    ]


def _archive_type(path):
    return next((mime for suffix, mime in ARCHIVE_TYPES.items() if path.lower().endswith(suffix)), None)


def _enclosures(request, snapshot):
    # Containers hold many resources: use enclosures, not extra URI-M entries.
    # anchor binds each download to its capture in a TimeMap (RFC 8288 section 3.2).
    anchor = build_snapshot_detail_url(snapshot.archive_path_from_db, request=request)
    results = snapshot.__dict__.get("_admin_archiveresults")
    if results is None:
        results = snapshot.__dict__.get("_prefetched_objects_cache", {}).get("archiveresult_set")
    if results is None:
        results = snapshot.archiveresult_set.filter(status="succeeded").only("snapshot_id", "plugin", "status", "output_files")
    for result in results:
        if result.status == result.StatusChoices.SUCCEEDED:
            # A raw favicon/image response also adds Memento links. Do not
            # validate and resolve every captured asset to find a few bundles.
            raw_files = result.output_files
            if isinstance(raw_files, dict):
                candidates = {key: value for key, value in raw_files.items() if _archive_type(str(key))}
                if not candidates:
                    continue
                files = result._normalize_output_files(candidates)
            else:
                files = result.output_file_map()
            for key in files:
                if not _archive_type(key):
                    continue
                path = result.output_file_path(key, output_file_map=files)
                if path and (mime := _archive_type(path)):
                    url = build_snapshot_url(str(snapshot.id), path, request=request) + "?raw=1"
                    yield f'<{url}>; rel="enclosure"; type="{mime}"; anchor="{anchor}"'


def add_memento_headers(request, snapshot, response, path="", primary=True, *, enclosures=True):
    archive_viewer = (mime := _archive_type(path)) and response.get("Content-Type", "").startswith("text/html")
    bundle = mime and not archive_viewer
    if bundle:
        # gzip is the saved file format, not HTTP content coding: range offsets
        # must address compressed bytes. Whole bundles are not individual Mementos.
        response["Content-Type"] = mime
        response.headers.pop("Content-Encoding", None)
    if response.status_code not in (200, 206, 301, 302, 303, 304, 307, 308):
        return response
    links = [response.get("Link"), *_links(request, snapshot)]
    if (
        (primary or archive_viewer)
        and not bundle
        and snapshot.downloaded_at
        and snapshot.output_size
        and response.status_code in (200, 206, 304)
    ):
        # Persisted completion time, never request/bookmark time (RFC 7089 4.5.6).
        response["Memento-Datetime"] = http_date(snapshot.downloaded_at.timestamp())
        if enclosures:
            links.extend(_enclosures(request, snapshot))
    response["Link"] = ", ".join(filter(None, links))
    return response


def timemap_response(request, snapshot):
    # Link format is required by https://www.rfc-editor.org/rfc/rfc7089.html#section-5
    navigation = _links(request, snapshot, relation="self")
    links = list(navigation)
    # TimeMaps need replay identities and enclosure manifests, never capture logs
    # or whole Crawl input lists duplicated across every joined capture.
    captures = (
        _captures(request, snapshot.url)
        .only(
            "id",
            "url",
            "downloaded_at",
            "fs_version",
            "timestamp",
            "bookmarked_at",
            "created_at",
            "crawl_id",
            "crawl__created_by_id",
            "crawl__created_by__username",
        )
        .prefetch_related(
            Prefetch("archiveresult_set", queryset=ArchiveResult.objects.only("snapshot_id", "plugin", "status", "output_files")),
        )
    )
    for capture in captures:
        url = build_snapshot_detail_url(capture.archive_path_from_db, request=request)
        links.append(f'<{url}>; rel="memento"; datetime="{http_date(capture.downloaded_at.timestamp())}"')
        links.extend(_enclosures(request, capture))
    if len(links) == len(navigation):
        raise Http404
    response = HttpResponse(",\n".join(links) + "\n", content_type="application/link-format")
    response["Link"] = ", ".join(navigation)
    response["Cache-Control"] = "private, no-store"  # Membership and visibility can change.
    return response


def timegate_response(request, url):
    # A source URL's query belongs to the lookup, never to the destination UI.
    if request.META.get("QUERY_STRING"):
        url += "?" + request.META["QUERY_STRING"]
    requested = request.headers.get("Accept-Datetime")
    timestamp = parse_http_date_safe(requested) if requested is not None else None
    # RFC 7089 4.5.3 requires strict IMF-fixdate and a 400 for invalid dates.
    if requested is not None and (timestamp is None or http_date(timestamp) != requested):
        return HttpResponse("Invalid Accept-Datetime", status=400)
    # Negotiation needs identity and the persisted replay path, not Crawl.urls,
    # config, notes, or user credentials repeated for every candidate.
    captures = _captures(request, url).only(
        "id",
        "url",
        "downloaded_at",
        "fs_version",
        "timestamp",
        "bookmarked_at",
        "created_at",
        "crawl_id",
        "crawl__created_by_id",
        "crawl__created_by__username",
    )
    if timestamp is None:
        selected = captures.order_by("-downloaded_at", "-id").first()
    else:
        target = datetime.fromtimestamp(timestamp, tz=UTC)
        # Only the closest capture on each side can win. Keep the first id at
        # each timestamp, matching the original ascending list's stable tie rule.
        before = captures.filter(downloaded_at__lte=target).order_by("-downloaded_at", "id").first()
        after = captures.filter(downloaded_at__gte=target).order_by("downloaded_at", "id").first()
        candidates = [capture for capture in (before, after) if capture is not None]
        selected = min(candidates, key=lambda capture: abs(capture.downloaded_at.timestamp() - timestamp)) if candidates else None
    if selected is None:
        raise Http404
    # Pattern 2.1: the negotiation redirect itself is not a Memento (RFC 7089 4.2.1).
    response = redirect(build_snapshot_detail_url(selected.archive_path_from_db, request=request))
    response["Link"] = ", ".join(_links(request, selected))
    patch_vary_headers(response, ("Accept-Datetime",))
    response["Cache-Control"] = "private, no-store"
    return response
