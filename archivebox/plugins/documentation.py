"""Links and screenshots published by the plugin gallery's existing conventions."""

import json
import re
from functools import lru_cache
from urllib.parse import quote

from archivebox.plugins.discovery import BUILTIN_PLUGINS_DIR, get_plugin_catalog

ABX_PLUGINS_DOCS_BASE_URL = "https://plugins.archivebox.io/"
SCREENSHOTS_BASE_URL = "https://archivebox.io/screenshots/"


def get_plugin_docs_url(plugin_name: str) -> str:
    return f"{ABX_PLUGINS_DOCS_BASE_URL}#{quote(plugin_name, safe='')}"


@lru_cache(maxsize=512)
def get_plugin_documentation(plugin_name: str) -> dict[str, str]:
    links = {"docs_url": "", "screenshot_url": "", "screenshot_page_url": "", "screenshot_label": ""}
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", plugin_name):
        return links
    # Collection-only plugins have no entry in the official packaged gallery.
    if not (BUILTIN_PLUGINS_DIR / plugin_name / "config.json").is_file():
        return links
    plugin = get_plugin_catalog().get(plugin_name)
    if plugin is None:
        return links
    links["docs_url"] = get_plugin_docs_url(plugin_name)
    schema = plugin.manifest
    recipe = {}
    recipe_name = schema.get("screenshot")
    if isinstance(recipe_name, str) and recipe_name:
        recipe_path = (plugin.path / recipe_name).resolve()
        if recipe_path.is_relative_to(plugin.path.resolve()):
            try:
                value = json.loads(recipe_path.read_text())
                if isinstance(value, dict):
                    recipe = value
            except (OSError, ValueError):
                pass
    templates = plugin.path / "templates"
    if not (recipe or (templates / "full.html").is_file() or ((templates / "card.html").is_file() and not schema.get("card_hidden"))):
        return links
    # Same slug and screenshot eligibility as abx-plugins/docs/generate.py.
    view = str(recipe.get("view") or f"Snapshot View ({plugin_name})")
    slug = re.sub(r"[^a-z0-9]+", "-", view.lower()).strip("-")
    if slug:
        links.update(
            screenshot_url=f"{SCREENSHOTS_BASE_URL}{slug}-desktop.png",
            screenshot_page_url=f"{SCREENSHOTS_BASE_URL}#{slug}",
            screenshot_label=view,
        )
    return links
