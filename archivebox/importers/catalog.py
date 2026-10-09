"""Read declarative import capabilities without importing any provider code."""

import logging
import re
from dataclasses import dataclass

from archivebox.plugins.discovery import get_plugin_catalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImporterDefinition:
    plugin: str
    feed: str
    provider: str
    title: str
    description: str
    auth: str
    fields: dict
    timeout: int
    setup: tuple
    icon: str


def get_importers() -> dict[tuple[str, str], ImporterDefinition]:
    catalog = get_plugin_catalog()
    definitions = {}
    for plugin in catalog.values():
        declarations = plugin.manifest.get("importers")
        if not isinstance(declarations, dict) or not declarations:
            continue
        if catalog.command(plugin.name, "import") is None:
            logger.warning("Import plugin %s has no executable import command", plugin.name)
            continue
        properties = plugin.manifest.get("properties", {})
        for feed, declaration in declarations.items():
            if not isinstance(declaration, dict) or not re.fullmatch(r"[a-z0-9_]+", feed):
                continue
            fields = declaration.get("config_fields", [])
            if not isinstance(fields, list) or any(not isinstance(key, str) or not isinstance(properties.get(key), dict) for key in fields):
                logger.warning("Invalid import config_fields for %s/%s", plugin.name, feed)
                continue
            auth = declaration.get("auth", "none")
            if auth not in {"none", "optional", "persona"}:
                continue
            try:
                timeout = min(1800, max(1, int(declaration.get("timeout", 60))))
            except (ValueError, TypeError):
                logger.warning("Invalid importer timeout for %s/%s", plugin.name, feed)
                continue
            setup = declaration.get("setup", plugin.manifest.get("importers_setup", []))
            if not isinstance(setup, list):
                setup = []
            definitions[plugin.name, feed] = ImporterDefinition(
                plugin=plugin.name,
                feed=feed,
                provider=str(declaration.get("provider") or plugin.manifest.get("title") or plugin.name),
                title=str(declaration.get("title") or feed),
                description=str(declaration.get("description") or plugin.manifest.get("description") or ""),
                auth=auth,
                fields={key: properties[key] for key in fields},
                timeout=timeout,
                setup=tuple(step for step in setup if isinstance(step, dict) and isinstance(step.get("title"), str)),
                icon=str(declaration.get("icon") or plugin.manifest.get("icon") or ""),
            )
    return definitions


def get_importer(plugin: str, feed: str) -> ImporterDefinition:
    try:
        return get_importers()[plugin, feed]
    except KeyError:
        raise ValueError("This import plugin is unavailable. Install or repair the plugin to continue.") from None
