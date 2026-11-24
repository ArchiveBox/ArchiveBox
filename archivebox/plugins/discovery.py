__package__ = "archivebox.plugins"

import re
from html import escape
from html.parser import HTMLParser
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


OPENCODE_PROVIDER_SETTINGS_PLUGIN = "opencode_providers"

BUILTIN_PLUGINS_DIR = Path(get_plugins_dir()).resolve()
USER_PLUGINS_DIR = CONSTANTS.USER_PLUGINS_DIR


def iter_plugin_dirs() -> list[Path]:
    """Return the exact plugin directories exposed by the shared catalog."""
    return [plugin.path for plugin in get_plugin_catalog().values()]


def _validate_presentation_metadata(name: str, manifest: dict[str, Any]) -> None:
    # Validate the declarations once, before requests select different subsets.
    # Otherwise one invalid plugin can silently disappear from cards but fail exports.
    string_fields = {"snapshot_output_group", "snapshot_display_name", "snapshot_live_preview_route", "presentation_module", "app_module"}
    for key, value in manifest.items():
        if key in string_fields:
            if not isinstance(value, str):
                raise ValueError(f"{name}: {key} must be a string")
        elif key in {"icon_hidden", "card_hidden", "card_interactive"} or (
            key.startswith("snapshot_") and key != "snapshot_thumbnail_cards" and not key.endswith("_order")
        ):
            if type(value) is not bool:
                raise ValueError(f"{name}: {key} must be boolean")
        elif key.startswith("snapshot_") and key.endswith("_order"):
            if type(value) is not int:
                raise ValueError(f"{name}: {key} must be an integer")

    aliases = manifest.get("archive_result_aliases", [])
    if not isinstance(aliases, list) or any(not isinstance(value, str) or not value or value != value.strip() for value in aliases):
        raise ValueError(f"{name}: archive_result_aliases must contain nonempty names")
    if len(set(aliases)) != len(aliases):
        raise ValueError(f"{name}: archive_result_aliases contains duplicate names")

    thumbnails = manifest.get("snapshot_thumbnail_cards", [])
    if not isinstance(thumbnails, list):
        raise ValueError(f"{name}: snapshot_thumbnail_cards must be a list")
    for card in thumbnails:
        if (
            not isinstance(card, dict)
            or not isinstance(card.get("archive_result_name"), str)
            or not card["archive_result_name"].strip()
            or type(card.get("order")) is not int
        ):
            raise ValueError(f"{name}: snapshot_thumbnail_cards requires archive_result_name and integer order")

    def relative_path(key, path):
        if (
            not isinstance(path, str)
            or not path
            or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\\" in path
            or ":" in path
        ):
            raise ValueError(f"{name}: {key} has an invalid relative path: {path!r}")

    if "default_output_path" in manifest:
        path = manifest["default_output_path"]
        relative_path("default_output_path", path)
        if len(PurePosixPath(path).parts) != 1:
            raise ValueError(f"{name}: default_output_path must be a filename")

    preview_extensions = manifest.get("file_preview_extensions", [])
    if not isinstance(preview_extensions, list) or any(
        not isinstance(ext, str) or not re.fullmatch(r"\.[a-z0-9]+", ext) for ext in preview_extensions
    ):
        raise ValueError(f"{name}: file_preview_extensions must contain lowercase extensions")

    crawler_paths = manifest.get("crawler_output_paths", [])
    if not isinstance(crawler_paths, list):
        raise ValueError(f"{name}: crawler_output_paths must be a list")
    for path in crawler_paths:
        relative_path("crawler_output_paths", path)
        if any(char in path for char in "*?[]#$") or PurePosixPath(path).suffix not in {".html", ".htm"}:
            raise ValueError(f"{name}: crawler_output_paths requires exact HTML paths")

    extensions = manifest.get("output_extension_preference", [])
    if not isinstance(extensions, list) or any(
        not isinstance(group, list)
        or not group
        or any(not isinstance(extension, str) or not re.fullmatch(r"\.[\w.+-]+", extension) for extension in group)
        for group in extensions
    ):
        raise ValueError(f"{name}: output_extension_preference must contain lists of file extensions")

    for key in ("replay_assets", "replay_document_patterns"):
        groups = manifest.get(key, {})
        if not isinstance(groups, dict):
            raise ValueError(f"{name}: {key} must map formats to path lists")
        for format, paths in groups.items():
            if (
                not isinstance(format, str)
                or not format
                or (key == "replay_document_patterns" and not re.fullmatch(r"[\w.+-]+/[\w.+-]+", format))
            ):
                raise ValueError(f"{name}: {key} has an invalid format: {format!r}")
            if not isinstance(paths, list) or not paths:
                raise ValueError(f"{name}: {key}.{format} must be a nonempty list")
            for path in paths:
                relative_path(key, path)
            if len(set(paths)) != len(paths):
                raise ValueError(f"{name}: {key}.{format} contains duplicate paths")


