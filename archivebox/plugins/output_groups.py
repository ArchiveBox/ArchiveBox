"""Snapshot output taxonomy. Display preference is independent of hook order."""

from pathlib import PurePosixPath
from typing import Any

from archivebox.plugins.discovery import get_plugin_name

# Preferred outputs come first; remaining outputs sort by total output bytes.
OUTPUT_GROUPS = (
    ("html", "HTML", ("archivewebpage", "singlefile", "chrome_mhtml", "wget", "dom")),
    ("raster", "Raster", ("screenshot", "pdf")),
    ("article_text", "Article text", ("readability", "defuddle", "mercury", "trafilatura", "htmltotext")),
    ("embedded_media", "Embedded media", ("papersdl",)),
    ("metadata", "Metadata", ()),
    ("other", "Other files", ()),
)
UNORDERED_OUTPUTS = {
    "embedded_media": {"responses", "ytdlp", "yt-dlp", "youtube-dl", "gallerydl", "forumdl", "git", "media", "liteparse"},
    "metadata": {
        "dns",
        "headers",
        "seo",
        "accessibility",
        "redirects",
        "consolelog",
        "sslcerts",
        "ssl",
        "title",
        "favicon",
        "hashes",
        "chrome",
        "parse_html_urls",
        "parse_txt_urls",
        "parse_dom_outlinks",
        "parse_jsonl_urls",
        "parse_netscape_urls",
        "parse_rss_urls",
        "tlsnotary",
        "opentimestamps",
    },
}

COLOR_ICON_PLUGINS = frozenset(
    {"singlefile", "archivewebpage", "screenshot", "ytdlp", "readability", "forumdl", "papersdl", "git", "gallerydl"},
)
HIDDEN_ICON_PLUGINS = frozenset({"archivedotorg"})
PLUGIN_DISPLAY_NAMES = {
    "singlefile": "SingleFile",
    "archivewebpage": "ArchiveWebpage",
    "ytdlp": "YouTube-DL",
    "readability": "Readability",
    "forumdl": "Forum-DL",
    "git": "Git",
    "gallerydl": "Gallery-DL",
}


def output_group_for_plugin(plugin: str) -> str:
    """Return the snapshot-detail stack that contains a plugin output."""
    for group_id, _, plugins in OUTPUT_GROUPS:
        if plugin in plugins or plugin in UNORDERED_OUTPUTS.get(group_id, set()):
            return group_id
    return "other"


def display_plugin_name(plugin: str) -> str:
    return PLUGIN_DISPLAY_NAMES.get(plugin, plugin.replace("_", " ").replace("-", " ").title())


def plugin_output_sizes(results) -> dict[str, int]:
    """Count each plugin's files once, even when several hooks report them."""
    files_by_plugin: dict[str, dict[str, int]] = {}
    for result in results:
        files = files_by_plugin.setdefault(result.plugin, {})
        for path, metadata in result.output_file_map().items():
            files[path] = result._coerce_output_file_size(metadata.get("size"))
    return {plugin: sum(files.values()) for plugin, files in files_by_plugin.items() if files}


def order_output_plugins(plugins, sizes: dict[str, int]) -> list[str]:
    """Use the detail-card ordering for icon piles, without synthetic cards."""
    return [output["name"] for output in order_snapshot_outputs([{"name": plugin, "size": sizes.get(plugin, 0)} for plugin in plugins])]


def _responses_html_card(outputs: list[dict[str, Any]]) -> dict[str, Any] | None:
    # Presentation-only exception to the usual 1:1 plugin:card rule. Responses
    # owns both this HTML view and its media gallery; responses_html is only a
    # unique card/anchor ID, never a plugin or a synthetic ArchiveResult.
    # Refactor this exception if plugins gain support for multiple cards.
    for output in outputs:
        if output["name"] != "responses" or not (result := output.get("result")):
            continue
        path = str(output.get("path") or "")
        if not path.startswith("responses/") or ".." in PurePosixPath(path).parts:
            continue
        files = result.output_file_map()
        info = files.get(path) or files.get(path.removeprefix("responses/")) or {}
        mime = str(info.get("mimetype") or "").split(";")[0].lower()
        if not info or result._coerce_output_file_size(info.get("size")) <= 0:
            continue
        if mime not in {"text/html", "application/xhtml+xml"} and PurePosixPath(path).suffix.lower() not in {".html", ".htm"}:
            continue
        return {
            "name": "responses_html",
            "path": path,
            "folder_path": "responses",
            "ts": output.get("ts"),
            "size": 0,  # Bytes are already counted by the real Responses card.
            "result": None,
            "direct_preview_path": f"{path}?card=responses_html",
        }
    return None


def order_snapshot_outputs(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate and order available cards; unknown plugins stay visible in Other files."""
    group_order = {group_id: index for index, (group_id, _, _) in enumerate(OUTPUT_GROUPS)}
    preferences = {}
    for group_id, _, plugins in OUTPUT_GROUPS:
        for rank, plugin in enumerate(plugins):
            preferences[plugin] = (group_id, rank)
    for group_id, plugins in UNORDERED_OUTPUTS.items():
        for plugin in plugins:
            preferences[plugin] = (group_id, None)

    if card := _responses_html_card(outputs):
        outputs = [*outputs, card]
    preferences["responses_html"] = ("html", len(OUTPUT_GROUPS[0][2]))

    def sort_key(output):
        plugin = get_plugin_name(output["name"])
        group_id, rank = preferences.get(plugin, ("other", None))
        output["output_group"] = group_id
        return (group_order[group_id], rank is None, rank if rank is not None else -int(output.get("size") or 0), plugin)

    return sorted(outputs, key=sort_key)
