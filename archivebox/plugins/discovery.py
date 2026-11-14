__package__ = "archivebox.plugins"

import re
from collections.abc import Iterable
from functools import lru_cache
from fnmatch import fnmatchcase
from importlib import import_module
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Protocol, TypedDict, cast

from abx_plugins import get_plugins_dir
from abx_dl.catalog import PluginCatalog, PluginConfigResolver
from django.utils.safestring import mark_safe

from archivebox.config.constants import CONSTANTS


class ConfigLookup(Protocol):
    def get(self, key: str, default: Any = None, /) -> Any: ...

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


def plugin_output_is_text(plugin_name: str) -> bool:
    plugin = get_plugin_catalog().get(get_plugin_name(plugin_name))
    return bool(plugin and plugin.manifest.get("output_str_type") == "text")


def read_plugin_output_text(plugin_name: str, snapshot_dir: Path, output_str: str = "") -> str:
    """Read a declared text value or the plugin's default saved artifact."""
    relative = get_plugin_default_output_path(plugin_name)
    if plugin_output_is_text(plugin_name) and output_str and (not relative or output_str not in {relative, Path(relative).name}):
        return output_str
    if relative:
        root = Path(snapshot_dir).resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            pass
    return ""


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


@lru_cache(maxsize=None)
def get_snapshot_role_names(role: str) -> tuple[str, ...]:
    """Return ArchiveResult names for a plugin-owned snapshot presentation role."""
    manifest_key = f"snapshot_{role}"
    providers = []
    for plugin in get_plugin_catalog().values():
        enabled = plugin.manifest.get(manifest_key, False)
        order = plugin.manifest.get(f"{manifest_key}_order", 0)
        if type(enabled) is not bool or type(order) is not int:
            raise ValueError(f"{plugin.name}: {manifest_key} must be boolean and its order must be an integer")
        if enabled:
            providers.append((order, plugin.name))
    return tuple(dict.fromkeys(name for _, plugin in sorted(providers) for name in get_archive_result_names(plugin)))


def get_snapshot_role_result(results, role: str):
    """Select the first successful result declared for a presentation role."""
    results_by_name = {result.plugin: result for result in results if result.status == "succeeded"}
    return next((results_by_name[name] for name in get_snapshot_role_names(role) if name in results_by_name), None)


def get_snapshot_role_paths(snapshot, results, role: str):
    """Yield distinct saved output paths in the declared role preference order."""
    results = list(results)
    seen = set()
    for name in get_snapshot_role_names(role):
        path = snapshot.plugin_output_path(name, archive_results=results)
        if path and path not in seen:
            seen.add(path)
            yield path


def get_replay_asset_bundle(format: str, provider: str | None = None) -> tuple[str, tuple[str, ...]]:
    """Select one provider's complete replay bundle, with stable name ordering."""
    catalog = get_plugin_catalog()
    for name in [provider] if provider else sorted(catalog):
        plugin = catalog.get(name)
        if plugin is None:
            raise ValueError(f"Unknown replay asset provider: {name}")
        bundles = plugin.manifest.get("replay_assets", {})
        if not isinstance(bundles, dict):
            raise ValueError(f"{name}: replay_assets must map formats to asset paths")
        if format not in bundles:
            continue
        paths = bundles[format]
        if not isinstance(paths, list) or not paths:
            raise ValueError(f"{name}: replay_assets.{format} must be a nonempty list of asset paths")
        for path in paths:
            if (
                not isinstance(path, str)
                or not path
                or PurePosixPath(path).is_absolute()
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or "\\" in path
                or ":" in path
            ):
                raise ValueError(f"{name}: invalid replay asset path: {path!r}")
        if len(set(paths)) != len(paths):
            raise ValueError(f"{name}: duplicate replay asset paths")
        return name, tuple(paths)
    raise ValueError(f"No plugin provides replay assets for {format}")


@lru_cache(maxsize=1)
def get_plugin_presentation_modules() -> tuple[ModuleType, ...]:
    """Load optional plugin-owned presentation hooks declared in manifests."""
    return tuple(module for plugin in get_plugin_catalog().values() if (module := get_plugin_presentation_module(plugin.name)) is not None)


def get_plugin_presentation_module(plugin_name: str) -> ModuleType | None:
    """Load one plugin's optional presentation hooks module."""
    plugin = get_plugin_catalog().get(get_plugin_name(plugin_name))
    module_name = str(plugin.manifest.get("presentation_module") or "").strip() if plugin else ""
    return import_module(module_name) if module_name else None


def get_plugin_app(plugin_name: str) -> ModuleType | None:
    """Load an optional host adapter without importing standalone hook code."""
    plugin = get_plugin_catalog().get(get_plugin_name(plugin_name))
    module_name = str(plugin.manifest.get("app_module") or "").strip() if plugin else ""
    return import_module(module_name) if module_name else None


@lru_cache(maxsize=1)
def get_plugin_apps() -> dict[str, ModuleType]:
    return {name: app for name in get_plugin_catalog() if (app := get_plugin_app(name)) is not None}


