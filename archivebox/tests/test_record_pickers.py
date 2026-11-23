import pytest
from django.urls import reverse
from django.test import Client

from archivebox.core.models import Folder
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def test_folder_picker_search_is_bounded_and_respects_destination_rules(admin_client, django_user_model):
    root = Folder.objects.create(name="👩🏽‍💻 Archive")
    child = Folder.objects.create(name="🗂️ 2026", parent=root)
    smart = Folder.objects.create(name="Smart result", rules={"field": "url", "lookup": "icontains", "value": "example.com"})
    Folder.objects.bulk_create([Folder(name=f"Result {i:02}") for i in range(35)])
    endpoint = "/api/v1/core/folders/autocomplete/"
    client = Client()
    assert client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST).status_code == 401
    client.force_login(django_user_model.objects.create_user("staff-without-folder-access", is_staff=True))
    assert client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403

    def lookup(**params):
        response = admin_client.get(endpoint, params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200, response.content
        return response.json()

    first = lookup(q="result")
    assert len(first["choices"]) == 20
    next_page = lookup(q="result", after=first["next"])
    assert len({item["id"] for item in first["choices"] + next_page["choices"]}) == 36
    assert {item["id"] for item in lookup(q="smart")["choices"]} == {str(smart.pk)}
    assert not lookup(q="smart", destination="true")["choices"]
    assert {"id": str(child.pk), "name": "👩🏽‍💻 Archive / 🗂️ 2026"} in lookup(q="2026")["choices"]
    assert lookup(q="Archive / 2026")["choices"] == [{"id": str(child.pk), "name": "👩🏽‍💻 Archive / 🗂️ 2026"}]
    assert not lookup(q="2026", exclude=str(root.pk))["choices"]


def test_rules_and_add_only_render_saved_folder_options(admin_client):
    root = Folder.objects.create(name="Unused Folder")
    editor = admin_client.get(reverse("webhooks:data"), HTTP_HOST=ADMIN_TEST_HOST)
    assert editor.status_code == 200
    assert str(root.pk) not in editor.content.decode()
    response = admin_client.get("/add/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert f'value="{root.pk}"'.encode() not in response.content


def test_folder_picker_moves_snapshot_at_mobile_width(live_server, browser_runtime, admin_user, snapshot):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    parent = Folder.objects.create(name="👩🏽‍💻 Research")
    destination = Folder.objects.create(name="📚 Reading", parent=parent)
    smart = Folder.objects.create(name="Reading smart", rules={"field": "url", "lookup": "icontains", "value": "example"})
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
            page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.locator(f'input.action-select[value="{snapshot.pk}"]').check()
            picker = page.locator('.record-picker:has(select[name="folder_destination"])')
            picker.get_by_role("combobox").select_option(label="Find a folder…")
            picker.get_by_role("searchbox").fill("Reading")
            choices = picker.locator("select")
            expect(choices.locator(f'option[value="{destination.pk}"]')).to_have_text("👩🏽‍💻 Research / 📚 Reading")
            expect(choices.locator(f'option[value="{smart.pk}"]')).to_have_count(0)
            choices.select_option(str(destination.pk))
            expect(page.locator(".messagelist")).to_contain_text("Moved 1 snapshot(s) to 📚 Reading")
        finally:
            browser.close()

    snapshot.refresh_from_db()
    assert snapshot.folder_id == destination.pk
