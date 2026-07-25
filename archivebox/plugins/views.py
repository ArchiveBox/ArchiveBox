__package__ = "archivebox.plugins"

import html
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from admin_data_views.typing import TableContext
from admin_data_views.utils import ItemLink, render_with_table_view
from django.http import HttpRequest, HttpResponseRedirect
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from archivebox.config.common import get_live_config_url
from archivebox.config.views import get_environment_binary_url, is_superuser
from archivebox.plugins.discovery import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR, discover_plugin_configs, iter_plugin_dirs

ABX_PLUGINS_DOCS_BASE_URL = "https://archivebox.github.io/abx-plugins/"
ABX_PLUGINS_GITHUB_BASE_URL = "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/"
LIVE_PLUGIN_BASE_URL = "/admin/environment/plugins/"


JSON_TOKEN_RE = re.compile(
    r'(?P<key>"(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")(?=\s*:)'
    r'|(?P<string>"(?:\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*")'
    r"|(?P<boolean>\btrue\b|\bfalse\b)"
    r"|(?P<null>\bnull\b)"
    r"|(?P<number>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
)


def render_code_block(text: str, *, highlighted: bool = False) -> str:
    code = html.escape(text, quote=False)

    if highlighted:

        def _wrap_token(match: re.Match[str]) -> str:
            styles = {
                "key": "color: #0550ae;",
                "string": "color: #0a7f45;",
                "boolean": "color: #8250df; font-weight: 600;",
                "null": "color: #6e7781; font-style: italic;",
                "number": "color: #b35900;",
            }
            token_type = next(name for name, value in match.groupdict().items() if value is not None)
            return f'<span style="{styles[token_type]}">{match.group(0)}</span>'

        code = JSON_TOKEN_RE.sub(_wrap_token, code)

    return (
        '<pre style="max-height: 600px; overflow: auto; background: #f6f8fa; '
        'border: 1px solid #d0d7de; border-radius: 6px; padding: 12px; margin: 0;">'
        '<code style="font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, '
        "'Liberation Mono', monospace; white-space: pre; line-height: 1.5;\">"
        f"{code}"
        "</code></pre>"
    )


def render_highlighted_json_block(value: Any) -> str:
    return render_code_block(json.dumps(value, indent=2, ensure_ascii=False), highlighted=True)


def get_plugin_docs_url(plugin_name: str) -> str:
    return f"{ABX_PLUGINS_DOCS_BASE_URL}#{plugin_name}"


def get_plugin_hook_source_url(plugin_name: str, hook_name: str) -> str:
    return f"{ABX_PLUGINS_GITHUB_BASE_URL}{quote(plugin_name)}/{quote(hook_name)}"


def get_machine_admin_url() -> str | None:
    from archivebox.machine.models import Machine

    return Machine.current().admin_change_url


def render_code_tag_list(values: list[str]) -> str:
    if not values:
        return '<span style="color: #6e7781;">(none)</span>'

    tags = "".join(
        str(
            format_html(
                '<code style="display: inline-block; margin: 0 6px 6px 0; padding: 2px 6px; '
                'background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 999px;">{}</code>',
                value,
            ),
        )
        for value in values
    )
    return f'<div style="display: flex; flex-wrap: wrap;">{tags}</div>'


def render_link_tag_list(values: list[str], url_resolver: Callable[[str], str] | None = None) -> str:
    if not values:
        return '<span style="color: #6e7781;">(none)</span>'

    tags = []
    for value in values:
        if url_resolver is None:
            tags.append(
                str(
                    format_html(
                        '<code style="display: inline-block; margin: 0 6px 6px 0; padding: 2px 6px; '
                        'background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 999px;">{}</code>',
                        value,
                    ),
                ),
            )
        else:
            tags.append(
                str(
                    format_html(
                        '<a href="{}" style="text-decoration: none;">'
                        '<code style="display: inline-block; margin: 0 6px 6px 0; padding: 2px 6px; '
                        'background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 999px;">{}</code>'
                        "</a>",
                        url_resolver(value),
                        value,
                    ),
                ),
            )
    return f'<div style="display: flex; flex-wrap: wrap;">{"".join(tags)}</div>'


