"""Snapshot output taxonomy. Display preference is independent of hook order."""

from typing import Any

from archivebox.plugins.discovery import get_plugin_name

# Ordered tuples are preference lists; unordered groups sort by total output bytes.
OUTPUT_GROUPS = (
    ("html", "HTML", ("archivewebpage", "singlefile", "chrome_mhtml", "wget", "responses", "dom")),
    ("raster", "Raster", ("screenshot", "pdf")),
    ("article_text", "Article text", ("defuddle", "readability", "mercury", "htmltotext")),
    ("embedded_media", "Embedded media", ()),
    ("ocr", "OCR", ("trafilatura", "liteparse")),
    ("metadata", "Metadata", ()),
    ("other", "Other files", ()),
)
UNORDERED_OUTPUTS = {
    "embedded_media": {"ytdlp", "yt-dlp", "youtube-dl", "gallerydl", "forumdl", "git", "media"},
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

    def sort_key(output):
        plugin = get_plugin_name(output["name"])
        group_id, rank = preferences.get(plugin, ("other", None))
        output["output_group"] = group_id
        return (group_order[group_id], rank if rank is not None else -int(output.get("size") or 0), plugin)

    return sorted(outputs, key=sort_key)
