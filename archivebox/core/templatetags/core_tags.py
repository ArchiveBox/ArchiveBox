import os
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from abx_plugins.plugins.archivewebpage.replay_preview import is_replay_target as is_archivewebpage_replay_target
from django import template
from django.templatetags.static import static
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.text import Truncator

from archivebox.config import CONSTANTS
from archivebox.core.routes_util import (
    build_snapshot_url,
    get_admin_base_url,
    get_snapshot_base_url,
    get_web_base_url,
)
from archivebox.core.setup_wizard import get_base_url_mismatch_context, get_setup_wizard_context
from archivebox.plugins.discovery import (
    get_plugin_icon,
    get_plugin_name,
    get_plugin_template,
)

register = template.Library()

_TEXT_PREVIEW_EXTS = (".json", ".jsonl", ".txt", ".csv", ".tsv", ".xml", ".yml", ".yaml", ".md", ".log")
_IMAGE_PREVIEW_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".avif")
_STATIC_URL_SAFE = "/@-._~!$&'()*+,;="

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


def _snapshot_id(value: Any) -> Any:
    from archivebox.core.models import Snapshot

    return value.id if isinstance(value, Snapshot) else value


def _coerce_output_file_size(value: Any) -> int | None:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return None


def _count_media_files(result) -> int:
    try:
        output_files = _normalize_output_files(result.output_files or {})
    except (AttributeError, TypeError, ValueError):
        output_files = {}

    if output_files:
        return sum(1 for path in output_files if Path(path).suffix.lower() in _MEDIA_FILE_EXTS)

    try:
        plugin_dir = Path(result.snapshot_dir) / result.plugin
    except (AttributeError, TypeError, ValueError):
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
    except (AttributeError, TypeError, ValueError):
        return media_files

    output_files = _normalize_output_files(result.output_files or {})
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
    except (OSError, RuntimeError, TypeError, ValueError):
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


def _static_snapshot_base_url(context, snapshot) -> str:
    start_dir = Path(context["STATIC_EXPORT_DIR"])
    relative_path = os.path.relpath(Path(snapshot.output_dir), start=start_dir).replace(os.sep, "/")
    if relative_path == ".":
        return "."
    return f"./{quote(relative_path, safe=_STATIC_URL_SAFE)}"


def _snapshot_base_url_for_context(context, snapshot) -> str:
    if context.get("STATIC_EXPORT"):
        return _static_snapshot_base_url(context, snapshot)
    return get_snapshot_base_url(
        str(_snapshot_id(snapshot)),
        request=context.get("request"),
        config=context.get("CONFIG"),
    )


def _snapshot_url_for_context(context, snapshot, path: str = "") -> str:
    if not context.get("STATIC_EXPORT"):
        return build_snapshot_url(
            str(_snapshot_id(snapshot)),
            path,
            request=context.get("request"),
            config=context.get("CONFIG"),
        )

    base_url = _static_snapshot_base_url(context, snapshot)
    raw_path = str(path or "")
    if not raw_path:
        return base_url
    path_part, separator, query = raw_path.lstrip("/").partition("?")
    quoted_path = quote(path_part, safe=_STATIC_URL_SAFE)
    suffix = f"?{query}" if separator else ""
    return f"{base_url.rstrip('/')}/{quoted_path}{suffix}"


def _build_snapshot_files_url(snapshot_id: str, request=None, config=None, base_url: str | None = None) -> str:
    return (
        f"{base_url.rstrip('/')}/index.jsonl"
        if base_url
        else build_snapshot_url(str(snapshot_id), "/?files=1", request=request, config=config)
    )


