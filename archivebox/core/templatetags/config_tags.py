"""Template tags for accessing config values in templates."""

from typing import Any

from django import template

from archivebox.config.common import get_config

register = template.Library()


@register.simple_tag(name="get_config")
def get_config_tag(key: str) -> Any:
    """
    Get a config value by key.

    Usage: {% get_config "ARCHIVEDOTORG_ENABLED" as enabled %}
    """
    try:
        return get_config().get(key)
    except (KeyError, AttributeError):
        return None
