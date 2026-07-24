__package__ = "archivebox.search"

import asyncio
import hashlib
import json
import threading
import time
from copy import copy
from queue import Full, Queue
from urllib.parse import urlsplit
from uuid import UUID

from django.core.cache import cache
from django.db import connections
from django.db.models import Q
from django.http import HttpResponseForbidden, QueryDict, StreamingHttpResponse

from archivebox.search.config import get_search_mode, get_search_mode_base
from archivebox.search.query import crawl_config_values_search_wave, iter_query_search_ids


SEARCH_RESULT_CACHE_TTL = 60
URL_PREFIX_SEARCH_LIMIT = 500


def get_admin_search_cache_key(request, url: str | None = None) -> str:
    """Build the cache key for one user and changelist URL."""
    # Search streams publish IDs for one exact changelist URL. Keeping the URL
    # whole makes sidebar filters, ordering, and user scope part of the key.
    payload = json.dumps(
        {
            "user": str(request.user.pk or "anon"),
            "url": url or request.get_full_path(),
        },
        sort_keys=True,
    )
    return f"abx:admin-search:{hashlib.sha256(payload.encode()).hexdigest()}"


def get_public_search_cache_key(request, url: str | None = None) -> str:
    """Build the cache key for one public search URL."""
    payload = json.dumps(
        {
            "url": url or request.get_full_path(),
        },
        sort_keys=True,
    )
    return f"abx:public-search:{hashlib.sha256(payload.encode()).hexdigest()}"


def get_cached_admin_search_ids(request) -> list[str] | None:
    """Return streamed admin search IDs from Django cache."""
    cached = cache.get(get_admin_search_cache_key(request))
    if isinstance(cached, dict):
        return cached.get("ids") or []
    return None


def get_cached_public_search_ids(request) -> list[str] | None:
    """Return streamed public search IDs from Django cache."""
    cached = get_cached_public_search_state(request)
    if isinstance(cached, dict):
        return cached.get("ids") or []
    return None


def get_cached_public_search_state(request) -> dict | None:
    """Return streamed public search state from Django cache."""
    cached = cache.get(get_public_search_cache_key(request))
    return cached if isinstance(cached, dict) else None


def iter_url_search_prefixes(query: str):
    """Yield URL prefixes that can use indexed startswith scans for common search input."""
    query = query.strip().lower()
    if not query or any(char.isspace() for char in query):
        return

    prefixes = []

    def add(prefix: str):
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)

    add(query)
    if "://" in query:
        parsed = urlsplit(query)
        if parsed.scheme and parsed.netloc:
            host = parsed.netloc
            path = parsed.path or ""
            if parsed.query:
                path = f"{path}?{parsed.query}"
            if host.startswith("www."):
                add(f"{parsed.scheme}://{host[4:]}{path}")
            else:
                add(f"{parsed.scheme}://www.{host}{path}")
    else:
        trimmed = query.lstrip("/")
        for scheme in ("https://", "http://"):
            add(f"{scheme}{trimmed}")
            if trimmed.startswith("www."):
                add(f"{scheme}{trimmed[4:]}")
            else:
                add(f"{scheme}www.{trimmed}")

    yield from prefixes


def url_prefix_upper_bound(prefix: str) -> str:
    """Return the exclusive upper bound for an indexed URL prefix range."""
    if not prefix:
        return prefix
    return f"{prefix[:-1]}{chr(ord(prefix[-1]) + 1)}"


