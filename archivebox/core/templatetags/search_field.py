import json
from django import template
from archivebox.search.language import ALIASES, OPERATORS
from archivebox.search.fields import snapshot_plugin_choices
from archivebox.core.permissions import is_admin_user

register = template.Library()


@register.inclusion_tag("search/field.html", takes_context=True)
def search_field(context, value="", name="q", field_id="searchbar"):
    operators = [
        {
            "key": key,
            "icon": icon,
            "description": description,
            "aliases": [alias for alias, field in ALIASES.items() if field == key and alias != "tag"],
        }
        for key, (icon, description) in OPERATORS.items()
    ]
    request = context.get("request")
    # A global admin search can complete registered plugins locally, including
    # installed plugins that have yet to produce their first successful output.
    if request and is_admin_user(request) and not any(key not in {"q", "p", "page", "search_mode", "o", "sidebar"} for key in request.GET):
        next(op for op in operators if op["key"] == "plugins")["choices"] = snapshot_plugin_choices()
    return {
        "value": value or "",
        "name": name,
        "field_id": field_id,
        "operators": json.dumps(operators),
        "assets_in_head": context.get("search_field_assets_in_head"),
    }
