import re
import time

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from .conftest import ADMIN_TEST_HOST


@pytest.mark.django_db(transaction=True)
def test_archive_size_does_not_scan_collection_while_rendering(client, admin_user, snapshot):
    cache.clear()
    client.force_login(admin_user)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert not any('SUM("core_snapshot"."output_size")' in query["sql"] for query in queries)


def _wait_for_collection(client, expected_bytes):
    deadline = time.monotonic() + 5
    while True:
        response = client.get("/progress.json", {"metrics": "1", "tree": "0"}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200, response.content
        summary = response.json().get("collection")
        if summary is not None:
            assert summary["bytes"] == expected_bytes
            return summary
        assert time.monotonic() < deadline, "background collection summary did not finish"
        time.sleep(0.05)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("size", [0, 1, 54 * 1024**3 + 1, 1024**4, 11 * 1024**4 // 10 + 1])
def test_progress_archive_size(client, admin_user, snapshot, size):
    from archivebox.core.models import Snapshot

    cache.clear()
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=size)
    client.force_login(admin_user)
    summary = _wait_for_collection(client, size)
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=2 * 1024**4)
    assert _wait_for_collection(client, size) == summary
    cache.clear()
    _wait_for_collection(client, 2 * 1024**4)
    client.logout()
    response = client.get("/progress.json", {"metrics": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert "collection" not in response.json()
    cache.clear()


@pytest.mark.django_db(transaction=True)
def test_archive_size_only_counts_staff_owners_snapshots(client, admin_user, snapshot):
    from django.contrib.auth import get_user_model
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    cache.clear()
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=123)
    other_user = get_user_model().objects.create_user(username="other-archive-size-owner")
    other_crawl = Crawl.objects.create(created_by=other_user, urls="https://private.example/")
    Snapshot.objects.create(crawl=other_crawl, url="https://private.example/", output_size=1024**4)
    admin_user.is_superuser = False
    admin_user.save(update_fields=["is_superuser"])
    client.force_login(admin_user)
    summary = _wait_for_collection(client, 123)
    assert summary["snapshots"] == 1
    cache.clear()


@pytest.mark.django_db(transaction=True)
def test_progress_archive_size_browser(live_server, admin_user, snapshot, browser_runtime):
    from playwright.sync_api import expect, sync_playwright
    from archivebox.core.models import Snapshot

    cache.clear()
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=54 * 1024**3 + 1)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{live_server.url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        expect(page.locator("#user-tools .navbar-archive-size")).to_have_count(0)
        # The fixture has a STARTED row but no live hook; it is not an active capture.
        expect(page.locator("#orchestrator-text")).to_have_text("0 - 0 queued")
        expect(page.locator("svg#orchestrator-dot path")).to_have_attribute("d", "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5")
        estimate = page.locator("#metric-storage")
        expect(estimate).to_be_visible()
        expect(estimate).to_contain_text("55 GB (")
        expect(estimate.locator("small")).to_contain_text(" free)")
        assert estimate.locator("small").evaluate("el => getComputedStyle(el).color") == "rgb(63, 185, 80)"
        assert estimate.locator("small").evaluate(
            "el => parseFloat(getComputedStyle(el).fontSize) < parseFloat(getComputedStyle(el.parentElement).fontSize)",
        )
        expect(page.locator("#metric-web .metric-text")).to_have_text(re.compile(r"^\d+\.\ds/Req$"))
        page.set_viewport_size({"width": 390, "height": 844})
        expect(estimate).to_be_visible()
        browser.close()
    cache.clear()
