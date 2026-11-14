import json
import os
import sqlite3
from pathlib import Path

import pytest
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from archivebox.config.configset import read_ini_config
from archivebox.machine.models import Machine
from archivebox.plugins.discovery import discover_plugin_configs
from archivebox.tests.conftest import (
    ADMIN_TEST_HOST,
    cli_env,
    get_free_port,
    run_archivebox_cmd,
    run_python_cwd,
    start_archivebox_server,
    stop_archivebox_process,
)


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "post"])
def test_system_settings_requires_superuser(client, django_user_model, method):
    url = reverse("system-settings")
    assert getattr(client, method)(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    staff = django_user_model.objects.create_user(username="settings-staff", is_staff=True)
    client.force_login(staff)
    before = list(Machine.objects.values_list("config", flat=True))
    response = getattr(client, method)(
        url,
        {"settings_editor": "1", "settings_changed": "TIMEOUT", "plugin_config__archivebox__TIMEOUT": "99"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 403
    assert list(Machine.objects.values_list("config", flat=True)) == before


@pytest.mark.django_db(transaction=True)
def test_system_and_persona_settings_save_only_edited_overrides_in_browser(initialized_archive, browser_runtime):
    root = initialized_archive
    stdout, stderr, code = run_python_cwd(
        """
import json
import django
django.setup()
from archivebox.config.common import get_config
from archivebox.machine.models import Machine
from archivebox.personas.models import Persona
machine = Machine.current()
baseline = get_config(include_machine=False, include_file=False)
machine.config.update(SCREENSHOT_WAIT_FOR_TEXT='', CUSTOM_SETTING={'keep': ['nested', 42]}, OPENAI_API_KEY='system-secret')
machine.save(update_fields=['config'])
Persona.objects.create(name='Research', config={'PERMISSIONS': 'private', 'SCREENSHOT_WAIT_FOR_TEXT': '', 'CUSTOM_SETTING': {'keep': ['persona', 42]}, 'OPENAI_API_KEY': 'persona-secret'})
print(json.dumps({'timeout': baseline.WGET_TIMEOUT, 'machine_id': str(machine.pk)}))
""",
        cwd=root,
    )
    assert code == 0, stderr
    setup = json.loads(stdout.splitlines()[-1])
    inherited_timeout = setup["timeout"]
    machine_id = setup["machine_id"]
    port = get_free_port()
    env = cli_env(
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
        DJANGO_SUPERUSER_USERNAME="settings-review",
        DJANGO_SUPERUSER_PASSWORD="local-settings-test-password",
        DJANGO_SUPERUSER_EMAIL="settings@example.com",
    )
    result = run_archivebox_cmd(["manage", "createsuperuser", "--noinput"], cwd=root, env=env, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr

    def stored_config(surface):
        with sqlite3.connect(f"file:{root / 'index.sqlite3'}?mode=ro", uri=True) as connection:
            if surface == "system":
                row = connection.execute("SELECT config FROM machine_machine WHERE id = ?", (machine_id,)).fetchone()
            else:
                row = connection.execute("SELECT config FROM personas_persona WHERE name = ?", ("Research",)).fetchone()
        return json.loads(row[0])

    initial_machine = stored_config("system")
    initial_persona = stored_config("persona")
    output = Path(os.environ.get("ARCHIVEBOX_UI_SCREENSHOT_DIR", root / "screenshots"))
    output.mkdir(parents=True, exist_ok=True)
    server = start_archivebox_server(root, port=port, env=env, log_name="settings-server.log")
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

            for surface in ("system", "persona"):
                if surface == "system":
                    page.goto(base + "/admin/settings/")
                    save = page.get_by_role("button", name="Save settings", exact=True)
                else:
                    page.goto(base + "/admin/personas/persona/")
                    page.get_by_role("link", name="Research", exact=True).click()
                    save = page.locator('button[name="_continue"]')
                expect(page.locator("#plugin-settings")).to_be_visible()
                for plugin in discover_plugin_configs():
                    if plugin == "base" or plugin.startswith("search_backend_"):
                        expect(page.locator(f'[role="tab"][data-plugin="{plugin}"]')).to_have_count(1)
                assert f"{surface}-secret" not in page.content()
                if surface == "system":
                    page.locator(".plugin-settings-tabs").evaluate("element => element.scrollTop = 0")
                    page.screenshot(path=str(output / "system-core.png"), full_page=True)
                # An unchanged save must retain deliberate equal-default overrides,
                # unknown plugin settings, and write-only credentials.
                save.click()
                expect(page.locator(".success")).to_be_visible()
                unchanged = stored_config(surface)
                assert unchanged == (initial_machine if surface == "system" else initial_persona)
                page.locator('[role="tab"][data-plugin="wget"]').click()
                field = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="WGET_TIMEOUT"][name]'))
                field.locator(".config-quantity-unit").select_option("s")
                field.locator(".config-quantity-value").fill("77")
                save.click()
                expect(page.locator(".success")).to_be_visible()
                saved = stored_config(surface)
                assert saved == {**(initial_machine if surface == "system" else initial_persona), "WGET_TIMEOUT": 77}
                if surface == "system":
                    assert read_ini_config(root / "ArchiveBox.conf")["WGET_TIMEOUT"] == "77"
                page.locator('[role="tab"][data-plugin="wget"]').click()
                page.locator(".plugin-settings-tabs").evaluate("element => element.scrollTop = 0")
                page.screenshot(path=str(output / f"{surface}.png"), full_page=True)
                field.locator(".config-quantity-unit").select_option("s")
                field.locator(".config-quantity-value").fill(str(inherited_timeout))
                save.click()
                expect(page.locator(".success")).to_be_visible()
                restored = stored_config(surface)
                assert restored == (initial_machine if surface == "system" else initial_persona)
                if surface == "system":
                    assert "WGET_TIMEOUT" not in read_ini_config(root / "ArchiveBox.conf")

            search = page.get_by_role("searchbox", name="Search plugin settings")
            search.fill("URL_ALLOWLIST")
            rules = page.locator(".config-url-rules").filter(has=page.locator('[data-config-key="URL_ALLOWLIST"]'))
            rules.locator("[data-rule-entries]").fill("example.com")
            rules.locator('[data-rule-action="append"]').click()
            expect(rules.locator(".config-rule-raw")).not_to_be_empty()
            rules.locator("summary").click()
            rules.locator("[data-rule-urls]").fill("https://example.com/article\nhttps://other.org/article")
            rules.locator('[data-rule-action="preview"]').click()
            expect(rules.locator('[data-allowed="true"]')).to_have_count(1)
            expect(rules.locator('[data-allowed="false"]')).to_have_count(1)
            page.screenshot(path=str(output / "persona-rules.png"), full_page=True)

            page.goto(base + "/admin/settings/")
            page.locator('[role="tab"][data-plugin="screenshot"]').click()
            screenshot_timeout = page.locator(".plugin-config-field").filter(
                has=page.locator('[data-config-key="SCREENSHOT_TIMEOUT"][name]'),
            )
            screenshot_timeout.locator(".config-quantity-unit").select_option("s")
            screenshot_timeout.locator(".config-quantity-value").fill("91")
            search = page.get_by_role("searchbox", name="Search plugin settings")
            search.fill("URL_ALLOWLIST")
            page.locator('[name="plugin_config__archivebox__URL_ALLOWLIST"]').fill("[")
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".errorlist").first).to_be_visible()
            assert stored_config("system") == initial_machine
            search.fill("URL_ALLOWLIST")
            page.locator('[name="plugin_config__archivebox__URL_ALLOWLIST"]').fill("")
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".success")).to_be_visible()
            assert stored_config("system") == {**initial_machine, "SCREENSHOT_TIMEOUT": 91}
            assert read_ini_config(root / "ArchiveBox.conf")["SCREENSHOT_TIMEOUT"] == "91"

            search.fill("CRAWL_MAX_URLS")
            url_limit = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="CRAWL_MAX_URLS"][name]'))
            url_limit.locator(".config-limit-slider").fill("250")
            expect(url_limit.locator("[name]")).to_have_value("250")
            url_limit.locator("[name]").fill("375")
            expect(url_limit.locator(".config-limit-slider")).to_have_value("375")

            search.fill("CRAWL_MAX_SIZE")
            size_limit = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="CRAWL_MAX_SIZE"][name]'))
            size_limit.locator(".config-quantity-unit").select_option("GiB")
            size_limit.locator(".config-quantity-value").fill("2")
            expect(size_limit.locator("[name]")).to_have_value("2147483648")
            expect(size_limit.locator(".config-limit-slider")).to_have_attribute("max", "107374182400")
            expect(size_limit.locator(".config-limit-slider")).to_have_value("2147483648")

            search.fill("DELETE_AFTER")
            retention = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="DELETE_AFTER"][name]'))
            retention.locator(".config-quantity-unit").select_option("d")
            retention.locator(".config-quantity-value").fill("30")
            expect(retention.locator("[name]")).to_have_value("30d")
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".success")).to_be_visible()
            final_config = {
                **initial_machine,
                "SCREENSHOT_TIMEOUT": 91,
                "CRAWL_MAX_URLS": 375,
                "CRAWL_MAX_SIZE": 2147483648,
                "DELETE_AFTER": "30d",
            }
            assert stored_config("system") == final_config
            mirrored = read_ini_config(root / "ArchiveBox.conf")
            assert mirrored["CRAWL_MAX_URLS"] == "375"
            assert mirrored["CRAWL_MAX_SIZE"] == "2147483648"
            assert mirrored["DELETE_AFTER"] == "30d"
            page.get_by_role("button", name="Save settings", exact=True).click()
            expect(page.locator(".success")).to_be_visible()
            assert stored_config("system") == final_config
            search.fill("")
            page.get_by_role("tab", name="Archiving", exact=True).click()
            page.locator(".plugin-settings-tabs").evaluate("element => element.scrollTop = 0")
            page.locator(".plugin-settings-content").evaluate("element => element.scrollTop = 0")
            page.screenshot(path=str(output / "system-core.png"), full_page=True)
            browser.close()
    finally:
        stop_archivebox_process(server)
