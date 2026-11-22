"""Sidebar work stays bounded by navigation entries, not per-entry menus/queries."""

from time import perf_counter

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Snapshot, SnapshotTag, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["tags", "domains"])
def test_large_sidebar_shares_one_action_menu(admin_client, admin_user, mode):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    tags = Tag.objects.bulk_create([Tag(name=f"Research topic {i:04}") for i in range(1000)])
    snapshots = Snapshot.objects.bulk_create(
        [Snapshot(crawl=crawl, url=f"https://research{i:04}.com/", timestamp=str(1900500000 + i)) for i in range(1000)],
    )
    SnapshotTag.objects.bulk_create([SnapshotTag(snapshot=snapshot, tag=tag) for snapshot, tag in zip(snapshots, tags, strict=True)])
    start = perf_counter()
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/core/snapshot/", {"sidebar": mode}, HTTP_HOST=ADMIN_TEST_HOST)
    elapsed = (perf_counter() - start) * 1000
    assert response.status_code == 200
    assert len(response.context["sidebar_entries"]) == 100
    html = response.content.decode()
    print(f"{mode}: {elapsed:.1f} ms, {len(queries)} queries, {len(html):,} bytes")
    assert html.count('id="library-entry-menu"') == 1
    assert len(queries) < 50


@pytest.mark.django_db
def test_sidebar_cursors_search_and_parent_order(admin_client, admin_user):
    from archivebox.core.models import Folder
    from archivebox.core.smart_folders import CHILDREN_RULES
    import re

    parent = Folder.objects.create(name="Parent", rules=CHILDREN_RULES)
    Folder.objects.bulk_create([Folder(name=f"Child {i:03}", parent=parent) for i in range(205)])
    Tag.objects.bulk_create([Tag(name=f"Topic {i:03}") for i in range(205)])
    path = "/admin/core/snapshot/sidebar/"

    def fetch(**params):
        response = admin_client.get(path, params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        return response.json()

    first = fetch(sidebar="tags")
    second = fetch(sidebar="tags", cursor=first["next"])
    third = fetch(sidebar="tags", cursor=second["next"])
    assert [len(page["choices"]) for page in (first, second, third)] == [100, 100, 5]
    assert len({tag["id"] for page in (first, second, third) for tag in page["choices"]}) == 205
    assert third["next"] == ""
    assert fetch(sidebar="tags", sidebar_q="204")["choices"][0]["name"] == "Topic 204"
    assert (
        admin_client.get(path, {"sidebar": "tags", "sidebar_q": "changed", "cursor": first["next"]}, HTTP_HOST=ADMIN_TEST_HOST).status_code
        == 400
    )
    roots = fetch(sidebar="folders")
    assert "Parent" in roots["html"] and "Child" not in roots["html"]
    children = fetch(sidebar="folders", parent=str(parent.pk))
    assert len(re.findall('class="folder-row ', children["html"])) == 100
    assert children["next"]
    result = fetch(sidebar="folders", sidebar_q="Child 204")["html"]
    assert result.index('data-folder-name="Parent"') < result.index('data-folder-name="Child 204"')


@pytest.mark.django_db(transaction=True)
def test_sidebar_search_replaces_lazy_pages(live_server, admin_user, browser_runtime):
    from urllib.parse import parse_qs, urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Folder
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    folders = Folder.objects.bulk_create([Folder(name=f"Field notes {i:03}") for i in range(105)])
    Folder.objects.create(name="Coastal survey", parent=folders[-1])
    Folder.objects.create(name="Field notes continuation", parent=folders[0], position=1)
    Tag.objects.bulk_create([Tag(name=f"Field notes {i:03}") for i in range(105)])
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://fieldnotes104.org/")
    Snapshot.objects.bulk_create(
        [Snapshot(crawl=crawl, url=f"https://fieldnotes{i:03}.org/", timestamp=str(1910000000 + i)) for i in range(105)],
    )

    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{origin}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        sidebar = page.locator(".folder-sidebar")
        tree = sidebar.locator(".folder-tree")
        empty = sidebar.locator(".folder-search-empty")

        def search(box, term):
            box.evaluate("""box => box.addEventListener('input', () => {
              const sidebar = box.closest('nav');
              box.dataset.pendingState = ['.folder-search-empty', '.library-load-status', '.library-load-more']
                .map(selector => sidebar.querySelector(selector).hidden).join(',');
            }, {once: true})""")
            with page.expect_response(
                lambda response: (
                    urlsplit(response.url).path.endswith("/snapshot/sidebar/")
                    and parse_qs(urlsplit(response.url).query).get("sidebar_q") == [term]
                ),
            ) as reply:
                box.fill(term)
            assert reply.value.status == 200
            assert box.get_attribute("data-pending-state") == "true,false,true"

        for mode, noun, term, match, common, last in [
            ("folders", "folder", "coastal", "Coastal survey", "Field notes", "Field notes 104"),
            ("tags", "tag", "104", "Field notes 104", "Field notes", "Field notes 104"),
            ("domains", "domain", "104", "fieldnotes104.org", "fieldnotes", "fieldnotes104.org"),
        ]:
            page.goto(f"{origin}/admin/core/snapshot/?sidebar={mode}")
            expect(sidebar.get_by_role("link", name=match, exact=True)).to_have_count(0)
            sidebar.get_by_role("button", name=f"Find a {noun}", exact=True).click()
            box = sidebar.get_by_role("searchbox", name=f"Find a {noun}")
            search(box, term)
            expect(sidebar.get_by_role("link", name=match, exact=True)).to_be_visible()
            expect(empty).to_be_hidden()
            if mode == "folders":
                expect(tree.locator(".folder-row").nth(0)).to_have_attribute("data-folder-name", "Field notes 104")
                expect(tree.locator(".folder-row").nth(1)).to_have_attribute("data-folder-name", "Coastal survey")

            search(box, common)
            expect(tree.locator(".library-load-more")).to_be_visible()
            tree.evaluate("tree => tree.scrollTop = tree.scrollHeight")
            expect(sidebar.get_by_role("link", name=last, exact=True)).to_be_visible()
            if mode == "folders":
                expect(tree.locator(".folder-row").nth(0)).to_have_attribute("data-folder-name", "Field notes 000")
                expect(tree.locator(".folder-row").nth(1)).to_have_attribute("data-folder-name", "Field notes continuation")
            search(box, "no matching records")
            expect(empty).to_be_visible()
            expect(sidebar.locator(".folder-empty")).to_have_count(0)
            expect(sidebar.locator(".library-load-status")).to_be_hidden()
        browser.close()


@pytest.mark.django_db
def test_domains_page_paginates_grouped_snapshots(admin_client, admin_user):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    Snapshot.objects.bulk_create(
        [Snapshot(crawl=crawl, url=f"https://site{i:03}.com/", timestamp=str(1910000000 + i)) for i in range(105)],
    )

    def fetch(**params):
        response = admin_client.get("/admin/domains/", params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        return response.context["domains"]

    first = fetch()
    assert [row["domain"] for row in first] == [f"site{i:03}.com" for i in range(50)]
    assert first.has_next()
    second = fetch(page=first.next_page_number())
    assert [row["domain"] for row in second] == [f"site{i:03}.com" for i in range(50, 100)]
    assert list(fetch(page=second.previous_page_number())) == list(first)
    assert [row["domain"] for row in fetch(q="104")] == ["site104.com"]
