"""
Search module for ArchiveBox.

Search indexing is handled by search backend hooks in plugins:
    abx_plugins/plugins/search_backend_*/on_Snapshot__*_index_*.py

This module provides the query interface that dynamically discovers
search backend plugins using the hooks system.

Search backends must provide a search.py module with:
    - search(query: str) -> List[str]  (returns snapshot IDs)
    - flush(snapshot_ids: Iterable[str]) -> None
"""

__package__ = "archivebox.search"

import os
from contextlib import contextmanager
from typing import Any

from django.db.models import Case, IntegerField, QuerySet, Value, When

from archivebox.misc.util import enforce_types
from archivebox.misc.logging import stderr
from archivebox.config.common import get_config


# Cache discovered backends to avoid repeated filesystem scans
_search_backends_cache: dict | None = None
SEARCH_MODES = ("meta", "contents", "deep")


@contextmanager
def search_backend_env(config: dict[str, Any] | None = None, **config_kwargs: Any):
    """Expose ArchiveBox collection roots to in-process search backends."""
    config = config or get_config(**config_kwargs)
    updates = {}
    for key, value in config.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool, os.PathLike)):
            updates[str(key)] = str(value)
    updates["DATA_DIR"] = str(config.DATA_DIR)
    updates["SNAP_DIR"] = str(config.USERS_DIR)
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def get_default_search_mode(config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    config = config or get_config(**config_kwargs)
    return "meta" if config.SEARCH_BACKEND_ENGINE == "ripgrep" else "contents"


def get_search_mode(search_mode: str | None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    normalized = (search_mode or "").strip().lower()
    return normalized if normalized in SEARCH_MODES else get_default_search_mode(config=config, **config_kwargs)


def prioritize_metadata_matches(
    base_queryset: QuerySet,
    metadata_queryset: QuerySet,
    fulltext_queryset: QuerySet,
    *,
    deep_queryset: QuerySet | None = None,
    ordering: list[str] | tuple[str, ...] | None = None,
) -> QuerySet:
    metadata_ids = list(metadata_queryset.values_list("pk", flat=True).distinct())
    metadata_id_set = set(metadata_ids)
    fulltext_ids = [pk for pk in fulltext_queryset.values_list("pk", flat=True).distinct() if pk not in metadata_id_set]
    fulltext_id_set = set(fulltext_ids)
    deep_ids = []
    if deep_queryset is not None:
        deep_ids = [
            pk for pk in deep_queryset.values_list("pk", flat=True).distinct() if pk not in metadata_id_set and pk not in fulltext_id_set
        ]

    if not metadata_ids and not fulltext_ids and not deep_ids:
        return base_queryset.none()

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


def get_available_backends() -> dict:
    """
    Discover all available search backend plugins.

    Uses the hooks system to find plugins with search.py modules.
    Results are cached after first call.
    """
    global _search_backends_cache

    if _search_backends_cache is None:
        from archivebox.hooks import get_search_backends

        _search_backends_cache = get_search_backends()

    return _search_backends_cache


def get_backend(config: dict[str, Any] | None = None, **config_kwargs: Any) -> Any:
    """
    Get the configured search backend module.

    Discovers available backends via the hooks system and returns
    the one matching SEARCH_BACKEND_ENGINE configuration.

    Falls back to 'ripgrep' if configured backend is not found.
    """
    config = config or get_config(**config_kwargs)
    backend_name = config.SEARCH_BACKEND_ENGINE
    backends = get_available_backends()

    if backend_name in backends:
        return backends[backend_name]

    # Fallback to ripgrep if available (no index needed)
    if "ripgrep" in backends:
        return backends["ripgrep"]

    # No backends found
    available = list(backends.keys())
    raise RuntimeError(
        f'Search backend "{backend_name}" not found. Available backends: {available or "none"}',
    )


@enforce_types
def query_search_index(query: str, search_mode: str | None = None, config: dict[str, Any] | None = None, **config_kwargs: Any) -> QuerySet:
    """
    Search for snapshots matching the query.

    Returns a QuerySet of Snapshot objects matching the search.
    """
    from archivebox.core.models import Snapshot

    config = config or get_config(**config_kwargs)
    if not config.USE_SEARCHING_BACKEND:
        return Snapshot.objects.none()

    search_mode = "contents" if search_mode is None else get_search_mode(search_mode, config=config)
    if search_mode == "meta":
        return Snapshot.objects.none()

    backends = get_available_backends()
    backend_names: list[str] = []
    configured_backend = config.SEARCH_BACKEND_ENGINE
    if search_mode == "deep":
        if "ripgrep" in backends:
            backend_names.append("ripgrep")
        backend_names.extend(name for name in backends if name != "ripgrep")
    elif configured_backend in backends:
        backend_names.append(configured_backend)
    elif "ripgrep" in backends:
        backend_names.append("ripgrep")
    else:
        get_backend()
        return Snapshot.objects.none()

    snapshot_pks: list[str] = []
    errors: list[Exception] = []
    successful_backends = 0
    try:
        for backend_name in backend_names:
            backend = backends[backend_name]
            try:
                with search_backend_env(config=config):
                    if backend_name == "ripgrep":
                        snapshot_pks.extend(backend.search(query, search_mode=search_mode))
                    else:
                        snapshot_pks.extend(backend.search(query))
                successful_backends += 1
            except Exception as err:
                errors.append(err)
                if search_mode != "deep":
                    raise
    except Exception as err:
        stderr()
        stderr(
            f"[X] The search backend threw an exception={err}:",
            color="red",
        )
        raise
    else:
        if not successful_backends and errors and search_mode == "deep":
            raise errors[0]
        return Snapshot.objects.filter(pk__in=list(dict.fromkeys(snapshot_pks)))


@enforce_types
def flush_search_index(snapshots: QuerySet, config: dict[str, Any] | None = None, **config_kwargs: Any) -> None:
    """
    Remove snapshots from the search index.
    """
    config = config or get_config(**config_kwargs)
    if not config.USE_INDEXING_BACKEND or not snapshots:
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
