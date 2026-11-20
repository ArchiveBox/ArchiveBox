"""Inline tag renaming through the native admin changelist."""

import pytest
from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from archivebox.core.models import Tag
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_inline_rename_uses_existing_tag_and_native_change_permissions(admin_user, django_user_model, snapshot):
    tag = Tag.objects.create(name="Release candidate", created_by=admin_user)
    other = Tag.objects.create(name="Published & ready", created_by=admin_user)
    snapshot.tags.add(tag)
    changelist = reverse("admin:core_tag_changelist")
    rename = reverse("admin:core_tag_rename", args=[tag.pk])
    editor = django_user_model.objects.create_user(username="inline-tag-editor", is_staff=True)
    editor.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="change_tag"))
    viewer = django_user_model.objects.create_user(username="inline-tag-viewer", is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_tag"))
    client = Client(enforce_csrf_checks=True, HTTP_HOST=ADMIN_TEST_HOST)

    client.force_login(viewer)
    response = client.get(changelist)
    assert response.status_code == 200
    assert b"Release candidate" in response.content
    assert b"data-tag-rename-url" not in response.content
    csrf = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert client.post(rename, {"name": "Rejected"}, HTTP_X_CSRFTOKEN=csrf).status_code == 403

    client.force_login(editor)
    response = client.get(changelist, {"q": "Release"})
    assert response.status_code == 200
    assert b"data-tag-rename-url" in response.content
    assert rename.encode() in response.content
    assert reverse("admin:core_tag_change", args=[tag.pk]).encode() in response.content
    assert client.get(rename).status_code == 405
    assert client.post(rename, {"name": "No CSRF"}).status_code == 403
    csrf = client.cookies[settings.CSRF_COOKIE_NAME].value

    response = client.post(rename, {"name": "  Release candidate  "}, HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 200
    assert response.json()["name"] == tag.name
    assert not LogEntry.objects.filter(user=editor, object_id=str(tag.pk)).exists()

    for value in ("", "&nbsp;", "pUBlished & READY", "x" * 101):
        response = client.post(rename, {"name": value}, HTTP_X_CSRFTOKEN=csrf)
        assert response.status_code == 400
        assert response.json()["error"]

    response = client.post(rename, {"name": "  Release reviewed  "}, HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 200
    assert response.json()["name"] == "Release reviewed"
    tag.refresh_from_db()
    other.refresh_from_db()
    assert tag.name == "Release reviewed" and tag.created_by_id == admin_user.pk
    assert other.name == "Published & ready"
    assert snapshot.tags.filter(pk=tag.pk, name="Release reviewed").exists()
    assert LogEntry.objects.filter(user=editor, object_id=str(tag.pk), action_flag=CHANGE).count() == 1


@pytest.mark.django_db(transaction=True)
def test_tag_pencil_renames_in_place_without_submitting_bulk_form(admin_user, live_server, browser_runtime):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine

    tag = Tag.objects.create(name="Release candidate", created_by=admin_user)
    Tag.objects.create(name="Published", created_by=admin_user)
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    origin = f"http://admin.archivebox.localhost:{port}"
    current = origin + reverse("admin:core_tag_changelist") + "?q=Release"
    change_path = reverse("admin:core_tag_change", args=[tag.pk])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            page.goto(origin + "/admin/login/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.locator('input[type="submit"]').click()
            page.wait_for_url(origin + "/admin/")
            page.goto(current)

            rename_path = reverse("admin:core_tag_rename", args=[tag.pk])
            row = page.locator("#result_list tbody tr").filter(has=page.locator(f'[data-tag-rename-url="{rename_path}"]'))
            pencil = row.get_by_role("button", name="Rename tag Release candidate")
            checkbox = row.get_by_role("checkbox")
            checkbox.check()
            pencil.click()
            editor = row.get_by_role("textbox", name="Tag name")
            expect(editor).to_be_focused()
            editor.fill("Discard this")
            editor.press("Escape")
            expect(pencil).to_be_focused()
            expect(row.get_by_role("link", name="Release candidate")).to_have_attribute("href", change_path)

            pencil.click()
            editor.fill("published")
            editor.press("Enter")
            expect(row.get_by_role("alert")).to_contain_text("already exists")
            expect(editor).to_be_focused()
            editor.fill("Release approved")
            editor.press("Enter")
            expect(page.get_by_role("link", name="Release approved")).to_have_attribute("href", change_path)
            expect(page.get_by_role("button", name="Rename tag Release approved")).to_be_focused()
            expect(checkbox).to_be_checked()
            expect(page).to_have_url(current)
        finally:
            browser.close()

    tag.refresh_from_db()
    assert tag.name == "Release approved"
