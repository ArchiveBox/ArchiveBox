"""Preset actions publish the final selection rather than each intermediate row."""

import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("preset", ["select-all", "clear-all", "text-only"])
def test_add_preset_updates_plugin_settings_and_saves_once(live_server, browser_runtime, admin_user, preset):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    origin = f"http://admin.archivebox.localhost:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{origin}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.goto(f"{origin}/add/")
        page.evaluate("""() => {
            document.addEventListener('click', event => {
                if (event.target.closest('[data-preset]')) window.selectionStarted = performance.now();
            }, true);
            document.addEventListener('click', event => {
                if (event.target.closest('[data-preset]')) window.selectionElapsed = performance.now() - selectionStarted;
            });
        }""")
        observer = page.context.new_page()
        observer.goto(f"{origin}/admin/")
        observer.evaluate("""() => {
            window.selectionWrites = [];
            addEventListener('storage', event => {
                if (event.key === 'archivebox_add_form_state') selectionWrites.push(JSON.parse(event.newValue));
            });
        }""")
        page.locator(f'[data-preset="{preset}"]').click()
        observer.wait_for_function("selectionWrites.length > 0")
        writes = observer.evaluate("selectionWrites")
        selected = page.locator(".plugin-section-toggle").evaluate_all(
            "inputs => inputs.map(input => [input.name + ':' + input.value, input.checked])",
        )
        assert len(selected) > 20
        assert all(writes[-1][key] == checked for key, checked in selected)
        plugins = {key.split(":", 1)[1] for key, checked in selected if checked}
        if preset == "select-all":
            assert all(checked for _key, checked in selected)
        elif preset == "clear-all":
            assert plugins == set()
        else:
            assert {"dom", "title", "hashes"} <= plugins
            assert {"screenshot", "wget", "singlefile"}.isdisjoint(plugins)
        config = json.loads(page.locator('[name="config"]').input_value())
        assert set(filter(None, config.get("PLUGINS", "").split(","))) == plugins
        mirrors = page.locator(".plugin-card[data-plugin-enabled-key]").evaluate_all("""cards => cards.flatMap(card => {
            const toggle = card.querySelector('.plugin-section-toggle');
            if (!toggle) return [];
            const input = card.querySelector(`.plugin-config-input[data-config-key="${CSS.escape(card.dataset.pluginEnabledKey)}"]`);
            const sidebar = document.querySelector(`.plugin-sidebar-toggle[data-plugin="${CSS.escape(toggle.value)}"]`);
            return [{plugin: toggle.value, checked: toggle.checked, input: input?.checked, type: input?.type, sidebar: sidebar?.checked}];
        })""")
        assert len(mirrors) > 20
        assert all(item["checked"] == item["sidebar"] for item in mirrors)
        assert all(item["checked"] == item["input"] for item in mirrors if item["type"] == "checkbox"), mirrors
        print("Preset synchronous handler milliseconds:", preset, page.evaluate("selectionElapsed"))
        assert len(writes) == 1, f"One preset serialized and saved {len(writes)} intermediate form states"
        if preset == "select-all":
            page.locator('.plugin-sidebar-toggle[data-plugin="screenshot"]').uncheck()
            updated = json.loads(page.locator('[name="config"]').input_value())
            assert "screenshot" not in updated["PLUGINS"].split(",")
            assert not page.locator('.plugin-section-toggle[value="screenshot"]').is_checked()
        browser.close()
