"""Shared library navigation uses real snapshot metadata and public permissions."""

import pytest
from django.test import Client

from archivebox.core.models import Folder, Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Machine
from archivebox.tests.conftest import ADMIN_TEST_HOST, API_TEST_HOST, WEB_TEST_HOST


@pytest.fixture
def sidebar_data(admin_user):
    Machine.from_json({"config": {"PUBLIC_INDEX": True, "SNAPSHOTS_PER_PAGE": 2}})
    folder = Folder.objects.create(name="Research")
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.co.uk/")
    pages = [
        Snapshot.objects.create(crawl=crawl, url=url, config={"PERMISSIONS": permission}, folder=folder)
        for url, permission in [
            ("https://example.co.uk/", "public"),
            ("https://news.example.co.uk/article", "public"),
            ("https://deep.news.example.co.uk/article", "public"),
            ("https://other.org/", "public"),
            ("https://secret.invalid/", "private"),
            ("https://unlisted.invalid/", "unlisted"),
        ]
    ]
    research = Tag.objects.create(name="Research & notes")
    other = Tag.objects.create(name="Other")
    secret = Tag.objects.create(name="Secret tag")
    for page in pages[:3]:
        page.tags.add(research)
    pages[3].tags.add(other)
    for page in pages[4:]:
        page.tags.add(secret)
    return pages, research, folder


@pytest.mark.django_db
def test_sidebar_modes_and_public_scope(admin_client, sidebar_data):
    from archivebox.tests.test_snapshot_exports import exported_ids

    pages, tag, _folder = sidebar_data
    client = Client()
    for browser, host, path, public in [
        (admin_client, ADMIN_TEST_HOST, "/admin/core/snapshot/", False),
        (client, WEB_TEST_HOST, "/public/", True),
    ]:
        response = browser.get(path, {"sidebar": "tags"}, HTTP_HOST=host)
        assert response.status_code == 200
        assert response.context["sidebar_mode"] == "tags"
        names = {entry["name"] for entry in response.context["sidebar_entries"]}
        assert names == ({"Research & notes", "Other"} if public else {"Research & notes", "Other", "Secret tag"})
        response = browser.get(path, {"sidebar": "domains"}, HTTP_HOST=host)
        assert response.status_code == 200
        names = {entry["name"] for entry in response.context["sidebar_entries"]}
        assert names == ({"example.co.uk", "other.org"} if public else {"example.co.uk", "other.org", "secret.invalid", "unlisted.invalid"})
        for params in [{"sidebar": "tags", "tag": tag.pk}, {"sidebar": "domains", "domain": "*.example.co.uk"}]:
            response = browser.get(path, params, HTTP_HOST=host)
            assert response.status_code == 200
            if public:
                ids = {obj.pk for obj in response.context["object_list"]}
                second = browser.get(path, {**params, "page": 2}, HTTP_HOST=host)
                ids.update(obj.pk for obj in second.context["object_list"])
            else:
                ids = set(response.context["cl"].queryset.values_list("pk", flat=True))
            assert ids == {page.pk for page in pages[:3]}
            export_path = "/api/v1/core/snapshots/export/csv" if public else "/admin/core/snapshot/export.csv"
            exported = browser.get(export_path, params, HTTP_HOST=API_TEST_HOST if public else host)
            assert exported.status_code == 200
            assert exported_ids(exported, "csv") == {str(page.pk) for page in pages[:3]}
        if public:
            html = response.content.decode()
            assert "data-move-url=" not in html
            assert 'class="folder-new' not in html
            assert 'class="folder-edit' not in html
    Folder.objects.all().delete()
    response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert b'id="folder-sidebar"' in response.content