@lru_cache(maxsize=1)
def get_plugin_catalog() -> PluginCatalog:
    catalog = PluginCatalog.discover(extra_plugin_dirs=[USER_PLUGINS_DIR], runtime="archivebox")
    aliases = {}
    thumbnails = set()
    for plugin in catalog.values():
        _validate_presentation_metadata(plugin.name, plugin.manifest)
        for alias in plugin.manifest.get("archive_result_aliases", []):
            if alias in aliases or (alias in catalog and alias != plugin.name):
                raise ValueError(f"{plugin.name}: archive_result_aliases conflicts with another plugin: {alias}")
            aliases[alias] = plugin.name
        for card in plugin.manifest.get("snapshot_thumbnail_cards", []):
            result_name = card["archive_result_name"]
            if result_name in thumbnails:
                raise ValueError(f"{plugin.name}: snapshot_thumbnail_cards duplicates {result_name}")
            thumbnails.add(result_name)
    return catalog


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
    return {alias: plugin.name for plugin in get_plugin_catalog().values() for alias in plugin.manifest.get("archive_result_aliases", [])}


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
    groups = plugin.manifest.get("output_extension_preference") if plugin else None
    return tuple(tuple(extension.lower() for extension in group) for group in groups) if groups else None


def get_plugin_default_output_path(plugin_name: str) -> str | None:
    prefix, separator, base_name = plugin_name.partition("_")
    archive_result_name = base_name if separator and prefix.isdigit() else plugin_name
    plugin = get_plugin_catalog().get(get_plugin_name(plugin_name))
    path = plugin.manifest.get("default_output_path") if plugin else None
    return f"{archive_result_name}/{path}" if path else None


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


@lru_cache(maxsize=2)
def get_snapshot_thumbnail_card_order(*, images_only: bool = False) -> dict[str, int]:
    """Return plugin-owned ArchiveResult names eligible for snapshot thumbnails."""
    return {
        card["archive_result_name"]: card["order"]
        for plugin in get_plugin_catalog().values()
        if not images_only or plugin.manifest.get("snapshot_output_group") == "images"
        for card in plugin.manifest.get("snapshot_thumbnail_cards", [])
    }


@lru_cache(maxsize=32)
def get_snapshot_role_names(role: str) -> tuple[str, ...]:
    """Return ArchiveResult names for a plugin-owned snapshot presentation role."""
    manifest_key = f"snapshot_{role}"
    providers = []
    for plugin in get_plugin_catalog().values():
        enabled = plugin.manifest.get(manifest_key, False)
        order = plugin.manifest.get(f"{manifest_key}_order", 0)
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


@lru_cache(maxsize=1)
def get_file_preview_providers() -> dict[str, str]:
    """Map saved file extensions to the plugin that renders their preview."""
    providers = {}
    for plugin in get_plugin_catalog().values():
        for extension in plugin.manifest.get("file_preview_extensions", []):
            if extension in providers:
                raise ValueError(f"{extension}: file preview already provided by {providers[extension]}")
            providers[extension] = plugin.name
    return providers


def render_plugin_file_preview(provider: str, filename: str, output_url: str, *, replay_base: str) -> str:
    """Render a registered file viewer independently of its extractor's primary output."""
    module = get_plugin_presentation_module(provider)
    if module is None:
        raise ValueError(f"{provider}: file preview requires a presentation module")
    return module.render_file_preview(filename, output_url, replay_base=replay_base)


def get_replay_asset_bundle(format: str, provider: str | None = None) -> tuple[str, tuple[str, ...]]:
    """Select one provider's complete replay bundle, with stable name ordering."""
    catalog = get_plugin_catalog()
    for name in [provider] if provider else sorted(catalog):
        plugin = catalog.get(name)
        if plugin is None:
            raise ValueError(f"Unknown replay asset provider: {name}")
        bundles = plugin.manifest.get("replay_assets", {})
        if format not in bundles:
            continue
        paths = bundles[format]
        return name, tuple(paths)
    raise ValueError(f"No plugin provides replay assets for {format}")


def get_snapshot_replay_asset_providers():
    """Yield each plugin's path matcher and the assets it serves beside a matching snapshot."""
    for name, plugin in sorted(get_plugin_catalog().items()):
        matches = getattr(get_plugin_presentation_module(name), "is_replay_target", None)
        if callable(matches):
            bundles = plugin.manifest.get("replay_assets", {})
            # File-preview assets are shared at the export root. Replay workers
            # live beside the snapshot whose files they serve.
            paths = tuple(dict.fromkeys(path for kind, bundle in bundles.items() if kind != "file-preview" for path in bundle))
            yield name, matches, paths


