__package__ = "archivebox.search"

import asyncio
import hashlib
import json
import threading
import time
from copy import copy
from itertools import batched
from queue import Empty, Full, Queue
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, QueryDict, StreamingHttpResponse

from archivebox.search.config import get_search_mode, get_search_mode_base
from archivebox.misc.util import equivalent_urls
from archivebox.search.query import crawl_config_values_search_wave, iter_query_search_ids, url_search_q


SEARCH_RESULT_CACHE_TTL = 60
URL_PREFIX_SEARCH_LIMIT = 500
# The stock LocMemCache is process-local. Serialize ownership changes and
# writes so a retired producer cannot replace newer membership for its key.
_search_cache_lock = threading.Lock()
_search_cache_owners: dict[str, object] = {}


def ranked_page_ids(scope, ids, *, start, size):
    """Keep provider order and recheck current visibility without sorting the whole cache in SQL."""
    page = []
    for batch in batched(ids, 512):
        valid = {pk.hex: pk for pk in scope.filter(pk__in=batch).order_by().values_list("pk", flat=True)}
        for snapshot_id in batch:
            if snapshot_id not in valid:
                continue
            if start:
                start -= 1
                continue
            page.append(valid[snapshot_id])
            if len(page) == size:
                return page
    return page


def sql_page_key(request, url, token):
    # A page belongs to one search, user, sort, and submission. Never put its
    # bounded IDs in the membership cache shared by exports or other pages.
    target = urlsplit(url)
    scope = sorted(QueryDict(target.query).lists())
    payload = json.dumps([str(request.user.pk), target.path, scope, token])
    return "abx:sql-page:" + hashlib.sha256(payload.encode()).hexdigest()


def streamed_page_ids(request):
    token = request.headers.get("X-ArchiveBox-Search-Page")
    if token and len(token) == 32:
        state = cache.get(sql_page_key(request, request.get_full_path(), token))
        if state is not None:
            return [UUID(pk) for pk in state["ids"]]
    return None


def get_admin_search_cache_key(request, url: str | None = None) -> str:
    """Key membership by user, route and filters, not page or display ordering."""
    target = urlsplit(url or request.get_full_path())
    params = QueryDict(target.query, mutable=True)
    for key in ("o", "p", "sidebar"):
        params.pop(key, None)
    # Preserve each key's value order: repeated values may be meaningful to
    # filters. Sorting keys only makes equivalent URL parameter order stable.
    if params.get("search_mode") == "query":
        params.pop("search_mode")
    payload = json.dumps(
        {
            "user": str(request.user.pk or "anon"),
            "path": target.path,
            "params": sorted((key, params.getlist(key)) for key in params),
            "mode": get_search_mode(params.get("search_mode") or "query", config=request.archivebox_config),
        },
        sort_keys=True,
    )
    return f"abx:admin-search:{hashlib.sha256(payload.encode()).hexdigest()}"


def get_public_search_cache_key(request, url: str | None = None) -> str:
    """Share public membership across pages, retaining route, mode and scope."""
    target = urlsplit(url or request.get_full_path())
    params = QueryDict(target.query, mutable=True)
    for key in ("page", "sidebar"):
        params.pop(key, None)
    if params.get("search_mode") == "query":
        params.pop("search_mode")
    payload = json.dumps(
        {
            "path": target.path,
            "params": sorted((key, params.getlist(key)) for key in params),
            "mode": get_search_mode(params.get("search_mode") or "query", config=request.archivebox_config),
        },
        sort_keys=True,
    )
    return f"abx:public-search:{hashlib.sha256(payload.encode()).hexdigest()}"


def get_cached_admin_search_state(request):
    """Read one membership cache once for consistent IDs and completion state."""
    cached = cache.get(get_admin_search_cache_key(request))
    return cached if isinstance(cached, dict) else None


