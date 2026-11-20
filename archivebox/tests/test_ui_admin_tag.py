"""Tag admin UI and API tests."""

import pytest
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_tag_admin_changelist_routes_search_into_native_actions(admin_client):
    response = admin_client.get(reverse("admin:core_tag_changelist"), {"q": "releasecandidate"}, HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert b'id="searchbar"' in response.content
    assert b'id="changelist-form"' in response.content
    assert b'id="tag-live-search"' not in response.content
    changelist = response.context["cl"]
    assert changelist.query == "releasecandidate"
    assert changelist.list_display[0] == "action_checkbox"
    actions = changelist.model_admin.get_actions(response.wsgi_request)
    assert {"delete_selected", "delete_tagged_snapshots", "resnapshot_snapshot", "move_to_folder"} <= actions.keys()
    assert changelist.result_count == 0
    assert "releasecandidate" in str(changelist.get_queryset(response.wsgi_request).query)


def test_tag_admin_add_view_renders_similar_tag_reference(admin_client):
    response = admin_client.get(reverse("admin:core_tag_add"), HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert b"Similar Tags" in response.content
    assert b'data-tag-name-input="1"' in response.content


def test_tag_admin_reuses_snapshot_controls_without_tags(admin_client):
    from django.template.loader import render_to_string

    response = admin_client.get(reverse("admin:core_tag_changelist"), {"q": "releasecandidate"}, HTTP_HOST=ADMIN_TEST_HOST)
    controls = render_to_string("admin/actions.html", response.context_data, request=response.wsgi_request)
    assert controls.count('class="action-rearchive-select"') == 1
    assert controls.count('class="action-permissions-select"') == 1
    assert controls.count('class="action-folder-select"') == 1
    assert controls.count('name="select_across"') == 1
    assert controls.count('name="action"') == 1
    assert 'aria-label="Tag actions"' in controls
    assert 'aria-label="Snapshot actions"' in controls
    assert 'data-admin-action="delete_selected"' in controls
    assert 'data-admin-action="delete_tagged_snapshots"' in controls


def test_tagged_snapshot_actions_respect_no_matches_and_permissions(admin_client, client, django_user_model):
    from django.contrib.auth.models import Permission
    from django.contrib.messages import get_messages

    url = reverse("admin:core_tag_changelist") + "?q=releasecandidate"
    missing = "2147483647"
    for across in ("0", "1"):
        response = admin_client.post(
            url,
            {"action": "resnapshot_snapshot", "_selected_action": missing, "select_across": across, "index": "0"},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 302
        assert any("No snapshots match the selected tags" in str(message) for message in get_messages(response.wsgi_request))
    user = django_user_model.objects.create_user(username="tag-viewer", is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(codename__in=["view_tag", "view_snapshot"]))
    client.force_login(user)
    response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["cl"].model_admin.get_actions(response.wsgi_request) == {}


def test_tagged_snapshot_delete_confirmation_binds_tag_selection(admin_user, rf, snapshot):
    from django.core import signing

    from archivebox.core.admin_site import archivebox_admin
    from archivebox.core.models import Snapshot

    path = reverse("admin:core_tag_changelist") + "?q=releasecandidate"
    snapshots = Snapshot.objects.filter(pk=snapshot.pk)
    model_admin = archivebox_admin._registry[Snapshot]
    args = {"confirmation_action": "delete_tagged_snapshots", "confirmation_selected": ["123"], "confirmation_across": False}
    request = rf.post(path)
    request.user = admin_user
    confirmation = model_admin.delete_selected(request, snapshots, **args)
    assert confirmation.status_code == 200
    selection = confirmation.context_data["selection"]
    payload = signing.loads(selection, salt="archivebox.snapshot-delete-selection")
    assert payload["scope"] == path and payload["ids"] == [str(snapshot.pk)]
    assert payload["source_selection"] == {"ids": ["123"], "across": False}
    request = rf.post(path, {"post": "yes", "selection": selection})
    request.user = admin_user
    for altered in ({"confirmation_selected": ["456"]}, {"confirmation_across": True}):
        assert model_admin.delete_selected(request, snapshots, **{**args, **altered}).status_code == 400
    snapshot.refresh_from_db()
    assert snapshot.status != Snapshot.DELETING_STATE
