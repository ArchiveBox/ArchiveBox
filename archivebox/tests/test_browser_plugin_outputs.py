"""Browser preparation only exposes cards when it saves content."""

import shutil
import subprocess
from pathlib import Path

import pytest
from abx_plugins import get_plugins_dir

from django.template.loader import render_to_string

from archivebox.core.models import ArchiveResult

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("plugin", ["puppeteer", "playwright", "stagehand", "browserharness"])
def test_browser_plugin_saved_files_card(snapshot, plugin):
    output = snapshot.output_dir / plugin
    output.mkdir(parents=True)
    (output / "result.log").write_text('{"title":"Prepared"}\n')
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin=plugin, status="succeeded", output_str="Page prepared")
    result.update_output_metadata_from_filesystem()
    empty = snapshot.get_html_details_context()
    assert plugin not in {item["name"] for item in empty["archiveresults"]}
    assert f'data-plugin-name="{plugin}"' not in render_to_string("core/snapshot_output_cards.html", empty)

    shutil.copyfile(Path(__file__).parent / "fixtures/consolelog_preview.html", output / "page.html")
    subprocess.run(["node", str(get_plugins_dir() / "base/downloads.js"), str(output)], check=True, capture_output=True, text=True)
    result.update_output_metadata_from_filesystem()
    context = snapshot.get_html_details_context()
    card = next(item for item in context["archiveresults"] if item["name"] == plugin)
    assert card["output_group"] == "embedded_media"
    assert card["path"] == f"{plugin}/index.html"
    assert 'href="page.html"' in (output / "index.html").read_text()
    assert f'data-plugin-name="{plugin}"' in render_to_string("core/snapshot_output_cards.html", context)
