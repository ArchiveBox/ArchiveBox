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
    url = reverse("admin:machine_machine_change", args=[Machine.current().pk])
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
                    page.goto(base + f"/admin/machine/machine/{machine_id}/change/")
                    save = page.locator('button[name="_continue"]')
                else:
                    page.goto(base + "/admin/personas/persona/")
                    page.get_by_role("link", name="Research", exact=True).click()
                    save = page.locator('button[name="_continue"]')
                expect(page.locator("#plugin-settings")).to_be_visible()
                core_tabs = page.locator('[role="tab"][id^="plugin-tab-system-"]')
                expect(core_tabs).to_have_text(
                    ["Crawl Defaults", "Server", "Authentication"] if surface == "system" else ["Crawl Defaults"],
                )
                expect(core_tabs.locator("svg")).to_have_count(3 if surface == "system" else 1)
                if surface == "system":
                    for tab, keys in (
                        ("Server", ("SEARCH_BACKEND_ENGINE", "PUBLIC_INDEX")),
                        ("Authentication", ("ALLAUTH_ENABLED", "LDAP_ENABLED")),
                    ):
                        page.get_by_role("tab", name=tab, exact=True).click()
                        panel = page.locator('[role="tabpanel"]:visible')
                        for key in keys:
                            expect(panel.locator(f'[data-config-key="{key}"][name]').first).to_be_visible()
                        content = page.locator(".plugin-settings-content")
                        assert content.evaluate("el => el.scrollHeight <= el.clientHeight + 1")
                        panel.locator(".plugin-config-field:visible").last.scroll_into_view_if_needed()
                        assert page.evaluate("window.scrollY") > 0
                        assert content.evaluate("el => el.scrollTop") == 0
                        sidebar = page.locator(".plugin-settings-sidebar").bounding_box()
                        panel_bounds = page.locator("#plugin-settings").bounding_box()
                        sticky_top = page.locator(".plugin-settings-sidebar").evaluate("el => parseFloat(getComputedStyle(el).top)")
                        expected_top = max(
                            panel_bounds["y"] + 1,
                            min(sticky_top, panel_bounds["y"] + panel_bounds["height"] - sidebar["height"] - 1),
                        )
                        assert abs(sidebar["y"] - expected_top) <= 1
                        page.evaluate("window.scrollTo(0, 0)")
                        page.screenshot(path=str(output / f"system-{tab.lower()}.png"), full_page=True)
                page.get_by_role("tab", name="Crawl Defaults", exact=True).click()
                for plugin in discover_plugin_configs():
                    if plugin == "base" or plugin.startswith("search_backend_"):
                        expect(page.locator(f'[role="tab"][data-plugin="{plugin}"]')).to_have_count(1)
                assert f"{surface}-secret" not in page.content()
                search = page.get_by_role("searchbox", name="Search plugin settings")
                for key, preset, zero_label, unit, amount in (
                    ("CRAWL_MAX_URLS", "10000", "No limit", None, "10000"),
                    ("CRAWL_MAX_SIZE", "100000000000", "No limit", "GB", "100"),
                    ("SNAPSHOT_MAX_SIZE", "3000000000", "No limit", "GB", "3"),
                    ("CRAWL_TIMEOUT", "86400", "No limit", "h", "24"),
                    ("DELETE_AFTER", "1y", "Keep forever", "y", "1"),
                ):
                    search.fill(key)
                    canonical = page.locator(f'[data-config-key="{key}"][name]')
                    field = page.locator(".plugin-config-field").filter(has=canonical)
                    editable = field.locator(".config-quantity-value" if unit else ".config-zero-value")
                    expect(canonical).to_have_value("0" if key == "DELETE_AFTER" else preset)
                    expect(editable).to_be_visible()
                    expect(editable).to_have_attribute("placeholder", zero_label)
                    expect(field.locator("input[type=range]")).to_be_visible()
                    if unit:
                        field.locator(".config-quantity-unit").select_option(unit)
                    editable.fill(amount)
                    expect(canonical).to_have_value(preset)
                    editable.fill("")
                    expect(canonical).to_have_value("0")
                    expect(editable).to_be_visible()
                    expect(editable).to_have_value("")
                    if key != "DELETE_AFTER":
                        editable.fill(amount)
                        expect(canonical).to_have_value(preset)
                    if key == "DELETE_AFTER":
                        field.scroll_into_view_if_needed()
                        page.screenshot(path=str(output / f"{surface}-retention-defaults.png"), full_page=True)
                search.fill("CRAWL_MAX_CONCURRENT_SNAPSHOTS")
                concurrency = page.locator(".config-concurrency")
                editable = concurrency.locator(".config-concurrency-value")
                expect(editable).to_be_visible()
                expect(editable).to_have_value("2")
                expect(editable).to_have_attribute("placeholder", "Automatic")
                expect(concurrency.locator("[data-concurrency-slider]")).to_be_visible()
                editable.fill("2")
                expect(concurrency.locator(".plugin-config-input")).to_have_value("2")
                editable.fill("")
                expect(concurrency.locator(".plugin-config-input")).to_have_value("0")
                expect(concurrency.locator(".config-concurrency-limit")).to_be_visible()
                expect(editable).to_have_value("")
                editable.fill("2")
                search.fill("")
                page.get_by_role("tab", name="Crawl Defaults", exact=True).click()
                assert page.locator(".plugin-settings-content").evaluate("el => el.scrollHeight <= el.clientHeight + 1")
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(output / f"{surface}-defaults.png"), full_page=True)
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

            page.goto(base + f"/admin/machine/machine/{machine_id}/change/")
            page.locator('[role="tab"][data-plugin="screenshot"]').click()
            screenshot_timeout = page.locator(".plugin-config-field").filter(
                has=page.locator('[data-config-key="SCREENSHOT_TIMEOUT"][name]'),
            )
            screenshot_timeout.locator(".config-quantity-unit").select_option("s")
            screenshot_timeout.locator(".config-quantity-value").fill("91")
            search = page.get_by_role("searchbox", name="Search plugin settings")
            search.fill("URL_ALLOWLIST")
            page.locator('[name="plugin_config__archivebox__URL_ALLOWLIST"]').fill("[")
            page.locator('button[name="_continue"]').click()
            expect(page.locator(".errorlist").first).to_be_visible()
            assert stored_config("system") == initial_machine
            search.fill("URL_ALLOWLIST")
            page.locator('[name="plugin_config__archivebox__URL_ALLOWLIST"]').fill("")
            page.locator('button[name="_continue"]').click()
            expect(page.locator(".success")).to_be_visible()
            assert stored_config("system") == {**initial_machine, "SCREENSHOT_TIMEOUT": 91}
            assert read_ini_config(root / "ArchiveBox.conf")["SCREENSHOT_TIMEOUT"] == "91"

            search.fill("CRAWL_MAX_URLS")
            url_limit = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="CRAWL_MAX_URLS"][name]'))
            url_limit.locator(".config-limit-slider").fill("250")
            expect(url_limit.locator("[name]")).to_have_value("250")
            url_limit.locator(".config-zero-value").fill("375")
            expect(url_limit.locator(".config-limit-slider")).to_have_value("375")

            search.fill("CRAWL_MAX_SIZE")
            size_limit = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="CRAWL_MAX_SIZE"][name]'))
            size_limit.locator(".config-quantity-unit").select_option("GiB")
            size_limit.locator(".config-quantity-value").fill("2")
            expect(size_limit.locator("[name]")).to_have_value("2147483648")
            expect(size_limit.locator(".config-limit-slider")).to_have_attribute("max", "100000000000000")
            expect(size_limit.locator(".config-limit-slider")).to_have_value("2147483648")

            search.fill("DELETE_AFTER")
            retention = page.locator(".plugin-config-field").filter(has=page.locator('[data-config-key="DELETE_AFTER"][name]'))
            retention.locator(".config-quantity-unit").select_option("d")
            retention.locator(".config-quantity-value").fill("30")
            expect(retention.locator("[name]")).to_have_value("30d")
            page.locator('button[name="_continue"]').click()
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
            page.locator('button[name="_continue"]').click()
            expect(page.locator(".success")).to_be_visible()
            assert stored_config("system") == final_config
            search.fill("")
            page.get_by_role("tab", name="Crawl Defaults", exact=True).click()
            page.locator(".plugin-settings-tabs").evaluate("element => element.scrollTop = 0")
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(output / "system-core.png"), full_page=True)
            # Explicit zero overrides remain available without an extra mode click.
            for key in ("CRAWL_MAX_URLS", "CRAWL_MAX_SIZE", "SNAPSHOT_MAX_SIZE", "CRAWL_TIMEOUT", "CRAWL_MAX_CONCURRENT_SNAPSHOTS"):
                search.fill(key)
                canonical = page.locator(f'[data-config-key="{key}"][name]')
                field = page.locator(".plugin-config-field").filter(has=canonical)
                field.locator(".config-zero-value, .config-quantity-value, .config-concurrency-value").fill("")
                expect(canonical).to_have_value("0")
                final_config[key] = 0
            page.locator('button[name="_continue"]').click()
            expect(page.locator(".success")).to_be_visible()
            assert stored_config("system") == final_config
            search.fill("CRAWL_MAX_CONCURRENT_SNAPSHOTS")
            expect(page.locator(".config-concurrency-value")).to_have_value("")
            expect(page.locator(".config-concurrency-value")).to_have_attribute("placeholder", "Automatic")
            page.locator('button[name="_continue"]').click()
            expect(page.locator(".success")).to_be_visible()
            assert stored_config("system") == final_config
            # Save as soon as it becomes clickable on a real, bandwidth-limited
            # response. The toolbar renders before the settings form finishes.
            network = page.context.new_cdp_session(page)
            network.send("Network.enable")
            network.send(
                "Network.emulateNetworkConditions",
                {"offline": False, "latency": 0, "downloadThroughput": 256_000, "uploadThroughput": 256_000},
            )
            page.goto(base + f"/admin/machine/machine/{machine_id}/change/", wait_until="commit")
            with page.expect_request(
                lambda request: request.method == "POST" and request.url.endswith(f"/admin/machine/machine/{machine_id}/change/"),
            ) as submission:
                page.locator('button[name="_continue"]').click()
            assert "settings_editor=1" in submission.value.post_data
            expect(page.locator(".success")).to_be_visible()
            assert stored_config("system") == final_config
            network.detach()
            browser.close()
    finally:
        stop_archivebox_process(server)
