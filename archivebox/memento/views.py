"""Read-only Memento negotiation: https://www.rfc-editor.org/rfc/rfc7089.html#section-3

The original URL (URI-R) identifies the page; canonical snapshots (URI-M) identify
captures. Existing /archive/<url> and snapshot?format=link routes provide the
TimeGate (URI-G) and TimeMap (URI-T), without capture hooks or new archive steps.
"""

from urllib.parse import quote

from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date, parse_http_date_safe

from archivebox.core.models import Snapshot
from archivebox.core.permissions import is_admin_user, public_snapshots_queryset
from archivebox.core.routes_util import build_snapshot_detail_url, build_snapshot_url, build_web_url

ARCHIVE_TYPES = {".wacz": "application/wacz", ".warc.gz": "application/gzip", ".warc": "application/warc"}


def _captures(request, url):
    # Exact identity matters; public discovery must not reveal unlisted captures.
    snapshots = Snapshot.objects.filter(url=url, downloaded_at__isnull=False, output_size__gt=0).select_related("crawl__created_by")
    return (snapshots if is_admin_user(request) else public_snapshots_queryset(snapshots)).order_by("downloaded_at", "id")


def _links(request, snapshot, relation="timemap"):
    original = quote(snapshot.url, safe=":/?#[]@!$&'()*+,;=%")
    # Encode nested query/fragment delimiters so the lookup keeps the original URL.
    gate = build_web_url("/archive/" + quote(snapshot.url, safe=":/"), request=request)
    timemap = build_snapshot_detail_url(snapshot.archive_path_from_db, request=request) + "?format=link"
    return [f'<{original}>; rel="original"', f'<{gate}>; rel="timegate"', f'<{timemap}>; rel="{relation}"; type="application/link-format"']


def _archive_type(path):
    return next((mime for suffix, mime in ARCHIVE_TYPES.items() if path.lower().endswith(suffix)), None)


def _enclosures(request, snapshot):
    # Containers hold many resources: use enclosures, not extra URI-M entries.
    # anchor binds each download to its capture in a TimeMap (RFC 8288 section 3.2).
    anchor = build_snapshot_detail_url(snapshot.archive_path_from_db, request=request)
    results = snapshot.__dict__.get("_admin_archiveresults")
    if results is None:
        results = snapshot.archiveresult_set.all()
    for result in results:
        if result.status == result.StatusChoices.SUCCEEDED:
            files = result.output_file_map()
            for key in files:
                path = result.output_file_path(key, output_file_map=files)
                if path and (mime := _archive_type(path)):
                    url = build_snapshot_url(str(snapshot.id), path, request=request) + "?raw=1"
                    yield f'<{url}>; rel="enclosure"; type="{mime}"; anchor="{anchor}"'


def add_memento_headers(request, snapshot, response, path="", primary=True):
    if (mime := _archive_type(path)) and not response.get("Content-Type", "").startswith("text/html"):
        # gzip is the saved file format, not HTTP content coding: range offsets
        # must address compressed bytes. Whole bundles are not individual Mementos.
        response["Content-Type"] = mime
        response.headers.pop("Content-Encoding", None)
        return response
    if primary and snapshot.downloaded_at and snapshot.output_size and response.status_code in (200, 206, 304):
        # Persisted completion time, never request/bookmark time (RFC 7089 4.5.6).
        response["Memento-Datetime"] = http_date(snapshot.downloaded_at.timestamp())
        response["Link"] = ", ".join(filter(None, [response.get("Link"), *_links(request, snapshot), *_enclosures(request, snapshot)]))
    return response


def timemap_response(request, snapshot):
    # Link format is required by https://www.rfc-editor.org/rfc/rfc7089.html#section-5
    links = _links(request, snapshot, relation="self")
    captures = _captures(request, snapshot.url).prefetch_related("archiveresult_set")
    for capture in captures:
        url = build_snapshot_detail_url(capture.archive_path_from_db, request=request)
        links.append(f'<{url}>; rel="memento"; datetime="{http_date(capture.downloaded_at.timestamp())}"')
        links.extend(_enclosures(request, capture))
    if len(links) == 3:
        raise Http404
    response = HttpResponse(",\n".join(links) + "\n", content_type="application/link-format")
    response["Link"] = ", ".join(links[:3])
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
    captures = list(_captures(request, url))
    if not captures:
        raise Http404
    # Nearest includes out-of-range endpoints; sorted captures break ties earlier.
    selected = captures[-1] if timestamp is None else min(captures, key=lambda capture: abs(capture.downloaded_at.timestamp() - timestamp))
    # Pattern 2.1: the negotiation redirect itself is not a Memento (RFC 7089 4.2.1).
    response = redirect(build_snapshot_detail_url(selected.archive_path_from_db, request=request))
    response["Link"] = ", ".join(_links(request, selected))
    patch_vary_headers(response, ("Accept-Datetime",))
    response["Cache-Control"] = "private, no-store"
    return response
