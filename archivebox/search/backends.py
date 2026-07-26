__package__ = "archivebox.search"

import os
from contextlib import contextmanager
from typing import Any

from archivebox.config.common import get_config


_search_backends_cache: dict | None = None


@contextmanager
def search_backend_env(config: dict[str, Any] | None = None, **config_kwargs: Any):
    """Temporarily expose resolved search config through os.environ for backend code."""
    config = config or get_config(**config_kwargs)
    updates = {}
    for key, value in config.items():
        key = str(key)
        if not (key.startswith("SEARCH_BACKEND_") or key.endswith("_BINARY")):
            continue
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool, os.PathLike)):
            updates[key] = str(value)
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


def normalize_search_backend_name(backend_name: str | None) -> str:
    """Normalize a backend name for config and plugin lookup."""
    return (backend_name or "").strip().lower().replace("-", "_")


def get_available_backends() -> dict:
    """Discover search backend plugin modules and cache them in memory."""
    global _search_backends_cache

    if _search_backends_cache is None:
        from archivebox.plugins.discovery import get_search_backends

        _search_backends_cache = get_search_backends()

    return _search_backends_cache


def get_backend(config: dict[str, Any] | None = None, **config_kwargs: Any) -> Any:
    """Resolve the configured search backend module."""
    config = config or get_config(**config_kwargs)
    backend_name = normalize_search_backend_name(config.SEARCH_BACKEND_ENGINE)
    backends = get_available_backends()

    if backend_name in backends:
        return backends[backend_name]

    if "ripgrep" in backends:
        return backends["ripgrep"]

    available = list(backends.keys())
    raise RuntimeError(
        f'Search backend "{backend_name}" not found. Available backends: {available or "none"}',
    )