def render_plugin_metadata_html(config: dict[str, Any]) -> str:
    required_binaries = [
        str(item.get("name")) for item in (config.get("required_binaries") or []) if isinstance(item, dict) and item.get("name")
    ]
    rows = (
        ("Title", config.get("title") or "(none)"),
        ("Description", config.get("description") or "(none)"),
        ("Required Plugins", mark_safe(render_link_tag_list(config.get("required_plugins") or [], get_plugin_docs_url))),
        ("Required Binaries", mark_safe(render_link_tag_list(required_binaries, get_environment_binary_url))),
        ("Output MIME Types", mark_safe(render_code_tag_list(config.get("output_mimetypes") or []))),
    )

    rendered_rows = "".join(
        str(
            format_html(
                '<div style="margin: 0 0 14px 0;"><div style="font-weight: 600; margin-bottom: 4px;">{}</div><div>{}</div></div>',
                label,
                value,
            ),
        )
        for label, value in rows
    )
    return f'<div style="margin: 4px 0 0 0;">{rendered_rows}</div>'


def render_property_links(prop_name: str, prop_info: dict[str, Any], machine_admin_url: str | None) -> str:
    links = [
        str(format_html('<a href="{}">Computed value</a>', get_live_config_url(prop_name))),
    ]
    if machine_admin_url:
        links.append(str(format_html('<a href="{}">Edit override</a>', machine_admin_url)))

    fallback = prop_info.get("x-fallback")
    if isinstance(fallback, str) and fallback:
        links.append(str(format_html('<a href="{}">Fallback: <code>{}</code></a>', get_live_config_url(fallback), fallback)))

    aliases = prop_info.get("x-aliases") or []
    if isinstance(aliases, list):
        for alias in aliases:
            if isinstance(alias, str) and alias:
                links.append(str(format_html('<a href="{}">Alias: <code>{}</code></a>', get_live_config_url(alias), alias)))

    default = prop_info.get("default")
    if prop_name.endswith("_BINARY") and isinstance(default, str) and default:
        links.append(str(format_html('<a href="{}">Binary: <code>{}</code></a>', get_environment_binary_url(default), default)))

    return " &nbsp; ".join(links)


def render_config_properties_html(properties: dict[str, Any], machine_admin_url: str | None) -> str:
    header_links = [
        str(format_html('<a href="{}">Dependencies</a>', "/admin/environment/binaries/")),
        str(format_html('<a href="{}">Installed Binaries</a>', "/admin/machine/binary/")),
    ]
    if machine_admin_url:
        header_links.insert(0, str(format_html('<a href="{}">Machine Config Editor</a>', machine_admin_url)))

    cards = [
        f'<div style="margin: 0 0 16px 0;">{" &nbsp; | &nbsp; ".join(header_links)}</div>',
    ]

    for prop_name, prop_info in properties.items():
        prop_type = prop_info.get("type", "unknown")
        if isinstance(prop_type, list):
            prop_type = " | ".join(str(type_name) for type_name in prop_type)
        prop_desc = prop_info.get("description", "")

        default_html = ""
        if "default" in prop_info:
            default_html = str(
                format_html(
                    '<div style="margin-top: 6px;"><b>Default:</b> <code>{}</code></div>',
                    prop_info["default"],
                ),
            )

        description_html = prop_desc or mark_safe('<span style="color: #6e7781;">(no description)</span>')
        cards.append(
            str(
                format_html(
                    '<div style="margin: 0 0 14px 0; padding: 12px; background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;">'
                    '<div style="margin-bottom: 6px;">'
                    '<a href="{}" style="font-weight: 600;"><code>{}</code></a>'
                    ' <span style="color: #6e7781;">({})</span>'
                    "</div>"
                    '<div style="margin-bottom: 6px;">{}</div>'
                    '<div style="font-size: 0.95em;">{}</div>'
                    "{}"
                    "</div>",
                    get_live_config_url(prop_name),
                    prop_name,
                    prop_type,
                    description_html,
                    mark_safe(render_property_links(prop_name, prop_info, machine_admin_url)),
                    mark_safe(default_html),
                ),
            ),
        )

    return "".join(cards)


def render_hook_links_html(plugin_name: str, hooks: list[str], source: str) -> str:
    if not hooks:
        return '<span style="color: #6e7781;">(none)</span>'

    items = []
    for hook_name in hooks:
        if source == "builtin":
            items.append(
                str(
                    format_html(
                        '<div style="margin: 0 0 8px 0;"><a href="{}" target="_blank" rel="noopener noreferrer"><code>{}</code></a></div>',
                        get_plugin_hook_source_url(plugin_name, hook_name),
                        hook_name,
                    ),
                ),
            )
        else:
            items.append(
                str(
                    format_html(
                        '<div style="margin: 0 0 8px 0;"><code>{}</code></div>',
                        hook_name,
                    ),
                ),
            )
    return "".join(items)


