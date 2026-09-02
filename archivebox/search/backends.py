__package__ = "archivebox.search"

import json
import os
from typing import Any

from archivebox.config.common import get_config


_search_backends_cache: dict | None = None


def search_backend_command_env(config: dict[str, Any] | None = None, **config_kwargs: Any) -> dict[str, str]:
    """Serialize resolved application config for a standalone plugin command."""
    config = config or get_config(**config_kwargs)
    env = os.environ.copy()
    for key, value in config.items():
        key = str(key)
        if value is None:
            continue
        if isinstance(value, bool):
            env[key] = "true" if value else "false"
        elif isinstance(value, (dict, list, tuple)):
            env[key] = json.dumps(value)
        elif isinstance(value, (str, int, float, os.PathLike)):
            env[key] = str(value)
    return env


def normalize_search_backend_name(backend_name: str | None) -> str:
    """Normalize a backend name for config and plugin lookup."""
    return (backend_name or "").strip().lower().replace("-", "_")


def get_available_backends() -> dict:
    """Discover search-capable plugins and cache their catalog entries."""
    global _search_backends_cache

    if _search_backends_cache is None:
        from archivebox.plugins.discovery import get_search_backends

        _search_backends_cache = get_search_backends()

    return _search_backends_cache


def get_backend(config: dict[str, Any] | None = None, **config_kwargs: Any) -> Any:
    """Resolve the configured search-capable plugin."""
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