@pytest.mark.django_db(transaction=True)
def test_sidebar_modes_in_browser(live_server, admin_user, browser_runtime, tmp_path):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}",
        "PUBLIC_INDEX": True,
        "SNAPSHOTS_PER_PAGE": 50,
    }
    machine.save(update_fields=["config"])
    Folder.objects.get_or_create(name="📥 Inbox")
    research = Folder.objects.create(name="Research")
    folders = {
        "Web archiving": Folder.objects.create(name="Web archiving", parent=research),
        "Python & Django": Folder.objects.create(name="Python & Django", parent=research),
        "Self-hosting": Folder.objects.create(name="Self-hosting"),
        "Read later": Folder.objects.create(name="Read later"),
    }
    Tag.objects.bulk_create([Tag(name=f"z-scroll-{index:03}") for index in range(120)])
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://archivebox.io/")
    records = [
        ("https://archivebox.io/", "ArchiveBox — Open source web archiving", "Web archiving", ["archiving", "self-hosted"]),
        ("https://docs.archivebox.io/", "ArchiveBox documentation", "Web archiving", ["archiving", "documentation"]),
        ("https://github.com/ArchiveBox/ArchiveBox", "ArchiveBox / ArchiveBox", "Web archiving", ["archiving", "open-source"]),
        ("https://developer.mozilla.org/en-US/docs/Web/API", "Web APIs | MDN", "Read later", ["documentation", "web-platform"]),
        ("https://www.djangoproject.com/", "Django: The web framework for perfectionists", "Python & Django", ["python", "web-platform"]),
        ("https://docs.djangoproject.com/en/5.2/", "Django documentation", "Python & Django", ["python", "documentation"]),
        ("https://docs.python.org/3/library/asyncio.html", "asyncio — Asynchronous I/O", "Python & Django", ["python", "read-later"]),
        ("https://www.python.org/", "Welcome to Python.org", "Python & Django", ["python", "open-source"]),
        ("https://www.home-assistant.io/", "Home Assistant", "Self-hosting", ["self-hosted", "home-lab"]),
        ("https://www.truenas.com/docs/", "TrueNAS documentation", "Self-hosting", ["home-lab", "documentation"]),
        ("https://en.wikipedia.org/wiki/Web_archiving", "Web archiving — Wikipedia", "Read later", ["archiving", "read-later"]),
    ]
    for url, title, folder, names in records:
        snapshot = Snapshot.objects.create(crawl=crawl, url=url, title=title, folder=folders[folder], config={"PERMISSIONS": "public"})
        snapshot.tags.set([Tag.objects.get_or_create(name=name)[0] for name in names])
    empty = Tag.objects.create(name="unused-tag")
    secret = Snapshot.objects.create(crawl=crawl, url="https://private.invalid/", config={"PERMISSIONS": "private"})
    secret.tags.add(Tag.objects.create(name="private-only"))
    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    evidence = tmp_path
    python_tag_id = Tag.objects.get(name="python").pk
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{origin}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        sidebar = page.locator(".folder-sidebar")
        expect(sidebar).to_be_visible()
        expect(sidebar.get_by_role("link", name="All folders", exact=True)).to_be_visible()
        sidebar.get_by_role("button", name="Expand Research", exact=True).click()
        expect(sidebar.get_by_role("link", name="Web archiving", exact=True)).to_be_visible()

        def choose(label):
            sidebar.get_by_role("button", name="Choose sidebar view").click()
            page.locator("#library-mode-menu").get_by_role("menuitem", name=label, exact=True).click()
            expect(page.locator("#result_list tbody tr")).to_have_count(12)

        page.screenshot(path=str(evidence / "all-snapshots.png"))
        sidebar.get_by_role("button", name="Choose sidebar view").click()
        page.screenshot(path=str(evidence / "view-menu.png"))
        page.keyboard.press("Escape")
        sidebar.get_by_role("link", name="Web archiving", exact=True).click()
        expect(page.locator("#result_list tbody tr")).to_have_count(3)
        choose("Tags")
        expect(sidebar.locator(".library-entry")).to_have_count(100)
        sidebar.get_by_role("button", name="Find a tag", exact=True).click()
        sidebar.get_by_role("searchbox", name="Find a tag").fill("python")
        expect(sidebar.locator(".library-entry:visible")).to_have_count(1)
        expect(page.locator("#result_list tbody tr")).to_have_count(12)
        page.keyboard.press("Escape")
        page.screenshot(path=str(evidence / "tags.png"))
        sidebar.get_by_role("link", name="python", exact=True).click()
        expect(page.locator("#result_list tbody tr")).to_have_count(4)
        choose("Tags")
        sidebar.get_by_role("link", name="python", exact=True).hover()
        sidebar.get_by_role("button", name="Actions for python", exact=True).click()
        menu = page.locator(".folder-menu:popover-open")
        expect(menu.get_by_role("menuitem", name="Rename", exact=True)).to_be_visible()
        expect(menu.get_by_role("menuitem", name="Delete snapshots", exact=True)).to_be_visible()
        assert menu.locator(".library-delete:visible").all_text_contents() == ["Delete tag", "Delete snapshots"]
        tag_delete = menu.get_by_role("menuitem", name="Delete tag", exact=True)
        assert tag_delete.get_attribute("href") == f"/admin/core/tag/{python_tag_id}/delete/"
        assert "tag=" in menu.get_by_role("menuitem", name="CSV", exact=True).get_attribute("href")
        page.screenshot(path=str(evidence / "tag-actions.png"))
        page.keyboard.press("Escape")
        page.goto(f"{origin}/admin/core/snapshot/?sidebar=domains")
        expect(sidebar.locator(".library-entry")).to_have_count(9)
        sidebar.get_by_role("button", name="Find a domain", exact=True).click()
        sidebar.get_by_role("searchbox", name="Find a domain").fill("django")
        expect(sidebar.locator(".library-entry:visible")).to_have_count(1)
        page.keyboard.press("Escape")
        page.screenshot(path=str(evidence / "domains.png"))
        sidebar.get_by_role("link", name="djangoproject.com", exact=True).hover()
        sidebar.get_by_role("button", name="Actions for djangoproject.com", exact=True).click()
        menu = page.locator(".folder-menu:popover-open")
        expect(menu.get_by_role("menuitem", name="Rename", exact=True)).to_have_count(0)
        expect(menu.get_by_role("menuitem", name="Merge...", exact=True)).to_have_count(0)
        expect(menu.get_by_role("menuitem", name="Delete tag", exact=True)).to_have_count(0)
        page.screenshot(path=str(evidence / "domain-actions.png"))
        menu.get_by_role("menuitem", name="Delete snapshots", exact=True).click()
        expect(page.get_by_role("main", name="Confirm snapshot deletion")).to_be_visible()
        expect(page.get_by_text("Queue exactly 2 selected snapshots for deletion?", exact=False)).to_be_visible()
        page.goto(f"{origin}/admin/core/snapshot/?sidebar=domains&domain=*.djangoproject.com")
        expect(page.locator("#result_list tbody tr")).to_have_count(2)
        choose("All folders")
        expect(sidebar.locator(".folder-row")).to_have_count(4)  # Root folders only; children load on expansion.
        public = browser.new_page(viewport={"width": 1440, "height": 1000})
        public_origin = live_server.url.replace("localhost", "web.archivebox.localhost")
        for mode in ("folders", "tags", "domains"):
            public.goto(f"{public_origin}/public/?sidebar={mode}")
            public_sidebar = public.locator(".folder-sidebar")
            expect(public_sidebar).to_be_visible()
            expect(public_sidebar.get_by_text("private-only", exact=True)).to_have_count(0)
            expect(public_sidebar.get_by_text("private.invalid", exact=True)).to_have_count(0)
            expect(public_sidebar.locator(".folder-new,.folder-edit,.library-delete,.library-add,[data-sidebar-tag-merge]")).to_have_count(
                0,
            )
            expect(public_sidebar.locator("[draggable=true]")).to_have_count(0)
            public.screenshot(path=str(evidence / f"public-{mode}.png"))
        public.locator(".folder-sidebar").get_by_role("link", name="djangoproject.com", exact=True).click()
        expect(public.locator("#table-bookmarks tbody tr")).to_have_count(2)
        page.goto(f"{origin}/admin/core/snapshot/?sidebar=tags")
        sidebar.get_by_role("button", name="Add tag", exact=True).click()
        new_tag = sidebar.get_by_role("textbox", name="New tag name")
        new_tag.fill("cancelled-tag")
        new_tag.press("Escape")
        expect(new_tag).to_be_hidden()
        sidebar.get_by_role("button", name="Add tag", exact=True).click()
        new_tag.fill("new-sidebar-tag")
        new_tag.press("Enter")
        expect(sidebar.get_by_role("link", name="new-sidebar-tag", exact=True)).to_be_visible()
        expect(new_tag).to_be_hidden()
        expect(page).to_have_url(f"{origin}/admin/core/snapshot/?sidebar=tags")
        page.goto(f"{origin}/admin/core/snapshot/?sidebar=domains")
        sidebar.get_by_role("link", name="Add domain", exact=True).click()
        expect(page).to_have_url(f"{origin}/admin/domains/")
        page.get_by_role("link", name="Delete snapshots for djangoproject.com").click()
        expect(page.get_by_role("main", name="Confirm snapshot deletion")).to_be_visible()
        expect(page.get_by_text("Queue exactly 2 selected snapshots for deletion?", exact=False)).to_be_visible()
        page.goto(f"{origin}/admin/core/snapshot/?sidebar=tags")
        sidebar.get_by_role("link", name="unused-tag", exact=True).hover()
        sidebar.get_by_role("button", name="Actions for unused-tag", exact=True).click()
        menu = page.locator(".folder-menu:popover-open")
        expect(menu.get_by_role("menuitem", name="Delete tag", exact=True)).to_be_visible()
        expect(menu.get_by_role("menuitem", name="Delete snapshots", exact=True)).to_have_count(0)
        menu.get_by_role("menuitem", name="Rename", exact=True).click()
        page.locator("#id_name").fill("python-notes")
        page.locator('button[name="_continue"]').click()
        expect(page.locator(".messagelist")).to_contain_text("successfully")
        page.goto(f"{origin}/admin/core/snapshot/?sidebar=tags")
        sidebar.get_by_role("link", name="python", exact=True).hover()
        sidebar.get_by_role("button", name="Actions for python", exact=True).click()
        page.locator(".folder-menu:popover-open").get_by_role("menuitem", name="Merge...", exact=True).click()
        expect(page.locator("#tag-merge-dialog")).to_be_visible()
        page.locator("#tag-merge-target").select_option(str(empty.pk))
        page.get_by_role("button", name="Merge Tags", exact=True).click()
        expect(page.locator("#tag-merge-dialog")).not_to_be_visible()
        page.goto(f"{origin}/admin/core/snapshot/?sidebar=tags")
        expect(sidebar.get_by_role("link", name="Domains", exact=True)).to_have_count(0)
        tree = sidebar.locator(".folder-tree")
        footer = sidebar.locator(".folder-actions")
        expect(footer.get_by_role("button", name="Export")).to_be_in_viewport()
        expect(footer.get_by_role("button", name="Import")).to_be_in_viewport()
        before = footer.bounding_box()
        pane = sidebar.bounding_box()
        assert before is not None and pane is not None
        assert abs((before["y"] + before["height"]) - (pane["y"] + pane["height"])) <= 1
        tree.evaluate("tree => tree.scrollTop = tree.scrollHeight")
        expect(sidebar.get_by_role("link", name="z-scroll-119", exact=True)).to_have_count(1)
        after = footer.bounding_box()
        assert after is not None and abs(after["y"] - before["y"]) <= 1
        assert tree.evaluate("tree => tree.scrollTop") > 0
        page.set_viewport_size({"width": 400, "height": 800})
        list_exports = page.locator(".snapshot-list-exports").get_by_role("button", name="Export")
        expect(footer).to_be_hidden()
        expect(list_exports).to_be_visible()
        sidebar.get_by_role("button", name="Show tags", exact=True).click()
        expect(footer.get_by_role("button", name="Export")).to_be_in_viewport()
        expect(footer.get_by_role("button", name="Import")).to_be_in_viewport()
        expect(list_exports).to_be_hidden()
        assert errors == []
        browser.close()
    assert Tag.objects.filter(name="new-sidebar-tag").exists()
    assert not Tag.objects.filter(name="cancelled-tag").exists()
    assert not Tag.objects.filter(name="python").exists()
    assert Tag.objects.get(pk=empty.pk).name == "python-notes"
    assert Tag.objects.get(pk=empty.pk).snapshot_set.count() == 4
    assert Snapshot.objects.count() == 12  # Opening confirmation does not delete.
    assert set(Snapshot.objects.values_list("status", flat=True)) == {Snapshot.StatusChoices.QUEUED}
