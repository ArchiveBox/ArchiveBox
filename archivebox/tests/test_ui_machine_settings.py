import os
import json
import sqlite3
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from archivebox.config.configset import read_ini_config
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_machine_admin_uses_shared_settings_and_preserves_custom_config(live_server, admin_user, browser_runtime, tmp_path):
    machine = Machine.current()
    machine.config.update(
        BASE_URL=live_server.url,
        SERVER_SECURITY_MODE="safe-onedomain-nojsreplay",
        CUSTOM_SETTING={"keep": [42, "nested"]},
        OPENAI_API_KEY="machine-settings-secret",
    )
    machine.save(update_fields=["config"])
    original = dict(machine.config)
    change_url = reverse("admin:machine_machine_change", args=[machine.pk])

    def stored_config():
        with sqlite3.connect(f"file:{settings.DATABASES['default']['NAME']}?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT config FROM machine_machine WHERE id = ?", (machine.pk.hex,)).fetchone()
        return json.loads(row[0])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        page.goto(f"{live_server.url}/admin/login/?next={change_url}")
        page.get_by_label("Username:", exact=True).fill(admin_user.username)
        page.get_by_label("Password:", exact=True).fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        expect(page.locator("#plugin-settings")).to_be_visible()
        expect(page.get_by_role("tab", name="Server", exact=True)).to_be_visible()
        expect(page.get_by_role("tab", name="Authentication", exact=True)).to_be_visible()
        settings_box = page.locator("#plugin-settings").bounding_box()
        assert settings_box["width"] >= page.locator("#machine_form").bounding_box()["width"] * 0.95
        assert page.locator(".field-hostname").bounding_box()["y"] > settings_box["y"] + settings_box["height"]
        assert "machine-settings-secret" not in page.content()
        save = page.locator('button[name="_continue"]')
        save.click()
        expect(page.locator(".success")).to_be_visible()
        assert stored_config() == original

        page.locator('[role="tab"][data-plugin="wget"]').click()
        field = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="WGET_TIMEOUT"][name]'))
        field.locator(".config-quantity-unit").select_option("s")
        field.locator(".config-quantity-value").fill("77")
        save.click()
        expect(page.locator(".success")).to_be_visible()
        assert stored_config() == {**original, "WGET_TIMEOUT": 77}
        assert read_ini_config(tmp_path / "ArchiveBox.conf")["WGET_TIMEOUT"] == "77"

        custom = page.locator(".key-value-row").filter(has=page.locator('input.kv-key[value="CUSTOM_SETTING"]'))
        custom.locator(".kv-value").fill('{"keep": [42, "edited"]}')
        save.click()
        expect(page.locator(".success")).to_be_visible()
        assert stored_config() == {**original, "WGET_TIMEOUT": 77, "CUSTOM_SETTING": {"keep": [42, "edited"]}}
        page.get_by_role("tab", name="Server", exact=True).click()
        assert page.locator(".plugin-settings-content").evaluate("el => el.scrollHeight <= el.clientHeight + 1")
        page.evaluate("window.scrollTo(0, 0)")
        output = Path(os.environ.get("ARCHIVEBOX_UI_SCREENSHOT_DIR", tmp_path))
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / "machine-admin-settings.png"), full_page=True)
        browser.close()
