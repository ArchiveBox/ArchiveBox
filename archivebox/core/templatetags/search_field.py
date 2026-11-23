import json
from django import template
from archivebox.search.language import OPERATORS

register = template.Library()


@register.inclusion_tag("search/field.html")
def search_field(value="", name="q", field_id="searchbar"):
    operators = [
        {"key": key, "icon": icon, "description": description, "aliases": ["site"] if key == "domain" else []}
        for key, (icon, description) in OPERATORS.items()
    ]
    return {"value": value or "", "name": name, "field_id": field_id, "operators": json.dumps(operators)}
