__package__ = "archivebox.plugins"

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Protocol, TypedDict

from abx_plugins import get_plugins_dir
from abx_dl.catalog import PluginCatalog, PluginConfigResolver
from django.utils.safestring import mark_safe

from archivebox.config.constants import CONSTANTS


class ConfigLookup(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...

    def items(self) -> Iterable[tuple[str, Any]]: ...


class PluginSpecialConfig(TypedDict):
    enabled: bool
    timeout: int
    binary: str


BUILTIN_PLUGINS_DIR = Path(get_plugins_dir()).resolve()
USER_PLUGINS_DIR = CONSTANTS.USER_PLUGINS_DIR


def iter_plugin_dirs() -> list[Path]:
    """Return the exact plugin directories exposed by the shared catalog."""
    return [plugin.path for plugin in get_plugin_catalog().values()]


@lru_cache(maxsize=1)
def get_plugin_catalog() -> PluginCatalog:
    return PluginCatalog.discover(extra_plugin_dirs=[USER_PLUGINS_DIR], runtime="archivebox")


@lru_cache(maxsize=1)
def get_plugin_config_resolver() -> PluginConfigResolver:
    return PluginConfigResolver(get_plugin_catalog())


@lru_cache(maxsize=1)
def get_plugins() -> list[str]:
    """
    Get list of available plugins by discovering plugin directories.

    Returns plugin directory names for any plugin that exposes hooks, config.json,
    or a standardized templates/icon.html asset. This includes non-extractor
    plugins such as binary providers and shared base plugins.
    """
    return sorted(get_plugin_catalog())


def get_plugin_name(plugin: str) -> str:
    """
    Get the base plugin name without numeric prefix.

    Examples:
        '10_title' -> 'title'
        '26_readability' -> 'readability'
        '50_parse_html_urls' -> 'parse_html_urls'
    """
    parts = plugin.split("_", 1)
    if len(parts) == 2 and parts[0].isdigit():
        plugin = parts[1]
    return get_archive_result_aliases().get(plugin, plugin)


@lru_cache(maxsize=1)
def get_archive_result_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for plugin in get_plugin_catalog().values():
        for alias in plugin.manifest.get("archive_result_aliases") or []:
            alias = str(alias or "").strip()
            if alias:
                aliases[alias] = plugin.name
    return aliases


def get_archive_result_names(plugin_name: str) -> tuple[str, ...]:
    """Return the canonical ArchiveResult name and its declared historic aliases."""
    canonical = get_plugin_name(plugin_name)
    aliases = get_archive_result_aliases()
    return tuple(dict.fromkeys((canonical, plugin_name, *(alias for alias, target in aliases.items() if target == canonical))))


def plugin_card_is_interactive(plugin_name: str) -> bool:
    plugin = get_plugin_catalog().get(get_plugin_name(plugin_name))
    return bool(plugin and plugin.manifest.get("card_interactive"))


def get_plugin_output_extension_preference(plugin_name: str) -> tuple[tuple[str, ...], ...] | None:
    plugin = get_plugin_catalog().get(get_plugin_name(plugin_name))
    raw_groups = plugin.manifest.get("output_extension_preference") if plugin else None
    if not isinstance(raw_groups, list):
        return None
    groups = []
    for raw_group in raw_groups:
        if not isinstance(raw_group, list):
            continue
        group = tuple(str(extension).lower() for extension in raw_group if str(extension).startswith("."))
        if group:
            groups.append(group)
    return tuple(groups) or None


def get_plugin_default_output_path(plugin_name: str) -> str | None:
    prefix, separator, base_name = plugin_name.partition("_")
    archive_result_name = base_name if separator and prefix.isdigit() else plugin_name
    plugin = get_plugin_catalog().get(get_plugin_name(plugin_name))
    raw_path = str(plugin.manifest.get("default_output_path") or "").strip() if plugin else ""
    path = PurePosixPath(raw_path)
    if not raw_path or raw_path.startswith("/") or ".." in path.parts or len(path.parts) != 1:
        return None
    return f"{archive_result_name}/{raw_path}"


@lru_cache(maxsize=1)
def get_snapshot_thumbnail_card_order() -> dict[str, int]:
    """Return plugin-owned ArchiveResult names eligible for snapshot thumbnails."""
    ordering: dict[str, int] = {}
    for plugin in get_plugin_catalog().values():
        declarations = plugin.manifest.get("snapshot_thumbnail_cards") or []
        if not isinstance(declarations, list):
            continue
        for declaration in declarations:
            if not isinstance(declaration, dict):
                continue
            result_name = str(declaration.get("archive_result_name") or "").strip()
            order = declaration.get("order")
            if not result_name or isinstance(order, bool) or not isinstance(order, int):
                continue
            ordering[result_name] = order
    return ordering


def get_enabled_plugins(config: ConfigLookup | None = None, **config_kwargs: Any) -> list[str]:
    """
    Get the list of enabled plugins based on config and available hooks.

    Filters plugins by USE_/SAVE_ flags. Only returns plugins that are enabled.
    """
    if config is None:
        from archivebox.config.common import get_config

        config = get_config(**config_kwargs)

    return get_plugin_config_resolver().enabled_plugin_names_from_flat(dict(config.items()))


def get_search_backends():
    """Return plugins that declare both standalone search commands."""
    catalog = get_plugin_catalog()
    return {
        plugin.name.removeprefix("search_backend_"): plugin
        for plugin in catalog.values()
        if catalog.command(plugin.name, "search") is not None and catalog.command(plugin.name, "flush") is not None
    }


@lru_cache(maxsize=1)
def discover_plugin_configs() -> dict[str, dict[str, Any]]:
    """
    Discover all plugin config.json schemas.

    Each plugin can define a config.json file with JSONSchema defining
    its configuration options. This is intentionally cached because these
    schemas are plugin package metadata, not live user config; runtime values
    still come from env/db config at each callsite.
    """
    return get_plugin_config_resolver().schemas


def get_plugin_special_config(plugin_name: str, config: ConfigLookup, _visited: set[str] | None = None) -> PluginSpecialConfig:
    """
    Extract special config keys for a plugin following naming conventions.

    ArchiveBox recognizes 3 special config key patterns per plugin:
        - {PLUGIN}_ENABLED: Enable/disable toggle (default True)
        - {PLUGIN}_TIMEOUT: Plugin-specific timeout (fallback to TIMEOUT, default 300)
        - {PLUGIN}_BINARY: Primary binary path (default to plugin_name)
    """
    return get_plugin_config_resolver().runtime_settings(plugin_name, dict(config.items()))


DEFAULT_TEMPLATES = {
    "icon": """
        <span title="{{ plugin }}" style="display:inline-flex; width:20px; height:20px; align-items:center; justify-content:center;">
            {{ icon }}
        </span>
    """,
    "card": """
        <iframe src="{{ output_path }}"
                class="card-img-top"
                style="width: 100%; height: 100%; border: none;"
                sandbox="allow-same-origin allow-scripts allow-forms"
                loading="lazy"
                fetchpriority="low">
        </iframe>
    """,
    "full": """
        <iframe src="{{ output_path }}"
                class="full-page-iframe"
                style="width: 100%; height: 100vh; border: none;"
                sandbox="allow-same-origin allow-scripts allow-forms">
        </iframe>
    """,
}


@lru_cache(maxsize=None)
def get_plugin_template(plugin: str, template_name: str, fallback: bool = True) -> str | None:
    """
    Get a plugin template by plugin name and template type.

    Args:
        plugin: Plugin name (e.g., 'screenshot', '15_singlefile')
        template_name: A template slot such as 'icon', 'card', or 'full'.
        fallback: If True, return default template if plugin template not found
    """
    base_name = get_plugin_name(plugin)

    catalog = get_plugin_catalog()
    if base_name in catalog:
        template_path = catalog.template_path(base_name, template_name)
        if template_path is not None:
            return template_path.read_text()

    if fallback:
        return DEFAULT_TEMPLATES.get(template_name, "")

    return None


@lru_cache(maxsize=None)
def get_plugin_icon(plugin: str) -> str:
    """
    Get the icon for a plugin from its icon.html template.
    """
    icon_template = get_plugin_template(plugin, "icon", fallback=False)
    if icon_template:
        return mark_safe(icon_template.strip())

    return mark_safe("📁")
