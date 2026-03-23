__package__ = "archivebox.config"

import html
import json
import os
import inspect
import re
from pathlib import Path
from typing import Any
from collections.abc import Callable
from urllib.parse import quote, urlencode
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from admin_data_views.typing import TableContext, ItemContext, SectionData
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink

from archivebox.config import CONSTANTS
from archivebox.misc.util import parse_date

from archivebox.machine.models import Binary

ABX_PLUGINS_DOCS_BASE_URL = "https://archivebox.github.io/abx-plugins/"
ABX_PLUGINS_GITHUB_BASE_URL = "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/"
LIVE_CONFIG_BASE_URL = "/admin/environment/config/"
ENVIRONMENT_BINARIES_BASE_URL = "/admin/environment/binaries/"
INSTALLED_BINARIES_BASE_URL = "/admin/machine/binary/"


# Common binaries to check for
KNOWN_BINARIES = [
    "wget",
    "curl",
    "chromium",
    "chrome",
    "google-chrome",
    "google-chrome-stable",
    "node",
    "npm",
    "npx",
    "yt-dlp",
    "git",
    "singlefile",
    "readability-extractor",
    "mercury-parser",
    "python3",
    "python",
    "bash",
    "zsh",
    "ffmpeg",
    "ripgrep",
    "rg",
    "sonic",
    "archivebox",
]

CANONICAL_BINARY_ALIASES = {
    "youtube-dl": "yt-dlp",
    "ytdlp": "yt-dlp",
    "ripgrep": "rg",
    "singlefile": "single-file",
    "mercury-parser": "postlight-parser",
}


def is_superuser(request: HttpRequest) -> bool:
    return bool(getattr(request.user, "is_superuser", False))


