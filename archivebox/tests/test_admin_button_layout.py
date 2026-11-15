"""Shared admin controls remain usable in narrow screens and plugin settings."""

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from archivebox.core.models import Snapshot
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_admin_controls_and_plugin_presets_on_mobile(live_server, browser_runtime, admin_user, crawl, tmp_path):
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    Snapshot.objects.create(url="https://example.com/controls", title="Button layout capture", crawl=crawl)
    base = live_server.url.replace("localhost", "admin.archivebox.localhost")
    output = Path(os.environ.get("ARCHIVEBOX_UI_SCREENSHOT_DIR", tmp_path))
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.goto(base + "/admin/core/snapshot/")
        page.locator("input.action-select").first.check()
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            buttons = page.locator(".actions-top .action-buttons .button")
            expect(buttons.first).to_be_visible()
            search_box = page.locator("#toolbar").bounding_box()
            actions_box = page.locator(".actions-top").bounding_box()
            rows_box = page.locator("#changelist-form > .results").bounding_box()
            folder_box = page.locator(".actions-folder select").bounding_box()
            move_box = buttons.first.bounding_box()
            if width == 1280:
                assert move_box["x"] - (folder_box["x"] + folder_box["width"]) >= 8
            else:
                assert move_box["y"] - (folder_box["y"] + folder_box["height"]) >= 8
            assert actions_box["y"] >= search_box["y"] + search_box["height"]
            assert rows_box["y"] >= actions_box["y"] + actions_box["height"]
            for control in buttons.all():
                box = control.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                if width == 390:
                    assert box["height"] >= 44, control.evaluate(
                        "node => ({html:node.outerHTML,min:getComputedStyle(node).minHeight,height:getComputedStyle(node).height,box:getComputedStyle(node).boxSizing})",
                    )
            page.screenshot(path=str(output / f"admin-actions-{width}.png"))
        page.locator(".action-permissions-select").select_option("private")
        expect(page.locator(".messagelist")).to_contain_text("private")
        # Start interacting while the large settings form is still being parsed.
        # Slow execution exposes clicks arriving before tab handlers are installed.
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 6})
        page.goto(base + "/admin/settings/", wait_until="commit")
        wget_tab = page.locator('[role="tab"][data-plugin="wget"]')
        wget_tab.click()
        expect(wget_tab).to_have_attribute("aria-selected", "true")
        timeout_field = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="WGET_TIMEOUT"][name]'))
        expect(timeout_field.locator(".config-quantity-unit")).to_be_visible()
        page.get_by_role("searchbox", name="Search plugin settings").fill("SCREENSHOT_RESOLUTION")
        expect(page.locator('.plugin-card[data-plugin-name="screenshot"]')).to_be_visible()
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        page.goto(base + "/admin/crawls/crawl/")
        page.locator("input.action-select").first.check()
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            buttons = page.locator(".actions-top .action-buttons .button")
            expect(buttons.first).to_be_visible()
            for control in buttons.all():
                box = control.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                if width == 390:
                    assert box["height"] >= 44
            page.screenshot(path=str(output / f"crawl-actions-{width}.png"))
        page.goto(base + "/add/")
        search = page.get_by_role("searchbox", name="Search plugin settings")
        search.fill("SCREENSHOT_RESOLUTION")
        card = page.locator('.plugin-card[data-plugin-name="screenshot"]')
        expect(card).to_be_visible()
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 900})
            card.get_by_role("button", name="Phone").click()
            expect(card.locator('input[data-config-key="SCREENSHOT_RESOLUTION"]')).to_have_value("390,844")
            card.get_by_role("button", name="Desktop").click()
            expect(card.locator('input[data-config-key="SCREENSHOT_RESOLUTION"]')).to_have_value("1440,2000")
            panel = page.locator("#plugin-settings").bounding_box()
            assert panel["x"] >= 0 and panel["x"] + panel["width"] <= width + 1
            for control in card.locator(".config-presets button").all():
                box = control.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                if width == 390:
                    assert box["height"] >= 44
            page.locator("#plugin-settings").screenshot(path=str(output / f"plugin-controls-{width}.png"))
        desktop_button = card.get_by_role("button", name="Desktop")
        desktop_button.focus()
        page.keyboard.press("Tab")
        page.keyboard.press("Shift+Tab")
        expect(desktop_button).to_be_focused()
        assert desktop_button.evaluate("node => node.matches(':focus-visible') && parseFloat(getComputedStyle(node).outlineWidth) >= 2")
        page.emulate_media(color_scheme="dark")
        expect(card.get_by_role("button", name="Desktop")).to_be_visible()
        page.locator("#plugin-settings").screenshot(path=str(output / "plugin-controls-dark-preference.png"))
        browser.close()
