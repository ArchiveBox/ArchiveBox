"""The action toolbar renders its final controls before JavaScript starts."""

import pytest
from django.urls import reverse
from lxml.html import fromstring

from archivebox.tests.conftest import ADMIN_TEST_HOST


@pytest.mark.django_db
def test_snapshot_action_toolbar_is_server_rendered(admin_client, snapshot):
    response = admin_client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    document = fromstring(response.content)
    toolbar = document.xpath('//div[contains(concat(" ", @class, " "), " actions-top ")]')[0]
    buttons = toolbar.xpath('.//div[@class="action-buttons"]')
    assert len(buttons) == 1
    assert "hidden" in buttons[0].attrib  # There are no selected rows on first paint.
    assert toolbar.xpath('.//select[@name="action"]/ancestor::*[@hidden]')
    assert toolbar.xpath('.//button[@name="index"]/ancestor::*[@hidden]')
    assert buttons[0].xpath('.//select[@class="action-rearchive-select"]/option[@value="update_snapshots"]')
    assert buttons[0].xpath('.//select[@class="action-permissions-select"]/option[@value="private"]')
    assert toolbar.xpath('.//span[contains(@class, "actions-tags-with-buttons")][@hidden]/button[@name="add_tags"]')


@pytest.mark.django_db(transaction=True)
def test_snapshot_action_toolbar_in_browser(live_server, browser_runtime, admin_user, crawl):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Folder, Snapshot, Tag

    from urllib.parse import urlsplit
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
    tags = [Tag.objects.create(name=name) for name in ("research", "software-engineering", "read-later", "long-term-reference")]
    for index in range(50):
        snapshot = Snapshot.objects.create(
            url=f"https://example.com/article/{index}",
            title=f"Saved article {index}",
            crawl=crawl,
            status="sealed",
        )
        snapshot.tags.set(tags)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{admin_url}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.goto(f"{admin_url}/admin/core/snapshot/")
        print(
            "list navigation timings",
            page.evaluate("""() => {
            const n = performance.getEntriesByType('navigation')[0];
            return {ttfb: n.responseStart - n.requestStart, domReadyWork: n.domContentLoadedEventEnd - n.domContentLoadedEventStart, loaded: n.loadEventEnd};
        }"""),
        )
        expect(page.locator("#result_list tbody tr")).to_have_count(50)
        expect(page.locator('.actions-top select[name="action"]')).to_be_hidden()
        expect(page.locator('.actions-top button[name="index"]')).to_be_hidden()
        expect(page.locator(".actions-top .action-buttons")).to_be_hidden()
        page.locator("input.action-select").first.check()
        expect(page.locator(".actions-top .action-buttons")).to_be_visible()
        expect(page.locator(".action-rearchive-select")).to_have_count(1)
        expect(page.locator('.actions-tags button[name="add_tags"]')).to_be_visible()
        page.locator(".action-permissions-select").select_option("private")
        expect(page.locator("#result_list tbody tr")).to_have_count(50)
        page.locator("input.action-select").first.check()
        page.once("dialog", lambda dialog: dialog.dismiss())
        page.locator(".action-rearchive-select").select_option("overwrite_snapshots")
        expect(page.locator(".action-rearchive-select")).to_have_value("")
        row = page.locator("#result_list tbody tr").first
        toggle = row.locator(".library-tags-toggle")
        for width in (1600, 1280, 390, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            expect(row.locator(".tag-pill")).to_have_count(4)
            if width <= 1500:
                if toggle.is_visible():
                    toggle.click()
                    expect(toggle).to_have_attribute("aria-expanded", "true")
                    expect(row.locator(".tag-pill:visible")).to_have_count(4)
                    toggle.click()
                    expect(toggle).to_have_attribute("aria-expanded", "false")
                row.locator(".tag-inline-input-sm").focus()
                expect(row.locator(".tag-pill:visible")).to_have_count(4)
                page.locator("#searchbar").focus()
            thumbnail = row.locator(".snapshot-thumbnail")
            if thumbnail.bounding_box()["height"] <= 64:
                expect(thumbnail.locator(".snapshot-thumbnail-caption").first).to_be_hidden()
                letter = thumbnail.locator(".snapshot-thumbnail-initial").bounding_box()
                box = thumbnail.bounding_box()
                assert letter["y"] >= box["y"] and letter["y"] + letter["height"] <= box["y"] + box["height"]
        tag_input = row.locator(".tag-inline-input-sm")
        tag_input.fill("new-test-tag")
        tag_input.press("Enter")
        expect(row.locator('.tag-pill[data-tag="new-test-tag"]')).to_be_visible()
        row.locator('.tag-pill[data-tag="new-test-tag"] .tag-remove-btn').click()
        expect(row.locator('.tag-pill[data-tag="new-test-tag"]')).to_have_count(0)
        navigation_start = page.evaluate("performance.timeOrigin")
        page.get_by_role("button", name="Create folder", exact=True).click()
        page.get_by_role("menuitem", name="New folder", exact=True).click()
        page.locator("#folder-name").fill("New sidebar folder")
        page.get_by_role("button", name="Save folder", exact=True).click()
        expect(page.locator(".folder-tree")).to_contain_text("New sidebar folder")
        assert page.evaluate("performance.timeOrigin") == navigation_start
        expect(page.locator("input.action-select").first).to_be_checked()
        page.locator('.folder-row[data-folder-name="New sidebar folder"]').hover()
        page.get_by_role("button", name="Add folder in New sidebar folder", exact=True).click()
        page.locator("#folder-name").fill("Sidebar child")
        page.get_by_role("button", name="Save folder", exact=True).click()
        expect(page.locator(".folder-tree")).to_contain_text("Sidebar child")
        expect(page.get_by_role("button", name="Add folder in New sidebar folder", exact=True)).to_be_visible()
        assert page.evaluate("performance.timeOrigin") == navigation_start
        browser.close()
    snapshot.refresh_from_db()
    assert snapshot.permissions == "private"
    assert snapshot.status == "sealed"
    assert set(snapshot.tags.values_list("name", flat=True)) == {tag.name for tag in tags}
    assert Folder.objects.get(name="Sidebar child").parent_id == Folder.objects.get(name="New sidebar folder").pk
