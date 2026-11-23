"""Provider keys have one masked settings home and reach only their intended plugins."""

import asyncio
import json
import re

import pytest
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST


pytestmark = pytest.mark.django_db
PANEL = "plugin-panel-shared_settings-opencode_providers"
PROVIDER_KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def test_provider_settings_have_one_masked_home_per_scope(admin_client, admin_user):
    from archivebox.machine.models import Machine
    from archivebox.personas.models import Persona

    machine = Machine.current()
    machine.config = dict.fromkeys(PROVIDER_KEYS, "synthetic-machine-marker")
    machine.save(update_fields=["config"])
    persona = Persona.objects.create(
        name="Provider credentials",
        created_by=admin_user,
        config=dict.fromkeys(PROVIDER_KEYS, "synthetic-persona-marker"),
    )
    for name, obj in (("personas_persona", persona), ("machine_machine", machine)):
        page = admin_client.get(reverse(f"admin:{name}_change", args=[obj.pk]), HTTP_HOST=ADMIN_TEST_HOST)
        assert page.status_code == 200
        html = page.content.decode()
        assert f'id="{PANEL}"' in html
        assert 'data-plugin-name="browserharness"' in html
        assert f'href="#{PANEL}">Edit API keys via OpenCode' in html
        assert "synthetic-persona-marker" not in html
        assert "synthetic-machine-marker" not in html
        for key in PROVIDER_KEYS:
            fields = re.findall(rf'<input[^>]*data-config-key="{key}"[^>]*>', html, re.S)
            assert len(fields) == 1
            assert 'type="password"' in fields[0] and 'value=""' in fields[0]
            assert f'name="plugin_config__opencode_providers__{key}"' in fields[0]
        for key in ("KAGI_SEARCH_API_KEY", "BRAVE_SEARCH_API_KEY", "EXA_SEARCH_API_KEY"):
            fields = re.findall(rf'<input[^>]*data-config-key="{key}"[^>]*>', html, re.S)
            assert len(fields) == 1
            assert 'type="password"' in fields[0]
            assert f'name="plugin_config__importer_search__{key}"' in fields[0]
        data = {
            "settings_editor": "1",
            "settings_changed": ["OPENAI_API_KEY"],
            "plugin_config__opencode_providers__OPENAI_API_KEY": "synthetic-new-marker",
            "config": json.dumps(dict.fromkeys(PROVIDER_KEYS, "")),
            "_save": "Save",
        }
        if name == "personas_persona":
            data.update(name=persona.name, created_by=str(admin_user.pk), permissions="public")
        else:
            form = page.context["adminform"].form
            data.update(
                {
                    field_name: form[field_name].value()
                    for field_name, field in form.fields.items()
                    if field.required and field_name not in data
                },
            )
        response = admin_client.post(reverse(f"admin:{name}_change", args=[obj.pk]), data, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 302
        obj.refresh_from_db()
        assert obj.config["OPENAI_API_KEY"] == "synthetic-new-marker"
        assert obj.config["ANTHROPIC_API_KEY"] == ("synthetic-persona-marker" if name == "personas_persona" else "synthetic-machine-marker")


@pytest.mark.django_db(transaction=True)
def test_provider_hook_env_obeys_real_dependency_graph(admin_user, tmp_path):
    from abx_dl.config import GlobalConfig, RuntimeConfig, get_plugin_env
    from asgiref.sync import async_to_sync

    from archivebox.config.common import build_crawl_config_snapshot, get_config
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import _importer_env
    from archivebox.machine.models import Machine
    from archivebox.personas.models import Persona
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.workers.runner import CrawlRunner

    machine = Machine.current()
    machine.config = dict.fromkeys((*PROVIDER_KEYS, "EXA_SEARCH_API_KEY"), "synthetic-machine-marker")
    machine.save(update_fields=["config"])
    persona = Persona.objects.create(
        name="Provider credentials",
        created_by=admin_user,
        config={"OPENAI_API_KEY": "synthetic-persona-marker", "EXA_SEARCH_API_KEY": "synthetic-exa-marker"},
    )
    config = get_config(persona=persona, machine=machine)
    assert not set(PROVIDER_KEYS).intersection(build_crawl_config_snapshot(persona=persona))
    crawl = Crawl.objects.create(urls="https://example.com/provider-fixture", persona=persona, created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    runner = CrawlRunner(crawl, show_progress=False)
    try:
        payload = async_to_sync(runner.load_snapshot_payload)(str(snapshot.pk))
    finally:
        asyncio.run(runner.bus.destroy(clear=False))
    runtime = RuntimeConfig(user=GlobalConfig(**payload["config"]), derived={})
    catalog = get_plugin_catalog()
    selection = catalog.select(["browserharness"])
    assert "opencode_providers" in selection
    assert "opencode" not in selection
    assert not selection["opencode_providers"].hooks

    async def get_env(name):
        return (await get_plugin_env(None, plugin=catalog[name], run_output_dir=tmp_path, config=runtime)).to_env()

    for plugin in ("browserharness", "stagehand", "autosummary", "autotag"):
        env = asyncio.run(get_env(plugin))
        assert env["OPENAI_API_KEY"] == "synthetic-persona-marker"
        assert env["ANTHROPIC_API_KEY"] == "synthetic-machine-marker"
        assert not env.get("EXA_SEARCH_API_KEY")
    for plugin in ("screenshot", "opencode", "claudecode", "claudechrome"):
        env = asyncio.run(get_env(plugin))
        assert not env.get("OPENAI_API_KEY")
        if plugin.startswith("claude"):
            assert env["ANTHROPIC_API_KEY"] == "synthetic-machine-marker"
        else:
            assert not env.get("ANTHROPIC_API_KEY")

    for plugin, feed in (("importer_search", "exa"), ("importer_rss", "rss"), ("importers_browser", "x_bookmarks")):
        source = ImporterSource(name=plugin, plugin=plugin, feed=feed, created_by=admin_user, persona=persona)
        env = _importer_env(source, config)
        if plugin == "importers_browser":
            assert env["OPENAI_API_KEY"] == "synthetic-persona-marker"
            assert env["ANTHROPIC_API_KEY"] == "synthetic-machine-marker"
        else:
            assert not set(PROVIDER_KEYS).intersection(env)
        if plugin == "importer_search":
            assert env["EXA_SEARCH_API_KEY"] == "synthetic-exa-marker"


@pytest.mark.django_db(transaction=True)
def test_open_provider_keys_from_browser_harness_in_both_settings_forms(live_server, admin_user, browser_runtime):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine
    from archivebox.personas.models import Persona

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    persona = Persona.objects.create(name="Scoped keys browser fixture", created_by=admin_user)
    origin = f"http://admin.archivebox.localhost:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(f"{origin}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        for route, obj in (("personas_persona", persona), ("machine_machine", machine)):
            path = reverse(f"admin:{route}_change", args=[obj.pk])
            page.goto(origin + path)
            search = page.get_by_role("searchbox", name="Search plugin settings")
            search.fill("browserharness")
            dep_tab = page.locator('[role="tab"][data-plugin="browserharness"]')
            expect(dep_tab).to_have_attribute("aria-selected", "true")
            link = page.locator('[role="tabpanel"][data-plugin-name="browserharness"]').get_by_role(
                "link",
                name="Edit API keys via OpenCode →",
                exact=True,
            )
            panel = page.locator(f"#{PANEL}")
            for activate in (link.click, lambda: link.press("Enter")):
                activate()
                expect(page).to_have_url(f"{origin}{path}#{PANEL}")
                expect(panel).to_be_visible()
                expect(panel).to_be_focused()
                expect(search).to_have_value("")
                for key in PROVIDER_KEYS:
                    expect(panel.locator(f'input[data-config-key="{key}"][type="password"]')).to_have_count(1)
                # Reselect the dependency without clearing the fragment: its
                # link must still work when no hashchange event fires.
                dep_tab.click()
        browser.close()