def iter_url_prefix_search_ids(prefix: str, queryset):
    """Yield IDs for one URL prefix using the URL index, then apply caller filters."""
    if not prefix:
        return

    model = queryset.model
    db_alias = queryset.db
    connection = connections[db_alias]
    table = connection.ops.quote_name(model._meta.db_table)
    pk_column = connection.ops.quote_name(model._meta.pk.column)
    url_column = connection.ops.quote_name(model._meta.get_field("url").column)
    raw_ids = []

    if connection.vendor == "sqlite":
        # Bytewise range comparison uses the plain url btree index directly.
        where_clause = f"{url_column} >= %s AND {url_column} < %s"
        where_params = [prefix, url_prefix_upper_bound(prefix)]
    else:
        # Range comparisons are collation-dependent on postgres (linguistic
        # collations don't compare bytewise), so use LIKE with escaped
        # wildcards instead — correct under any collation and able to use the
        # url pattern-ops index.
        from archivebox.search.query import escape_like_query

        where_clause = f"{url_column} LIKE %s ESCAPE '\\'"
        where_params = [f"{escape_like_query(prefix)}%"]

    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT {pk_column}
            FROM {table}
            WHERE {where_clause}
            ORDER BY {url_column}
            LIMIT %s
            """,
            [*where_params, URL_PREFIX_SEARCH_LIMIT],
        )
        raw_ids = [str(row[0]).replace("-", "") for row in cursor.fetchall()]

    if not raw_ids:
        return

    valid_ids = {str(pk).replace("-", "") for pk in queryset.filter(pk__in=raw_ids).values_list("pk", flat=True)}
    for snapshot_id in raw_ids:
        if snapshot_id in valid_ids:
            yield snapshot_id


def iter_meta_search_ids(query, queryset):
    """Yield metadata search matches from a filtered Snapshot queryset."""
    seen = set()
    try:
        snapshot_id = UUID(query)
    except ValueError:
        snapshot_id = None
    if snapshot_id:
        for pk in queryset.filter(pk=snapshot_id).values_list("pk", flat=True):
            seen.add(pk)
            yield pk

    for prefix in iter_url_search_prefixes(query):
        for pk in iter_url_prefix_search_ids(prefix, queryset):
            if pk in seen:
                continue
            seen.add(pk)
            yield pk

    waves = [
        Q(timestamp__startswith=query) | Q(title__istartswith=query),
        Q(url__icontains=query),
        Q(title__icontains=query),
        Q(tags__name__icontains=query),
        Q(notes__icontains=query),
    ]
    for wave in waves:
        for pk in queryset.filter(wave).values_list("pk", flat=True).distinct().iterator(chunk_size=500):
            if pk in seen:
                continue
            seen.add(pk)
            yield pk

    crawl_metadata_wave = Q(crawl__notes__icontains=query) | Q(crawl__label__icontains=query) | Q(crawl__created_by__username=query)
    if not seen:
        for pk in queryset.filter(crawl_metadata_wave).values_list("pk", flat=True).distinct().iterator(chunk_size=500):
            seen.add(pk)
            yield pk

    config_wave = crawl_config_values_search_wave(query)
    if config_wave is not None and not seen:
        for pk in queryset.filter(config_wave).values_list("pk", flat=True).distinct().iterator(chunk_size=500):
            seen.add(pk)
            yield pk


def normalize_search_result_id(snapshot_id) -> str | None:
    """Return a compact Snapshot ID string from a search provider result."""
    snapshot_id = str(snapshot_id).strip().lower().replace("-", "")
    if len(snapshot_id) != 32:
        return None
    return snapshot_id


def iter_filtered_search_result_ids(iterator, queryset, *, flush_max_delay=0.05):
    """Yield provider IDs that still match the filtered queryset.

    This is the single intersection/dedupe path used for metadata and every
    search backend. It flushes by elapsed time so sparse providers stream rows
    as soon as IDs are found instead of waiting for a fixed batch size.
    """
    batch = []
    seen = set()
    queued = set()
    last_flush_at = 0.0

    def flush_batch():
        nonlocal batch, queued, last_flush_at
        if not batch:
            return
        batch_ids = batch
        batch = []
        queued = set()
        last_flush_at = time.monotonic()
        valid = {str(pk).replace("-", "") for pk in queryset.filter(pk__in=batch_ids).values_list("pk", flat=True)}
        for snapshot_id in batch_ids:
            if snapshot_id in valid and snapshot_id not in seen:
                seen.add(snapshot_id)
                yield snapshot_id

    for snapshot_id in iterator:
        snapshot_id = normalize_search_result_id(snapshot_id)
        if not snapshot_id or snapshot_id in seen or snapshot_id in queued:
            continue
        batch.append(snapshot_id)
        queued.add(snapshot_id)
        if not seen or time.monotonic() - last_flush_at >= flush_max_delay:
            yield from flush_batch()
    if batch:
        yield from flush_batch()


def iter_search_result_ids(query, base_queryset, *, search_mode, config):
    """Yield filtered Snapshot IDs from the selected search provider."""
    search_mode_base = get_search_mode_base(search_mode, config=config)
    provider = (
        iter_meta_search_ids(query, base_queryset)
        if search_mode_base == "meta"
        else iter_query_search_ids(query, search_mode=search_mode, config=config)
    )
    yield from iter_filtered_search_result_ids(provider, base_queryset)


def snapshot_search_stream_response(query, base_queryset, *, search_mode, config, cache_key, thread_name):
    """Stream Snapshot search progress and cache matching IDs for a list view."""
    if not query:
        return StreamingHttpResponse((), content_type="text/plain")

    async def snapshot_ids():
        seen = set()
        ids = []
        last_sent = 0
        last_sent_at = time.monotonic()
        stream_max_delay = 0.05
        stream_padding = " " * 4096
        cache.set(cache_key, {"ids": [], "done": False}, SEARCH_RESULT_CACHE_TTL)
        queue = Queue(maxsize=8)
        stop_event = threading.Event()

        def emit(item):
            while not stop_event.is_set():
                try:
                    queue.put(item, timeout=0.1)
                    return
                except Full:
                    continue

        def publish_count(done=False):
            nonlocal last_sent, last_sent_at
            cache.set(cache_key, {"ids": list(ids), "done": done}, SEARCH_RESULT_CACHE_TTL)
            last_sent = len(ids)
            last_sent_at = time.monotonic()
            emit(f"{last_sent}{stream_padding}\n")

        def run_search():
            iterator = None
            try:
                iterator = iter_search_result_ids(query, base_queryset, search_mode=search_mode, config=config)
                for snapshot_id in iterator:
                    if stop_event.is_set():
                        break
                    snapshot_id = normalize_search_result_id(snapshot_id)
                    if not snapshot_id or snapshot_id in seen:
                        continue
                    seen.add(snapshot_id)
                    ids.append(snapshot_id)
                    if len(ids) == 1 or time.monotonic() - last_sent_at >= stream_max_delay:
                        publish_count()
                if not stop_event.is_set() and len(ids) != last_sent:
                    publish_count(done=True)
            except BaseException as err:
                emit(err)
            finally:
                if iterator is not None:
                    try:
                        iterator.close()
                    except AttributeError:
                        pass
                cache.set(cache_key, {"ids": list(ids), "done": True}, SEARCH_RESULT_CACHE_TTL)
                emit(None)

        threading.Thread(target=run_search, name=thread_name, daemon=True).start()
        yield f"0{stream_padding}\n"
        try:
            while True:
                item = await asyncio.to_thread(queue.get)
                if item is None:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            stop_event.set()

    response = StreamingHttpResponse(snapshot_ids(), content_type="text/plain")
    response["X-Accel-Buffering"] = "no"
    return response


def admin_snapshot_search_stream_view(model_admin, request):
    """Stream admin Snapshot search progress and cache matching IDs."""
    query = (request.GET.get("q") or "").strip()
    config = request.archivebox_config
    search_mode = get_search_mode(request.GET.get("search_mode"), config=config)

    search_url = request.GET.get("search_url") or request.get_full_path()
    target_url = urlsplit(search_url)
    target_get = QueryDict(target_url.query, mutable=True)
    for key in ("q", "search_mode", "p", "search_url"):
        target_get.pop(key, None)

    filter_request = copy(request)
    filter_request.path = target_url.path or request.path
    filter_request.path_info = target_url.path or request.path_info
    filter_request.GET = target_get
    filter_request.archivebox_config = config

    # Build the same filtered base queryset the changelist uses, but with the
    # search params stripped. The stream intersects each wave with this queryset
    # before writing IDs into the short-lived cache consumed by the changelist.
    current_request = model_admin.__dict__.get("request")
    try:
        base_queryset = model_admin.get_changelist_instance(filter_request).queryset
    finally:
        model_admin.request = current_request

    return snapshot_search_stream_response(
        query,
        base_queryset,
        search_mode=search_mode,
        config=config,
        cache_key=get_admin_search_cache_key(request, search_url),
        thread_name="admin-snapshot-search-stream",
    )


def public_snapshot_search_stream_view(request):
    """Stream public Snapshot search progress and cache matching IDs."""
    from archivebox.config.common import get_request_config
    from archivebox.core.models import Snapshot
    from archivebox.core.permissions import public_snapshots_queryset

    config = getattr(request, "archivebox_config", None) or get_request_config(request, resolve_plugins=False)
    if not request.user.is_authenticated and not config.PUBLIC_INDEX:
        return HttpResponseForbidden("Public index is disabled")

    query = (request.GET.get("q") or "").strip()
    search_mode = get_search_mode(request.GET.get("search_mode"), config=config)
    search_url = request.GET.get("search_url") or request.get_full_path()
    base_queryset = public_snapshots_queryset(Snapshot.objects.all())

    return snapshot_search_stream_response(
        query,
        base_queryset,
        search_mode=search_mode,
        config=config,
        cache_key=get_public_search_cache_key(request, search_url),
        thread_name="public-snapshot-search-stream",
    )
