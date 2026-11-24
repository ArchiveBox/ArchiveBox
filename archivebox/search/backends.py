__package__ = "archivebox.search"

import json
import os
from typing import Any

from archivebox.config.common import ArchiveBoxBaseConfig, get_config


_search_backends_cache: dict | None = None


def search_backend_command_env(config: ArchiveBoxBaseConfig | dict[str, Any] | None = None, **config_kwargs: Any) -> dict[str, str]:
    """Serialize resolved application config for a standalone plugin command."""
    from abx_dl.models import PluginEnv
    from abxpkg import BinProvider

    config = config or get_config(**config_kwargs)
    env: dict[str, str] = {}
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
    # Use the same runtime bootstrap as hooks so the installation's abxpkg
    # entrypoint remains available even without an activated virtualenv.
    return BinProvider.build_exec_env(base_env=PluginEnv.model_validate(dict(os.environ)).to_env(), extra_env=env)


def normalize_search_backend_name(backend_name: str | None) -> str:
    """Normalize a backend name for config and plugin lookup."""
    return (backend_name or "").strip().lower().replace("-", "_")


def get_available_backends(config=None) -> dict:
    """Cache plugin discovery, but evaluate scan eligibility per collection."""
    global _search_backends_cache
    if _search_backends_cache is None:
        from archivebox.plugins.discovery import get_search_backends

        _search_backends_cache = get_search_backends()
    config = config or get_config()
    # Only configuration can permit disk reads. An unreachable index, missing
    # posting or empty response must never turn into an archive traversal.
    # A selected but missing provider is a configuration error, not permission
    # to scan. Keep fail-closed behavior across plugin upgrades/uninstalls.
    selected = normalize_search_backend_name(config.get("SEARCH_BACKEND_ENGINE"))
    missing = bool(selected and selected not in _search_backends_cache)
    indexed = missing or any(not p.config.search_scan and config.get(p.enabled_key, True) for p in _search_backends_cache.values())
    return {
        name: p
        for name, p in _search_backends_cache.items()
        if not p.config.search_scan or (not indexed and config.get(p.enabled_key, True))
    }


def get_backend(config: ArchiveBoxBaseConfig | dict[str, Any] | None = None, **config_kwargs: Any) -> Any:
    """Prefer the selected enabled provider, then registered priority order."""
    config = config or get_config(**config_kwargs)
    backends = get_available_backends(config)
    selected = backends.get(normalize_search_backend_name(config.get("SEARCH_BACKEND_ENGINE")))
    if selected and config.get(selected.enabled_key, True):
        return selected
    return next((p for p in backends.values() if config.get(p.enabled_key, True)), None)
