"""The Hacker News gallery keeps its required real capture outputs."""

import asyncio
from pathlib import Path

import pytest
import yaml

from archivebox.config.common import get_config
from archivebox.core.library_screenshots import library_capture_plugins
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.plugins.discovery import get_enabled_plugins
from archivebox.services.runner import CrawlRunner


class CaptureFailed(Exception):
    pass


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("model,capture_fails", [("", False), ("openai/gpt-5.4-mini", True)])
def test_gallery_hn_only_drops_redundant_notarization(model, capture_fails, monkeypatch):
    monkeypatch.delenv("OPENCODE_ENABLED", raising=False)
    if model:
        # Match the protected gallery's machine environment; a Persona cannot
        # enable the Agent or its dependency gate for an existing supervisor.
        workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "screenshots.yml"
        jobs = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)["jobs"]
        gallery = next(step for step in jobs["deploy"]["steps"] if step.get("name") == "Build UI screenshot gallery")
        assert jobs["deploy"]["environment"] == "provider-capture"
        assert "OPENCODE_ENABLED" not in str(jobs["public_recipes"])
        assert gallery["env"]["OPENCODE_ENABLED"] == "True"
        monkeypatch.setenv("OPENCODE_ENABLED", gallery["env"]["OPENCODE_ENABLED"])

    persona = Persona.get_or_create_named("Default")
    previous = {
        "TLSNOTARY_ENABLED": True,
        "CHROME_ENABLED": True,
        "ARCHIVEWEBPAGE_ENABLED": True,
        "DOM_ENABLED": True,
        "SCREENSHOT_ENABLED": True,
    }
    persona.config = previous
    persona.save(update_fields=["config"])
    persona.refresh_from_db(fields=["config"])
    previous = persona.config
    required = {"chrome", "archivewebpage", "dom", "screenshot"}
    before = set(get_enabled_plugins(config=get_config(persona=persona)))
    assert {"tlsnotary", *required} <= before

    try:
        with library_capture_plugins(persona, model=model):
            persona.refresh_from_db(fields=["config"])
            assert persona.config["TLSNOTARY_ENABLED"] is False
            assert "OPENCODE_ENABLED" not in persona.config
            crawl = Crawl.objects.create(urls="https://example.com/gallery-article", persona=persona)
            assert "OPENCODE_ENABLED" not in crawl.config
            snapshot = Snapshot.objects.create(crawl=crawl, url=crawl.urls)
            runner = CrawlRunner(crawl, show_progress=False)
            payload = asyncio.run(runner.load_snapshot_payload(str(snapshot.pk), prepare=False))
            assert payload["config"]["TLSNOTARY_ENABLED"] is False
            enabled = set(get_enabled_plugins(config=get_config(crawl=crawl)))
            assert "tlsnotary" not in enabled
            assert required <= enabled
            if model:
                assert {"autotag", "autosummary", "opencode"} <= enabled
                assert payload["config"]["AUTOTAG_MODEL"] == payload["config"]["AUTOSUMMARY_MODEL"] == model
            if capture_fails:
                raise CaptureFailed
    except CaptureFailed:
        assert capture_fails

    persona.refresh_from_db(fields=["config"])
    assert persona.config == previous
    assert set(get_enabled_plugins(config=get_config(persona=persona))) == before
