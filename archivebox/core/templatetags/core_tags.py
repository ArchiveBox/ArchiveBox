from typing import Any

from django import template
from django.contrib.admin.templatetags.base import InclusionAdminNode
from django.utils.safestring import mark_safe
from django.utils.html import escape

from pathlib import Path

from archivebox.hooks import (
    get_plugin_icon,
    get_plugin_template,
    get_plugin_name,
)
from archivebox.core.host_utils import (
    get_admin_base_url,
    get_public_base_url,
    get_web_base_url,
    get_snapshot_base_url,
    build_snapshot_url,
)


register = template.Library()

_TEXT_PREVIEW_EXTS = (".json", ".jsonl", ".txt", ".csv", ".tsv", ".xml", ".yml", ".yaml", ".md", ".log")
_IMAGE_PREVIEW_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif")

_MEDIA_FILE_EXTS = {
    ".mp4",
    ".webm",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".ts",
    ".m2ts",
    ".mts",
    ".3gp",
    ".3g2",
    ".ogv",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".flac",
    ".alac",
    ".aiff",
    ".wma",
    ".mka",
    ".ac3",
    ".eac3",
    ".dts",
}


def _normalize_output_files(output_files: Any) -> dict[str, dict[str, Any]]:
    if isinstance(output_files, dict):
        normalized: dict[str, dict[str, Any]] = {}
        for path, metadata in output_files.items():
            if not path:
                continue
            normalized[str(path)] = dict(metadata) if isinstance(metadata, dict) else {}
        return normalized
    return {}


def _coerce_output_file_size(value: Any) -> int | None:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return None


def _count_media_files(result) -> int:
    try:
        output_files = _normalize_output_files(getattr(result, "output_files", None) or {})
    except Exception:
        output_files = {}

    if output_files:
        return sum(1 for path in output_files.keys() if Path(path).suffix.lower() in _MEDIA_FILE_EXTS)

    try:
        plugin_dir = Path(result.snapshot_dir) / result.plugin
    except Exception:
        return 0

    if not plugin_dir.exists():
        return 0

    count = 0
    scanned = 0
    max_scan = 500
    for file_path in plugin_dir.rglob("*"):
        if scanned >= max_scan:
            break
        scanned += 1
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() in _MEDIA_FILE_EXTS:
            count += 1
    return count


def _list_media_files(result) -> list[dict]:
    media_files: list[dict] = []
    try:
        plugin_dir = Path(result.snapshot_dir) / result.plugin
    except Exception:
        return media_files

    output_files = _normalize_output_files(getattr(result, "output_files", None) or {})
    candidates: list[tuple[Path, int | None]] = []
    if output_files:
        for path, metadata in output_files.items():
            rel_path = Path(path)
            if rel_path.suffix.lower() in _MEDIA_FILE_EXTS:
                candidates.append((rel_path, _coerce_output_file_size(metadata.get("size"))))

    if not candidates and plugin_dir.exists():
        scanned = 0
        max_scan = 2000
        for file_path in plugin_dir.rglob("*"):
            if scanned >= max_scan:
                break
            scanned += 1
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in _MEDIA_FILE_EXTS:
                try:
                    rel_path = file_path.relative_to(plugin_dir)
                except ValueError:
                    continue
                try:
                    size = file_path.stat().st_size
                except OSError:
                    size = None
                candidates.append((rel_path, size))

    for rel_path, size in candidates:
        href = str(Path(result.plugin) / rel_path)
        media_files.append(
            {
                "name": rel_path.name,
                "path": href,
                "size": size,
            },
        )

    media_files.sort(key=lambda item: item["name"].lower())
    return media_files


def _resolve_snapshot_output_file(snapshot_dir: str | Path | None, raw_output_path: str | None) -> Path | None:
    if not snapshot_dir or not raw_output_path or str(raw_output_path).strip() in (".", "/", "./"):
        return None

    output_file = Path(raw_output_path)
    if not output_file.is_absolute():
        output_file = Path(snapshot_dir) / raw_output_path

    try:
        output_file = output_file.resolve()
        snap_dir = Path(snapshot_dir).resolve()
        if snap_dir not in output_file.parents and output_file != snap_dir:
            return None
    except Exception:
        return None

    if output_file.exists() and output_file.is_file():
        return output_file
    return None


def _is_text_preview_path(raw_output_path: str | None) -> bool:
    return (raw_output_path or "").lower().endswith(_TEXT_PREVIEW_EXTS)


def _is_image_preview_path(raw_output_path: str | None) -> bool:
    return (raw_output_path or "").lower().endswith(_IMAGE_PREVIEW_EXTS)


def _is_root_snapshot_output_path(raw_output_path: str | None) -> bool:
    normalized = str(raw_output_path or "").strip().lower()
    return normalized in ("", ".", "./", "/", "index.html", "index.json")


