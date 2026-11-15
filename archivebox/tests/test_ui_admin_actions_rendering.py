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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("drag_source", ["preview", "title", "whitespace", "all"])
def test_streamed_search_rows_drag_checked_snapshots(live_server, browser_runtime, admin_user, crawl, drag_source):
    from pathlib import Path
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import ArchiveResult, Folder, Snapshot
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    folder = Folder.objects.create(name="Dragged results")
    snapshots = []
    png = (Path(__file__).parents[1] / "templates/static/archive.png").read_bytes()
    for index in range(3):
        snapshot = Snapshot.objects.create(
            url=f"https://example.com/streamed/{index}",
            title=f"Streamed capture {index}",
            crawl=crawl,
            status="sealed",
            config={"PERMISSIONS": "public"},
        )
        output = Path(snapshot.output_dir) / "screenshot/screenshot.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(png)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="screenshot",
            hook_name="on_Snapshot__50_screenshot.js",
            status="succeeded",
            output_str="screenshot/screenshot.png",
            output_size=len(png),
            output_files={"screenshot.png": {"size": len(png), "mimetype": "image/png"}},
        )
        snapshots.append(snapshot)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        original_form = page.locator("#changelist-form").element_handle()
        page.locator('select[name="search_mode"]').select_option("meta")
        page.locator("#searchbar").fill("Streamed")
        with page.expect_response(
            lambda response: (
                "/admin/core/snapshot/?" in response.url and response.request.headers.get("x-requested-with") == "XMLHttpRequest"
            ),
        ):
            page.locator("#searchbar").press("Enter")
        page.wait_for_function("oldForm => !oldForm.isConnected", arg=original_form)
        expect(page.locator("#result_list tbody tr")).to_have_count(3)
        source = page.locator("#result_list tbody tr").filter(has_text="Streamed capture 0")
        expect(source).to_have_attribute("draggable", "true")
        for snapshot in snapshots[:2]:
            page.locator(f'input.action-select[value="{snapshot.pk}"]').check()
        if drag_source == "all":
            page.locator(".action-total-select").click()
            expect(page.locator("input.select-across")).to_have_value("1")
            expect(page.locator("input.action-select:checked")).to_have_count(3)
        target = page.locator(f'.folder-row[data-folder-id="{folder.pk}"]')
        if drag_source == "preview":
            image = source.frame_locator(".field-preview_icon iframe").locator(".screenshot-thumbnail")
            expect(image).to_be_visible()
            expect(image).to_have_js_property("complete", True)
            assert image.evaluate("image => image.naturalWidth") > 0
            source.locator(".field-preview_icon").drag_to(target)
        elif drag_source in ("title", "all"):
            source.locator(".field-title_str").drag_to(target)
        else:
            box = source.bounding_box()
            source.drag_to(target, source_position={"x": box["width"] - 3, "y": box["height"] / 2})
        moved = 3 if drag_source == "all" else 2
        expect(page.locator(".messagelist")).to_contain_text(f"Moved {moved} snapshot(s) to Dragged results")
        browser.close()
    assert set(Snapshot.objects.filter(folder=folder).values_list("pk", flat=True)) == {snapshot.pk for snapshot in snapshots[:moved]}
    if moved < 3:
        assert Snapshot.objects.get(pk=snapshots[2].pk).folder_id is None
