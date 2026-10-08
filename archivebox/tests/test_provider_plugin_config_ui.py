"""Verify provider controls in both real browser configuration forms."""

import json
from pathlib import Path

from abx_plugins import get_plugins_dir
from playwright.sync_api import expect, sync_playwright

from .conftest import cli_env, get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process


PROVIDERS = "onedrive microsoft365 notion figma tldraw excalidraw drawio miro canva box nextcloud wetransfer mega protondrive protondocs iclouddrive iwork".split()
TEXT_PROVIDERS = {"microsoft365", "notion", "protondocs", "iwork"}


def test_provider_config_grids_in_browser(initialized_archive, browser_runtime):
    root = initialized_archive
    port = get_free_port()
    env = cli_env(
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
        DJANGO_SUPERUSER_USERNAME="provider-grid-review",
        DJANGO_SUPERUSER_PASSWORD="local-provider-grid-test-password",
        DJANGO_SUPERUSER_EMAIL="provider-grid@example.com",
    )
    for command in (["manage", "createsuperuser", "--noinput"], ["persona", "create", "Provider Grid"]):
        result = run_archivebox_cmd(command, cwd=root, env=env, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
    server = start_archivebox_server(root, port=port, env=env, log_name="server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill(env["DJANGO_SUPERUSER_USERNAME"])
            page.get_by_label("Password:", exact=True).fill(env["DJANGO_SUPERUSER_PASSWORD"])
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page.get_by_role("button", name="Log out", exact=True)).to_be_visible()
            for form in ("add", "persona"):
                if form == "add":
                    page.goto(base + "/add/")
                else:
                    page.goto(base + "/admin/personas/persona/")
                    page.get_by_role("link", name="Provider Grid", exact=True).click()
                for plugin in PROVIDERS:
                    config = json.loads((Path(get_plugins_dir()) / plugin / "config.json").read_text())
                    card = page.locator(f'.plugin-card[data-plugin-name="{plugin}"]')
                    expect(card).to_be_visible()
                    group = card.locator("xpath=ancestor::details[contains(@class, 'plugin-group')]")
                    expect(group.locator("summary")).to_contain_text("Text" if plugin in TEXT_PROVIDERS else "Media")
                    expect(card.locator(".plugin-choice-description")).to_have_text(config["description"])
                    logo = card.locator(".plugin-choice-icon svg").first
                    expect(logo).to_be_visible()
                    assert logo.locator("path, circle, rect, polygon, ellipse, polyline").count() > 0
                    card.locator(".plugin-config-marker").click()
                    timeout = card.locator(f'[name="plugin_config__{plugin}__{plugin.upper()}_TIMEOUT"]')
                    expect(timeout).to_be_visible()
                    assert timeout.input_value()
                    card.locator(".plugin-config-marker").click()
                page.locator('.plugin-card[data-plugin-name="onedrive"]').scroll_into_view_if_needed()
                page.screenshot(path=str(root / f"provider-grid-{form}.png"))
            browser.close()
    finally:
        stop_archivebox_process(server)
