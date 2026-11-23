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


def test_snapshot_page_links_navigate_real_rows(live_server, browser_runtime, admin_user, paginated_snapshots):
    from playwright.sync_api import expect, sync_playwright
    from archivebox.machine.models import Machine
    from archivebox.progressmonitor.collection import collection_summary

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
    assert collection_summary(admin_user, refresh=False)["snapshots"] == 123
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        admin_url = f"http://admin.archivebox.localhost:{port}"
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        expect(page.locator("input.action-select")).to_have_count(50)
        expect(page.locator(".paginator")).to_contain_text("123 snapshots")
        page.get_by_role("link", name="Page 3", exact=True).click()
        page.wait_for_url("**/admin/core/snapshot/?p=3")
        expect(page.locator("input.action-select")).to_have_count(23)
        expect(page.locator(".paginator")).to_contain_text("Page 3 of 3")
        expect(page.locator(".paginator").get_by_role("link", name="Next", exact=True)).to_have_count(0)
        page.get_by_role("link", name="Page 1", exact=True).click()
        expect(page.locator("input.action-select")).to_have_count(50)
        browser.close()
