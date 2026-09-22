"""ArchiveBox adapters around the framework-free abx-dl plugin runtime.

Discovery and execution are owned by abx-dl. ArchiveBox keeps only the small
Django projection adapter and its application-specific URL-output reader.
"""

from __future__ import annotations

__package__ = "archivebox.plugins"

from pathlib import Path
from typing import Any

from abx_dl.models import parse_hook_filename

from archivebox.misc.util import fix_url_from_markdown, sanitize_extracted_url
from archivebox.plugins.discovery import ConfigLookup, get_enabled_plugins, get_plugin_catalog


def is_background_hook(hook_name: str) -> bool:
    parsed = parse_hook_filename(Path(hook_name).name)
    return bool(parsed and parsed[2])


def normalize_hook_event_name(event_name: str) -> str | None:
    normalized = str(event_name or "").strip()
    if not normalized:
        return None
    return normalized.removesuffix("Event") or None


def discover_hooks(
    event_name: str,
    filter_disabled: bool = True,
    config: ConfigLookup | None = None,
    **config_kwargs: Any,
) -> list[Path]:
    """Return the exact catalog hooks used by abx-dl, in execution order."""
    normalized = normalize_hook_event_name(event_name)
    if not normalized or normalized == "BinaryRequest":
        return []
    names = None
    if filter_disabled:
        if config is None:
            from archivebox.config.common import get_config

            config = get_config(**config_kwargs)
        names = get_enabled_plugins(config=config)
    return [hook.path for _plugin, hook in get_plugin_catalog().hooks(normalized, names=names)]


def collect_urls_from_plugins(snapshot_dir: Path) -> list[dict[str, Any]]:
    """Read the durable urls.jsonl interface emitted by parser plugins."""
    urls: list[dict[str, Any]] = []
    if not snapshot_dir.exists():
        return urls

    from archivebox.machine.models import Process

    for subdir in snapshot_dir.iterdir():
        urls_file = subdir / "urls.jsonl"
        if not subdir.is_dir() or not urls_file.is_file():
            continue
        try:
            for entry in Process.parse_records_from_text(urls_file.read_text()):
                if not entry.get("url"):
                    continue
                entry["url"] = sanitize_extracted_url(fix_url_from_markdown(str(entry["url"]).strip()))
                if entry["url"]:
                    entry["plugin"] = subdir.name
                    urls.append(entry)
        except (OSError, UnicodeError):
            continue
    return urls
