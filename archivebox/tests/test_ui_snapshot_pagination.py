"""Snapshot lists retain full display totals without counting on every request."""

from threading import enumerate as threads
from urllib.parse import parse_qs, urlsplit

import pytest
from django.core.cache import cache
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def paginated_snapshots(crawl):
    from archivebox.core.models import Snapshot

    cache.clear()
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://example.com/page/{index}",
                title=f"Capture {index}",
                timestamp=str(1900500000 + index),
                crawl=crawl,
                status="sealed",
            )
            for index in range(123)
        ],
    )
    yield
    for thread in threads():
        if thread.name in {"snapshot-list-count", "collection-summary", "crawl-summary"}:
            thread.join(timeout=10)
            assert not thread.is_alive()
    cache.clear()


def test_cold_snapshot_list_uses_existing_statistics_for_total_and_page_links(admin_client, paginated_snapshots):
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("ANALYZE core_snapshot")
            with CaptureQueriesContext(connection) as queries:
                response = admin_client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_TEST_HOST)
            transaction.set_rollback(True)
    finally:
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("ANALYZE sqlite_schema")
    assert response.status_code == 200
    changelist = response.context_data["cl"]
    assert changelist.display_result_count == 123
    html = response.content.decode()
    assert 'aria-label="Page 3"' in html
    assert "of ≈3" in html
    assert not any("COUNT(*)" in query["sql"] and 'FROM "core_snapshot"' in query["sql"] for query in queries)


