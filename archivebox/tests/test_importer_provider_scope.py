"""Keep optional browser-provider credentials scoped during a package upgrade."""

import pytest


@pytest.mark.django_db
def test_importer_provider_keys_follow_installed_capture_schema(admin_user):
    from archivebox.config.common import get_config
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import _importer_env
    from archivebox.machine.models import Machine
    from archivebox.personas.models import Persona
    from archivebox.plugins.discovery import discover_plugin_configs, get_plugin_catalog

    machine = Machine.current()
    machine.config = {
        "ANTHROPIC_API_KEY": "synthetic-machine-anthropic",
        "EXA_SEARCH_API_KEY": "synthetic-machine-exa",
    }
    machine.save(update_fields=["config"])
    persona = Persona.objects.create(
        name="Synthetic provider scope",
        created_by=admin_user,
        config={"OPENAI_API_KEY": "synthetic-persona-openai"},
    )
    config = get_config(persona=persona, machine=machine)

    def env(plugin, feed):
        source = ImporterSource(name=plugin, plugin=plugin, feed=feed, created_by=admin_user, persona=persona)
        return _importer_env(source, config)

    browser = env("importers_browser", "x_bookmarks")
    rss = env("importer_rss", "rss")
    exa = env("importer_search", "exa")
    assert browser["OPENAI_API_KEY"] == "synthetic-persona-openai"
    assert browser["ANTHROPIC_API_KEY"] == "synthetic-machine-anthropic"
    for unrelated in (rss, exa):
        assert "OPENAI_API_KEY" not in unrelated
    assert exa["EXA_SEARCH_API_KEY"] == "synthetic-machine-exa"

    catalog = get_plugin_catalog()
    provider_schema = discover_plugin_configs().get("opencode_providers", {})
    if "opencode_providers" in catalog:
        assert {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"} <= set(provider_schema["properties"])
        dependencies = catalog.select(["browserharness"])
        assert "opencode_providers" in dependencies and "opencode" not in dependencies
        assert not dependencies["opencode_providers"].hooks
        assert "ANTHROPIC_API_KEY" not in rss
        assert "ANTHROPIC_API_KEY" not in exa
    else:
        assert not provider_schema
        assert rss["ANTHROPIC_API_KEY"] == "synthetic-machine-anthropic"