def _build_snapshot_preview_url(
    snapshot_id: str,
    path: str = "",
    request=None,
    config=None,
    plugin: str = "",
    base_url: str | None = None,
) -> str:
    if path == "about:blank":
        return path
    if _is_root_snapshot_output_path(path):
        return _build_snapshot_files_url(snapshot_id, request=request, config=config, base_url=base_url)
    if base_url:
        path_part, separator, query = str(path).lstrip("/").partition("?")
        url = f"{base_url.rstrip('/')}/{quote(path_part, safe=_STATIC_URL_SAFE)}"
        if separator:
            url = f"{url}?{query}"
    else:
        url = build_snapshot_url(str(snapshot_id), path, request=request, config=config)
    path_parts = Path(path).parts
    plugin = get_plugin_name(plugin) if plugin else (path_parts[0] if len(path_parts) > 1 else "")
    has_plugin_preview = bool(plugin and get_plugin_template(plugin, "full", fallback=False))
    if not (
        _is_text_preview_path(path) or _is_image_preview_path(path) or has_plugin_preview or is_archivewebpage_replay_target(path or "")
    ):
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
    except (OSError, UnicodeDecodeError, ValueError):
        return None


@register.filter(name="split")
def split(value, separator: str = ","):
    return (value or "").split(separator)


@register.filter(name="index")
def index(value, position):
    try:
        return value[int(position)]
    except (IndexError, TypeError, ValueError):
        return None


@register.filter
def file_size(num_bytes: float) -> str:
    for count in ["Bytes", "KB", "MB", "GB"]:
        if num_bytes > -1024.0 and num_bytes < 1024.0:
            return f"{num_bytes:3.1f} {count}"
        num_bytes /= 1024.0
    return "{:3.1f} {}".format(num_bytes, "TB")


@register.filter
def intcomma(value: int | str | None) -> str:
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return str(value or "")


@register.inclusion_tag("admin/snapshots_grid.html", takes_context=True, name="snapshots_grid")
def result_list(context, cl):
    """
    Monkey patched result
    """
    num_sorted_fields = 0
    request = context.get("request")
    config = request.__dict__.get("archivebox_config") if request is not None else context.get("CONFIG")
    results = cl.result_list
    if config is not None:
        for obj in results:
            obj._runtime_config = config
    return {
        "cl": cl,
        "num_sorted_fields": num_sorted_fields,
        "results": results,
        "request": request,
        "CONFIG": config,
    }


_LOW_DISK_THRESHOLD_GB = 1.0
_HIGH_MEMORY_THRESHOLD_PCT = 95.0
_HIGH_LOAD_MULTIPLE = 3  # 15-min loadavg > 3 * cpu_count
_HEALTH_CHECK_INTERVAL_SECONDS = 30
_health_cache: dict = {"checked_at": 0.0, "stats": {}}


def _machine_health_stats() -> dict:
    """Cached wrapper around the Machine-admin stats util.

    The Machine list/change pages already render disk / mem / load via
    ``archivebox.machine.detect.get_host_stats()`` — we reuse the same call so
    the banner thresholds line up 1:1 with what's shown on /admin/machine/.
    Cached for 30s because the inclusion tag fires on every page render and
    ``get_host_stats`` shells into several psutil probes.
    """
    import time

    now = time.monotonic()
    if _health_cache["stats"] and (now - _health_cache["checked_at"]) < _HEALTH_CHECK_INTERVAL_SECONDS:
        return _health_cache["stats"]

    try:
        from archivebox.machine.detect import get_host_stats

        stats = get_host_stats() or {}
    except (ImportError, RuntimeError, TypeError, ValueError):
        stats = {}

    _health_cache["checked_at"] = now
    _health_cache["stats"] = stats
    return stats


