import json

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.personas.models import Persona


@pytest.mark.django_db
def test_smart_folder_relationship_choices_are_named_scoped_and_bounded(client, admin_user):
    url = reverse("admin:core_folder_rules")
    tag = Tag.objects.create(name="⭐")
    persona = Persona.objects.create(name="Work browser")
    folder = Folder.objects.create(
        name="Starred work",
        rules={
            "op": "AND",
            "rules": [
                {"field": "tags", "lookup": "in", "value": [tag.pk]},
                {"field": "crawl__persona", "lookup": "exact", "value": str(persona.pk)},
            ],
        },
    )
    assert client.get(url, {"related_field": "tags", "q": "⭐"}).status_code == 302
    client.force_login(admin_user)
    response = client.get(url, {"folder_id": str(folder.pk)})
    assert response.status_code == 200
    data = response.json()
    assert data["related_fields"]["tags"] == "core.tag"
    assert data["related_fields"]["crawl__persona"] == "personas.persona"
    assert {"id": tag.pk, "name": "⭐"} in data["related_selected"]["core.tag"]
    assert {"id": str(persona.pk), "name": "Work browser"} in data["related_selected"]["personas.persona"]
    Tag.objects.bulk_create([Tag(name=f"Fixture {i}") for i in range(25)])
    assert len(client.get(url, {"related_field": "tags", "q": "fixture"}).json()["choices"]) == 20
    for path in ("crawl__created_by__password", "archiveresult__process", "snapshottag", "api.outboundwebhook"):
        assert client.get(url, {"related_field": path}).status_code == 403
    staff = User.objects.create_user("folder-only", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_folder"))
    client.force_login(staff)
    assert client.get(url, {"related_field": "tags", "q": "⭐"}).status_code == 403
    assert client.get(url, {"related_field": "crawl__persona", "q": "Work"}).status_code == 403
    assert not client.get(url, {"folder_id": str(folder.pk)}).json()["related_selected"]


@pytest.mark.django_db
def test_nested_folder_choices_have_names_for_real_folder_viewer(client):
    folder = Folder.objects.create(name="Reading list")
    smart = Folder.objects.create(
        name="Existing rule",
        rules={"field": "crawl__folder", "lookup": "in", "value": [str(folder.pk)]},
    )
    viewer = User.objects.create_user("folder-viewer", is_staff=True)
    viewer.user_permissions.add(Permission.objects.get(codename="view_folder"))
    client.force_login(viewer)
    url = reverse("admin:core_folder_rules")
    expected = [{"id": str(folder.pk), "name": folder.name}]
    assert client.get(url, {"related_field": "crawl__folder", "q": "Reading"}).json()["choices"] == expected
    schema = client.get(url, {"folder_id": str(smart.pk)}).json()
    assert schema["related_selected"]["core.folder"] == expected
    assert schema["rules"] == smart.rules


@pytest.mark.django_db(transaction=True)
def test_smart_folder_selects_m2m_and_fk_values_by_name(browser_runtime, live_server, admin_user, snapshot):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    base = f"http://archivebox.localhost:{port}"
    admin = f"http://admin.archivebox.localhost:{port}"
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base}
    machine.save(update_fields=["config"])
    tag = Tag.objects.create(name="⭐")
    research = Tag.objects.create(name="Research")
    persona = Persona.objects.create(name="Work browser")
    snapshot.tags.set([research])
    snapshot.crawl.persona = persona
    snapshot.crawl.save(update_fields=["persona"])
    folder = Folder.objects.create(name="Fixture folder", rules={"field": "tags", "lookup": "in", "value": [tag.pk]})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{admin}/admin/login/?next=/admin/core/snapshot/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            row = page.locator(f'.folder-row[data-folder-id="{folder.pk}"]')
            row.hover()
            row.get_by_role("button", name="Actions for Fixture folder", exact=True).click()
            row.get_by_role("menuitem", name="Rename", exact=True).click()
            dialog = page.locator("#folder-dialog")
            first = dialog.locator(".rule-condition").first
            expect(first.get_by_role("button", name="Remove ⭐", exact=True)).to_be_visible()
            first.get_by_role("searchbox", name="Find an existing value").fill("research")
            choices = first.get_by_label("Choose an existing value", exact=True)
            expect(choices.get_by_role("option", name="Research", exact=True)).to_have_count(1)
            choices.select_option(label="Research")
            dialog.get_by_role("button", name="+ Rule", exact=True).click()
            second = dialog.locator(".rule-condition").last
            second.get_by_label("Field", exact=True).select_option("crawl__persona")
            second.get_by_role("searchbox", name="Find an existing value").fill("work")
            choices = second.get_by_label("Choose an existing value", exact=True)
            expect(choices.get_by_role("option", name="Work browser", exact=True)).to_have_count(1)
            choices.select_option(label="Work browser")
            expected = {
                "op": "AND",
                "rules": [
                    {"field": "tags", "lookup": "in", "value": [tag.pk, research.pk]},
                    {"field": "crawl__persona", "lookup": "exact", "value": str(persona.pk)},
                ],
            }
            assert json.loads(dialog.locator('[name="rules"]').input_value()) == expected
            dialog.get_by_role("button", name="Save folder").click()
            expect(dialog).not_to_be_visible()
        finally:
            browser.close()
    folder.refresh_from_db()
    assert folder.rules == expected
    assert list(Folder.select_snapshots(Snapshot.objects.all(), folder.pk)) == [snapshot]
