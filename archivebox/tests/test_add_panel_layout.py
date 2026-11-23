"""The URL editor and filter panel share a CSS grid row."""

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_add_filter_panel_tracks_native_textarea_resize(live_server, browser_runtime, admin_user):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    origin = f"http://admin.archivebox.localhost:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1200})
        page.goto(f"{origin}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.goto(f"{origin}/add/")
        editor = page.locator('textarea[name="url"]')
        editor.fill("https://example.com/\nhttps://example.org/")
        panel = page.locator(".detected-urls-panel")
        typography = page.evaluate("""() => {
            const properties = ['font', 'padding', 'tabSize', 'letterSpacing', 'wordSpacing', 'textIndent', 'textTransform'];
            return ['textarea[name="url"]', '#url-highlight-layer'].map(selector => {
                const style = getComputedStyle(document.querySelector(selector));
                return properties.map(name => style[name]);
            });
        }""")
        assert typography[0] == typography[1]

        before = editor.bounding_box()
        page.mouse.move(before["x"] + before["width"] - 3, before["y"] + before["height"] - 3)
        page.mouse.down()
        page.mouse.move(before["x"] + before["width"] - 3, before["y"] + before["height"] + 100, steps=5)
        page.mouse.up()
        after = editor.bounding_box()
        box = panel.bounding_box()
        assert after["height"] > before["height"] + 50
        assert abs(box["y"] - after["y"]) <= 1
        assert abs(box["height"] - after["height"]) <= 1
        assert not panel.evaluate("element => element.style.height")
        page.set_viewport_size({"width": 390, "height": 844})
        assert panel.bounding_box()["y"] > editor.bounding_box()["y"]
        assert panel.bounding_box()["height"] >= 240
        for width in (390, 556, 768, 1024, 1600):
            page.set_viewport_size({"width": width, "height": 900})
            header = page.locator("#header").bounding_box()
            toolbar = page.locator("#user-tools").bounding_box()
            assert toolbar["y"] >= header["y"]
            assert toolbar["y"] + toolbar["height"] <= header["y"] + header["height"], f"Toolbar outside header at {width}px"
            assert toolbar["x"] + toolbar["width"] <= width
        browser.close()
