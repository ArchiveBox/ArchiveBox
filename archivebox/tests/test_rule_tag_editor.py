"""Rules reuse the shared tag widget without changing action/auth semantics."""

import json

import pytest
from django.test import Client
from django.urls import reverse

from archivebox.api.models import Rule
from archivebox.core.models import Tag
from archivebox.core.widgets import TagEditorWidget
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_rules_include_real_tag_editor_and_authenticated_suggestions(admin_client):
    assert reverse("rules:index") == "/admin/rules/"
    Tag.objects.create(name="Existing tag")
    page = admin_client.get(reverse("rules:index"), HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert page.context["webhook_editor"]["tag_editor"] == str(TagEditorWidget().render("webhook_action_tags_TOKEN", None))
    widget = page.context["webhook_editor"]["tag_editor"]
    assert "/api/v1/core/tags/autocomplete/" in widget
    assert 'list="webhook_action_tags_TOKEN_datalist"' in widget
    assert b"window.ARCHIVEBOX_API_KEY" in page.content
    assert Client().get(reverse("rules:index"), HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    suggestions = admin_client.get("/api/v1/core/tags/autocomplete/", {"q": "Existing"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert suggestions.status_code == 200
    assert "Existing tag" in [tag["name"] for tag in suggestions.json()["tags"]]
    assert list(Tag.objects.values_list("name", flat=True)) == ["Existing tag"]


def test_repeated_rule_tag_actions_preserve_csv_order_and_validation(admin_client):
    actions = [
        {"type": "add_tags", "add_tags": "Existing tag,Fresh"},
        {"type": "remove_tags", "remove_tags": "Old tag"},
        {"type": "add_tags", "add_tags": "Third"},
    ]
    payload = {
        "name": "Tagged rule",
        "ref": "archivebox.core.models.Snapshot",
        "signal": "BEFORE_CAPTURE",
        "enabled": False,
        "actions": actions,
    }
    response = admin_client.post(reverse("rules:save"), json.dumps(payload), content_type="application/json", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    hook = Rule.objects.get(pk=response.json()["hook"]["id"])
    assert hook.actions == actions
    assert not Tag.objects.exists()  # Configuring a rule does not execute its tag actions.
    payload["id"] = str(hook.pk)
    payload["actions"] = list(reversed(actions))
    response = admin_client.post(reverse("rules:save"), json.dumps(payload), content_type="application/json", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    hook.refresh_from_db()
    assert hook.actions == list(reversed(actions))
    payload["actions"] = [{"type": "add_tags", "add_tags": "x" * 101}]
    invalid = admin_client.post(reverse("rules:save"), json.dumps(payload), content_type="application/json", HTTP_HOST=ADMIN_TEST_HOST)
    assert invalid.status_code == 400
    hook.refresh_from_db()
    assert hook.actions == list(reversed(actions))
