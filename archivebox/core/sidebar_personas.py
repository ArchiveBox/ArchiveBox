"""Personas in the admin snapshot sidebar, backed by the native Persona admin."""

from django.urls import reverse

from archivebox.personas.models import Persona
from archivebox.uuid_compat import compact_uuid


def _persona_admin(request):
    from archivebox.core.admin_site import archivebox_admin

    if not archivebox_admin.has_permission(request) or not archivebox_admin.is_registered(Persona):
        return None
    return archivebox_admin.get_model_admin(Persona)


def persona_sidebar_allowed(request):
    model_admin = _persona_admin(request)
    return model_admin is not None and model_admin.has_view_or_change_permission(request)


def persona_add_actions(request):
    model_admin = _persona_admin(request)
    if model_admin is None or not model_admin.has_add_permission(request):
        return []
    return [{"label": "Add Persona", "url": reverse("admin:personas_persona_add")}]


def _selected_persona(request):
    try:
        return compact_uuid(request.GET.get("persona") or None)
    except ValueError:
        return None


def persona_entries_page(request, *, term, parent, cursor, limit):
    model_admin = _persona_admin(request)
    if parent or model_admin is None or not model_admin.has_view_or_change_permission(request):
        return [], None
    if cursor is not None and (not isinstance(cursor, list) or len(cursor) != 1 or not isinstance(cursor[0], str)):
        raise ValueError("Invalid Persona sidebar cursor")

    # Reuse the native visibility queryset, but do not read browser settings or
    # browser profile files just to render names. The name is already unique.
    personas = model_admin.get_queryset(request).only("id", "name").order_by("name")
    selected_id = _selected_persona(request) if not term and limit > 1 else None
    if term:
        personas = personas.filter(name__icontains=term)
    if cursor is not None:
        personas = personas.filter(name__gt=cursor[0])
        if selected_id:
            personas = personas.exclude(pk=selected_id)
    rows = list(personas[: limit + 1])
    next_key = [rows[limit - 1].name] if len(rows) > limit else None
    page = rows[:limit]

    if selected_id and cursor is None and all(persona.pk != selected_id for persona in page):
        if (selected := personas.filter(pk=selected_id).first()) is not None:
            # Reserve the last slot for a selected Persona outside the first
            # page. Continue after the last natural row and skip the pinned ID.
            page = page[: limit - 1]
            next_key = [page[-1].name] if page else None
            page.append(selected)

    entries = []
    for persona in page:
        persona_id = str(persona.pk)
        entries.append(
            {
                "id": persona_id,
                "name": persona.name,
                "scope": "persona",
                "filter_value": persona_id,
                "parent_id": "",
                "has_children": False,
                "delete_url": reverse("admin:personas_persona_delete", args=[persona.pk])
                if model_admin.has_delete_permission(request, persona)
                else "",
                "delete_label": "Delete Persona",
                "actions": [
                    {
                        "label": "Edit" if model_admin.has_change_permission(request, persona) else "View",
                        "url": reverse("admin:personas_persona_change", args=[persona.pk]),
                    },
                ],
            },
        )
    return entries, next_key