def test_filtered_page_totals_keep_their_scope_and_new_pages(admin_client, crawl, paginated_snapshots):
    from archivebox.core.models import Snapshot
    from archivebox.progressmonitor.collection import snapshot_list_count

    Snapshot.objects.create(url="https://example.org/excluded", timestamp="1900600000", crawl=crawl, status="queued")
    url = reverse("admin:core_snapshot_changelist")
    response = admin_client.get(url, {"status__exact": "sealed"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    for thread in threads():
        if thread.name in {"snapshot-list-count", "collection-summary", "crawl-summary"}:
            thread.join(timeout=10)
            assert not thread.is_alive()
    snapshot_list_count(response.context_data["cl"].queryset)
    for thread in threads():
        if thread.name == "snapshot-list-count":
            thread.join(timeout=10)
            assert not thread.is_alive()

    response = admin_client.get(url, {"status__exact": "sealed", "p": 2}, HTTP_HOST=ADMIN_TEST_HOST)
    changelist = response.context_data["cl"]
    assert changelist.display_result_count == 123
    assert changelist.display_num_pages == 3
    last_link = changelist.display_page_links[-1]
    assert parse_qs(urlsplit(last_link["url"]).query) == {"p": ["3"], "status__exact": ["sealed"]}

    Snapshot.objects.bulk_create(
        [
            Snapshot(url=f"https://example.org/new/{index}", timestamp=str(1900700000 + index), crawl=crawl, status="sealed")
            for index in range(50)
        ],
    )
    response = admin_client.get(url, {"status__exact": "sealed", "p": 3}, HTTP_HOST=ADMIN_TEST_HOST)
    changelist = response.context_data["cl"]
    assert changelist.display_result_count == 151
    assert changelist.display_num_pages == 4
    assert parse_qs(urlsplit(changelist.next_page_url).query) == {"p": ["4"], "status__exact": ["sealed"]}


@pytest.mark.parametrize("scope", ["folder", "unfiled", "tag"])
def test_plain_scope_counts_use_existing_membership_indexes(admin_client, crawl, paginated_snapshots, scope):
    from archivebox.core.models import Folder, Snapshot, SnapshotTag, Tag

    if scope == "folder":
        selected = Folder.objects.create(name="Selected folder")
        Snapshot.objects.update(folder=selected)
    elif scope == "tag":
        selected = Tag.objects.create(name="Selected tag")
        SnapshotTag.objects.bulk_create([SnapshotTag(snapshot_id=pk, tag=selected) for pk in Snapshot.objects.values_list("pk", flat=True)])
    else:
        selected = Folder.objects.create(name="Other folder")
    Snapshot.objects.create(
        url="https://example.org/outside-scope",
        timestamp="1900800000",
        crawl=crawl,
        status="sealed",
        folder=selected if scope == "unfiled" else None,
    )
    params = {"folder": "unfiled"} if scope == "unfiled" else {scope: str(selected.pk)}
    params["sidebar"] = "tags" if scope == "tag" else "folders"
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get(reverse("admin:core_snapshot_changelist"), params, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    changelist = response.context_data["cl"]
    assert changelist.display_result_count == 123
    assert changelist.result_count_exact
    assert changelist.display_num_pages == 3
    assert parse_qs(urlsplit(changelist.display_page_links[-1]["url"]).query) == {
        "p": ["3"],
        **{key: [value] for key, value in params.items()},
    }
    tables = (Snapshot._meta.db_table, SnapshotTag._meta.db_table)
    counts = [
        query["sql"] for query in queries if "COUNT(" in query["sql"].upper() and any(f'"{table}"' in query["sql"] for table in tables)
    ]
    assert len(counts) == 1, counts
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + counts[0])
            plan = " ".join(str(row[-1]) for row in cursor.fetchall())
        assert "SEARCH" in plan and "COVERING INDEX" in plan, plan
        assert "SCAN core_snapshot" not in plan, plan
    if scope == "tag":
        assert '"core_snapshot"' not in counts[0], "Count indexed membership rows without fetching each snapshot"


@pytest.mark.parametrize("scope", [None, "folder", "tag"])
def test_snapshot_page_links_navigate_real_rows(live_server, browser_runtime, admin_user, crawl, paginated_snapshots, scope):
    from playwright.sync_api import expect, sync_playwright
    from archivebox.core.models import Folder, Snapshot, SnapshotTag, Tag
    from archivebox.machine.models import Machine
    from archivebox.progressmonitor.collection import collection_summary

    params = {}
    if scope == "folder":
        selected = Folder.objects.create(name="Browser folder")
        Snapshot.objects.update(folder=selected)
        params = {"folder": str(selected.pk)}
    elif scope == "tag":
        selected = Tag.objects.create(name="Browser tag")
        SnapshotTag.objects.bulk_create([SnapshotTag(snapshot_id=pk, tag=selected) for pk in Snapshot.objects.values_list("pk", flat=True)])
        params = {"tag": str(selected.pk)}
    if scope:
        Snapshot.objects.create(url="https://example.org/not-selected", timestamp="1900900000", crawl=crawl, status="sealed")
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    # Run the same real background aggregate as progress polling. Pagination
    # should reuse that completed sample on its first page load.
    collection_summary(admin_user)
    for thread in threads():
        if thread.name == "collection-summary":
            thread.join(timeout=10)
            assert not thread.is_alive()
    assert collection_summary(admin_user, refresh=False)["snapshots"] == (124 if scope else 123)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        admin_url = f"http://admin.archivebox.localhost:{port}"
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        if params:
            page.goto(f"{admin_url}/admin/core/snapshot/?{scope}={params[scope]}")
        expect(page.locator("input.action-select")).to_have_count(50)
        expect(page.locator(".paginator")).to_contain_text("123 snapshots")
        page.get_by_role("link", name="Page 3", exact=True).click()
        page.wait_for_url(lambda url: parse_qs(urlsplit(url).query).get("p") == ["3"])
        assert parse_qs(urlsplit(page.url).query) == {"p": ["3"], **{key: [value] for key, value in params.items()}}
        expect(page.locator("input.action-select")).to_have_count(23)
        expect(page.locator(".paginator")).to_contain_text("Page 3 of 3")
        expect(page.locator(".paginator").get_by_role("link", name="Next", exact=True)).to_have_count(0)
        page.get_by_role("link", name="Page 1", exact=True).click()
        expect(page.locator("input.action-select")).to_have_count(50)
        browser.close()


def test_snapshot_pagination_fits_the_table(live_server, browser_runtime, admin_user, crawl, paginated_snapshots):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine
    from archivebox.progressmonitor.collection import collection_summary

    # This browser uses one localhost origin, so finish that installation's
    # hosting configuration before testing clicks behind the setup wizard.
    machine = Machine.current()
    machine.config.update(BASE_URL=live_server.url, SERVER_SECURITY_MODE="safe-onedomain-nojsreplay")
    machine.save(update_fields=["config"])
    Snapshot.objects.bulk_create(
        [
            Snapshot(url=f"https://example.org/page/{index}", timestamp=str(1901000000 + index), crawl=crawl, status="sealed")
            for index in range(1200)
        ],
    )
    collection_summary(admin_user)
    for thread in threads():
        if thread.name == "collection-summary":
            thread.join(timeout=10)
            assert not thread.is_alive()
    assert collection_summary(admin_user, refresh=False)["snapshots"] == 1323
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.goto(f"{live_server.url}/admin/login/?next=/admin/core/snapshot/%3Fp%3D12")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        pager = page.get_by_role("navigation", name="Snapshot pages")
        expect(pager.get_by_role("link", name="Page 4", exact=True)).to_be_visible()
        expect(pager.get_by_role("link", name="Page 27", exact=True)).to_be_visible()
        expect(pager.locator("[aria-current=page]")).to_have_text("12")
        assert pager.get_by_role("link", name="Next", exact=True).evaluate(
            """link => {
                const style = getComputedStyle(link);
                const toolbar = getComputedStyle(document.querySelector('#changelist-toolbar-filter-toggle'));
                return style.backgroundColor === toolbar.backgroundColor &&
                    style.borderTopColor === toolbar.borderTopColor &&
                    style.borderTopWidth === toolbar.borderTopWidth;
            }""",
        )
        alignment = pager.evaluate(
            """nav => {
                const previous = nav.querySelector('a[rel=prev]').getBoundingClientRect();
                const next = nav.querySelector('a[rel=next]').getBoundingClientRect();
                const resultTable = document.querySelector('#result_list');
                const table = resultTable.getBoundingClientRect();
                const results = resultTable.closest('.results').getBoundingClientRect();
                const pager = nav.getBoundingClientRect();
                return {buttons: (previous.left + next.right) / 2, table: (table.left + table.right) / 2,
                    results: (results.left + results.right) / 2, pager: (pager.left + pager.right) / 2};
            }""",
        )
        assert abs(alignment["buttons"] - alignment["table"]) < 2, alignment
        page.set_viewport_size({"width": 390, "height": 800})
        expect(pager.get_by_role("link", name="Page 4", exact=True)).to_have_count(0)
        expect(pager.get_by_role("link", name="Page 13", exact=True)).to_be_visible()
        expect(pager.get_by_role("link", name="Page 27", exact=True)).to_be_visible()
        pager.get_by_role("link", name="Page 13", exact=True).click()
        expect(pager.locator("[aria-current=page]")).to_have_text("13")
        browser.close()
