"""Library organization exercised through the real admin and database."""

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_nested_folders_filter_and_export(admin_client, admin_user):
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/paper", title="A paper", crawl=crawl, folder=child)
    Snapshot.objects.create(url="https://example.com/unfiled", title="Unfiled", crawl=crawl)
    response = admin_client.get("/admin/core/snapshot/", {"folder": parent.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert list(response.context["cl"].queryset.values_list("pk", flat=True)) == [snapshot.pk]
    assert b'aria-label="Folders"' in response.content
    assert b"Research" in response.content and b"Papers" in response.content
    response = admin_client.get("/admin/core/snapshot/", {"folder": child.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [folder.pk for folder in response.context["folder_breadcrumbs"]] == [parent.pk, child.pk]
    breadcrumbs = response.content.decode().split('<nav class="library-breadcrumbs"', 1)[1].split("</nav>", 1)[0]
    assert '<a href="/admin/core/snapshot/">Snapshots</a>' in breadcrumbs
    assert f'<a href="?folder={parent.pk}">Research</a>' in breadcrumbs
    assert '<span aria-current="page">Papers</span>' in breadcrumbs
    response = admin_client.get("/admin/core/snapshot/feed/", {"folder": parent.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/rss+xml")
    assert b"A paper" in response.content and b"Unfiled" not in response.content


def test_folder_cycles_rejected_and_deletion_preserves_snapshots(admin_client, admin_user):
    from django.core.exceptions import ValidationError
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    parent.parent = child
    with pytest.raises(ValidationError, match="cycle"):
        parent.save()
    parent.refresh_from_db()
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/paper", crawl=crawl, folder=child)
    child.delete()
    snapshot.refresh_from_db()
    assert snapshot.folder_id is None


def test_bulk_move_snapshots_to_folder(admin_client, admin_user):
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    folder = Folder.objects.create(name="Read later")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/paper", crawl=crawl)
    response = admin_client.post(
        "/admin/core/snapshot/",
        {
            "action": "move_to_folder",
            "folder_destination": folder.pk,
            "_selected_action": str(snapshot.pk),
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    snapshot.refresh_from_db()
    assert snapshot.folder_id == folder.pk


def test_folder_feed_requires_login(client):
    response = client.get("/admin/core/snapshot/feed/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert "/login/" in response["Location"]


def test_folder_feed_search_resolves_without_browser_cache(admin_client, admin_user):
    from xml.etree import ElementTree

    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    folder = Folder.objects.create(name="RSS research")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    matching = Snapshot.objects.create(url="https://example.com/feed-query-match", title="Matching story", crawl=crawl, folder=folder)
    Snapshot.objects.create(url="https://example.com/unrelated", title="Unrelated story", crawl=crawl, folder=folder)
    Snapshot.objects.create(url="https://example.com/feed-query-match-outside", title="Outside folder", crawl=crawl)
    response = admin_client.get(
        "/admin/core/snapshot/feed/",
        {"folder": folder.pk, "q": "feed-query-match", "search_mode": "meta"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    items = ElementTree.fromstring(response.content).findall("./channel/item")
    assert [item.findtext("title") for item in items] == [matching.title]


def test_view_only_staff_cannot_move_snapshots_to_folder(client, admin_user, django_user_model):
    from django.contrib.auth.models import Permission

    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    user = django_user_model.objects.create_user("library-viewer", password="testpassword", is_staff=True)
    user.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_snapshot"))
    folder = Folder.objects.create(name="Restricted destination")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/view-only", crawl=crawl)
    client.force_login(user)
    response = client.post(
        "/admin/core/snapshot/",
        {"action": "move_to_folder", "folder_destination": folder.pk, "_selected_action": str(snapshot.pk)},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    snapshot.refresh_from_db()
    assert snapshot.folder_id is None
    response = client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b'value="move_to_folder"' not in response.content
    response = client.post("/admin/core/folder/move/", {"folder_id": folder.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 403


def test_inline_folder_save_rejects_cycles(admin_client):
    from archivebox.core.models import Folder

    response = admin_client.post("/admin/core/folder/save/", {"name": "Research"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    parent = response.json()["id"]
    response = admin_client.post("/admin/core/folder/save/", {"name": "Papers", "parent": parent}, HTTP_HOST=ADMIN_TEST_HOST)
    child = response.json()["id"]
    response = admin_client.post(
        "/admin/core/folder/save/",
        {"folder_id": parent, "name": "Research", "parent": child},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 400 and "cycle" in response.json()["error"]
    assert Folder.objects.get(pk=parent).parent_id is None


def test_inline_folder_save_validates_normalized_name(admin_client):
    from archivebox.core.models import Folder

    response = admin_client.post("/admin/core/folder/save/", {"name": "<b></b>"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 400
    assert "name" in response.json()["error"].lower()
    assert not Folder.objects.exists()
    response = admin_client.post("/admin/core/folder/save/", {"name": "  <b>Reading list</b>  "}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.json()["name"] == "Reading list"
    assert Folder.objects.get(pk=response.json()["id"]).name == "Reading list"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("view", ["table", "grid"])
def test_browser_drag_single_and_checked_snapshots(live_server, admin_user, browser_runtime, view):
    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine
    from urllib.parse import urlsplit

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshots = [Snapshot.objects.create(url=f"https://example.com/{i}", title=f"Capture {i}", crawl=crawl) for i in range(3)]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        if view == "grid":
            page.goto(f"{admin_url}/admin/core/snapshot/grid/")
        row_selector, drag_selector = (".cards .card", ".card-title") if view == "grid" else ("#result_list tbody tr", ".field-title_str")
        source = page.locator(row_selector).filter(has_text="Capture 0")
        expect(source).to_have_attribute("draggable", "true")
        source.locator(drag_selector).drag_to(page.locator(f'.folder-row[data-folder-id="{child.pk}"]'))
        expect(page.locator(".messagelist")).to_contain_text("Moved 1 snapshot(s) to Papers")
        for snapshot in snapshots[1:]:
            page.locator(f'input.action-select[value="{snapshot.pk}"]').check()
        page.locator(row_selector).filter(has_text="Capture 1").locator(drag_selector).drag_to(
            page.locator(f'.folder-row[data-folder-id="{parent.pk}"]'),
        )
        expect(page.locator(".messagelist")).to_contain_text("Moved 2 snapshot(s) to Research")
        page.locator(".folder-new").first.click()
        page.locator("#folder-name").fill("Design inspiration")
        page.locator("#folder-parent").select_option(str(parent.pk))
        page.get_by_role("button", name="Save folder", exact=True).click()
        expect(page.locator(".folder-tree")).to_contain_text("Design inspiration")
        page.get_by_role("searchbox", name="Find a folder").fill("Design")
        expect(page.locator(f'.folder-row[data-folder-id="{child.pk}"]')).to_be_hidden()
        expect(page.locator(f'.folder-row[data-folder-id="{parent.pk}"]')).to_be_visible()
        page.get_by_role("searchbox", name="Find a folder").fill("")
        page.locator(f'.folder-row[data-folder-id="{child.pk}"] .folder-link').drag_to(page.get_by_role("link", name="All snapshots"))
        expect(page.locator(f'.folder-row[data-folder-id="{child.pk}"]')).to_have_attribute("data-parent-id", "")
        browser.close()
    for snapshot in snapshots:
        snapshot.refresh_from_db()
    assert snapshots[0].folder_id == child.pk
    assert {snapshot.folder_id for snapshot in snapshots[1:]} == {parent.pk}
    assert Folder.objects.get(name="Design inspiration").parent_id == parent.pk


def test_folder_reparent_reorder_and_cycle_protection(admin_client):
    from archivebox.core.models import Folder

    first = Folder.objects.create(name="First")
    last = Folder.objects.create(name="Last")
    child = Folder.objects.create(name="Child", parent=first)
    response = admin_client.post(
        "/admin/core/folder/move/",
        {"folder_id": last.pk, "target_id": first.pk, "placement": "before"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert list(Folder.objects.filter(parent=None).values_list("pk", flat=True)) == [last.pk, first.pk]
    response = admin_client.post("/admin/core/folder/move/", {"folder_id": first.pk, "target_id": child.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 400 and "cycle" in response.json()["error"]
    response = admin_client.post("/admin/core/folder/move/", {"folder_id": child.pk, "target_id": last.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    child.refresh_from_db()
    assert child.parent_id == last.pk


def test_folder_tree_counts_descendants_and_labels(admin_user):
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    Snapshot.objects.create(url="https://example.com/paper", folder=child, crawl=crawl)
    tree = Folder.tree()
    assert [(folder.path_label, folder.snapshot_count) for folder in tree] == [("Research", 1), ("Research / Papers", 1)]
