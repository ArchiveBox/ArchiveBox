"""Preset actions publish the final selection rather than each intermediate row."""

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from archivebox.config.common import get_config
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Machine
from archivebox.plugins.discovery import get_enabled_plugins
from archivebox.plugins.selection import parse_plugin_selection


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("preset", ["select-all", "clear-all", "text-only"])
def test_add_preset_updates_plugin_settings_and_saves_once(live_server, browser_runtime, admin_user, preset):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    origin = f"http://admin.archivebox.localhost:{port}"

    def installed_plan():
        crawl = Crawl.objects.get(created_by=admin_user)
        effective = get_config(crawl=crawl)
        return crawl.status, crawl.config["PLUGINS"], effective.PLUGINS, set(get_enabled_plugins(config=effective))

    with ThreadPoolExecutor(max_workers=1) as reader, sync_playwright() as playwright:
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
        assert "PLUGINS" not in config
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
            assert "PLUGINS" not in updated
            assert not page.locator('.plugin-section-toggle[value="screenshot"]').is_checked()
            plugins.remove("screenshot")

        page.locator('textarea[name="url"]').fill(f"https://example.com/{preset}")
        page.locator(".advanced-section > summary").click()
        page.locator('input[name="start_paused"]').check()
        groups = sorted({key.split(":", 1)[0] for key, _checked in selected})
        submission = page.locator("#add-form").evaluate(
            """(form, groups) => {
                const fields = new FormData(form);
                return {plugins: groups.flatMap(name => fields.getAll(name)),
                        mode: fields.get('capture_plugins'), config: JSON.parse(fields.get('config'))};
            }""",
            groups,
        )
        assert set(submission["plugins"]) == plugins
        assert submission["mode"] is None
        assert "PLUGINS" not in submission["config"]
        with page.expect_response(
            lambda response: response.request.method == "POST" and urlsplit(response.url).path == "/add/",
        ) as submitted:
            page.locator("#submit").click()
        assert submitted.value.status == 302
        status, stored, effective, active = reader.submit(installed_plan).result()
        assert status == "paused"
        assert parse_plugin_selection(effective) == parse_plugin_selection(stored)
        if preset == "clear-all":
            assert stored == effective == ""
            assert {"wget", "title"} <= active
        elif preset == "text-only":
            assert set(parse_plugin_selection(stored) or []) == plugins
            assert {"dom", "title", "hashes"} <= active
            assert {"screenshot", "wget", "singlefile"}.isdisjoint(active)
        else:
            assert set(parse_plugin_selection(stored) or []) == plugins
            assert {"wget", "title"} <= active
            assert "screenshot" not in active
        browser.close()
