"""Published documentation conventions and native settings disclosure behavior."""

import json
import re

from playwright.sync_api import expect, sync_playwright

from archivebox.plugins.discovery import get_plugin_catalog
from archivebox.plugins.documentation import get_plugin_documentation

from .conftest import cli_env, create_admin_and_token, get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process


def test_documentation_matches_installed_gallery_metadata():
    catalog = get_plugin_catalog()
    assert {"puppeteer", "screenshot", "mobilesize", "ssl"} <= set(catalog)
    for name, plugin in catalog.items():
        links = get_plugin_documentation(name)
        assert links["docs_url"] == f"https://plugins.archivebox.io/#{name}"
        schema = json.loads((plugin.path / "config.json").read_text())
        recipe = json.loads((plugin.path / schema["screenshot"]).read_text()) if schema.get("screenshot") else {}
        templates = plugin.path / "templates"
        expected = bool(
            recipe or (templates / "full.html").is_file() or ((templates / "card.html").is_file() and not schema.get("card_hidden")),
        )
        assert bool(links["screenshot_url"]) is expected, name
        if expected:
            slug = re.sub(r"[^a-z0-9]+", "-", recipe.get("view", f"Snapshot View ({name})").lower()).strip("-")
            assert links["screenshot_url"] == f"https://archivebox.io/screenshots/{slug}-desktop.png"
            assert links["screenshot_page_url"] == f"https://archivebox.io/screenshots/#{slug}"
    assert get_plugin_documentation("mobilesize")["screenshot_url"].endswith("/mobile-size-configuration-desktop.png")
    assert get_plugin_documentation("screenshot")["screenshot_url"].endswith("/snapshot-view-screenshot-desktop.png")
    assert get_plugin_documentation("ssl")["screenshot_url"] == ""


def test_settings_advanced_search_and_native_validation(initialized_archive, browser_runtime):
    root = initialized_archive
    create_admin_and_token(root)
    port = get_free_port()
    server = start_archivebox_server(root, env=cli_env(port=port, server=True), port=port, log_name="presentation-server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill("apitestadmin")
            page.get_by_label("Password:", exact=True).fill("testpass123")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.goto(base + "/admin/settings/")
            search = page.get_by_role("searchbox", name="Search plugin settings")
            page.locator('[role="tab"][data-plugin="wget"]').click()
            wget = page.locator('.plugin-card[data-plugin-name="wget"]')
            expect(wget.get_by_role("link", name="Docs ↗", exact=True)).to_have_attribute("href", "https://plugins.archivebox.io/#wget")
            expect(wget.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="WGET_TIMEOUT"][name]'))).to_be_visible()
            binary = wget.locator('[data-config-key="WGET_BINARY"][name]')
            expect(binary).not_to_be_visible()
            search.fill("WGET_BINARY")
            expect(binary).to_be_visible()
            expect(wget.locator(".plugin-advanced")).to_have_js_property("open", True)

            # A plugin without gallery screenshots must not render a broken image slot.
            assert page.locator('.plugin-card[data-plugin-name="ssl"] .config-plugin-preview').count() == 0
            screenshot = page.locator('.plugin-card[data-plugin-name="screenshot"]')
            expect(screenshot.locator("[data-plugin-preview-src]")).to_have_attribute(
                "data-plugin-preview-src",
                "https://archivebox.io/screenshots/snapshot-view-screenshot-desktop.png",
            )

            search.fill("SEARCH_BACKEND_SONIC_PORT")
            sonic = page.locator('.plugin-card[data-plugin-name="search_backend_sonic"]')
            advanced = sonic.locator(".plugin-advanced")
            sonic_port = sonic.locator('[data-config-key="SEARCH_BACKEND_SONIC_PORT"][name]')
            expect(advanced).to_have_js_property("open", True)
            expect(sonic_port).to_be_visible()
            sonic_port.fill("65536")
            assert sonic_port.evaluate("input => input.validity.rangeOverflow")
            search.fill("")
            advanced.locator(":scope > summary").click()
            expect(advanced).to_have_js_property("open", False)
            page.locator('[role="tab"][data-plugin="screenshot"]').click()
            posted = []
            page.on("request", lambda request: posted.append(request.url) if request.method == "POST" else None)
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator('[role="tab"][data-plugin="search_backend_sonic"]')).to_have_attribute("aria-selected", "true")
            expect(advanced).to_have_js_property("open", True)
            expect(sonic_port).to_be_focused()
            assert posted == [], "Invalid advanced fields must be revealed before submitting"
            sonic_port.fill("1492")
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".success")).to_be_visible()
            browser.close()
        saved = run_archivebox_cmd(
            [
                "manage",
                "shell",
                "-c",
                "from archivebox.machine.models import Machine; print(Machine.current().config['SEARCH_BACKEND_SONIC_PORT'])",
            ],
            cwd=root,
            timeout=60,
        )
        assert saved.returncode == 0, saved.stdout + saved.stderr
        assert saved.stdout.strip().splitlines()[-1] == "1492"
    finally:
        stop_archivebox_process(server)