@register.inclusion_tag("system_warnings_banner.html", takes_context=True)
def system_warnings_banner(context):
    """Render the top-of-page warning banner for one of the conditions below,
    in priority order (highest first):

    1. ``mode="unconfigured"``— ``BASE_URL`` is empty. Security/correctness
       issue: until it's pinned, generated URLs can echo any Host the client
       sends, and admin/web/api routing has no canonical anchor.
    2. ``mode="base_url_mismatch"`` — the browser reached ArchiveBox through
       an origin that differs from the configured canonical ``BASE_URL``.
    3. ``mode="unsafe"``      — ``SERVER_SECURITY_MODE`` explicitly enables
       a lower-security replay mode.
    4. ``mode="low_disk"``    — ``DATA_DIR`` has <1 GiB free; new archive
       jobs will start failing on ENOSPC.
    5. ``mode="high_memory"`` — virtual memory utilization at/above 95%; the
       host is one OOM-kill from a crash.
    6. ``mode="high_load"``   — 15-minute load average exceeds 3 × CPU count
       (the kernel's own sustained-load EMA, so no rolling buffer of ours is
       needed).

    Config/security warnings come first because they affect correctness +
    security and need explicit operator action; host-health warnings come
    after and reuse ``machine.detect.get_host_stats`` (the same function that
    populates the Machine admin page), cached for 30s.
    """
    if context.get("first_admin_setup"):
        return {"mode": ""}

    config = context.get("CONFIG")
    if config is None:
        from archivebox.config.common import get_config

        config = get_config(resolve_plugins=False)

    if not config.BASE_URL:
        return get_setup_wizard_context(context.get("request"), config)
    mismatch = get_base_url_mismatch_context(context.get("request"), config)
    if mismatch:
        return mismatch
    if config.IS_LOWER_SECURITY_MODE:
        return {"mode": "unsafe"}

    stats = _machine_health_stats()
    free_gb = stats.get("disk_data_free_gb")
    if isinstance(free_gb, (int, float)) and free_gb < _LOW_DISK_THRESHOLD_GB:
        return {"mode": "low_disk", "free_gb": f"{free_gb:.2f}"}

    mem_pct = stats.get("mem_virt_used_pct")
    if isinstance(mem_pct, (int, float)) and mem_pct >= _HIGH_MEMORY_THRESHOLD_PCT:
        return {"mode": "high_memory", "mem_pct": f"{mem_pct:.1f}"}

    cpu_load = stats.get("cpu_load") or ()
    cpu_count = stats.get("cpu_count") or 1
    # ``cpu_load`` is the (1min, 5min, 15min) tuple from psutil.getloadavg();
    # we take the 15-min figure because the operator's threshold was
    # "sustained for 15min" and the kernel already maintains that EMA.
    load_15 = cpu_load[2] if isinstance(cpu_load, (list, tuple)) and len(cpu_load) >= 3 else None
    if isinstance(load_15, (int, float)) and load_15 > _HIGH_LOAD_MULTIPLE * cpu_count:
        if os.environ.get("UI_SCREENSHOT_HIDE_HIGH_LOAD_WARNING") == "1":
            return {"mode": ""}
        return {
            "mode": "high_load",
            "load_15": f"{load_15:.2f}",
            "cpu_count": cpu_count,
            "load_threshold": _HIGH_LOAD_MULTIPLE * cpu_count,
        }

    return {"mode": ""}


@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    dict_ = context["request"].GET.copy()
    dict_.update(**kwargs)
    return dict_.urlencode()


@register.simple_tag(takes_context=True)
def admin_base_url(context) -> str:
    return get_admin_base_url(request=context.get("request"), config=context.get("CONFIG"))


@register.simple_tag(takes_context=True)
def web_base_url(context) -> str:
    return get_web_base_url(request=context.get("request"), config=context.get("CONFIG"))


@register.simple_tag(takes_context=True)
def static_export_root_url(context) -> str:
    if not context.get("STATIC_EXPORT"):
        return ""
    relative_path = os.path.relpath(CONSTANTS.DATA_DIR, start=Path(context["STATIC_EXPORT_DIR"]))
    relative_path = relative_path.replace(os.sep, "/")
    return "./" if relative_path == "." else f"{quote(relative_path, safe=_STATIC_URL_SAFE)}/"


@register.simple_tag(takes_context=True)
def snapshot_base_url(context, snapshot) -> str:
    return _snapshot_base_url_for_context(context, snapshot)


@register.simple_tag(takes_context=True)
def snapshot_url(context, snapshot, path: str = "") -> str:
    return _snapshot_url_for_context(context, snapshot, path)


