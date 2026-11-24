__package__ = "archivebox.search"

from typing import Any

from archivebox.config.common import ArchiveBoxBaseConfig, get_config
from archivebox.search.backends import get_available_backends, normalize_search_backend_name


SEARCH_MODES = ("query", "meta", "url", "contents")


def get_default_search_mode(config: ArchiveBoxBaseConfig | dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    """Choose the default search mode from config and discovered backends."""
    return "contents"


def get_search_mode(search_mode: str | None, config: ArchiveBoxBaseConfig | dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    """Normalize a user-supplied search mode or fall back to the default."""
    normalized = (search_mode or "").strip().lower().replace(" ", "")
    if normalized in ("content", "deep"):
        normalized = "contents"
    if normalized in SEARCH_MODES:
        return normalized
    if ":" in normalized:
        mode, backend_name = normalized.split(":", 1)
        backend_name = normalize_search_backend_name(backend_name)
        if mode in ("content", "deep"):
            mode = "contents"
        if mode == "contents" and backend_name in get_available_backends(config or get_config(**config_kwargs)):
            return f"{mode}:{backend_name}"
    return get_default_search_mode(config=config, **config_kwargs)


def get_search_mode_base(search_mode: str | None, config: ArchiveBoxBaseConfig | dict[str, Any] | None = None, **config_kwargs: Any) -> str:
    """Return the mode portion of a normalized search mode."""
    return get_search_mode(search_mode, config=config, **config_kwargs).split(":", 1)[0]


def get_search_mode_backend(
    search_mode: str | None,
    config: ArchiveBoxBaseConfig | dict[str, Any] | None = None,
    **config_kwargs: Any,
) -> str | None:
    """Return the backend portion of a backend-qualified search mode."""
    normalized = get_search_mode(search_mode, config=config, **config_kwargs)
    if ":" not in normalized:
        return None
    return normalized.split(":", 1)[1]


def get_search_mode_options(config: ArchiveBoxBaseConfig | dict[str, Any] | None = None, **config_kwargs: Any) -> list[dict[str, str]]:
    """Build search mode choices for admin and public selectors."""
    config = config or get_config(**config_kwargs)
    backends = get_available_backends(config)
    configured_backend = normalize_search_backend_name(config.get("SEARCH_BACKEND_ENGINE"))
    backend_names = [
        *([configured_backend] if configured_backend in backends else []),
        *(name for name in sorted(backends) if name != configured_backend),
    ]
    options = [
        {"value": "meta", "label": "meta"},
        {"value": "url", "label": "URL"},
        {"value": "contents", "label": "contents"},
    ]
    if backend_names:
        options.extend(
            {
                "value": f"contents:{backend_name}",
                "label": f"contents:{backend_name}",
            }
            for backend_name in backend_names
        )
    return options
