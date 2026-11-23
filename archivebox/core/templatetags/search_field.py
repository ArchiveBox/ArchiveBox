import json
from django import template
from archivebox.core.context_processors import get_static_cache_key
from archivebox.search.language import OPERATORS

register = template.Library()


@register.inclusion_tag("search/field.html", takes_context=True)
def search_field(context, value="", name="q", field_id="searchbar"):
    operators = [
        {"key": key, "icon": icon, "description": description, "aliases": ["site"] if key == "domain" else []}
        for key, (icon, description) in OPERATORS.items()
    ]
    return {
        "value": value or "",
        "name": name,
        "field_id": field_id,
        "operators": json.dumps(operators),
        "static_cache_key": context.get("STATIC_CACHE_KEY") or get_static_cache_key(),
    }