def get_filesystem_plugins() -> dict[str, dict[str, Any]]:
    """Discover plugins from filesystem directories."""
    plugins = {}

    for base_dir, source in [(BUILTIN_PLUGINS_DIR, "builtin"), (USER_PLUGINS_DIR, "user")]:
        if not base_dir.exists():
            continue

        for plugin_dir in base_dir.iterdir():
            if plugin_dir.is_dir() and not plugin_dir.name.startswith("_"):
                plugin_id = f"{source}.{plugin_dir.name}"

                hooks = []
                for ext in ("sh", "py", "js"):
                    hooks.extend(plugin_dir.glob(f"on_*__*.{ext}"))

                config_file = plugin_dir / "config.json"
                config_data = None
                if config_file.exists():
                    try:
                        with open(config_file) as f:
                            config_data = json.load(f)
                    except (json.JSONDecodeError, OSError):
                        config_data = None

                plugins[plugin_id] = {
                    "id": plugin_id,
                    "name": plugin_dir.name,
                    "path": str(plugin_dir),
                    "source": source,
                    "hooks": [str(h.name) for h in hooks],
                    "config": config_data,
                }

    return plugins


def find_plugin_for_config_key(key: str) -> str | None:
    for plugin_name, schema in discover_plugin_configs().items():
        if key in (schema.get("properties") or {}):
            return plugin_name
    return None


def get_config_definition_link(key: str) -> tuple[str, str]:
    plugin_name = find_plugin_for_config_key(key)
    if not plugin_name:
        return (
            f"https://github.com/search?q=repo%3AArchiveBox%2FArchiveBox+path%3Aconfig+{quote(key)}&type=code",
            "archivebox/config",
        )

    plugin_dir = next((path.resolve() for path in iter_plugin_dirs() if path.name == plugin_name), None)
    if plugin_dir:
        builtin_root = BUILTIN_PLUGINS_DIR.resolve()
        if plugin_dir.is_relative_to(builtin_root):
            return (
                f"{ABX_PLUGINS_GITHUB_BASE_URL}{quote(plugin_name)}/config.json",
                f"abx_plugins/plugins/{plugin_name}/config.json",
            )

        user_root = USER_PLUGINS_DIR.resolve()
        if plugin_dir.is_relative_to(user_root):
            return (
                f"{LIVE_PLUGIN_BASE_URL}user.{quote(plugin_name)}/",
                f"data/custom_plugins/{plugin_name}/config.json",
            )

    return (
        f"{LIVE_PLUGIN_BASE_URL}builtin.{quote(plugin_name)}/",
        f"abx_plugins/plugins/{plugin_name}/config.json",
    )


@render_with_table_view
def plugins_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    rows = {
        "Name": [],
        "Source": [],
        "Path": [],
        "Hooks": [],
        "Config": [],
    }

    plugins = get_filesystem_plugins()

    for plugin_id, plugin in plugins.items():
        rows["Name"].append(ItemLink(plugin["name"], key=plugin_id))
        rows["Source"].append(plugin["source"])
        rows["Path"].append(format_html("<code>{}</code>", plugin["path"]))
        rows["Hooks"].append(", ".join(plugin["hooks"]) or "(none)")

        if plugin.get("config"):
            config_properties = plugin["config"].get("properties", {})
            config_count = len(config_properties)
            rows["Config"].append(f"✅ {config_count} properties" if config_count > 0 else "✅ present")
        else:
            rows["Config"].append("❌ none")

    if not plugins:
        rows["Name"].append("(no plugins found)")
        rows["Source"].append("-")
        rows["Path"].append(mark_safe("<code>abx_plugins/plugins/</code> or <code>data/custom_plugins/</code>"))
        rows["Hooks"].append("-")
        rows["Config"].append("-")

    return TableContext(
        title="Installed plugins",
        table=rows,
    )


def plugin_detail_view(request: HttpRequest, key: str, **kwargs) -> HttpResponseRedirect:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    plugin_name = key.removeprefix("builtin.").removeprefix("user.")
    return HttpResponseRedirect(get_plugin_docs_url(plugin_name))
