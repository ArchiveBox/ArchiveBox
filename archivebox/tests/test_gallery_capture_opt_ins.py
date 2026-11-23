"""Check real installed gallery recipes against the normal crawl runtime."""

import asyncio
import json
import subprocess
import sys
import runpy
from pathlib import Path

import pytest

from archivebox.config.common import get_config
from screenshot_gallery_helpers import gallery_persona_config
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.personas.models import Persona
from archivebox.plugins.discovery import get_enabled_plugins
from archivebox.workers.runner import CrawlRunner


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = runpy.run_path(ROOT / "bin/screenshot_gallery_helpers.py")


@pytest.mark.django_db(transaction=True)
def test_gallery_capture_opt_ins_are_visible_only_to_the_owned_native_runtime():
    plan = GENERATOR["plugin_screenshot_plan"]()
    select = GENERATOR["capture_settings"]
    expected_opt_ins = {
        "opendataloader": "OPENDATALOADER_ENABLED",
        "opentimestamps": "OPENTIMESTAMPS_ENABLED",
        "tlsnotary": "TLSNOTARY_ENABLED",
    }
    assert expected_opt_ins.items() <= plan["capture_opt_ins"].items()
    assert not set(expected_opt_ins) & set(plan["enabled"])
    assert "AI agent" in plan["required"] and "opencode" in plan["enabled"]
    config_overrides = {"TLSNOTARY_ENABLED": False, "CHROME_TIMEOUT": 90}
    plan["overrides"]["tlsnotary"]["config_overrides"] = config_overrides
    assert select(plan, ["tlsnotary"]) == (config_overrides, {"TLSNOTARY_ENABLED": False})
    del plan["overrides"]["tlsnotary"]["config_overrides"]
    assert any(view["plugin"] == "importer_readwise" for view in plan["importer_views"])
    default = Persona.get_or_create_named("Default")
    default.config = {"CHROME_ENABLED": True}
    default.save(update_fields=["config"])
    other = Persona.get_or_create_named("Other")
    ordinary = Crawl.objects.create(urls="http://example.test/other", persona=other)
    crawl = Crawl.objects.create(urls="http://example.test/owned", persona=default)
    snapshot = Snapshot.objects.create(crawl=crawl, url=crawl.urls)
    runner = CrawlRunner(crawl, show_progress=False)
    default_on = {"chrome", "archivewebpage", "dom", "screenshot"}
    before = set(get_enabled_plugins(config=get_config(crawl=crawl)))
    assert default_on <= before
    assert not set(expected_opt_ins) & before

    for owners, expected in (
        (["tlsnotary"], {"tlsnotary"}),
        (["opendataloader"], {"opendataloader"}),
        (["tlsnotary", "opendataloader"], {"tlsnotary", "opendataloader"}),
        ([], {"opentimestamps"}),
    ):
        _, overrides = select(plan, owners)
        assert set(overrides) & set(expected_opt_ins.values()) == {expected_opt_ins[name] for name in expected}
        with gallery_persona_config(default, overrides):
            payload = asyncio.run(runner.load_snapshot_payload(str(snapshot.pk), prepare=False))
            for name, flag in expected_opt_ins.items():
                assert payload["config"][flag] is (name in expected)
            enabled = set(get_enabled_plugins(config=get_config(crawl=crawl)))
            assert default_on <= enabled
            assert enabled & set(expected_opt_ins) == expected
            assert not set(expected_opt_ins) & set(get_enabled_plugins(config=get_config(crawl=ordinary)))
        assert set(get_enabled_plugins(config=get_config(crawl=crawl))) == before


@pytest.mark.django_db(transaction=True)
def test_gallery_capture_config_restores_keys_on_failure_without_undoing_other_edits():
    persona = Persona.get_or_create_named("Default")
    original = {"TLSNOTARY_ENABLED": False}
    persona.config = original
    persona.save(update_fields=["config"])
    with pytest.raises(RuntimeError, match="native capture stopped"), gallery_persona_config(persona, {"TLSNOTARY_ENABLED": True}):
        Persona.objects.filter(pk=persona.pk).update(config={"TLSNOTARY_ENABLED": True, "CHROME_ENABLED": False})
        raise RuntimeError("native capture stopped")
    persona.refresh_from_db()
    assert persona.config == {**original, "CHROME_ENABLED": False}


def test_gallery_add_uses_native_cli_error_and_restores_disposable_config(initialized_archive):
    plan = GENERATOR["plugin_screenshot_plan"]()
    path = initialized_archive / "test-gallery-plan.json"
    path.write_text(json.dumps(plan))
    shell = "from archivebox.personas.models import Persona; print(Persona.get_or_create_named('Default').config)"
    config_command = [sys.executable, "-m", "archivebox", "manage", "shell", "--no-imports", "-c", shell]

    def config():
        return subprocess.check_output(config_command, cwd=initialized_archive, text=True, timeout=30).splitlines()[-1]

    before = config()
    argv = ["--depth=0", "--overwrite", "--tag=screenshot-gallery", "not an archive URL"]
    native = subprocess.run(
        [sys.executable, "-m", "archivebox", "add", *argv],
        cwd=initialized_archive,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert native.returncode == 2
    for scoped in ("0", "1"):
        captured = subprocess.run(
            [sys.executable, str(ROOT / "bin/screenshot_gallery_helpers.py"), "capture-add", str(path), scoped, "tlsnotary", argv[-1]],
            cwd=initialized_archive,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert captured.returncode == native.returncode
        assert captured.stderr.rsplit("Error:", 1)[-1] == native.stderr.rsplit("Error:", 1)[-1]
        assert config() == before
