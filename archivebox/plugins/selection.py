"""Shared capture-plugin selection syntax for form, config and runner."""

import json

NO_CAPTURE_PLUGINS = "[]"


def parse_plugin_selection(value: object) -> list[str] | None:
    """None inherits defaults, [] explicitly selects no capture plugins."""
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        value = raw.split(",")
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                value = parsed
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    return list(dict.fromkeys(str(plugin).strip().lower() for plugin in value if str(plugin).strip()))


def format_plugin_selection(names: list[str]) -> str:
    return ",".join(names) if names else NO_CAPTURE_PLUGINS
