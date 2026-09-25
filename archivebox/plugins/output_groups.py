"""Snapshot output taxonomy. Display preference is independent of hook order."""

from typing import Any

from abx_plugins.plugins.responses.presentation import extra_snapshot_output_card

from archivebox.plugins.discovery import get_plugin_catalog, get_plugin_name, get_snapshot_thumbnail_card_order

_GROUP_LABELS = (
    ("html", "HTML"),
    ("raster", "Raster"),
    ("article_text", "Article text"),
    ("embedded_media", "Embedded media"),
    ("metadata", "Metadata"),
    ("other", "Other files"),
)


def _plugin_presentation() -> dict[str, dict[str, Any]]:
    presentation = {}
    for plugin in get_plugin_catalog().values():
        manifest = plugin.manifest
        order = manifest.get("snapshot_output_order")
        presentation[plugin.name] = {
            "group": manifest.get("snapshot_output_group") or "other",
            "order": order if isinstance(order, int) and not isinstance(order, bool) else None,
            "display_name": manifest.get("snapshot_display_name"),
            "icon_hidden": bool(manifest.get("icon_hidden")),
            "card_hidden": bool(manifest.get("card_hidden")),
        }
    return presentation


PLUGIN_PRESENTATION = _plugin_presentation()
OUTPUT_GROUPS = tuple(
    (
        group_id,
        label,
        tuple(
            name
            for name, metadata in sorted(
                PLUGIN_PRESENTATION.items(),
                key=lambda item: (item[1]["order"] is None, item[1]["order"] or 0, item[0]),
            )
            if metadata["group"] == group_id and metadata["order"] is not None
        ),
    )
    for group_id, label in _GROUP_LABELS
)
UNORDERED_OUTPUTS = {
    group_id: {name for name, metadata in PLUGIN_PRESENTATION.items() if metadata["group"] == group_id and metadata["order"] is None}
    for group_id, _label in _GROUP_LABELS
}
HIDDEN_ICON_PLUGINS = frozenset(name for name, metadata in PLUGIN_PRESENTATION.items() if metadata["icon_hidden"])
HIDDEN_CARD_PLUGINS = frozenset(name for name, metadata in PLUGIN_PRESENTATION.items() if metadata["card_hidden"])


def output_group_for_plugin(plugin: str) -> str:
    """Return the snapshot-detail stack that contains a plugin output."""
    plugin = get_plugin_name(plugin)
    for group_id, _, plugins in OUTPUT_GROUPS:
        if plugin in plugins or plugin in UNORDERED_OUTPUTS.get(group_id, set()):
            return group_id
    return "other"


def plugin_icon_is_hidden(plugin: str) -> bool:
    return get_plugin_name(plugin) in HIDDEN_ICON_PLUGINS


def plugin_card_is_hidden(plugin: str) -> bool:
    return get_plugin_name(plugin) in HIDDEN_CARD_PLUGINS


def display_plugin_name(plugin: str) -> str:
    canonical = get_plugin_name(plugin)
    return PLUGIN_PRESENTATION.get(canonical, {}).get("display_name") or plugin.replace("_", " ").replace("-", " ").title()


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


def snapshot_thumbnail_result(results):
    """Select the first available card using plugin-owned thumbnail priority."""
    card_order = get_snapshot_thumbnail_card_order()
    candidates = []
    for result in results:
        if result.plugin not in card_order:
            continue
        try:
            path = result.embed_path()
        except (TypeError, ValueError, OverflowError):
            continue
        if not path:
            continue
        candidates.append((card_order[result.plugin], str(result.id), result))
    return min(candidates, default=(None, None, None))[2]


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

    if card := extra_snapshot_output_card(outputs):
        outputs = [*outputs, card]

    def sort_key(output):
        plugin = get_plugin_name(output["name"])
        declared_group = output.get("output_group")
        declared_order = output.get("output_order")
        if declared_group in group_order and isinstance(declared_order, int) and not isinstance(declared_order, bool):
            group_id, rank = declared_group, declared_order
        else:
            group_id, rank = preferences.get(plugin, ("other", None))
        output["output_group"] = group_id
        return (group_order[group_id], rank is None, rank if rank is not None else -int(output.get("size") or 0), plugin)

    return sorted(outputs, key=sort_key)