def _build_snapshot_files_url(snapshot_id: str, request=None) -> str:
    return build_snapshot_url(str(snapshot_id), "/?files=1", request=request)


def _build_snapshot_preview_url(snapshot_id: str, path: str = "", request=None) -> str:
    if path == "about:blank":
        return path
    if _is_root_snapshot_output_path(path):
        return _build_snapshot_files_url(snapshot_id, request=request)
    url = build_snapshot_url(str(snapshot_id), path, request=request)
    if not (_is_text_preview_path(path) or _is_image_preview_path(path)):
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}preview=1"


def _render_text_preview(plugin: str, icon_html: str, snippet: str) -> str:
    plugin_attr = escape(plugin or "")
    plugin_label = escape(plugin or "")
    escaped = escape(snippet)
    return (
        f'<div class="thumbnail-text" data-plugin="{plugin_attr}" data-compact="1">'
        f'<div class="thumbnail-text-header">'
        f'<span class="thumbnail-compact-icon">{icon_html}</span>'
        f'<span class="thumbnail-text-title">{plugin_label}</span>'
        f"</div>"
        f'<pre class="thumbnail-text-pre">{escaped}</pre>'
        f"</div>"
    )


def _render_fallback_card(plugin: str, icon_html: str, fallback_label: str) -> str:
    plugin_attr = escape(plugin or "")
    plugin_label = escape(plugin or "")
    fallback_attr = escape(fallback_label)
    return (
        f'<div class="thumbnail-compact" data-plugin="{plugin_attr}" data-compact="1">'
        f'<span class="thumbnail-compact-icon">{icon_html}</span>'
        f'<span class="thumbnail-compact-label">{plugin_label}</span>'
        f'<span class="thumbnail-compact-meta">{fallback_attr}</span>'
        f"</div>"
    )


def _render_text_file_preview(snapshot_dir: str | Path | None, raw_output_path: str | None, plugin: str, icon_html: str) -> str | None:
    output_file = _resolve_snapshot_output_file(snapshot_dir, raw_output_path)
    if not output_file:
        return None

    try:
        with output_file.open("rb") as f:
            raw = f.read(4096)
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        lines = text.splitlines()[:6]
        snippet = "\n".join(lines)
        return _render_text_preview(plugin, icon_html, snippet)
    except Exception:
        return None


@register.filter(name="split")
def split(value, separator: str = ","):
    return (value or "").split(separator)


@register.filter(name="index")
def index(value, position):
    try:
        return value[int(position)]
    except Exception:
        return None


@register.filter
def file_size(num_bytes: int | float) -> str:
    for count in ["Bytes", "KB", "MB", "GB"]:
        if num_bytes > -1024.0 and num_bytes < 1024.0:
            return f"{num_bytes:3.1f} {count}"
        num_bytes /= 1024.0
    return "{:3.1f} {}".format(num_bytes, "TB")


def result_list(cl):
    """
    Monkey patched result
    """
    num_sorted_fields = 0
    return {
        "cl": cl,
        "num_sorted_fields": num_sorted_fields,
        "results": cl.result_list,
    }


@register.tag(name="snapshots_grid")
def result_list_tag(parser, token):
    return InclusionAdminNode(
        parser,
        token,
        func=result_list,
        template_name="snapshots_grid.html",
        takes_context=False,
    )


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    dict_ = context["request"].GET.copy()
    dict_.update(**kwargs)
    return dict_.urlencode()


@register.simple_tag(takes_context=True)
def admin_base_url(context) -> str:
    return get_admin_base_url(request=context.get("request"))


@register.simple_tag(takes_context=True)
def web_base_url(context) -> str:
    return get_web_base_url(request=context.get("request"))


@register.simple_tag(takes_context=True)
def public_base_url(context) -> str:
    return get_public_base_url(request=context.get("request"))


@register.simple_tag(takes_context=True)
def snapshot_base_url(context, snapshot) -> str:
    snapshot_id = getattr(snapshot, "id", snapshot)
    return get_snapshot_base_url(str(snapshot_id), request=context.get("request"))


@register.simple_tag(takes_context=True)
def snapshot_url(context, snapshot, path: str = "") -> str:
    snapshot_id = getattr(snapshot, "id", snapshot)
    return build_snapshot_url(str(snapshot_id), path, request=context.get("request"))


@register.simple_tag(takes_context=True)
def snapshot_preview_url(context, snapshot, path: str = "") -> str:
    snapshot_id = getattr(snapshot, "id", snapshot)
    return _build_snapshot_preview_url(str(snapshot_id), path, request=context.get("request"))


@register.simple_tag
def plugin_icon(plugin: str) -> str:
    """
    Render the icon for a plugin.

    Usage: {% plugin_icon "screenshot" %}
    """
    icon_html = get_plugin_icon(plugin)
    return mark_safe(
        f'<span class="abx-plugin-icon" style="display:inline-flex; width:20px; height:20px; align-items:center; justify-content:center;">{icon_html}</span>',
    )