@register.simple_tag(takes_context=True)
def snapshot_archiveresult_url(context, snapshot, plugin: str, filename: str) -> str:
    snapshot_id = str(_snapshot_id(snapshot))
    url_cache = snapshot.__dict__.setdefault("_snapshot_archiveresult_url_cache", {})
    cache_key = (
        plugin,
        filename,
        bool(context.get("STATIC_EXPORT")),
        str(context.get("STATIC_EXPORT_DIR") or ""),
    )
    if cache_key in url_cache:
        return url_cache[cache_key]

    results = None
    if "_admin_archiveresults" in snapshot.__dict__:
        results = snapshot.__dict__["_admin_archiveresults"]
    elif "archiveresult_set" in snapshot.__dict__.get("_prefetched_objects_cache", {}):
        results = snapshot.archiveresult_set.all()
    elif "_snapshot_archiveresult_url_results" in snapshot.__dict__:
        results = snapshot.__dict__["_snapshot_archiveresult_url_results"]

    if results is None:
        from archivebox.core.models import ArchiveResult

        results = list(
            ArchiveResult.objects.filter(
                snapshot_id=snapshot_id,
                plugin__in=("screenshot", "chrome_extension_screenshot", "favicon"),
                status=ArchiveResult.StatusChoices.SUCCEEDED,
            ).only(
                "plugin",
                "status",
                "output_files",
            ),
        )
        snapshot.__dict__["_snapshot_archiveresult_url_results"] = results

    for result in results:
        if result.plugin != plugin or result.status != "succeeded":
            continue
        output_files = result.output_files or {}
        file_info = output_files.get(filename)
        if not isinstance(file_info, dict) or int(file_info.get("size") or 0) <= 0:
            continue
        output_path = filename if file_info.get("root_relative") else f"{plugin}/{filename}"
        url_cache[cache_key] = _snapshot_url_for_context(context, snapshot, output_path)
        return url_cache[cache_key]

    url_cache[cache_key] = ""
    return ""