def format_parsed_datetime(value: object) -> str:
    parsed = parse_date(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else ""


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


def get_live_config_url(key: str) -> str:
    return f"{LIVE_CONFIG_BASE_URL}{quote(key)}/"


def get_environment_binary_url(name: str) -> str:
    return f"{ENVIRONMENT_BINARIES_BASE_URL}{quote(name)}/"


def get_installed_binary_change_url(name: str, binary: Any) -> str | None:
    binary_id = getattr(binary, "id", None)
    if not binary_id:
        return None

    base_url = getattr(binary, "admin_change_url", None) or f"{INSTALLED_BINARIES_BASE_URL}{binary_id}/change/"
    changelist_filters = urlencode({"q": canonical_binary_name(name)})
    return f"{base_url}?{urlencode({'_changelist_filters': changelist_filters})}"


def get_machine_admin_url() -> str | None:
    try:
        from archivebox.machine.models import Machine

        return Machine.current().admin_change_url
    except Exception:
        return None


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


def render_plugin_metadata_html(config: dict[str, Any]) -> str:
    rows = (
        ("Title", config.get("title") or "(none)"),
        ("Description", config.get("description") or "(none)"),
        ("Required Plugins", mark_safe(render_link_tag_list(config.get("required_plugins") or [], get_plugin_docs_url))),
        ("Required Binaries", mark_safe(render_link_tag_list(config.get("required_binaries") or [], get_environment_binary_url))),
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
        str(format_html('<a href="{}">Dependencies</a>', ENVIRONMENT_BINARIES_BASE_URL)),
        str(format_html('<a href="{}">Installed Binaries</a>', INSTALLED_BINARIES_BASE_URL)),
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


def render_binary_detail_description(name: str, merged: dict[str, Any], db_binary: Any) -> str:
    installed_binary_url = get_installed_binary_change_url(name, db_binary)

    if installed_binary_url:
        return str(
            format_html(
                '<code>{}</code><br/><a href="{}">View Installed Binary Record</a>',
                merged["abspath"],
                installed_binary_url,
            ),
        )

    return str(format_html("<code>{}</code>", merged["abspath"]))


def obj_to_yaml(obj: Any, indent: int = 0) -> str:
    indent_str = "  " * indent
    if indent == 0:
        indent_str = "\n"  # put extra newline between top-level entries

    if isinstance(obj, dict):
        if not obj:
            return "{}"
        result = "\n"
        for key, value in obj.items():
            result += f"{indent_str}{key}:{obj_to_yaml(value, indent + 1)}\n"
        return result

    elif isinstance(obj, list):
        if not obj:
            return "[]"
        result = "\n"
        for item in obj:
            result += f"{indent_str}- {obj_to_yaml(item, indent + 1).lstrip()}\n"
        return result.rstrip()

    elif isinstance(obj, str):
        if "\n" in obj:
            return f" |\n{indent_str}  " + obj.replace("\n", f"\n{indent_str}  ")
        else:
            return f" {obj}"

    elif isinstance(obj, (int, float, bool)):
        return f" {str(obj)}"

    elif callable(obj):
        source = (
            "\n".join("" if "def " in line else line for line in inspect.getsource(obj).split("\n") if line.strip())
            .split("lambda: ")[-1]
            .rstrip(",")
        )
        return f" {indent_str}  " + source.replace("\n", f"\n{indent_str}  ")

    else:
        return f" {str(obj)}"


def canonical_binary_name(name: str) -> str:
    return CANONICAL_BINARY_ALIASES.get(name, name)


def _binary_sort_key(binary: Binary) -> tuple[int, int, int, Any]:
    return (
        int(binary.status == Binary.StatusChoices.INSTALLED),
        int(bool(binary.version)),
        int(bool(binary.abspath)),
        binary.modified_at,
    )


def get_db_binaries_by_name() -> dict[str, Binary]:
    grouped: dict[str, list[Binary]] = {}
    for binary in Binary.objects.all():
        grouped.setdefault(canonical_binary_name(binary.name), []).append(binary)

    return {name: max(records, key=_binary_sort_key) for name, records in grouped.items()}


def serialize_binary_record(name: str, binary: Binary | None) -> dict[str, Any]:
    is_installed = bool(binary and binary.status == Binary.StatusChoices.INSTALLED)
    return {
        "name": canonical_binary_name(name),
        "version": str(getattr(binary, "version", "") or ""),
        "binprovider": str(getattr(binary, "binprovider", "") or ""),
        "abspath": str(getattr(binary, "abspath", "") or ""),
        "sha256": str(getattr(binary, "sha256", "") or ""),
        "status": str(getattr(binary, "status", "") or ""),
        "is_available": is_installed and bool(getattr(binary, "abspath", "") or ""),
    }


def get_filesystem_plugins() -> dict[str, dict[str, Any]]:
    """Discover plugins from filesystem directories."""
    import json
    from archivebox.hooks import BUILTIN_PLUGINS_DIR, USER_PLUGINS_DIR

    plugins = {}

    for base_dir, source in [(BUILTIN_PLUGINS_DIR, "builtin"), (USER_PLUGINS_DIR, "user")]:
        if not base_dir.exists():
            continue

        for plugin_dir in base_dir.iterdir():
            if plugin_dir.is_dir() and not plugin_dir.name.startswith("_"):
                plugin_id = f"{source}.{plugin_dir.name}"

                # Find hook scripts
                hooks = []
                for ext in ("sh", "py", "js"):
                    hooks.extend(plugin_dir.glob(f"on_*__*.{ext}"))

                # Load config.json if it exists
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


@render_with_table_view
def binaries_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    rows = {
        "Binary Name": [],
        "Found Version": [],
        "Provided By": [],
        "Found Abspath": [],
    }

    db_binaries = get_db_binaries_by_name()
    all_binary_names = sorted(db_binaries.keys())

    for name in all_binary_names:
        merged = serialize_binary_record(name, db_binaries.get(name))

        rows["Binary Name"].append(ItemLink(name, key=name))

        if merged["is_available"]:
            rows["Found Version"].append(f"✅ {merged['version']}" if merged["version"] else "✅ found")
            rows["Provided By"].append(merged["binprovider"] or "-")
            rows["Found Abspath"].append(merged["abspath"] or "-")
        else:
            rows["Found Version"].append("❌ missing")
            rows["Provided By"].append("-")
            rows["Found Abspath"].append("-")

    return TableContext(
        title="Binaries",
        table=rows,
    )


@render_with_item_view
def binary_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."
    key = canonical_binary_name(key)

    db_binary = get_db_binaries_by_name().get(key)
    merged = serialize_binary_record(key, db_binary)

    if merged["is_available"]:
        section: SectionData = {
            "name": key,
            "description": mark_safe(render_binary_detail_description(key, merged, db_binary)),
            "fields": {
                "name": key,
                "binprovider": merged["binprovider"] or "-",
                "abspath": merged["abspath"] or "not found",
                "version": merged["version"] or "unknown",
                "sha256": merged["sha256"],
                "status": merged["status"],
            },
            "help_texts": {},
        }
        return ItemContext(
            slug=key,
            title=key,
            data=[section],
        )

    section: SectionData = {
        "name": key,
        "description": "No persisted Binary record found",
        "fields": {
            "name": key,
            "binprovider": merged["binprovider"] or "not recorded",
            "abspath": merged["abspath"] or "not recorded",
            "version": merged["version"] or "N/A",
            "status": merged["status"] or "unrecorded",
        },
        "help_texts": {},
    }
    return ItemContext(
        slug=key,
        title=key,
        data=[section],
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

        # Show config status
        if plugin.get("config"):
            config_properties = plugin["config"].get("properties", {})
            config_count = len(config_properties)
            rows["Config"].append(f"✅ {config_count} properties" if config_count > 0 else "✅ present")
        else:
            rows["Config"].append("❌ none")

    if not plugins:
        # Show a helpful message when no plugins found
        rows["Name"].append("(no plugins found)")
        rows["Source"].append("-")
        rows["Path"].append(mark_safe("<code>abx_plugins/plugins/</code> or <code>data/custom_plugins/</code>"))
        rows["Hooks"].append("-")
        rows["Config"].append("-")

    return TableContext(
        title="Installed plugins",
        table=rows,
    )


@render_with_item_view
def plugin_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    plugins = get_filesystem_plugins()

    plugin = plugins.get(key)
    if not plugin:
        return ItemContext(
            slug=key,
            title=f"Plugin not found: {key}",
            data=[],
        )

    # Base fields that all plugins have
    docs_url = get_plugin_docs_url(plugin["name"])
    machine_admin_url = get_machine_admin_url()
    fields = {
        "id": plugin["id"],
        "name": plugin["name"],
        "source": plugin["source"],
    }

    sections: list[SectionData] = [
        {
            "name": plugin["name"],
            "description": format_html(
                '<code>{}</code><br/><a href="{}" target="_blank" rel="noopener noreferrer">ABX Plugin Docs</a>',
                plugin["path"],
                docs_url,
            ),
            "fields": fields,
            "help_texts": {},
        },
    ]

    if plugin["hooks"]:
        sections.append(
            {
                "name": "Hooks",
                "description": mark_safe(render_hook_links_html(plugin["name"], plugin["hooks"], plugin["source"])),
                "fields": {},
                "help_texts": {},
            },
        )

    if plugin.get("config"):
        sections.append(
            {
                "name": "Plugin Metadata",
                "description": mark_safe(render_plugin_metadata_html(plugin["config"])),
                "fields": {},
                "help_texts": {},
            },
        )

        sections.append(
            {
                "name": "config.json",
                "description": mark_safe(render_highlighted_json_block(plugin["config"])),
                "fields": {},
                "help_texts": {},
            },
        )

        config_properties = plugin["config"].get("properties", {})
        if config_properties:
            sections.append(
                {
                    "name": "Config Properties",
                    "description": mark_safe(render_config_properties_html(config_properties, machine_admin_url)),
                    "fields": {},
                    "help_texts": {},
                },
            )

    return ItemContext(
        slug=key,
        title=plugin["name"],
        data=sections,
    )


@render_with_table_view
def worker_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    rows = {
        "Name": [],
        "State": [],
        "PID": [],
        "Started": [],
        "Command": [],
        "Logfile": [],
        "Exit Status": [],
    }

    from archivebox.workers.supervisord_util import get_existing_supervisord_process

    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        return TableContext(
            title="No running worker processes",
            table=rows,
        )

    all_config: dict[str, dict[str, object]] = {}
    config_items = supervisor.getAllConfigInfo()
    if not isinstance(config_items, list):
        config_items = []
    for config_data in config_items:
        if not isinstance(config_data, dict):
            continue
        config_name = config_data.get("name")
        if not isinstance(config_name, str):
            continue
        all_config[config_name] = config_data

    # Add top row for supervisord process manager
    rows["Name"].append(ItemLink("supervisord", key="supervisord"))
    supervisor_state = supervisor.getState()
    rows["State"].append(str(supervisor_state.get("statename") if isinstance(supervisor_state, dict) else ""))
    rows["PID"].append(str(supervisor.getPID()))
    rows["Started"].append("-")
    rows["Command"].append("supervisord --configuration=tmp/supervisord.conf")
    rows["Logfile"].append(
        format_html(
            '<a href="/admin/environment/logs/{}/">{}</a>',
            "supervisord",
            "logs/supervisord.log",
        ),
    )
    rows["Exit Status"].append("0")

    # Add a row for each worker process managed by supervisord
    process_items = supervisor.getAllProcessInfo()
    if not isinstance(process_items, list):
        process_items = []
    for proc_data in process_items:
        if not isinstance(proc_data, dict):
            continue
        proc_name = str(proc_data.get("name") or "")
        proc_description = str(proc_data.get("description") or "")
        proc_start = proc_data.get("start")
        proc_logfile = str(proc_data.get("stdout_logfile") or "")
        proc_config = all_config.get(proc_name, {})

        rows["Name"].append(ItemLink(proc_name, key=proc_name))
        rows["State"].append(str(proc_data.get("statename") or ""))
        rows["PID"].append(proc_description.replace("pid ", ""))
        rows["Started"].append(format_parsed_datetime(proc_start))
        rows["Command"].append(str(proc_config.get("command") or ""))
        rows["Logfile"].append(
            format_html(
                '<a href="/admin/environment/logs/{}/">{}</a>',
                proc_logfile.split("/")[-1].split(".")[0],
                proc_logfile,
            ),
        )
        rows["Exit Status"].append(str(proc_data.get("exitstatus") or ""))

    return TableContext(
        title="Running worker processes",
        table=rows,
    )


@render_with_item_view
def worker_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    from archivebox.workers.supervisord_util import get_existing_supervisord_process, get_worker, get_sock_file, CONFIG_FILE_NAME

    SOCK_FILE = get_sock_file()
    CONFIG_FILE = SOCK_FILE.parent / CONFIG_FILE_NAME

    supervisor = get_existing_supervisord_process()
    if supervisor is None:
        return ItemContext(
            slug="none",
            title="error: No running supervisord process.",
            data=[],
        )

    all_config: list[dict[str, object]] = []
    config_items = supervisor.getAllConfigInfo()
    if not isinstance(config_items, list):
        config_items = []
    for config_data in config_items:
        if isinstance(config_data, dict):
            all_config.append(config_data)

    if key == "supervisord":
        relevant_config = CONFIG_FILE.read_text()
        relevant_logs = str(supervisor.readLog(0, 10_000_000))
        start_ts = [line for line in relevant_logs.split("\n") if "RPC interface 'supervisor' initialized" in line][-1].split(",", 1)[0]
        start_dt = parse_date(start_ts)
        uptime = str(timezone.now() - start_dt).split(".")[0] if start_dt else ""
        supervisor_state = supervisor.getState()

        proc: dict[str, object] = {
            "name": "supervisord",
            "pid": supervisor.getPID(),
            "statename": str(supervisor_state.get("statename") if isinstance(supervisor_state, dict) else ""),
            "start": start_ts,
            "stop": None,
            "exitstatus": "",
            "stdout_logfile": "logs/supervisord.log",
            "description": f"pid 000, uptime {uptime}",
        }
    else:
        worker_data = get_worker(supervisor, key)
        proc = worker_data if isinstance(worker_data, dict) else {}
        relevant_config = next((config for config in all_config if config.get("name") == key), {})
        log_result = supervisor.tailProcessStdoutLog(key, 0, 10_000_000)
        relevant_logs = str(log_result[0] if isinstance(log_result, tuple) else log_result)

    section: SectionData = {
        "name": key,
        "description": key,
        "fields": {
            "Command": str(proc.get("name") or ""),
            "PID": str(proc.get("pid") or ""),
            "State": str(proc.get("statename") or ""),
            "Started": format_parsed_datetime(proc.get("start")),
            "Stopped": format_parsed_datetime(proc.get("stop")),
            "Exit Status": str(proc.get("exitstatus") or ""),
            "Logfile": str(proc.get("stdout_logfile") or ""),
            "Uptime": str(str(proc.get("description") or "").split("uptime ", 1)[-1]),
            "Config": obj_to_yaml(relevant_config) if isinstance(relevant_config, dict) else str(relevant_config),
            "Logs": relevant_logs,
        },
        "help_texts": {"Uptime": "How long the process has been running ([days:]hours:minutes:seconds)"},
    }

    return ItemContext(
        slug=key,
        title=key,
        data=[section],
    )


@render_with_table_view
def log_list_view(request: HttpRequest, **kwargs) -> TableContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    log_files: list[Path] = []
    for logfile in sorted(CONSTANTS.LOGS_DIR.glob("*.log"), key=os.path.getmtime)[::-1]:
        if isinstance(logfile, Path):
            log_files.append(logfile)

    rows = {
        "Name": [],
        "Last Updated": [],
        "Size": [],
        "Most Recent Lines": [],
    }

    # Add a row for each worker process managed by supervisord
    for logfile in log_files:
        st = logfile.stat()
        rows["Name"].append(ItemLink("logs" + str(logfile).rsplit("/logs", 1)[-1], key=logfile.name))
        rows["Last Updated"].append(format_parsed_datetime(st.st_mtime))
        rows["Size"].append(f"{st.st_size // 1000} kb")

        with open(logfile, "rb") as f:
            try:
                f.seek(-1024, os.SEEK_END)
            except OSError:
                f.seek(0)
            last_lines = f.read().decode("utf-8", errors="replace").split("\n")
            non_empty_lines = [line for line in last_lines if line.strip()]
            rows["Most Recent Lines"].append(non_empty_lines[-1])

    return TableContext(
        title="Debug Log files",
        table=rows,
    )


@render_with_item_view
def log_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:
    assert is_superuser(request), "Must be a superuser to view configuration settings."

    log_file = [logfile for logfile in CONSTANTS.LOGS_DIR.glob("*.log") if key in logfile.name][0]

    log_text = log_file.read_text()
    log_stat = log_file.stat()

    section: SectionData = {
        "name": key,
        "description": key,
        "fields": {
            "Path": str(log_file),
            "Size": f"{log_stat.st_size // 1000} kb",
            "Last Updated": format_parsed_datetime(log_stat.st_mtime),
            "Tail": "\n".join(log_text[-10_000:].split("\n")[-20:]),
            "Full Log": log_text,
        },
    }

    return ItemContext(
        slug=key,
        title=key,
        data=[section],
    )
