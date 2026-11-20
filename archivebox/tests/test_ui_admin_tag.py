"""Tag admin UI and API tests."""

import pytest
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_tag_admin_changelist_routes_search_into_native_actions(admin_client):
    response = admin_client.get(reverse("admin:core_tag_changelist"), {"q": "releasecandidate"}, HTTP_HOST=ADMIN_TEST_HOST)

    assert response.status_code == 200
    assert b'id="searchbar"' in response.content
    assert b'id="tag_list_create_input"' in response.content
    assert reverse("admin:core_tag_add").encode() not in response.content
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
    assert b'id="tag_list_create_input"' not in response.content


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


@pytest.mark.django_db(transaction=True)
def test_tag_list_inline_create_and_native_actions_in_browser(live_server, admin_user, browser_runtime):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Tag
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config.update(BASE_URL=live_server.url, SERVER_SECURITY_MODE="safe-onedomain-nojsreplay")
    machine.save(update_fields=["config"])
    Tag.objects.create(name="fixture existing")
    url = live_server.url + reverse("admin:core_tag_changelist")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        page.goto(f"{live_server.url}/admin/login/?next={reverse('admin:core_tag_changelist')}")
        page.get_by_label("Username:", exact=True).fill(admin_user.username)
        page.get_by_label("Password:", exact=True).fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        field = page.get_by_role("combobox", name="Add tag", exact=True)
        expect(field).to_be_visible()
        search = page.get_by_role("textbox", name="Search", exact=True)
        left, right = field.bounding_box(), search.bounding_box()
        assert left["x"] + left["width"] < right["x"]
        assert abs(left["y"] + left["height"] / 2 - right["y"] - right["height"] / 2) <= 3
        page.locator("#result_list tbody input.action-select").first.check()
        groups = page.locator(".tag-list-action-group")
        expect(groups).to_have_count(2)
        expect(groups.first.get_by_role("button", name="Delete Tags", exact=True)).to_be_visible()
        expect(groups.last.get_by_role("button", name="Delete Snapshots", exact=True)).to_be_visible()
        expect(groups.last.get_by_role("combobox", name="Move to folder", exact=True)).to_have_count(1)
        expect(groups.last.get_by_role("combobox", name="Re-Archive", exact=True)).to_have_count(1)
        expect(page.locator("#changelist-form .actions-tags")).to_have_count(0)
        centers = groups.evaluate_all("""groups => groups.flatMap(g =>
            [...g.children].map(el => {
                const r = el.getBoundingClientRect();
                return r.y + r.height / 2;
            }))""")
        assert max(centers) - min(centers) <= 3
        page.set_viewport_size({"width": 390, "height": 844})
        mobile_controls = page.locator(".tag-list-action-group .button").evaluate_all("""buttons =>
            buttons.map(el => {const r = el.getBoundingClientRect();return [r.left, r.right, r.height, innerWidth];})""")
        assert all(0 <= x < end <= width and height >= 44 for x, end, height, width in mobile_controls)
        field.fill("fixture")
        expect(page.locator('#tag_list_create_datalist option[value="fixture existing"]')).to_have_count(1)
        field.fill("fixture new tag")
        with page.expect_response(
            lambda response: "/api/v1/core/tags/create/" in response.url and response.request.method == "POST",
        ) as request:
            field.press("Enter")
        assert request.value.ok
        expect(page.get_by_role("link", name="fixture new tag", exact=True)).to_be_visible()
        assert page.url.startswith(url + "?q=")
        browser.close()
    assert Tag.objects.filter(name="fixture new tag").count() == 1


def test_tag_create_api_keeps_staff_permissions_and_csrf(django_user_model, admin_user):
    from django.conf import settings
    from django.contrib.auth.models import Permission
    from django.test import Client

    from archivebox.api.auth import get_or_create_api_token
    from archivebox.core.models import Tag

    url = reverse("api-1:tags_create")
    changelist = reverse("admin:core_tag_changelist")
    view_tag = Permission.objects.get(content_type__app_label="core", codename="view_tag")
    add_tag = Permission.objects.get(content_type__app_label="core", codename="add_tag")
    staff = django_user_model.objects.create_user(username="tag-creator", is_staff=True)
    staff.user_permissions.add(view_tag)
    session = Client(enforce_csrf_checks=True)
    session.force_login(staff)
    session.get(changelist, HTTP_HOST=ADMIN_TEST_HOST)
    csrf = session.cookies[settings.CSRF_COOKIE_NAME].value

    def create(name, **headers):
        return session.post(url, {"name": name}, content_type="application/json", HTTP_HOST=ADMIN_TEST_HOST, **headers)

    assert create("fixture denied", HTTP_X_CSRFTOKEN=csrf).status_code == 403
    staff.user_permissions.add(add_tag)
    assert create("fixture missing csrf").status_code == 403
    wrong = ("A" if csrf[0] != "A" else "B") + csrf[1:]
    assert create("fixture wrong csrf", HTTP_X_CSRFTOKEN=wrong).status_code == 403
    assert create("fixture scoped", HTTP_X_CSRFTOKEN=csrf).json()["created"]
    assert create("fixture scoped", HTTP_X_CSRFTOKEN=csrf).json()["created"] is False
    assert session.get(url, {"name": "fixture GET"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 405

    ordinary = django_user_model.objects.create_user(username="nonstaff-tag-creator")
    ordinary.user_permissions.add(add_tag)
    session.force_login(ordinary)
    assert create("fixture nonstaff", HTTP_X_CSRFTOKEN=csrf).status_code in {401, 403}
    session.logout()
    assert create("fixture anonymous", HTTP_X_CSRFTOKEN=csrf).status_code in {401, 403}

    assert create("fixture legacy token", HTTP_X_ARCHIVEBOX_API_KEY=get_or_create_api_token(admin_user).token).json()["created"]
    assert set(Tag.objects.filter(name__startswith="fixture").values_list("name", flat=True)) == {"fixture legacy token", "fixture scoped"}