@register.simple_tag(takes_context=True)
def snapshot_index_row(context, link) -> str:
    snapshot_base = _snapshot_base_url_for_context(context, link)

    status = getattr(link, "status", None) or "unknown"
    bookmarked_at = getattr(link, "bookmarked_at", None)
    timestamp = getattr(link, "timestamp", "")
    if bookmarked_at:
        bookmarked_at = timezone.localtime(bookmarked_at)
        date_text = bookmarked_at.strftime("%Y-%m-%d")
        time_text = bookmarked_at.strftime("%H:%M")
        sort_value = str(bookmarked_at.timestamp())
        title_time = f"Bookmarked: {bookmarked_at} ({timestamp})"
    else:
        date_text = ""
        time_text = ""
        sort_value = ""
        title_time = f"Bookmarked: ({timestamp})"

    url = getattr(link, "url", "") or ""
    title = unescape(getattr(link, "title", "") or "")
    is_pending = status in {"queued", "started", "backoff"}
    title_text = title or url
    tags_str = link.tags_str() if callable(getattr(link, "tags_str", None)) else getattr(link, "tags_str", "")
    tag_html = "".join(f'<span class="snapshot-tag">{escape(tag)}</span>' for tag in (tags_str or "").split(",") if tag)
    if tag_html:
        tag_cell = f'<span class="snapshot-tags">{tag_html}</span>'
    else:
        tag_cell = '<span class="empty-value">...</span>'

    num_outputs = int(getattr(link, "num_outputs", 0) or 0)
    if context.get("STATIC_EXPORT") and callable(getattr(link, "icons", None)):
        icons = link.icons(path=quote(link.static_archive_path, safe=_STATIC_URL_SAFE), prefix="./", quote_paths=True)
    else:
        icons = link.icons() if callable(getattr(link, "icons", None)) else getattr(link, "icons", "")
    icons_cell = str(icons) if icons else '<span class="empty-value">...</span>'
    archive_size = int(getattr(link, "archive_size", 0) or 0)
    size_cell = file_size(archive_size) if archive_size else '<span class="empty-value">...</span>'
    output_plural = "" if num_outputs == 1 else "s"
    files_url = _snapshot_url_for_context(context, link, "index.jsonl") if context.get("STATIC_EXPORT") else f"{snapshot_base}/?files=1"

    if is_pending:
        preview_html = '<span class="snapshot-preview snapshot-preview-spinner" aria-label="Archiving in progress"></span>'
        if not context.get("STATIC_EXPORT"):
            preview_html = (
                '<span class="snapshot-preview snapshot-preview-spinner" aria-label="Archiving in progress">'
                f'<img src="{escape(static("spinner.gif"))}" alt="" decoding="async" loading="lazy">'
                "</span>"
            )
    elif "_public_preview_paths" in link.__dict__:
        preview_paths = list(getattr(link, "_public_preview_paths", []) or [])
        if preview_paths:
            preview_urls = [_snapshot_url_for_context(context, link, path) for path in preview_paths]
            preview_html = (
                f'<img src="{escape(preview_urls[0])}" '
                f'data-fallbacks="{escape(",".join(preview_urls[1:]))}" '
                'onerror="nextPublicSnapshotPreview(this)" class="snapshot-preview screenshot" alt="" decoding="async" loading="lazy">'
            )
        else:
            preview_html = '<span class="snapshot-preview snapshot-preview-empty" aria-label="No preview available"></span>'
    else:
        preview_urls = [
            url
            for url in (
                snapshot_archiveresult_url(context, link, "screenshot", "screenshot.png"),
                snapshot_archiveresult_url(context, link, "chrome_extension_screenshot", "screenshot-1.png"),
                snapshot_archiveresult_url(context, link, "chrome_extension_screenshot", "screenshot.png"),
            )
            if url
        ]
        if preview_urls:
            preview_html = (
                f'<img src="{escape(preview_urls[0])}" '
                f'data-fallbacks="{escape(",".join(preview_urls[1:]))}" '
                'onerror="nextPublicSnapshotPreview(this)" class="snapshot-preview screenshot" alt="" decoding="async" loading="lazy">'
            )
        else:
            preview_html = '<span class="snapshot-preview snapshot-preview-empty" aria-label="No preview available"></span>'

    if "_public_favicon_paths" in link.__dict__:
        favicon_paths = list(getattr(link, "_public_favicon_paths", []) or [])
        if favicon_paths:
            favicon_urls = [_snapshot_url_for_context(context, link, path) for path in favicon_paths]
            favicon_html = (
                f'<img src="{escape(favicon_urls[0])}" '
                f'data-fallbacks="{escape(",".join(favicon_urls[1:]))}" '
                'onerror="nextPublicSnapshotPreview(this)" '
                'class="link-favicon" alt="" decoding="async" loading="lazy">'
            )
        else:
            favicon_html = '<span class="link-favicon link-favicon-empty" aria-hidden="true"></span>'
    else:
        favicon_url = snapshot_archiveresult_url(context, link, "favicon", "favicon.ico")
        favicon_html = (
            (
                f'<img src="{escape(favicon_url)}" '
                'data-fallbacks="" '
                'onerror="nextPublicSnapshotPreview(this)" '
                'class="link-favicon" alt="" decoding="async" loading="lazy">'
            )
            if favicon_url
            else '<span class="link-favicon link-favicon-empty" aria-hidden="true"></span>'
        )

    html = f"""
<tr class="snapshot-row status-{escape(status)}">
    <td class="snapshot-time" title="{escape(title_time)}" data-sort="{escape(sort_value)}">
        <a href="{escape(snapshot_base)}/index.html">
            <span>{escape(date_text)}</span>
            <small>{escape(time_text)}</small>
        </a>
    </td>
    <td class="snapshot-preview-cell">
        <a href="{escape(snapshot_base)}/index.html" title="Open archived snapshot">
            {preview_html}
        </a>
    </td>
    <td class="snapshot-title-cell" title="{escape(title or url)}">
        <div class="snapshot-title-line">
            <a href="{escape(snapshot_base)}/index.html" class="snapshot-favicon-link" title="Open archived snapshot">
                {favicon_html}
            </a>
            <a href="{escape(snapshot_base)}/index.html" class="snapshot-title">
                {escape(Truncator(title_text).chars(110))}
            </a>
        </div>
        <a href="{escape(url)}" class="snapshot-url" title="{escape(url)}" target="_blank" rel="noopener noreferrer">
            {escape(url)}
        </a>
        <span class="snapshot-mobile-saved">Saved {escape(date_text)} at {escape(time_text)}</span>
    </td>
    <td class="snapshot-tags-cell">
        {tag_cell}
    </td>
    <td class="snapshot-status-cell">
        <span class="snapshot-status">{escape(status)}</span>
    </td>
    <td class="snapshot-files-cell">
        <span data-number-for="{escape(url)}" title="{num_outputs} successful outputs">
            {icons_cell}
        </span>
    </td>
    <td class="snapshot-size-cell">
        <a href="{escape(files_url)}" title="View archived file manifest">
            {size_cell}
        </a>
        <small>{num_outputs} output{output_plural}</small>
    </td>
</tr>
"""
    return mark_safe(html)


