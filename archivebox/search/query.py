__package__ = "archivebox.search"

from typing import Any

from django.db import connection
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

from archivebox.config.common import get_config
from archivebox.misc.logging import stderr
from archivebox.misc.util import enforce_types
from archivebox.search.backends import get_available_backends, get_backend, normalize_search_backend_name, search_backend_env
from archivebox.search.config import get_search_mode, get_search_mode_backend, get_search_mode_base


MAX_SEARCH_RANK_IDS = 500


def escape_like_query(query: str) -> str:
    """Escape a string for SQL LIKE matching (used with ESCAPE '\\')."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def crawl_config_values_search_wave(query: str) -> Q | None:
    """Build a Snapshot Q predicate matching values inside Crawl.config."""
    from archivebox.crawls.models import Crawl

    pattern = f"%{escape_like_query(query).lower()}%"
    if connection.vendor == "sqlite":
        matching_crawls = Crawl.objects.extra(
            where=[
                """
                EXISTS (
                    SELECT 1
                    FROM json_tree(config)
                    WHERE json_tree.atom IS NOT NULL
                      AND LOWER(CAST(json_tree.atom AS TEXT)) LIKE %s ESCAPE '\\'
                )
                """,
            ],
            params=[pattern],
        )
    elif connection.vendor == "postgresql":
        # Match only scalar config *values*, not keys (mirrors SQLite's
        # json_tree.atom). jsonb_path_query('$.**') walks every nested node;
        # keep the non-container leaves and compare their text form.
        matching_crawls = Crawl.objects.extra(
            where=[
                """
                EXISTS (
                    SELECT 1
                    FROM jsonb_path_query(config, '$.**') AS leaf
                    WHERE jsonb_typeof(leaf) NOT IN ('object', 'array')
                      AND LOWER(leaf #>> '{}') LIKE %s ESCAPE '\\'
                )
                """,
            ],
            params=[pattern],
        )
    else:
        return None
    return Q(crawl_id__in=matching_crawls.values("pk"))


def snapshot_metadata_search_waves(query: str, *, include_id_matches: bool = False) -> list[Q]:
    """Build ordered metadata predicates for Snapshot search."""
    waves = []
    if include_id_matches:
        waves.append(Q(id__istartswith=query) | Q(id__iendswith=query))

    waves.extend(
        [
            Q(title__icontains=query) | Q(url__icontains=query) | Q(timestamp__icontains=query),
            Q(tags__name__icontains=query),
            Q(notes__icontains=query) | Q(crawl__notes__icontains=query) | Q(crawl__label__icontains=query),
            Q(crawl__created_by__username=query),
        ],
    )

    config_wave = crawl_config_values_search_wave(query)
    if config_wave is not None:
        waves.append(config_wave)
    return waves


def prioritize_metadata_matches(
    base_queryset: QuerySet,
    metadata_queryset: QuerySet,
    fulltext_queryset: QuerySet,
    *,
    deep_queryset: QuerySet | None = None,
    ordering: list[str] | tuple[str, ...] | None = None,
) -> QuerySet:
    """Rank metadata hits before backend full-text hits."""
    metadata_ids = list(metadata_queryset.values_list("pk", flat=True).distinct()[: MAX_SEARCH_RANK_IDS + 1])
    metadata_id_set = set(metadata_ids)
    fulltext_ids = [
        pk for pk in fulltext_queryset.values_list("pk", flat=True).distinct()[: MAX_SEARCH_RANK_IDS + 1] if pk not in metadata_id_set
    ]
    fulltext_id_set = set(fulltext_ids)
    deep_ids = []
    if deep_queryset is not None:
        deep_ids = [
            pk
            for pk in deep_queryset.values_list("pk", flat=True).distinct()[: MAX_SEARCH_RANK_IDS + 1]
            if pk not in metadata_id_set and pk not in fulltext_id_set
        ]

    if not metadata_ids and not fulltext_ids and not deep_ids:
        return base_queryset.none()

    if any(len(ids) > MAX_SEARCH_RANK_IDS for ids in (metadata_ids, fulltext_ids, deep_ids)):
        search_filter = Q()
        if metadata_ids:
            search_filter |= Q(pk__in=metadata_queryset.values("pk").distinct())
        if fulltext_ids:
            search_filter |= Q(pk__in=fulltext_queryset.values("pk").distinct())
        if deep_queryset is not None and deep_ids:
            search_filter |= Q(pk__in=deep_queryset.values("pk").distinct())
        qs = base_queryset.filter(search_filter)
        if ordering is not None:
            qs = qs.order_by(*ordering)
        return qs.distinct()

    qs = base_queryset.filter(pk__in=[*metadata_ids, *fulltext_ids, *deep_ids]).annotate(
        search_rank=Case(
            When(pk__in=metadata_ids, then=Value(0)),
            When(pk__in=fulltext_ids, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        ),
    )

    if ordering is not None:
        qs = qs.order_by("search_rank", *ordering)

    return qs.distinct()


def apply_snapshot_search(
    base_queryset: QuerySet,
    query: str,
    *,
    search_mode: str | None = None,
    config: dict[str, Any] | None = None,
    ordering: list[str] | tuple[str, ...] | None = None,
    max_results: int | None = None,
    skip_backend_when_metadata_satisfies_limit: bool = False,
    include_metadata_for_forced_backend: bool = False,
    include_id_matches: bool = False,
) -> QuerySet:
    """Apply shared CLI/API/public/admin Snapshot search semantics."""
    query = (query or "").strip()
    if not query:
        return base_queryset

    config = config or get_config()
    search_mode = get_search_mode(search_mode, config=config)
    search_mode_base = get_search_mode_base(search_mode, config=config)
    search_mode_backend = get_search_mode_backend(search_mode, config=config)
    metadata_filter = Q()
    for wave in snapshot_metadata_search_waves(query, include_id_matches=include_id_matches):
        metadata_filter |= wave
    metadata_queryset = base_queryset.filter(metadata_filter)

    if search_mode_base == "meta":
        return metadata_queryset.distinct()

    if skip_backend_when_metadata_satisfies_limit and max_results:
        metadata_ids = list(metadata_queryset.values_list("pk", flat=True).distinct()[:max_results])
        if len(metadata_ids) >= max_results:
            return metadata_queryset.distinct()

    if search_mode_base == "deep":
        fulltext_search_mode = f"contents:{search_mode_backend}" if search_mode_backend else "contents"
        fulltext_queryset = query_search_index(query, search_mode=fulltext_search_mode, config=config, max_results=max_results)
        deep_queryset = query_search_index(query, search_mode=search_mode, config=config, max_results=max_results)
        return prioritize_metadata_matches(
            base_queryset,
            metadata_queryset,
            fulltext_queryset,
            deep_queryset=deep_queryset,
            ordering=ordering,
        )

    backend_queryset = query_search_index(query, search_mode=search_mode, config=config, max_results=max_results)
    if search_mode_backend and not include_metadata_for_forced_backend:
        return base_queryset.filter(pk__in=backend_queryset.values("pk")).distinct()

    return prioritize_metadata_matches(
        base_queryset,
        metadata_queryset,
        backend_queryset,
        ordering=ordering,
    )


@enforce_types
def query_search_index(
    query: str,
    search_mode: str | None = None,
    config: dict[str, Any] | None = None,
    max_results: int | None = None,
    **config_kwargs: Any,
) -> QuerySet:
    """Return a Snapshot queryset from backend search IDs."""
    from archivebox.core.models import Snapshot

    config = config or get_config(**config_kwargs)
    search_mode = "contents" if search_mode is None else get_search_mode(search_mode, config=config)
    search_mode_base = get_search_mode_base(search_mode, config=config)
    if search_mode_base == "meta":
        return Snapshot.objects.none()

    snapshot_pks = list(iter_query_search_ids(query, search_mode=search_mode, config=config, max_results=max_results))
    return Snapshot.objects.filter(pk__in=list(dict.fromkeys(snapshot_pks)))


def iter_query_search_ids(
    query: str,
    search_mode: str | None = None,
    config: dict[str, Any] | None = None,
    max_results: int | None = None,
    **config_kwargs: Any,
):
    """Yield snapshot IDs from configured search backend modules."""
    config = config or get_config(**config_kwargs)
    search_mode = "contents" if search_mode is None else get_search_mode(search_mode, config=config)
    search_mode_base = get_search_mode_base(search_mode, config=config)
    forced_backend = get_search_mode_backend(search_mode, config=config)
    if search_mode_base == "meta":
        return

    backends = get_available_backends()
    configured_backend = normalize_search_backend_name(config.SEARCH_BACKEND_ENGINE)
    fallback_enabled = search_mode_base == "deep" and (not forced_backend or forced_backend == configured_backend == "sonic")
    if forced_backend:
        if forced_backend not in backends:
            raise RuntimeError(
                f'Search backend "{forced_backend}" not found. Available backends: {list(backends) or "none"}',
            )
        backend_names = (
            [
                forced_backend,
                *(name for name in backends if name not in {forced_backend, "ripgrep"}),
                *(["ripgrep"] if "ripgrep" in backends and forced_backend != "ripgrep" else []),
            ]
            if fallback_enabled
            else [forced_backend]
        )
    elif search_mode_base == "deep":
        backend_names = [
            *([configured_backend] if configured_backend in backends and configured_backend != "ripgrep" else []),
            *(name for name in backends if name not in {configured_backend, "ripgrep"}),
            *(["ripgrep"] if "ripgrep" in backends else []),
        ]
    elif configured_backend in backends:
        backend_names = [configured_backend]
    elif "ripgrep" in backends:
        backend_names = ["ripgrep"]
    else:
        get_backend()
        return

    errors: list[Exception] = []
    successful_backends = 0
    seen: set[str] = set()
    try:
        for backend_name in backend_names:
            backend = backends[backend_name]
            try:
                if backend_name == "sonic":
                    import sys
                    from contextlib import redirect_stdout

                    from archivebox.core.takeover_util import ensure_daemon_stack

                    # Search commands can produce structured stdout such as
                    # --csv/--json. Keep daemon diagnostics on stderr.
                    with redirect_stdout(sys.stderr):
                        ensure_daemon_stack(reason="search query")
                with search_backend_env(config=config):
                    if backend_name == "ripgrep":
                        ids = backend.iter_search(query, search_mode=search_mode_base)
                    else:
                        ids = backend.search(query)
                    for snapshot_id in ids:
                        if snapshot_id in seen:
                            continue
                        seen.add(snapshot_id)
                        yield snapshot_id
                        if max_results and len(seen) >= max_results:
                            return
                successful_backends += 1
            except Exception as err:
                errors.append(err)
                if not fallback_enabled:
                    raise
    except Exception as err:
        stderr()
        stderr(
            f"[X] The search backend threw an exception={err}:",
            color="red",
        )
        raise
    else:
        if not successful_backends and errors and search_mode_base == "deep":
            raise errors[0]


@enforce_types
def flush_search_index(snapshots: QuerySet, config: dict[str, Any] | None = None, **config_kwargs: Any) -> None:
    """Remove Snapshot IDs from the configured search backend index."""
    config = config or get_config(**config_kwargs)
    if not snapshots:
        return

    backend = get_backend(config=config)
    snapshot_pks = [str(pk) for pk in snapshots.values_list("pk", flat=True)]

    try:
        with search_backend_env(config=config):
            backend.flush(snapshot_pks)
    except Exception as err:
        stderr()
        stderr(
            f"[X] The search backend threw an exception={err}:",
            color="red",
        )
