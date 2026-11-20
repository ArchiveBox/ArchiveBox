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
from archivebox.personas.models import Persona


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
        server_tab = page.get_by_role("tab", name="Server", exact=True)
        expect(server_tab).to_be_visible()
        expect(page.get_by_role("tab", name="Authentication", exact=True)).to_be_visible()
        # The initial fallback renders every panel until the tabs are initialized.
        expect(server_tab).to_be_enabled()
        layout = page.evaluate("""() => {
            const settings = document.querySelector('#plugin-settings').getBoundingClientRect();
            const form = document.querySelector('#machine_form').getBoundingClientRect();
            const hostname = document.querySelector('.field-hostname').getBoundingClientRect();
            return {settingsWidth: settings.width, formWidth: form.width, settingsBottom: settings.bottom, hostnameTop: hostname.top};
        }""")
        assert layout["settingsWidth"] >= layout["formWidth"] * 0.95
        assert layout["hostnameTop"] > layout["settingsBottom"]
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


@pytest.mark.django_db(transaction=True)
def test_machine_and_persona_save_at_both_right_edges(live_server, admin_user, browser_runtime):
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": live_server.url}
    machine.save(update_fields=["config"])
    persona = Persona.objects.create(name="Settings save controls")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(live_server.url + "/admin/login/")
        page.get_by_label("Username:", exact=True).fill(admin_user.username)
        page.get_by_label("Password:", exact=True).fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        for model_name, model, route in (
            ("machine", machine, "admin:machine_machine_change"),
            ("persona", persona, "admin:personas_persona_change"),
        ):
            url = live_server.url + reverse(route, args=[model.pk])
            page.goto(url)
            top = page.locator(".archivebox-toolbar .ab-settings-save-top")
            bottom = page.locator(".ab-settings-save-footer input")
            expect(page.locator('[type="submit"][name="_continue"]')).to_have_count(2)
            for width in (1440, 390):
                page.set_viewport_size({"width": width, "height": 900})
                for button, container in ((top, ".archivebox-toolbar"), (bottom, ".ab-settings-save-footer")):
                    expect(button).to_be_enabled()
                    assert button.evaluate("input => input.form.id") == f"{model_name}_form"
                    parent = page.locator(container).bounding_box()
                    control = button.bounding_box()
                    assert 0 <= parent["x"] + parent["width"] - control["x"] - control["width"] < 16
            posts = []

            def listener(request):
                if request.method == "POST":
                    posts.append(request)

            page.on("request", listener)
            for value, button in ((71, top), (73, bottom)):
                page.get_by_role("tab", name="Wget", exact=False).first.click()
                field = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="WGET_TIMEOUT"][name]'))
                field.locator(".config-quantity-unit").select_option("s")
                field.locator(".config-quantity-value").fill(str(value))
                with page.expect_response(lambda response: response.request.method == "POST") as submitted:
                    button.click()
                assert submitted.value.status == 302
                expect(page.locator(".messagelist .success")).to_be_visible()
                expect(page).to_have_url(url)
                assert len(posts) == (1 if value == 71 else 2)
                assert "_continue" in (posts[-1].post_data or "")
                page.get_by_role("tab", name="Wget", exact=False).first.click()
                expect(field.locator(".config-quantity-value")).to_have_value(str(value))
            page.remove_listener("request", listener)

        page.goto(live_server.url + reverse("admin:personas_persona_add"))
        expect(page.locator('[type="submit"][name="_save"]')).to_have_count(2)
        page.goto(live_server.url + "/add/")
        expect(page.locator("[data-settings-submit]")).to_have_count(1)
        expect(page.locator("#submit")).to_contain_text("Create Crawl")