def read_replay_assets(config, provider: str, paths: tuple[str, ...]) -> dict[str, bytes]:
    """Read a provider's declared assets through its normal serving hook."""
    from django.http import HttpResponse

    assets = {}
    for path in paths:
        response = serve_plugin_replay_asset(path, config, HttpResponse, provider=provider)
        if response is None:
            raise ValueError(f"Replay asset provider {provider} cannot serve {path}")
        try:
            if response.status_code != 200:
                raise ValueError(f"Replay asset provider {provider} returned {response.status_code} for {path}")
            assets[path] = b"".join(response.streaming_content) if response.streaming else response.content
        finally:
            response.close()
    return assets


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


def register_plugin_eventbus(bus, config) -> None:
    """Offer each application plugin the bus; plugins own registration policy."""
    for app in get_plugin_apps().values():
        register = getattr(app, "register_eventbus", None)
        if register is not None:
            register(bus, config)


def wrap_plugin_asgi(application, config):
    """Compose optional application plugins around the complete ASGI lifetime."""
    for app in reversed(tuple(get_plugin_apps().values())):
        wrap = getattr(app, "wrap_asgi", None)
        if wrap is not None:
            application = wrap(application, config)
    return application


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
    """Load declared document transforms without importing them during catalog discovery."""
    providers = []
    for name, plugin in sorted(get_plugin_catalog().items()):
        declarations = plugin.manifest.get("replay_document_patterns", {})
        for content_type, patterns in declarations.items():
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
    contained_root = None
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
            if root in seen:
                continue
            seen.add(root)
            try:
                # Missing providers are common on replay asset fallbacks. One
                # stat proves absence without lstat-ing every ancestor first.
                if not root.is_dir():
                    continue
                if contained_root is None:
                    contained_root = snapshot_root.resolve()
                available = root.resolve().is_relative_to(contained_root)
            except (OSError, RuntimeError):
                continue
            if available:
                yield root


class _ReplayMetadataHead(HTMLParser):
    """Locate head metadata without parsing a potentially huge saved body."""

    def __init__(self):
        super().__init__()
        self.offsets = [0]
        self.insertion = 0
        self.removals = []
        self.done = False

    def handle_decl(self, decl):
        if not self.done and decl.lower().startswith("doctype"):
            line, column = self.getpos()
            self.insertion = self.offsets[line - 1] + column + len(decl) + 3

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        line, column = self.getpos()
        start = self.offsets[line - 1] + column
        end = start + len(self.get_starttag_text())
        if tag in {"html", "head"}:
            self.insertion = end
        elif tag not in {"base", "basefont", "bgsound", "link", "meta", "title", "noframes", "script", "style", "template", "noscript"}:
            # HTML permits omitted head/body tags. The first body element also
            # ends the head, so fragments need not scan their saved content.
            self.done = True
        values = dict(reversed(attrs))
        if (tag == "link" and {"canonical", "original"}.intersection((values.get("rel") or "").lower().split())) or (
            tag == "meta" and (values.get("name") or "").lower() == "robots"
        ):
            self.removals.append((start, end, ""))

    def handle_endtag(self, tag):
        if tag == "head":
            self.done = True


def add_replay_document_metadata(document: str, original_url: str) -> str:
    """Set attribution on a rendered representation, never its saved source."""
    if not original_url:
        return document
    parsed = _ReplayMetadataHead()
    for offset in range(0, len(document), 4096):
        chunk = document[offset : offset + 4096]
        parsed.offsets.extend(offset + match.end() for match in re.finditer("\n", chunk))
        parsed.feed(chunk)
        if parsed.done:
            break
    url = escape(original_url, quote=True)
    metadata = f'<link rel="canonical" href="{url}"><link rel="original" href="{url}"><meta name="robots" content="noindex, follow">'
    if len(parsed.removals) == 3 and document.startswith(metadata, parsed.insertion):
        # Full/card viewers may also pass through shared response/export code.
        # Already-normalized metadata needs no second copy of the saved body.
        return document
    edits = [*parsed.removals, (parsed.insertion, parsed.insertion, metadata)]
    chunks = []
    previous = 0
    for start, end, replacement in sorted(edits):
        chunks.extend((document[previous:start], replacement))
        previous = end
    chunks.append(document[previous:])
    return "".join(chunks)


