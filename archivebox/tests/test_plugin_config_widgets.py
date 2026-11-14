"""Verify provider controls in both real browser configuration forms."""

import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from .conftest import cli_env, get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process


PROVIDERS = [
    "screenshot",
    "pdf",
    "mobilesize",
    "chrome_screencast",
    "puppeteer",
    "playwright",
    "stagehand",
    "browserharness",
    "autosummary",
]


def test_config_widget_overrides_in_browser(initialized_archive, browser_runtime):
    root = initialized_archive
    port = get_free_port()
    env = cli_env(
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
        DJANGO_SUPERUSER_USERNAME="widget-review",
        DJANGO_SUPERUSER_PASSWORD="local-widget-test-password",
        DJANGO_SUPERUSER_EMAIL="widgets@example.com",
    )
    for command in (["manage", "createsuperuser", "--noinput"], ["persona", "create", "Widget Review"]):
        result = run_archivebox_cmd(command, cwd=root, env=env, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
    server = start_archivebox_server(root, port=port, env=env, log_name="server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
            base = f"http://admin.archivebox.localhost:{port}"
            page.goto(base + "/admin/login/")
            page.get_by_label("Username:", exact=True).fill(env["DJANGO_SUPERUSER_USERNAME"])
            page.get_by_label("Password:", exact=True).fill(env["DJANGO_SUPERUSER_PASSWORD"])
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page.locator(".navbar-username")).to_have_text(env["DJANGO_SUPERUSER_USERNAME"])
            expect(page.locator(".navbar-username")).to_be_visible()
            output = Path(os.environ.get("ARCHIVEBOX_UI_SCREENSHOT_DIR", root / "screenshots"))
            output.mkdir(parents=True, exist_ok=True)
            for surface in ("add", "persona"):
                if surface == "add":
                    page.goto(base + "/add/")
                else:
                    page.goto(base + "/admin/personas/persona/")
                    page.get_by_role("link", name="Widget Review", exact=True).click()
                    primary = page.locator(".persona-card-primary").bounding_box()
                    settings = page.locator("#plugin-settings").bounding_box()
                    browser_state = page.locator(".field-import_artifact_status").bounding_box()
                    assert primary["height"] <= 200, "Persona identity fields should form one compact desktop row"
                    assert primary["y"] < settings["y"] < browser_state["y"], "Plugin settings should precede browser state"
                    assert page.locator("#id_created_by").bounding_box()["width"] >= 150, "The owner selector must keep its value readable"
                for plugin in PROVIDERS:
                    card = page.locator(f'.plugin-card[data-plugin-name="{plugin}"]')
                    page.locator(f'[role="tab"][data-plugin="{plugin}"]').click()
                    expect(card).to_be_visible()
                    expect(page.locator(".plugin-card:visible")).to_have_count(1)
                    if plugin in ("screenshot", "pdf"):
                        card.get_by_role("button", name="Phone").click()
                        expect(card.locator(f'[name="plugin_config__{plugin}__{plugin.upper()}_RESOLUTION"]')).to_have_value("390,844")
                        card.get_by_role("button", name="Desktop").click()
                    if plugin == "mobilesize":
                        slider = card.locator(".config-range-slider:not(.config-timeout-slider)")
                        slider.fill("7")
                        expect(card.locator('[name="plugin_config__mobilesize__MOBILESIZE_WAIT"]')).to_have_value("7")
                    if plugin == "puppeteer":
                        card.get_by_role("button", name="+ Expand details", exact=True).click()
                        expect(card.locator('textarea[data-config-key="PUPPETEER_SCRIPT"]')).to_have_value(
                            "await page.evaluate(() => {\n  document.querySelectorAll('details').forEach(el => el.open = true);\n});"
                        )
                    if plugin == "playwright":
                        card.get_by_role("button", name="+ Expand details", exact=True).click()
                        script = card.locator('textarea[data-config-key="PLAYWRIGHT_SCRIPT"]')
                        original = script.input_value()
                        card.get_by_role("button", name="+ Route by domain", exact=True).click()
                        assert original in script.input_value()
                        assert "__SCRIPT__" not in script.input_value()
                        assert "onDomain('example.com')" in script.input_value()
                    if plugin == "stagehand":
                        prompt = card.locator('textarea[data-config-key="STAGEHAND_PROMPT"]')
                        prompt.fill('Expand "read more" sections.\nKeep the page in English.')
                        card.get_by_role("button", name="+ Domain prompts", exact=True).click()
                        script = card.locator('textarea[data-config-key="STAGEHAND_SCRIPT"]')
                        assert "__VALUE__" not in script.input_value()
                        assert 'return {prompt: "Expand \\"read more\\" sections.\\nKeep the page in English."}' in script.input_value()
                    if plugin == "browserharness":
                        card.get_by_role("button", name="+ Expand details", exact=True).click()
                        script = card.locator('textarea[data-config-key="BROWSERHARNESS_SCRIPT"]')
                        original = script.input_value()
                        assert "querySelectorAll" in original
                        card.get_by_role("button", name="+ Domain guard", exact=True).click()
                        assert script.input_value().startswith("import sys\n")
                        assert script.input_value().endswith(original)
                        assert "sys.exit(10)" in script.input_value()
                    if plugin == "autosummary":
                        card.get_by_role("button", name="+ Bullet points", exact=True).click()
                        expect(card.locator('textarea[data-config-key="AUTOSUMMARY_PROMPT"]')).to_have_value(
                            "Use concise bullet points. Focus on the main ideas and conclusions."
                        )
                    expect(card.locator(".plugin-config-control").first).to_be_visible()
                    card.locator("textarea").evaluate_all("elements => elements.forEach(element => element.scrollTop = 0)")
                    page.locator(".plugin-settings-content").evaluate("element => element.scrollTop = 0")
                    page.locator(".plugin-config-form").screenshot(path=str(output / f"{surface}-{plugin}.png"))
                    if plugin in {"screenshot", "stagehand"}:
                        page.screenshot(path=str(output / f"{surface}-{plugin}-page.png"), full_page=True)
                search = page.get_by_role("searchbox", name="Search plugin settings")
                search.fill("BROWSER_COLOR_SCHEME")
                appearance = page.locator('.plugin-card[data-plugin-name="chrome"]')
                appearance.get_by_role("button", name="Dark", exact=True).click()
                expect(appearance.locator('.plugin-config-input[data-config-key="BROWSER_COLOR_SCHEME"]')).to_have_value("dark")
                search.fill("appearance")
                page.locator(".plugin-config-form").screenshot(path=str(output / f"{surface}-appearance.png"))
                search.fill("SCREENSHOT_RESOLUTION")
                expect(page.locator('[role="tab"]:visible')).to_have_count(1)
                expect(page.locator(".plugin-config-field:visible")).to_have_count(1)
                page.locator(".plugin-config-form").screenshot(path=str(output / f"{surface}-search.png"))
                search.fill("no matching setting xyz")
                expect(page.get_by_text("No settings found", exact=True)).to_be_visible()
                search.fill("")
                page.locator('[role="tab"][data-plugin="screenshot"]').click()
                page.set_viewport_size({"width": 390, "height": 844})
                page.locator(".plugin-config-form").screenshot(path=str(output / f"{surface}-screenshot-mobile.png"))
                page.screenshot(path=str(output / f"{surface}-screenshot-mobile-page.png"), full_page=True)
                page.set_viewport_size({"width": 1600, "height": 1100})
                if surface == "persona":
                    page.locator('button[name="_continue"]').click()
                    expect(page.locator(".success")).to_be_visible()
                    card = page.locator('.plugin-card[data-plugin-name="mobilesize"]')
                    page.locator('[role="tab"][data-plugin="mobilesize"]').click()
                    expect(card).to_be_visible()
                    expect(page.locator(".plugin-card:visible")).to_have_count(1)
                    expect(card.locator('[name="plugin_config__mobilesize__MOBILESIZE_WAIT"]')).to_have_value("7")
                    expect(card.locator(".config-range-slider:not(.config-timeout-slider)")).to_have_value("7")
                    page.locator('[role="tab"][data-plugin="puppeteer"]').click()
                    expect(page.locator('textarea[data-config-key="PUPPETEER_SCRIPT"]')).to_have_value(
                        "await page.evaluate(() => {\n  document.querySelectorAll('details').forEach(el => el.open = true);\n});"
                    )
                    page.locator('[role="tab"][data-plugin="autosummary"]').click()
                    expect(page.locator('textarea[data-config-key="AUTOSUMMARY_PROMPT"]')).to_have_value(
                        "Use concise bullet points. Focus on the main ideas and conclusions."
                    )
            browser.close()
    finally:
        stop_archivebox_process(server)
