import re

import pytest
from django.core.cache import cache

from .conftest import ADMIN_TEST_HOST


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "0 GB"), (1, "1 GB"), (54 * 1024**3 + 1, "55 GB"), (1024**4, "1.0 TB"), (11 * 1024**4 // 10 + 1, "1.2 TB")],
)
def test_progress_archive_size(client, admin_user, snapshot, size, expected):
    from archivebox.core.models import Snapshot

    cache.clear()
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=size)
    assert client.login(username=admin_user.username, password="testpassword")
    response = client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert f"const archiveSize = '{expected}';" in response.content.decode()
    Snapshot.objects.filter(pk=snapshot.pk).update(output_size=2 * 1024**4)
    response = client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.context["ARCHIVE_SIZE_ESTIMATE"] == expected
    cache.clear()
    response = client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.context["ARCHIVE_SIZE_ESTIMATE"] == "2.0 TB"
    admin_user.is_staff = False
    admin_user.is_superuser = False
    admin_user.save()
    response = client.get("/public/", HTTP_HOST=ADMIN_TEST_HOST)
    assert b"navbar-archive-size" not in response.content
    client.logout()
    response = client.get("/public/", HTTP_HOST=ADMIN_TEST_HOST)
    assert b"navbar-archive-size" not in response.content
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
