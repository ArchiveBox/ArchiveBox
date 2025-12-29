"""
Search module for ArchiveBox.

Search indexing is handled by search backend hooks in plugins:
    archivebox/plugins/search_backend_*/on_Snapshot__*_index_*.py

This module provides the query interface that dynamically discovers
search backend plugins using the hooks system.

Search backends must provide a search.py module with:
    - search(query: str) -> List[str]  (returns snapshot IDs)
    - flush(snapshot_ids: Iterable[str]) -> None
"""

__package__ = 'archivebox.search'

from typing import TYPE_CHECKING, Any, Optional

from django.db.models import QuerySet

from archivebox.misc.util import enforce_types
from archivebox.misc.logging import stderr
from archivebox.config.common import SEARCH_BACKEND_CONFIG

if TYPE_CHECKING:
    from archivebox.core.models import Snapshot


# Cache discovered backends to avoid repeated filesystem scans
_search_backends_cache: Optional[dict] = None


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


def get_backend() -> Any:
    """
    Get the configured search backend module.

    Discovers available backends via the hooks system and returns
    the one matching SEARCH_BACKEND_ENGINE configuration.

    Falls back to 'ripgrep' if configured backend is not found.
    """
    backend_name = SEARCH_BACKEND_CONFIG.SEARCH_BACKEND_ENGINE
    backends = get_available_backends()

    if backend_name in backends:
        return backends[backend_name]

    # Fallback to ripgrep if available (no index needed)
    if 'ripgrep' in backends:
        return backends['ripgrep']

    # No backends found
    available = list(backends.keys())
    raise RuntimeError(
        f'Search backend "{backend_name}" not found. '
        f'Available backends: {available or "none"}'
    )


@enforce_types
def query_search_index(query: str) -> QuerySet:
    """
    Search for snapshots matching the query.

    Returns a QuerySet of Snapshot objects matching the search.
    """
    from archivebox.core.models import Snapshot

    if not SEARCH_BACKEND_CONFIG.USE_SEARCHING_BACKEND:
        return Snapshot.objects.none()

    backend = get_backend()
    try:
        snapshot_pks = backend.search(query)
    except Exception as err:
        stderr()
        stderr(
            f'[X] The search backend threw an exception={err}:',
            color='red',
        )
        raise
    else:
        return Snapshot.objects.filter(pk__in=snapshot_pks)


@enforce_types
def flush_search_index(snapshots: QuerySet) -> None:
    """
    Remove snapshots from the search index.
    """
    if not SEARCH_BACKEND_CONFIG.USE_INDEXING_BACKEND or not snapshots:
        return

    backend = get_backend()
    snapshot_pks = [str(pk) for pk in snapshots.values_list('pk', flat=True)]

    try:
        backend.flush(snapshot_pks)
    except Exception as err:
        stderr()
        stderr(
            f'[X] The search backend threw an exception={err}:',
            color='red',
        )
