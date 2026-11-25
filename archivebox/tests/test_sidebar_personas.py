import pytest
from django.contrib.auth.models import Permission
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from archivebox.core.sidebar_personas import persona_add_actions, persona_entries_page, persona_sidebar_allowed
from archivebox.personas.models import Persona

pytestmark = pytest.mark.django_db


def _personas_page(request, *, term="", cursor=None, limit=2):
    return persona_entries_page(request, term=term, parent="", cursor=cursor, limit=limit)


def _create_personas(owner, *names):
    return Persona.objects.bulk_create(
        [
            Persona(name=name, created_by=owner, config={"PERMISSIONS": "private", "OPENAI_API_KEY": "not-a-sidebar-field"})
            for name in names
        ],
    )


def test_persona_sidebar_queries_one_bounded_page_per_cursor(rf, admin_user):
    personas = _create_personas(admin_user, *(f"Research {number:02d}" for number in range(5)))
    request = rf.get("/")
    request.user = admin_user
    with CaptureQueriesContext(connection) as queries:
        entries, cursor = _personas_page(request, term="research")
        more, last = _personas_page(request, term="research", cursor=cursor)
        final, end = _personas_page(request, term="research", cursor=last)
    assert len(queries) == 3
    assert all("LIMIT 3" in query["sql"] and '"config"' not in query["sql"] and "OFFSET" not in query["sql"] for query in queries)
    assert [entry["id"] for entry in entries + more + final] == [str(persona.pk) for persona in personas]
    assert end is None
    assert entries[0]["actions"] == [{"label": "Edit", "url": reverse("admin:personas_persona_change", args=[personas[0].pk])}]
    assert persona_add_actions(request) == [{"label": "Add Persona", "url": reverse("admin:personas_persona_add")}]


def test_persona_sidebar_pins_off_page_selection_without_duplicates(rf, admin_user):
    personas = _create_personas(admin_user, "Research A", "Research B", "Research C", "Research D")
    request = rf.get("/", {"persona": str(personas[-1].pk)})
    request.user = admin_user
    entries, cursor = _personas_page(request)
    more, end = _personas_page(request, cursor=cursor)
    assert [entry["name"] for entry in entries] == ["Research A", "Research D"]
    assert [entry["name"] for entry in more] == ["Research B", "Research C"]
    assert end is None
    matching, _ = _personas_page(request, term="Research B")
    assert [entry["name"] for entry in matching] == ["Research B"]


def test_persona_sidebar_matches_existing_native_admin_permissions(rf, django_user_model, admin_user):
    (persona,) = _create_personas(admin_user, "Shared with authorized staff")
    staff = django_user_model.objects.create_user(username="persona-viewer", is_staff=True)
    request = rf.get("/")
    request.user = staff
    assert not persona_sidebar_allowed(request)
    assert _personas_page(request) == ([], None)
    assert persona_add_actions(request) == []

    view_persona = Permission.objects.get(content_type__app_label="personas", codename="view_persona")
    staff.user_permissions.add(view_persona)
    request.user = django_user_model.objects.get(pk=staff.pk)
    assert persona_sidebar_allowed(request)
    entries, next_key = _personas_page(request)
    assert next_key is None
    assert entries == [
        {
            "id": str(persona.pk),
            "name": persona.name,
            "scope": "persona",
            "filter_value": str(persona.pk),
            "parent_id": "",
            "has_children": False,
            "actions": [{"label": "View", "url": reverse("admin:personas_persona_change", args=[persona.pk])}],
        },
    ]
    assert persona_add_actions(request) == []

    request.user.is_staff = False
    assert not persona_sidebar_allowed(request)
    assert _personas_page(request) == ([], None)
