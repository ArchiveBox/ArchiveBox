"""Snapshot output taxonomy. Display preference is independent of hook order."""

from typing import Any

from archivebox.plugins.discovery import (
    get_extra_snapshot_output_cards,
    get_plugin_catalog,
    get_plugin_name,
    get_snapshot_thumbnail_card_order,
)

# Labels belong to the UI; plugin membership and ordering come from the catalog.
OUTPUT_GROUPS = (
    ("html", "HTML"),
    ("raster", "Raster"),
    ("article_text", "Article text"),
    ("embedded_media", "Embedded media"),
    ("metadata", "Metadata"),
    ("other", "Other files"),
)


def output_group_for_plugin(plugin: str) -> str:
    """Return the snapshot-detail stack that contains a plugin output."""
    item = get_plugin_catalog().get(get_plugin_name(plugin))
    group = item.manifest.get("snapshot_output_group", "other") if item else "other"
    return group if any(group == name for name, _ in OUTPUT_GROUPS) else "other"


def plugin_icon_is_hidden(plugin: str) -> bool:
    item = get_plugin_catalog().get(get_plugin_name(plugin))
    return bool(item and item.manifest.get("icon_hidden", False))


def plugin_card_is_hidden(plugin: str) -> bool:
    item = get_plugin_catalog().get(get_plugin_name(plugin))
    return bool(item and item.manifest.get("card_hidden", False))


def display_plugin_name(plugin: str) -> str:
    item = get_plugin_catalog().get(get_plugin_name(plugin))
    name = item.manifest.get("snapshot_display_name") if item else None
    return name or plugin.replace("_", " ").replace("-", " ").title()


def plugin_output_sizes(results) -> dict[str, int]:
    """Count a plugin's shared files once; single-result sizes need no manifest."""
    from archivebox.core.models import ArchiveResult

    by_plugin = {}
    for result in results:
        by_plugin.setdefault(result.plugin, []).append(result)
    sizes = {}
    for plugin, plugin_results in by_plugin.items():
        if len(plugin_results) == 1:
            size = plugin_results[0].output_size or 0
        else:
            files = {}
            for result in plugin_results:
                for path, metadata in result.output_file_map().items():
                    files[path] = ArchiveResult._coerce_output_file_size(metadata.get("size"))
            size = sum(files.values())
        if size:
            sizes[plugin] = size
    return sizes


def order_output_plugins(plugins, sizes: dict[str, int]) -> list[str]:
    """Use the detail-card ordering for icon piles, without synthetic cards."""
    return [output["name"] for output in order_snapshot_outputs([{"name": plugin, "size": sizes.get(plugin, 0)} for plugin in plugins])]


def snapshot_thumbnail_result(results):
    """Select the first available card using plugin-owned thumbnail priority."""
    card_order = get_snapshot_thumbnail_card_order()
    # Resolve paths in priority order and stop at the first hit: embed_path()
    # can scan a whole output manifest, and lower-priority cards never show.
    candidates = sorted(
        (result for result in results if result.plugin in card_order),
        key=lambda result: (card_order[result.plugin], str(result.id)),
    )
    for result in candidates:
        try:
            path = result.embed_path()
        except (TypeError, ValueError, OverflowError):
            continue
        if path:
            return result
    return None


def order_snapshot_outputs(outputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate and order available cards; unknown plugins stay visible in Other files."""
    group_order = {group_id: index for index, (group_id, _) in enumerate(OUTPUT_GROUPS)}
    catalog = get_plugin_catalog()

    if cards := get_extra_snapshot_output_cards(outputs):
        outputs = [*outputs, *cards]

    def sort_key(output):
        plugin = get_plugin_name(output["name"])
        declared_group = output.get("output_group")
        declared_order = output.get("output_order")
        if declared_group in group_order and isinstance(declared_order, int) and not isinstance(declared_order, bool):
            group_id, rank = declared_group, declared_order
        else:
            item = catalog.get(plugin)
            group_id = item.manifest.get("snapshot_output_group", "other") if item else "other"
            rank = item.manifest.get("snapshot_output_order") if item else None
            if group_id not in group_order:
                group_id, rank = "other", None
        output["output_group"] = group_id
        return (group_order[group_id], rank is None, rank if rank is not None else -int(output.get("size") or 0), plugin)

    return sorted(outputs, key=sort_key)