@register.simple_tag(takes_context=True)
def plugin_card(context, result) -> str:
    """
    Render the card template for an archive result.

    Usage: {% plugin_card result %}

    Context variables passed to template:
        - result: ArchiveResult object
        - snapshot: Parent Snapshot object
        - output_path: Path to output relative to snapshot dir (from embed_path())
        - plugin: Plugin base name
    """
    if result is None or not hasattr(result, "plugin"):
        return ""

    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, "card")

    # Use embed_path() for the display path
    raw_output_path = result.embed_path() if hasattr(result, "embed_path") else ""
    output_url = build_snapshot_url(
        str(getattr(result, "snapshot_id", "")),
        raw_output_path or "",
        request=context.get("request"),
    )

    icon_html = get_plugin_icon(plugin)
    plugin_lower = (plugin or "").lower()
    media_file_count = _count_media_files(result) if plugin_lower in ("ytdlp", "yt-dlp", "youtube-dl") else 0
    media_files = _list_media_files(result) if plugin_lower in ("ytdlp", "yt-dlp", "youtube-dl") else []
    if media_files:
        snapshot_id = str(getattr(result, "snapshot_id", ""))
        request = context.get("request")
        for item in media_files:
            path = item.get("path") or ""
            item["url"] = build_snapshot_url(snapshot_id, path, request=request) if path else ""

    output_lower = (raw_output_path or "").lower()
    force_text_preview = output_lower.endswith(_TEXT_PREVIEW_EXTS)

    # Create a mini template and render it with context
    try:
        if template_str and raw_output_path and str(raw_output_path).strip() not in (".", "/", "./") and not force_text_preview:
            tpl = template.Template(template_str)
            ctx = template.Context(
                {
                    "result": result,
                    "snapshot": result.snapshot,
                    "output_path": output_url,
                    "output_path_raw": raw_output_path,
                    "plugin": plugin,
                    "plugin_icon": icon_html,
                    "media_file_count": media_file_count,
                    "media_files": media_files,
                },
            )
            rendered = tpl.render(ctx)
            # Only return non-empty content (strip whitespace to check)
            if rendered.strip():
                return mark_safe(rendered)
    except Exception:
        pass

    if force_text_preview:
        preview = _render_text_file_preview(getattr(result, "snapshot_dir", None), raw_output_path, plugin, icon_html)
        if preview:
            return mark_safe(preview)

    if output_lower.endswith(_TEXT_PREVIEW_EXTS):
        fallback_label = "text"
    else:
        fallback_label = "output"

    return mark_safe(_render_fallback_card(plugin, icon_html, fallback_label))


@register.simple_tag
def output_card(snapshot, output_path: str, plugin: str) -> str:
    plugin_name = get_plugin_name(plugin)
    icon_html = get_plugin_icon(plugin_name)
    preview = _render_text_file_preview(getattr(snapshot, "output_dir", None), output_path, plugin_name, icon_html)
    if preview:
        return mark_safe(preview)

    output_lower = (output_path or "").lower()
    fallback_label = "text" if output_lower.endswith(_TEXT_PREVIEW_EXTS) else "output"
    return mark_safe(_render_fallback_card(plugin_name, icon_html, fallback_label))


@register.simple_tag(takes_context=True)
def plugin_full(context, result) -> str:
    """
    Render the full template for an archive result.

    Usage: {% plugin_full result %}
    """
    if result is None or not hasattr(result, "plugin"):
        return ""

    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, "full")

    if not template_str:
        return ""

    raw_output_path = ""
    if hasattr(result, "embed_path_db"):
        raw_output_path = result.embed_path_db() or ""
    if not raw_output_path and hasattr(result, "embed_path"):
        raw_output_path = result.embed_path() or ""
    if _is_root_snapshot_output_path(raw_output_path):
        return ""
    output_url = build_snapshot_url(
        str(getattr(result, "snapshot_id", "")),
        raw_output_path,
        request=context.get("request"),
    )

    try:
        tpl = template.Template(template_str)
        ctx = template.Context(
            {
                "result": result,
                "snapshot": result.snapshot,
                "output_path": output_url,
                "output_path_raw": raw_output_path,
                "plugin": plugin,
            },
        )
        rendered = tpl.render(ctx)
        # Only return non-empty content (strip whitespace to check)
        if rendered.strip():
            return mark_safe(rendered)
        return ""
    except Exception:
        return ""


@register.filter
def plugin_name(value: str) -> str:
    """
    Get the base name of a plugin (strips numeric prefix).

    Usage: {{ result.plugin|plugin_name }}
    """
    return get_plugin_name(value)


@register.simple_tag(takes_context=True)
def api_token(context) -> str:
    """
    Return an API token string for the logged-in user, creating one if needed.
    """
    from archivebox.api.auth import get_or_create_api_token

    request = context.get("request")
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return ""

    token = get_or_create_api_token(user)
    return token.token if token else ""
