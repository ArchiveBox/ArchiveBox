"""Shared admin controls remain usable in narrow screens and plugin settings."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.db import connections
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
        for width in (1280, 390, 320):
            page.set_viewport_size({"width": width, "height": 900})
            buttons = page.locator(".actions-top .action-buttons .button")
            expect(buttons.first).to_be_visible()
            assert page.locator(".actions-folder").count() == 0
            folder_select = page.get_by_role("combobox", name="Move to folder", exact=True)
            expect(folder_select).to_be_visible()
            expect(page.locator(".action-folder-label")).to_have_text("Move")
            expect(folder_select.locator('option[value="__choose__"]')).to_have_text("Move")
            folder_search = page.get_by_role("searchbox", name="Find a folder", exact=True)
            expect(folder_search).to_be_hidden()
            expect(page.locator(".action-folder-wrapper > .button")).to_be_visible()
            folder_select.select_option(label="Find a folder…")
            expect(folder_search).to_be_focused()
            expect(page.locator(".action-folder-wrapper .record-picker > button")).to_be_hidden()
            assert folder_select.evaluate("node => node.tagName") == "SELECT"
            for control in (folder_search, folder_select):
                box = control.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                if width <= 390:
                    assert box["height"] >= 44
            folder_search.press("Escape")
            expect(folder_search).to_be_hidden()
            page.get_by_role("combobox", name="Permissions", exact=True).focus()
            expect(folder_select).to_have_value("__choose__")
            page.locator("input.action-select").first.uncheck()
            expect(folder_select).not_to_be_visible()
            page.locator("input.action-select").first.check()
            expect(folder_select).to_be_visible()
            for control in buttons.all():
                box = control.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                if width <= 390:
                    assert box["height"] >= 44, control.evaluate(
                        "node => ({html:node.outerHTML,min:getComputedStyle(node).minHeight,height:getComputedStyle(node).height,box:getComputedStyle(node).boxSizing})",
                    )
            page.locator(".actions-top").screenshot(path=str(output / f"snapshot-toolbar-{width}.png"))
            page.screenshot(path=str(output / f"admin-actions-{width}.png"))
        page.locator(".action-permissions-select").select_option("private")
        expect(page.locator(".messagelist")).to_contain_text("private")
        # Start interacting while the large settings form is still being parsed.
        # Slow execution exposes clicks arriving before tab handlers are installed.
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 6})
        page.goto(base + f"/admin/machine/machine/{machine.pk}/change/", wait_until="commit")
        wget_tab = page.locator('[role="tab"][data-plugin="wget"]')
        wget_tab.click()
        expect(wget_tab).to_have_attribute("aria-selected", "true")
        timeout_field = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="WGET_TIMEOUT"][name]'))
        expect(timeout_field.locator(".config-quantity-unit")).to_be_visible()
        page.get_by_role("searchbox", name="Search plugin settings").fill("SCREENSHOT_RESOLUTION")
        expect(page.locator('.plugin-card[data-plugin-name="screenshot"]')).to_be_visible()
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
        machine_card = page.locator('.plugin-card[data-plugin-name="screenshot"]')
        machine_four_k = machine_card.get_by_role("button", name="4K 3840 × 3240", exact=True)
        machine_four_k.click()
        expect(machine_card.locator('input[data-config-key="SCREENSHOT_RESOLUTION"]')).to_have_value("3840,3240")
        expect(machine_four_k).to_have_attribute("aria-pressed", "true")
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
        for width in (1280, 1060, 390):
            page.set_viewport_size({"width": width, "height": 900})
            resolution = card.locator('input[data-config-key="SCREENSHOT_RESOLUTION"]')
            for name, value in (
                ("Phone 390 × 844", "390,844"),
                ("Tablet 768 × 1024", "768,1024"),
                ("Desktop 1440 × 2000", "1440,2000"),
                ("4K 3840 × 3240", "3840,3240"),
            ):
                preset = card.get_by_role("button", name=name, exact=True)
                preset.click()
                expect(resolution).to_have_value(value)
                expect(preset).to_have_attribute("aria-pressed", "true")
                box = preset.bounding_box()
                assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                assert preset.evaluate("button => button.scrollWidth <= button.clientWidth")
                if width == 390:
                    assert box["height"] >= 44
            # Fit uses the space the settings pane actually allocates, not the viewport.
            available, columns = card.locator(".config-presets").evaluate(
                "grid => [grid.clientWidth, getComputedStyle(grid).gridTemplateColumns.split(' ').length]",
            )
            if available > 350:
                assert columns == 4
            panel = page.locator("#plugin-settings").bounding_box()
            assert panel["x"] >= 0 and panel["x"] + panel["width"] <= width + 1
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("streamed", [False, True])
def test_folder_action_menu_reopens_and_moves_real_selection(live_server, browser_runtime, admin_user, crawl, streamed):
    from archivebox.core.models import Folder

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    snapshot = Snapshot.objects.create(url="https://example.com/folder-menu", crawl=crawl)
    Snapshot.objects.create(url="https://example.com/also-in-search", crawl=crawl)
    parent = Folder.objects.create(name="2026")
    folder = Folder.objects.create(name="OneTab", parent=parent)
    base = live_server.url.replace("localhost", "admin.archivebox.localhost")

    def current_folder_id():
        # Playwright's synchronous API still runs an asyncio loop on this thread.
        # Keep each real committed-DB assertion on a separate synchronous thread.
        try:
            snapshot.refresh_from_db()
            return str(snapshot.folder_id or "")
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as reader, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 390, "height": 700})
        page.goto(base + "/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.goto(base + "/admin/core/snapshot/")
        if streamed:
            editor = page.locator('#changelist-search [role="combobox"]')
            editor.fill("title:missing OR domain:example.com")
            editor.press("Enter")
            expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")
        for destination in (str(folder.pk), "", str(folder.pk)):
            checkbox = page.locator(f'input.action-select[value="{snapshot.pk}"]')
            checkbox.check()
            menu = page.get_by_role("combobox", name="Move to folder", exact=True)
            expect(menu).to_be_visible()
            menu.select_option(label="Find a folder…")
            page.get_by_role("searchbox", name="Find a folder", exact=True).fill("OneTab")
            expect(menu.locator(f'option[value="{folder.pk}"]')).to_have_text("2026 / OneTab")
            expect(menu).to_have_value("__choose__")
            menu.focus()
            page.keyboard.press("Escape")
            page.get_by_role("combobox", name="Re-Archive", exact=True).focus()
            expect(menu).to_have_value("__choose__")
            if destination and streamed:
                menu.select_option(label="Find a folder…")
                page.get_by_role("searchbox", name="Find a folder", exact=True).fill("OneTab")
            with page.expect_navigation(wait_until="domcontentloaded"):
                if destination and streamed:
                    page.get_by_role("button", name="2026 / OneTab", exact=True).click()
                else:
                    menu.select_option(destination)
            assert reader.submit(current_folder_id).result() == destination
            expect(menu).not_to_be_visible()
        browser.close()


@pytest.mark.django_db(transaction=True)
def test_add_crawl_tip_dismisses_after_three_background_clicks(live_server, browser_runtime, admin_user):
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    base = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(base + "/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.goto(base + "/add/")
        tip = page.locator(".crawl-explanation")
        background = tip.get_by_text("Tip:", exact=True)
        link = tip.get_by_role("link", name="Get the extension")
        # Observe the original event at the window, then suppress external travel
        # so this fixture can test normal link activation without using the network.
        page.evaluate("""() => {
            window.linkActivations = [];
            window.addEventListener('click', event => {
                const link = event.target.closest('.crawl-tip a[href]');
                if (!link) return;
                window.linkActivations.push([link.href, event.defaultPrevented]);
                event.preventDefault();
            });
        }""")
        link.locator("img").click()
        link.press("Enter")
        assert page.evaluate("window.linkActivations") == [
            ["https://github.com/ArchiveBox/archivebox-browser-extension", False],
            ["https://github.com/ArchiveBox/archivebox-browser-extension", False],
        ]
        tip.locator(".crawl-tip-url-target").click()
        expect(tip).to_be_visible()
        background.click()
        expect(tip).to_be_visible()
        page.locator('textarea[name="url"]').fill("https://example.com/not-persisted")
        page.reload()
        expect(page.locator('textarea[name="url"]')).to_have_value("")
        background.click()
        expect(tip).to_be_visible()
        page.reload()
        expect(tip).to_be_visible()
        background.click()
        expect(tip).to_be_hidden()
        page.reload()
        expect(tip).to_be_hidden()
