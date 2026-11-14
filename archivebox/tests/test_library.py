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
    html = response.content.decode()
    assert 'class="library-breadcrumbs"' not in html
    assert 'class="library-context"' not in html
    assert '<span class="folder-current">Papers</span>' in html
    assert 'aria-label="Add folder in Research"' not in html
    assert "Add subfolder" in html
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
    assert list(Folder.objects.values_list("name", "rules")) == [
        ("📥 Inbox", {"op": "NOT", "rules": [{"field": "folder", "lookup": "in_folder", "value": "*"}]}),
    ]
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
        page.locator(f'.folder-row[data-folder-id="{parent.pk}"]').hover()
        page.get_by_role("button", name="Actions for Research", exact=True).click()
        menu = page.locator(f"#folder-menu-{parent.pk}")
        expect(menu).to_be_visible()
        expect(menu.get_by_role("menuitem", name="Rename", exact=True)).to_be_focused()
        page.keyboard.press("Escape")
        expect(menu).to_be_hidden()
        page.get_by_role("button", name="Actions for Research", exact=True).click()
        menu.get_by_role("menuitem", name="Rename", exact=True).click()
        expect(page.locator("#folder-name")).to_have_value("Research")
        page.locator(".folder-dialog-close").first.click()
        page.get_by_role("button", name="Actions for Research", exact=True).click()
        menu.get_by_role("menuitem", name="Add subfolder", exact=True).click()
        expect(page.locator("#folder-parent")).to_have_value(str(parent.pk))
        page.locator("#folder-name").fill("Design inspiration")
        page.get_by_role("button", name="Save folder", exact=True).click()
        expect(page.locator(".folder-tree")).to_contain_text("Design inspiration")
        page.get_by_role("button", name="Find a folder", exact=True).click()
        page.get_by_role("searchbox", name="Find a folder").fill("Design")
        expect(page.locator(f'.folder-row[data-folder-id="{child.pk}"]')).to_be_hidden()
        expect(page.locator(f'.folder-row[data-folder-id="{parent.pk}"]')).to_be_visible()
        page.get_by_role("searchbox", name="Find a folder").fill("")
        page.keyboard.press("Escape")
        page.locator(f'.folder-row[data-folder-id="{child.pk}"] .folder-link').drag_to(page.get_by_role("link", name="All Snapshots"))
        expect(page.locator(f'.folder-row[data-folder-id="{child.pk}"]')).to_have_attribute("data-parent-id", "")
        page.locator(f'.folder-row[data-folder-id="{parent.pk}"]').hover()
        page.get_by_role("button", name="Actions for Research", exact=True).click()
        menu.get_by_role("menuitem", name="Delete snapshots", exact=True).click()
        expect(page.locator('input[name="post"][value="yes"]')).to_have_count(1)
        expect(page.locator(".cancel-link")).to_be_visible()
        assert set(page.locator('input[name="_selected_action"]').evaluate_all("nodes => nodes.map(node => node.value)")) == {
            str(snapshot.pk) for snapshot in snapshots[1:]
        }
        page.locator(".cancel-link").click()
        expect(page.locator("#changelist-form")).to_be_visible()
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
    assert list(Folder.objects.filter(parent=None).values_list("pk", flat=True)) == [
        last.pk,
        first.pk,
        Folder.objects.get(name="📥 Inbox").pk,
    ]
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
    assert [(folder.path_label, folder.snapshot_count) for folder in tree] == [
        ("Research", 1),
        ("Research / Papers", 1),
        ("📥 Inbox", None),
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("view", ["table", "grid"])
def test_browser_folder_reordering_and_nesting(live_server, admin_user, browser_runtime, view):
    import re
    from concurrent.futures import ThreadPoolExecutor

    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import Folder
    from archivebox.machine.models import Machine
    from urllib.parse import urlsplit

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    first = Folder.objects.create(name="First", position=1)
    second = Folder.objects.create(name="Second", position=2)
    smart = Folder.objects.create(name="Smart", position=3, rules={"field": "url", "lookup": "icontains", "value": "news"})
    child = Folder.objects.create(name="Child", parent=first, position=0)
    sibling = Folder.objects.create(name="Sibling", parent=first, position=1)
    inbox = Folder.objects.filter(name="📥 Inbox").first()
    roots = [inbox] if inbox else []
    with ThreadPoolExecutor(max_workers=1) as db, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        if view == "grid":
            page.goto(f"{admin_url}/admin/core/snapshot/grid/")

        def row(folder):
            return page.locator(f'.folder-row[data-folder-id="{folder.pk}"]')

        def drag(source, target, placement):
            box = row(target).bounding_box()
            y = {"before": 2, "inside": box["height"] / 2, "after": box["height"] - 2}[placement]
            with page.expect_navigation():
                row(source).locator(".folder-link").drag_to(row(target), target_position={"x": 80, "y": y})
            expect(row(source)).to_have_attribute(
                "data-parent-id",
                db.submit(lambda: str(Folder.objects.get(pk=source.pk).parent_id or "")).result(),
            )

        def order(parent, expected):
            assert db.submit(lambda: list(Folder.objects.filter(parent=parent).values_list("pk", flat=True))).result() == [
                f.pk for f in expected
            ]
            expect(
                page.locator(f'.folder-row[data-parent-id="{parent.pk if parent else ""}"] .folder-link>span:not(.folder-title-emoji)'),
            ).to_have_text(
                [f.name.removeprefix("📥 ") for f in expected],
            )

        drag(smart, first, "before")
        order(None, roots + [smart, first, second])
        drag(smart, second, "after")
        order(None, roots + [first, second, smart])
        drag(sibling, child, "before")
        order(first, [sibling, child])
        drag(sibling, child, "after")
        order(first, [child, sibling])
        drag(second, child, "inside")
        order(child, [second])
        drag(smart, second, "before")
        order(child, [smart, second])
        drag(smart, first, "after")
        order(None, roots + [first, smart])
        with page.expect_navigation():
            row(second).locator(".folder-link").drag_to(page.get_by_role("link", name="All Snapshots", exact=True))
        order(None, roots + [first, smart, second])
        drag(smart, child, "inside")
        order(child, [smart])
        drag(second, smart, "inside")
        assert db.submit(lambda: Folder.objects.get(parent=smart, name="Items").rules).result() == smart.rules
        with page.expect_navigation():
            row(smart).locator(".folder-link").drag_to(page.get_by_role("link", name="All Snapshots", exact=True))
        expect(row(second)).to_have_attribute("data-parent-id", str(smart.pk))
        with page.expect_navigation():
            row(second).locator(".folder-link").drag_to(page.get_by_role("link", name="All Snapshots", exact=True))
        row(first).locator(".folder-toggle").click()
        expect(row(child)).to_be_hidden()
        source = row(second).locator(".folder-link").bounding_box()
        target = row(first).bounding_box()
        page.mouse.move(source["x"] + 45, source["y"] + source["height"] / 2)
        page.mouse.down()
        page.mouse.move(target["x"] + 80, target["y"] + target["height"] / 2, steps=12)
        page.mouse.move(target["x"] + 81, target["y"] + target["height"] / 2)
        expect(row(first)).to_have_class(re.compile("drop-active"))
        expect(row(child)).to_be_visible()
        with page.expect_navigation():
            page.mouse.up()
        order(first, [child, sibling, second])
        expect(row(second)).to_be_visible()
        expect(row(child)).to_be_visible()
        # The UI must reject a parent dropped into its own subtree, without a request.
        invalid_moves = []
        page.on("request", lambda request: invalid_moves.append(request.url) if request.url.endswith("/folder/move/") else None)
        source = row(first).locator(".folder-link").bounding_box()
        target = row(child).bounding_box()
        page.mouse.move(source["x"] + 45, source["y"] + source["height"] / 2)
        page.mouse.down()
        page.mouse.move(target["x"] + 80, target["y"] + target["height"] / 2, steps=12)
        page.mouse.move(target["x"] + 81, target["y"] + target["height"] / 2)
        expect(row(child)).not_to_have_class(re.compile("drop-active"))
        page.mouse.up()
        expect(page.locator(".folder-drop-status")).to_be_empty()
        assert invalid_moves == []
        browser.close()