def get_cached_admin_search_ids(request) -> list[str] | None:
    """Return streamed admin search IDs from Django cache."""
    cached = get_cached_admin_search_state(request)
    return (cached.get("ids") or []) if cached is not None else None


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

    # For a bare hostname, prefer its domain boundary to lexical lookalikes
    # such as example.com-news.test. Reuse the existing indexed, filtered
    # prefix scan; retain every original wave below for complete recall.
    if "://" not in query and "." in query and not any(char in query for char in "/:?#@"):
        for scheme in ("https://", "http://"):
            add(f"{scheme}{query}/")
            alternate = query[4:] if query.startswith("www.") else f"www.{query}"
            add(f"{scheme}{alternate}/")

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

    # A URL query may be spelled as IRI (/über) or URI (/%C3%BCber), and the
    # snapshot stored in the other spelling; prefix-scan each of them.
    for url_query in equivalent_urls(query):
        for prefix in iter_url_search_prefixes(url_query):
            for pk in iter_url_prefix_search_ids(prefix, queryset):
                if pk in seen:
                    continue
                seen.add(pk)
                yield pk

    waves = [
        Q(timestamp__startswith=query) | Q(title__istartswith=query),
        url_search_q(query),
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
    for pk in queryset.filter(crawl_metadata_wave).values_list("pk", flat=True).distinct().iterator(chunk_size=500):
        if pk in seen:
            continue
        seen.add(pk)
        yield pk

    config_wave = crawl_config_values_search_wave(query, crawl_ids=queryset.order_by().values("crawl_id"))
    if config_wave is not None:
        for pk in queryset.filter(config_wave).values_list("pk", flat=True).distinct().iterator(chunk_size=500):
            if pk in seen:
                continue
            seen.add(pk)
            yield pk


def normalize_search_result_id(snapshot_id) -> str | None:
    """Return a compact Snapshot ID string from a search provider result."""
    snapshot_id = str(snapshot_id).strip().lower().replace("-", "")
    if len(snapshot_id) != 32 or any(char not in "0123456789abcdef" for char in snapshot_id):
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


def iter_search_result_ids(query, base_queryset, *, search_mode, config, stop_event=None):
    """Yield filtered Snapshot IDs from the selected search provider."""
    search_mode_base = get_search_mode_base(search_mode, config=config)
    if search_mode_base == "query":
        from archivebox.search.interpreter import SnapshotSearch

        yield from SnapshotSearch(base_queryset, query, config=config, stop_event=stop_event).stream()
        return
    if search_mode_base == "url":
        provider = base_queryset.filter(url_search_q(query.strip())).values_list("pk", flat=True).iterator(chunk_size=1000)
    elif search_mode_base == "meta":
        provider = iter_meta_search_ids(query, base_queryset)
    else:
        provider = iter_query_search_ids(query, search_mode=search_mode, config=config, stop_event=stop_event)
    try:
        yield from iter_filtered_search_result_ids(provider, base_queryset)
    finally:
        provider.close()


def snapshot_search_stream_response(query, base_queryset, *, search_mode, config, cache_key, thread_name, public=False, page_request=None):
    """Stream Snapshot search progress and cache matching IDs for a list view."""
    if not query:
        return StreamingHttpResponse((), content_type="text/plain")

    search = None
    page_query = None
    page_token = None
    if search_mode == "query":
        from archivebox.search.interpreter import SnapshotSearch

        try:
            search = SnapshotSearch(base_queryset, query, config=config, public=public, streaming=True)
        except (ValueError, ValidationError) as err:
            return HttpResponseBadRequest(str(err), content_type="text/plain")
        page_query = search.sql_queryset()
    elif search_mode == "url" and page_request:
        page_query = base_queryset.filter(url_search_q(query.strip()))

    if page_query is not None:
        if not page_request:
            return HttpResponse(status=204)
        request, list_url = page_request
        page_token = uuid4().hex
        cache_key = sql_page_key(request, list_url, page_token)
    elif page_request:
        # Mixed queries use provider rank unless the user chose a column.
        if "o" not in QueryDict(urlsplit(page_request[1]).query):
            base_queryset = base_queryset.order_by()
            if search is not None:
                search.scope = base_queryset

    async def snapshot_ids():
        seen = set()
        ids = []
        last_sent = 0
        last_sent_at = time.monotonic()
        stream_max_delay = 0.05
        stream_padding = " " * 4096
        queue = Queue(maxsize=256)
        stop_event = threading.Event()
        owner = object()
        with _search_cache_lock:
            cache.set(cache_key, {"ids": [], "done": False}, SEARCH_RESULT_CACHE_TTL)
            _search_cache_owners[cache_key] = owner

        def cache_results(done):
            with _search_cache_lock:
                if _search_cache_owners.get(cache_key) is owner:
                    cache.set(
                        cache_key,
                        {"ids": list(ids), "done": done, "partial": bool(search and search.partial)},
                        SEARCH_RESULT_CACHE_TTL,
                    )

        def emit(item):
            while not stop_event.is_set():
                try:
                    queue.put(item, timeout=0.1)
                    return
                except Full:
                    continue

        def next_batch():
            # A producer may find several rows then block on remote storage.
            # Flush on the consumer clock even when no next match arrives.
            batch = []
            try:
                batch.append(queue.get(timeout=stream_max_delay))
                while len(batch) < queue.maxsize:
                    batch.append(queue.get_nowait())
            except Empty:
                pass
            return batch

        def run_search():
            iterator = None
            try:
                close_old_connections()
                if page_query is not None:
                    from archivebox.misc.paginators import iter_snapshot_page

                    iterator = iter_snapshot_page(
                        page_query.values_list("pk", flat=True),
                        base_queryset=base_queryset.model.objects.using(base_queryset.db).values_list("pk", flat=True),
                        start=0,
                        size=config.SNAPSHOTS_PER_PAGE + 1,
                        chunk_size=1,
                    )
                elif search is not None:
                    search.stop_event = stop_event
                    iterator = search.stream()
                else:
                    iterator = iter_search_result_ids(query, base_queryset, search_mode=search_mode, config=config, stop_event=stop_event)
                for snapshot_id in iterator:
                    if stop_event.is_set():
                        break
                    snapshot_id = normalize_search_result_id(snapshot_id)
                    if not snapshot_id or snapshot_id in seen:
                        continue
                    seen.add(snapshot_id)
                    emit(snapshot_id)
            except BaseException as err:
                emit(err)
            finally:
                if iterator is not None:
                    try:
                        iterator.close()
                    except AttributeError:
                        pass
                close_old_connections()
                emit(None)

        try:
            threading.Thread(target=run_search, name=thread_name, daemon=True).start()
            yield f"0{stream_padding}\n"
            heartbeat = time.monotonic()
            while True:
                done = False
                for item in await asyncio.to_thread(next_batch):
                    if isinstance(item, BaseException):
                        raise item
                    if item is None:
                        done = True
                    else:
                        ids.append(item)
                now = time.monotonic()
                if done or (len(ids) != last_sent and (not last_sent or now - last_sent_at >= stream_max_delay)):
                    cache_results(done)
                    if len(ids) != last_sent:
                        last_sent, last_sent_at = len(ids), now
                        yield f"{last_sent}{stream_padding}\n"
                if done:
                    break
                if now - heartbeat >= 10:
                    with _search_cache_lock:
                        if _search_cache_owners.get(cache_key) is owner:
                            cache.touch(cache_key, SEARCH_RESULT_CACHE_TTL)
                    heartbeat = now
                    yield "\n"
        finally:
            stop_event.set()
            with _search_cache_lock:
                if _search_cache_owners.get(cache_key) is owner:
                    del _search_cache_owners[cache_key]

    response = StreamingHttpResponse(snapshot_ids(), content_type="text/plain")
    if page_token:
        response["X-ArchiveBox-Search-Page"] = page_token
    response["X-Accel-Buffering"] = "no"
    return response


def stream_target_matches(request, search_url, query, mode):
    # The client includes its list URL to preserve filters and pagination.
    # Never let a producer fill a different expression's membership cache.
    params = QueryDict(urlsplit(search_url).query)
    return (params.get("q") or "").strip() == query and get_search_mode(
        params.get("search_mode") or "query",
        config=request.archivebox_config,
    ) == mode


def snapshot_view_scope(request, list_url, *, model_admin=None, ordered=False):
    """Use the list's own filters for both matching and value suggestions."""
    target = urlsplit(list_url)
    filtered = copy(request)
    filtered.path = filtered.path_info = target.path
    filtered.GET = QueryDict(target.query, mutable=True)
    for key in ("q", "search_mode", "p", "page", "search_url"):
        filtered.GET.pop(key, None)
    if model_admin is None:
        from archivebox.core.views import PublicIndexView

        view = PublicIndexView()
        view.setup(filtered)
        qs = view.get_queryset().defer(None).select_related(None)
        return qs.order_by(*view.ordering, "pk") if ordered else qs.order_by()

    # SnapshotAdmin uses the current request to render columns. A per-request
    # copy keeps simultaneous streams and keystrokes off the shared admin object.
    scoped_admin = copy(model_admin)
    scoped_admin.request = filtered
    filtered._archivebox_search_filter_only = True
    qs = scoped_admin.get_changelist_instance(filtered).queryset
    return qs if ordered or "o" in filtered.GET else qs.order_by()


def wants_streamed_page(request, list_url):
    params = QueryDict(urlsplit(list_url).query)
    return request.headers.get("X-ArchiveBox-Search-Page") == "first" and not any(k in params for k in ("all", "page", "p"))


def admin_snapshot_search_stream_view(model_admin, request):
    """Stream admin Snapshot search progress and cache matching IDs."""
    query = (request.GET.get("q") or "").strip()
    config = request.archivebox_config
    search_mode = get_search_mode(request.GET.get("search_mode") or "query", config=config)

    search_url = request.GET.get("search_url") or request.get_full_path()
    if not stream_target_matches(request, search_url, query, search_mode):
        return HttpResponseBadRequest("Search expression and result URL disagree.", content_type="text/plain")
    ordered = wants_streamed_page(request, search_url)
    base_queryset = snapshot_view_scope(request, search_url, model_admin=model_admin, ordered=ordered)

    return snapshot_search_stream_response(
        query,
        base_queryset,
        search_mode=search_mode,
        config=config,
        cache_key=get_admin_search_cache_key(request, search_url),
        thread_name="admin-snapshot-search-stream",
        page_request=(request, search_url) if ordered else None,
    )


def public_snapshot_search_stream_view(request):
    """Stream public Snapshot search progress and cache matching IDs."""
    from archivebox.config.common import get_request_config

    config = getattr(request, "archivebox_config", None) or get_request_config(request, resolve_plugins=False)
    if not request.user.is_authenticated and not config.PUBLIC_INDEX:
        return HttpResponseForbidden("Public index is disabled")

    query = (request.GET.get("q") or "").strip()
    search_mode = get_search_mode(request.GET.get("search_mode") or "query", config=config)
    search_url = request.GET.get("search_url") or request.get_full_path()
    if not stream_target_matches(request, search_url, query, search_mode):
        return HttpResponseBadRequest("Search expression and result URL disagree.", content_type="text/plain")
    ordered = wants_streamed_page(request, search_url)
    base_queryset = snapshot_view_scope(request, search_url, ordered=ordered)

    return snapshot_search_stream_response(
        query,
        base_queryset,
        search_mode=search_mode,
        config=config,
        cache_key=get_public_search_cache_key(request, search_url),
        thread_name="public-snapshot-search-stream",
        public=True,
        page_request=(request, search_url) if ordered else None,
    )