def get_snapshot_file_inventory(snapshot_dir: Path, *, verify: bool = False) -> dict[str, dict[str, Any]] | None:
    """Read the first available declared inventory without rescanning outputs."""
    seen = set()
    for name in get_snapshot_role_names("file_inventory"):
        name = get_plugin_name(name)
        if name in seen:
            continue
        seen.add(name)
        read = getattr(get_plugin_app(name), "read_snapshot_inventory", None)
        if read is None:
            raise ValueError(f"{name}: file inventory role requires read_snapshot_inventory")
        inventory = read(snapshot_dir, verify=verify)
        if inventory is not None:
            if not isinstance(inventory, dict):
                raise ValueError(f"{name}: read_snapshot_inventory must return a file metadata mapping or None")
            return inventory
    return None


def plugin_has_custom_full_response(plugin_name: str) -> bool:
    """Return whether a plugin renders its full template through a response hook."""
    module = get_plugin_presentation_module(plugin_name)
    return bool(module and getattr(module, "render_full_response", None))


def get_extra_snapshot_output_cards(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collect additional cards from plugin-owned presentation hooks."""
    records = [
        {
            **{key: value for key, value in output.items() if key != "result"},
            "output_files": output["result"].output_file_map() if output.get("result") else {},
        }
        for output in outputs
    ]
    cards = []
    for module in get_plugin_presentation_modules():
        hook = getattr(module, "extra_snapshot_output_cards", None)
        if hook is not None:
            cards.extend(hook(records) or ())
    return cards


def serve_plugin_replay_asset(path: str, config, response_class, *, provider: str | None = None):
    """Serve a selected provider's asset, or discover a live replay asset handler."""
    modules = (get_plugin_presentation_module(provider),) if provider else get_plugin_presentation_modules()
    for module in modules:
        hook = getattr(module, "serve_replay_asset_response", None)
        if hook is not None and (response := hook(path, config, response_class)) is not None:
            return response
    return None


@lru_cache(maxsize=1)
def get_replay_document_providers():
    """Validate declared document transforms once when loading plugin metadata."""
    providers = []
    for name, plugin in sorted(get_plugin_catalog().items()):
        declarations = plugin.manifest.get("replay_document_patterns", {})
        if not isinstance(declarations, dict):
            raise ValueError(f"{name}: replay_document_patterns must map MIME types to path patterns")
        for content_type, patterns in declarations.items():
            if not isinstance(content_type, str) or not re.fullmatch(r"[\w.+-]+/[\w.+-]+", content_type):
                raise ValueError(f"{name}: invalid replay document MIME type: {content_type!r}")
            if not isinstance(patterns, list) or not patterns:
                raise ValueError(f"{name}: replay document patterns must be a nonempty list")
            for pattern in patterns:
                if (
                    not isinstance(pattern, str)
                    or not pattern
                    or PurePosixPath(pattern).is_absolute()
                    or any(part in {"", ".", ".."} for part in pattern.split("/"))
                    or "\\" in pattern
                    or ":" in pattern
                ):
                    raise ValueError(f"{name}: invalid replay document path pattern: {pattern!r}")
            module = get_plugin_presentation_module(name)
            hook = getattr(module, "rewrite_replay_document", None)
            if not callable(hook):
                raise ValueError(f"{name}: replay document patterns require a rewrite_replay_document hook")
            providers.append((content_type.lower(), tuple(patterns), hook))
    return tuple(providers)


def get_replay_document_hooks(rel_path: str, content_type: str):
    """Select transforms without reading a captured document or its dependencies."""
    content_type = content_type.partition(";")[0].strip().lower()
    return tuple(
        hook
        for mime, patterns, hook in get_replay_document_providers()
        if content_type == mime and any(fnmatchcase(rel_path, pattern) for pattern in patterns)
    )


def rewrite_plugin_replay_document(
    text: str,
    *,
    snapshot_root: Path,
    rel_path: str,
    content_type: str,
    page_url: str | None = None,
    replay_url: str | None = None,
    source_text: str | None = None,
) -> tuple[str, int]:
    """Transform a served/exported document without modifying captured bytes."""
    content_type = content_type.partition(";")[0].strip().lower()
    count = 0
    for hook in get_replay_document_hooks(rel_path, content_type):
        text, changed = hook(
            text,
            snapshot_root=snapshot_root,
            rel_path=rel_path,
            content_type=content_type,
            page_url=page_url,
            replay_url=replay_url,
            source_text=source_text,
        )
        count += changed
    return text, count


def get_plugin_replay_roots(snapshot_root: Path, url: str):
    """Yield existing provider URL roots inside an authorized snapshot."""
    snapshot_root = Path(snapshot_root)
    contained_root = snapshot_root.resolve()
    seen = set()
    for module in get_plugin_presentation_modules():
        hook = getattr(module, "replay_roots", None)
        if hook is None:
            continue
        paths = hook(snapshot_root, url)
        if not isinstance(paths, (tuple, list)):
            raise ValueError(f"{module.__name__}.replay_roots must return relative paths")
        for relative in paths:
            if (
                not isinstance(relative, str)
                or not relative
                or PurePosixPath(relative).is_absolute()
                or ".." in PurePosixPath(relative).parts
            ):
                raise ValueError(f"{module.__name__}: invalid replay root: {relative!r}")
            root = snapshot_root / relative
            try:
                available = root.resolve().is_relative_to(contained_root) and root.is_dir()
            except (OSError, RuntimeError):
                continue
            if root not in seen and available:
                seen.add(root)
                yield root


def render_plugin_full_response(path: str, output_url: str, **kwargs):
    """Let plugin presentation hooks render a saved output's full template."""
    for module in get_plugin_presentation_modules():
        render = getattr(module, "render_full_response", None)
        if render is not None and (response := render(path, output_url, **kwargs)) is not None:
            return response
    return None


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
        for plugin in sorted(catalog.values(), key=lambda plugin: (int(plugin.manifest.get("search_order", 1000)), plugin.name))
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
    return cast(PluginSpecialConfig, get_plugin_config_resolver().runtime_settings(plugin_name, dict(config.items())))


DEFAULT_TEMPLATES = {
    "icon": """
        <span title="{{ plugin }}" style="display:inline-flex; width:20px; height:20px; align-items:center; justify-content:center;">
            {{ icon }}
        </span>
    """,
    "card": """
        <iframe src="{{ output_path }}" title="{{ plugin }} output"
                class="card-img-top"
                style="width: 100%; height: 100%; border: none;"
                sandbox="allow-same-origin allow-scripts allow-forms"
                loading="lazy"
                fetchpriority="low">
        </iframe>
    """,
    "full": """
        <iframe src="{{ output_path }}" title="{{ plugin }} output"
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


# A list page repeats each plugin's icon on every row (~40 icons per snapshot),
# and inline SVG was about half of every row's HTML. Single-SVG icons are drawn
# once per page as <symbol>s (get_plugin_icon_sprite) and each row <use>s them.
# The <span> wrapper (classes, tooltip) and outer <svg> box stay per icon, and
# the symbol carries the drawing attributes, so the rendered icon is unchanged.
_ICON_SVG_RE = re.compile(r"(<span [^<>]*>)<svg ([^<>]*)>((?:(?!<svg\b|</svg>).)*)</svg></span>", re.S)
_ICON_SVG_ATTR_RE = re.compile(r'\s*([a-zA-Z][\w:-]*)="([^"<>]*)"')
_ICON_BOX_ATTRS = ("width", "height", "aria-hidden", "focusable")
_ICON_SYMBOL_ATTRS = frozenset(("viewBox", "preserveAspectRatio", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"))


@lru_cache(maxsize=None)
def _plugin_icon_sprite_parts(plugin: str) -> tuple[str, str] | None:
    """(symbol, inline markup using it) for a single-SVG icon; None keeps the icon inline."""
    if not re.fullmatch(r"[a-z0-9_]+", plugin):
        return None
    match = _ICON_SVG_RE.fullmatch(str(get_plugin_icon(plugin)))
    if match is None:
        return None
    span, svg_attrs, drawing = match.groups()
    attrs = _ICON_SVG_ATTR_RE.findall(svg_attrs)
    # Anything besides the known box/drawing attributes (class, style, ids...)
    # might style the outer element differently; keep such icons inline.
    if "".join(f' {name}="{value}"' for name, value in attrs).strip() != svg_attrs.strip():
        return None
    if any(name not in _ICON_BOX_ATTRS and name not in _ICON_SYMBOL_ATTRS for name, _ in attrs):
        return None
    if "id=" in drawing or "url(" in drawing:
        return None
    symbol_attrs = "".join(f' {name}="{value}"' for name, value in attrs if name in _ICON_SYMBOL_ATTRS)
    box_attrs = "".join(f' {name}="{value}"' for name, value in attrs if name in _ICON_BOX_ATTRS)
    symbol = f'<symbol id="abx-icon-{plugin}"{symbol_attrs}>{drawing}</symbol>'
    return symbol, f'{span}<svg{box_attrs}><use href="#abx-icon-{plugin}"></use></svg></span>'


def get_plugin_list_icon(plugin: str) -> str:
    """Icon markup for list rows; pages that use it must include get_plugin_icon_sprite()."""
    parts = _plugin_icon_sprite_parts(plugin)
    return mark_safe(parts[1]) if parts else get_plugin_icon(plugin)


@lru_cache(maxsize=1)
def get_plugin_icon_sprite() -> str:
    """Hidden <svg> holding every sprite-able plugin icon once (see get_plugin_list_icon)."""
    symbols = "".join(parts[0] for name in sorted(get_plugin_catalog()) if (parts := _plugin_icon_sprite_parts(name)))
    # Not display:none: some browsers then skip painting the referenced symbols.
    return mark_safe(f'<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">{symbols}</svg>')
