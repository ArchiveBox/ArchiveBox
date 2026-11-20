"""Shared importer API keys stay live rather than being pinned to new crawls."""

import pytest
from abx_dl.models import PluginEnv

from archivebox.config.common import build_crawl_config_snapshot, get_config
from archivebox.personas.models import Persona

pytestmark = pytest.mark.django_db


def test_search_keys_reach_plugin_without_copying_into_crawl_config(monkeypatch):
    key = "KAGI_SEARCH_API_KEY"
    server_key = "dummy-machine-key"
    persona_key = "dummy-persona-key"
    monkeypatch.setenv(key, server_key)
    persona = Persona.objects.create(name="Separate credentials", config={key: persona_key})

    # Use the same live config -> child environment transformation as the worker.
    global_config = get_config()
    persona_config = get_config(persona=persona)
    assert PluginEnv(**global_config.model_dump(mode="json")).to_env()[key] == server_key
    assert PluginEnv(**persona_config.model_dump(mode="json")).to_env()[key] == persona_key
    assert key not in build_crawl_config_snapshot()
    assert key not in build_crawl_config_snapshot(persona=persona)