@register.simple_tag(takes_context=True)
def snapshot_preview_url(context, snapshot, path: str = "", result=None) -> str:
    snapshot_id = _snapshot_id(snapshot)
    plugin = getattr(result, "plugin", "") if result else ""
    return _build_snapshot_preview_url(
        str(snapshot_id),
        path,
        request=context.get("request"),
        config=context.get("CONFIG"),
        plugin=plugin,
        base_url=_snapshot_base_url_for_context(context, snapshot) if context.get("STATIC_EXPORT") else None,
    )


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
    from archivebox.core.models import ArchiveResult

    if result is None or not isinstance(result, ArchiveResult):
        return ""

    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, "card")

    # Use embed_path() for the display path
    raw_output_path = result.embed_path() or ""
    output_url = _snapshot_url_for_context(context, result.snapshot, raw_output_path or "")

    icon_html = get_plugin_icon(plugin)
    plugin_lower = (plugin or "").lower()
    media_file_count = _count_media_files(result) if plugin_lower in ("ytdlp", "yt-dlp", "youtube-dl") else 0
    media_files = _list_media_files(result) if plugin_lower in ("ytdlp", "yt-dlp", "youtube-dl") else []
    if context.get("STATIC_EXPORT") and media_files:
        media_files = [
            item
            for item in media_files
            if (media_path := Path(str(item.get("path") or "")))
            and not media_path.is_absolute()
            and ".." not in media_path.parts
            and (Path(result.snapshot_dir) / media_path).is_file()
        ]
        media_file_count = len(media_files)
    if media_files:
        for item in media_files:
            path = item.get("path") or ""
            item["url"] = _snapshot_url_for_context(context, result.snapshot, path) if path else ""

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
    except (template.TemplateSyntaxError, AttributeError, TypeError, ValueError):
        rendered = ""

    if force_text_preview:
        preview = _render_text_file_preview(result.snapshot_dir, raw_output_path, plugin, icon_html)
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
    preview = _render_text_file_preview(snapshot.output_dir, output_path, plugin_name, icon_html)
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
    from archivebox.core.models import ArchiveResult

    if result is None or not isinstance(result, ArchiveResult):
        return ""

    plugin = get_plugin_name(result.plugin)
    template_str = get_plugin_template(plugin, "full")

    if not template_str:
        return ""

    raw_output_path = ""
    raw_output_path = result.embed_path_db() or ""
    if not raw_output_path:
        raw_output_path = result.embed_path() or ""
    if _is_root_snapshot_output_path(raw_output_path):
        return ""
    output_url = _snapshot_url_for_context(context, result.snapshot, raw_output_path)

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
    except (template.TemplateSyntaxError, AttributeError, TypeError, ValueError):
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
    user = request.user
    if not user or not user.is_authenticated:
        return ""

    token = get_or_create_api_token(user)
    return token.token if token else ""
