from urllib.parse import urlsplit

import pytest
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from archivebox.importers.models import ImporterSource
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_create_edit_cancel_matches_save(live_server, admin_user, browser_runtime):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    source = ImporterSource.objects.create(
        name="Local style fixture",
        created_by=admin_user,
        plugin="importer_rss",
        feed="feed",
        settings={"IMPORTER_RSS_URL": "https://example.invalid/feed.xml"},
    )
    base = f"http://admin.archivebox.localhost:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(base + "/admin/login/")
        page.get_by_label("Username:", exact=True).fill(admin_user.username)
        page.get_by_label("Password:", exact=True).fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        for route in (reverse("importers:new", args=["importer_rss", "feed"]), reverse("importers:edit", args=[source.pk])):
            page.goto(base + route)
            cancel = page.get_by_role("link", name="Cancel", exact=True)
            save = page.get_by_role("button", name="Save importer", exact=True)
            expect(cancel).to_have_attribute("href", reverse("importers:index"))
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 900})
                cancel.scroll_into_view_if_needed()
                assert cancel.evaluate("link => getComputedStyle(link).textDecorationLine") == "none"
                bounds = cancel.bounding_box()
                other = save.bounding_box()
                assert abs(bounds["height"] - other["height"]) < 1
                assert abs(bounds["y"] - other["y"]) < 1
        browser.close()
