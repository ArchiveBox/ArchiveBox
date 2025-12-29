"""Template tags for accessing config values in templates."""

from django import template

from archivebox.config.configset import get_config as _get_config

register = template.Library()


@register.simple_tag
def get_config(key: str) -> any:
    """
    Get a config value by key.

    Usage: {% get_config "ARCHIVEDOTORG_ENABLED" as enabled %}
    """
    try:
        return _get_config(key)
    except (KeyError, AttributeError):
        return None