def render_plugin_full_response(path: str, output_url: str, *, provider: str | None = None, **kwargs):
    """Let plugin presentation hooks render a saved output's full template."""
    modules = (get_plugin_presentation_module(provider),) if provider else get_plugin_presentation_modules()
    for module in modules:
        render = getattr(module, "render_full_response", None)
        if render is not None and (response := render(path, output_url, **kwargs)) is not None:
            body, content_type, headers = response
            if content_type.partition(";")[0].strip().lower() == "text/html":
                body = add_replay_document_metadata(body, kwargs.get("fallback_url", ""))
            return body, content_type, headers
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


def get_opencode_provider_keys() -> frozenset[str]:
    schema = discover_plugin_configs().get(OPENCODE_PROVIDER_SETTINGS_PLUGIN, {})
    return frozenset((schema.get("properties") or {}).keys())


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


@lru_cache(maxsize=2048)
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


@lru_cache(maxsize=512)
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
_ICON_SVG_RE = re.compile(r"(?:<!--.*?-->\s*)*(<span [^<>]*>)<svg ([^<>]*)>((?:(?!<svg\b|</svg>).)*)</svg></span>", re.S)
_ICON_SVG_ATTR_RE = re.compile(r'\s*([a-zA-Z][\w:-]*)="([^"<>]*)"')
_ICON_BOX_ATTRS = ("width", "height", "aria-hidden", "focusable")
_ICON_SYMBOL_ATTRS = frozenset(("viewBox", "preserveAspectRatio", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin"))
_ICON_NAMESPACES = {"xmlns": "http://www.w3.org/2000/svg", "xmlns:xlink": "http://www.w3.org/1999/xlink"}


@lru_cache(maxsize=512)
def get_plugin_icon_asset(plugin: str) -> tuple[str, bytes] | None:
    """Return a content-addressed standalone SVG for a plugin's list icon."""
    from hashlib import sha256

    if not re.fullmatch(r"[a-z0-9_]+", plugin) or plugin not in get_plugin_catalog():
        return None
    match = _ICON_SVG_RE.fullmatch(str(get_plugin_icon(plugin)))
    if match is None:
        return None
    _, attributes, drawing = match.groups()
    if not re.search(r'\bxmlns="', attributes):
        attributes = f'xmlns="{_ICON_NAMESPACES["xmlns"]}" {attributes}'
    if "xlink:" in drawing and "xmlns:xlink=" not in attributes:
        attributes = f'xmlns:xlink="{_ICON_NAMESPACES["xmlns:xlink"]}" {attributes}'
    svg = f"<svg {attributes}>{drawing}</svg>".encode()
    return sha256(svg).hexdigest()[:20], svg


@lru_cache(maxsize=512)
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
    # Namespace declarations describe the standalone SVG, not its appearance.
    # HTML's enclosing <svg> already supplies these namespaces for its symbols.
    if any(name not in _ICON_BOX_ATTRS and name not in _ICON_SYMBOL_ATTRS and _ICON_NAMESPACES.get(name) != value for name, value in attrs):
        return None
    # Branded gradients already namespace their IDs by plugin. They can live
    # in a shared symbol unchanged; arbitrary IDs could collide with other icons.
    drawing_ids = re.findall(r'\bid="([^"]+)"', drawing)
    if len(drawing_ids) != len(set(drawing_ids)) or any(not name.startswith(f"abx-{plugin}-") for name in drawing_ids):
        return None
    references = re.findall(r"url\(#([^\s)]+)\)", drawing)
    if drawing.count("url(") != len(references):
        return None
    references.extend(re.findall(r'\bhref="#([^"]+)"', drawing))
    if any(reference not in drawing_ids for reference in references):
        return None
    symbol_attrs = "".join(f' {name}="{value}"' for name, value in attrs if name in _ICON_SYMBOL_ATTRS)
    box_attrs = "".join(f' {name}="{value}"' for name, value in attrs if name in _ICON_BOX_ATTRS)
    symbol = f'<symbol id="abx-icon-{plugin}"{symbol_attrs}>{drawing}</symbol>'
    return symbol, f'{span}<svg{box_attrs}><use href="#abx-icon-{plugin}"></use></svg></span>'


def get_plugin_list_icon(plugin: str) -> str:
    """Icon markup for list rows; pages that use it must include get_plugin_icon_sprite()."""
    parts = _plugin_icon_sprite_parts(plugin)
    return mark_safe(parts[1]) if parts else get_plugin_icon(plugin)


def get_plugin_icon_sprite(plugins: Iterable[str] | None = None) -> str:
    """Hidden <svg> holding the requested plugin drawings (all plugins by default)."""
    names = get_plugin_catalog() if plugins is None else plugins
    symbols = "".join(parts[0] for name in sorted(set(names)) if (parts := _plugin_icon_sprite_parts(name)))
    if not symbols:
        return ""
    # Not display:none: some browsers then skip painting the referenced symbols.
    return mark_safe(f'<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">{symbols}</svg>')
