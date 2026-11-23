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
    assert len(response.context["sidebar_entries"]) == (50 if mode == "domains" else 100)
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
def test_folder_expansion_survives_refresh_and_rename(live_server, admin_user, browser_runtime):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Folder
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    root = Folder.objects.create(name="Research")
    branch = Folder.objects.create(name="Archives", parent=root)
    Folder.objects.create(name="Field notes", parent=branch)

    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{origin}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        tree = page.locator(".folder-tree")
        leaf = tree.get_by_role("link", name="Field notes", exact=True)
        tree.get_by_role("button", name="Expand Research", exact=True).click()
        tree.get_by_role("button", name="Expand Archives", exact=True).click()
        expect(leaf).to_be_visible()

        page.reload()
        expect(leaf).to_be_visible()

        row = tree.locator(f'.folder-row[data-folder-id="{root.pk}"]')
        row.hover()
        row.get_by_role("button", name="Actions for Research", exact=True).click()
        row.get_by_role("menuitem", name="Rename", exact=True).click()
        page.locator("#folder-name").fill("Research notes")
        page.get_by_role("button", name="Save folder", exact=True).click()
        expect(row.get_by_role("button", name="Collapse Research notes", exact=True)).to_be_visible()
        expect(leaf).to_be_visible()

        sidebar = page.locator(".folder-sidebar")
        sidebar.get_by_role("button", name="Find a folder", exact=True).click()
        sidebar.get_by_role("searchbox", name="Find a folder", exact=True).fill("Field notes")
        tree.get_by_role("button", name="Collapse Archives", exact=True).click()
        expect(leaf).to_be_hidden()
        sidebar.get_by_role("button", name="Close sidebar search", exact=True).click()
        expect(leaf).to_be_visible()
        assert page.evaluate("JSON.parse(localStorage.getItem('archivebox.folder-expansion'))") == {
            "expanded": [str(root.pk), str(branch.pk)],
            "collapsed": [],
        }

        leaf.click()
        tree.get_by_role("button", name="Collapse Research notes", exact=True).click()
        page.reload()
        expect(tree.get_by_role("button", name="Expand Research notes", exact=True)).to_be_visible()
        expect(leaf).to_be_hidden()
        tree.get_by_role("button", name="Expand Research notes", exact=True).click()
        expect(leaf).to_be_visible()
        browser.close()


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
            ("domains", "domain", "*.fieldnotes104.org", "fieldnotes104.org", "fieldnotes", "fieldnotes104.org"),
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
            more = tree.locator(".library-load-more")
            for _ in range(2 if mode == "domains" else 1):
                expect(more).to_be_visible()
                cursor = more.get_attribute("data-cursor")
                tree.evaluate("tree => tree.scrollTop = tree.scrollHeight")
                expect(more).not_to_have_attribute("data-cursor", cursor)
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

    def fetch(query="", **params):
        response = admin_client.get("/admin/domains/" + query, params or None, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert response.context["domain_table_loading"]
        table = admin_client.get("/admin/domains/" + response.context["domain_table_url"], HTTP_HOST=ADMIN_TEST_HOST)
        assert table.status_code == 200
        return table.context

    first = fetch()
    assert [row["domain"] for row in first["domains"]] == [f"site{i:03}.com" for i in range(50)]
    assert first["domain_total"] is None
    assert first["domain_next_url"]
    second = fetch(first["domain_next_url"])
    assert [row["domain"] for row in second["domains"]] == [f"site{i:03}.com" for i in range(50, 100)]
    assert fetch(second["domain_previous_url"])["domains"] == first["domains"]
    last = fetch(o="-domain")
    assert [row["domain"] for row in last["domains"]] == [f"site{i:03}.com" for i in range(104, 54, -1)]
    for term in ("104", "site104.com", "*.site104.com"):
        assert [row["domain"] for row in fetch(q=term)["domains"]] == ["site104.com"]


@pytest.mark.django_db
def test_domains_page_bounds_capture_metadata_and_defers_global_totals(admin_client, admin_user):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    Snapshot.objects.bulk_create(
        [Snapshot(crawl=crawl, url=f"https://example.com/post/{i}", timestamp=str(1917800000 + i)) for i in range(300)],
    )
    with CaptureQueriesContext(connection) as queries:
        initial = admin_client.get("/admin/domains/", HTTP_HOST=ADMIN_TEST_HOST)
    assert initial.status_code == 200 and initial.context["domain_table_loading"]
    assert not any('FROM "core_snapshot"' in query["sql"] for query in queries)
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/domains/" + initial.context["domain_table_url"], HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["domain_total"] is None
    row = response.context["domains"][0]
    assert row["domain"] == "example.com" and row["totals_limited"]
    assert row["snapshot_count"] == 300
    metadata_sql = [query["sql"] for query in queries if 'AS "_page_domain"' in query["sql"]]
    assert len(metadata_sql) == 1 and "LIMIT 65" in metadata_sql[0]
    assert 'JOIN "crawls_crawl"' not in metadata_sql[0]
    with CaptureQueriesContext(connection) as queries:
        sorted_page = admin_client.get("/admin/domains/", {"o": "-count"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert sorted_page.status_code == 200 and sorted_page.context["domain_table_loading"]
    assert not any('FROM "core_snapshot"' in query["sql"] for query in queries)
    table = admin_client.get("/admin/domains/", {"o": "-count", "table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert table.status_code == 200
    assert table.context["domains"][0]["snapshot_count"] == 300


@pytest.mark.django_db
def test_sidebar_domain_cursor_keeps_one_group_when_its_hosts_cross_pages(admin_client, admin_user):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    urls = ["https://example.com/", "http://deep.sub.example.com/path", "https://example.com:8080/"]
    urls += [f"https://example-{i:03}.com/" for i in range(105)]
    Snapshot.objects.bulk_create(
        [Snapshot(crawl=crawl, url=url, timestamp=str(1916700000 + i)) for i, url in enumerate(urls)],
    )

    def fetch(**params):
        response = admin_client.get("/admin/core/snapshot/sidebar/", {"sidebar": "domains", **params}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        return response.json()

    first = fetch()
    assert len(first["choices"]) == 50 and first["next"]
    second = fetch(cursor=first["next"])
    assert len(second["choices"]) == 50 and second["next"]
    third = fetch(cursor=second["next"])
    names = [row["name"] for page in (first, second, third) for row in page["choices"]]
    assert names.count("example.com") == 1
    assert len(set(names)) == len(names) == 107
    assert not third["next"]
    for term in ("example.com", "*.example.com"):
        assert {row["name"] for row in fetch(sidebar_q=term)["choices"]} == {"example.com", "example.com:8080"}


@pytest.mark.django_db(transaction=True)
def test_mobile_folder_search_keeps_tree_and_reveals_nested_results(live_server, admin_user, browser_runtime):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Folder
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    root = Folder.objects.create(name="OneTab")
    year = Folder.objects.create(name="2025", parent=root)
    Folder.objects.create(name="March", parent=year)
    Folder.objects.create(name="2026", parent=root)

    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 390, "height": 400}, is_mobile=True, has_touch=True)
        page.goto(f"{origin}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        sidebar = page.locator(".folder-sidebar")
        sidebar.get_by_role("button", name="Show folders").tap()
        tree = sidebar.locator(".folder-tree")
        expect(tree.get_by_role("button", name="Expand OneTab")).to_be_visible()
        root_link = tree.get_by_role("link", name="OneTab")
        expect(root_link).to_be_in_viewport(ratio=0.5)
        sidebar.get_by_role("button", name="Find a folder").tap()
        box = sidebar.get_by_role("searchbox", name="Find a folder")
        expect(box).to_be_focused()
        expect(root_link).to_be_in_viewport(ratio=0.5)
        original_root = root_link.element_handle()
        box.fill("  ")
        expect(root_link).to_be_in_viewport(ratio=0.5)
        assert root_link.evaluate("(link, original) => link === original", original_root)
        sidebar.get_by_role("button", name="Close sidebar search").tap()
        assert root_link.evaluate("(link, original) => link === original", original_root)
        sidebar.get_by_role("button", name="Find a folder").tap()
        box.fill("202")
        expect(tree.get_by_role("button", name="Collapse OneTab")).to_be_visible()
        expect(tree.get_by_role("link", name="2025")).to_be_in_viewport(ratio=0.5)
        expect(tree.get_by_role("link", name="2026")).to_be_in_viewport(ratio=0.5)
        box.fill("March")
        expect(tree.get_by_role("button", name="Collapse 2025")).to_be_visible()
        leaf = tree.get_by_role("link", name="March")
        expect(leaf).to_be_in_viewport(ratio=0.5)
        tree.get_by_role("button", name="Collapse OneTab").tap()
        expect(leaf).to_be_hidden()
        sidebar.get_by_role("button", name="Close sidebar search").tap()
        expect(tree.get_by_role("button", name="Expand OneTab")).to_be_visible()
        expect(tree.get_by_role("link", name="2025")).to_have_count(0)
        browser.close()
