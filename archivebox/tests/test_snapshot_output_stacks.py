"""Snapshot grouping uses real stored outputs, including portable exports."""

import shutil
from pathlib import Path

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from archivebox.core.models import ArchiveResult
from archivebox.core.views import SnapshotView
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db
FIXTURE = Path(__file__).parent / "fixtures" / "consolelog_preview.html"


def save_output(snapshot, plugin, filename="content.html", *, hook="50", extra_files=()):
    directory = Path(snapshot.output_dir) / plugin
    directory.mkdir(parents=True, exist_ok=True)
    for name in (filename, *extra_files):
        shutil.copyfile(FIXTURE, directory / name)
    files = {name: {"size": (directory / name).stat().st_size, "mimetype": "text/html"} for name in (filename, *extra_files)}
    return ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        hook_name=f"on_Snapshot__{hook}_{plugin}.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str=filename,
        output_files=files,
        output_size=sum(file["size"] for file in files.values()),
    )


def test_snapshot_groups_prefer_requested_plugins_and_keep_unclassified_outputs(snapshot):
    for plugin in (
        "dom",
        "singlefile",
        "wget",
        "mercury",
        "htmltotext",
        "defuddle",
        "readability",
        "liteparse",
        "trafilatura",
        "custom_output",
        "archivewebpage",
        "chrome_mhtml",
        "responses",
        "pdf",
        "screenshot",
    ):
        save_output(snapshot, plugin)

    context = snapshot.get_html_details_context()
    groups = {group["id"]: group for group in context["output_groups"]}
    assert list(groups) == ["html", "raster", "article_text", "embedded_media", "ocr", "metadata", "other"]
    outputs = context["archiveresults"]

    def names(group):
        return [output["name"] for output in outputs if output["output_group"] == group]

    assert names("html") == ["archivewebpage", "singlefile", "chrome_mhtml", "wget", "responses", "dom"]
    assert names("raster") == ["screenshot", "pdf"]
    assert names("article_text") == ["defuddle", "readability", "mercury", "htmltotext"]
    assert names("ocr") == ["trafilatura", "liteparse"]
    assert names("other") == ["custom_output"]
    assert context["best_result"]["name"] == "archivewebpage"


def test_equal_outputs_sort_by_whole_output_size_without_double_counting_hooks(snapshot):
    save_output(snapshot, "git", extra_files=("README.html", "license.html"))
    save_output(snapshot, "forumdl")
    save_output(snapshot, "gallerydl")
    save_output(snapshot, "dns", extra_files=("second.html",))
    save_output(snapshot, "headers")
    # Two hooks report an overlapping path. The second also captures another file.
    save_output(snapshot, "dns", hook="60", extra_files=("third.html",))
    context = snapshot.get_html_details_context()
    outputs = context["archiveresults"]
    assert [output["name"] for output in outputs if output["output_group"] == "embedded_media"] == ["git", "forumdl", "gallerydl"]
    metadata = [output for output in outputs if output["output_group"] == "metadata"]
    assert [output["name"] for output in metadata] == ["dns", "headers"]
    assert metadata[0]["size"] == 3 * FIXTURE.stat().st_size
    assert len(metadata[0]["result_ids"].split(",")) == 2


def test_stacks_render_live_and_static_without_losing_output_actions(snapshot, admin_user):
    result = save_output(snapshot, "defuddle")
    request = RequestFactory().get(f"/{snapshot.url_path}/index.html", HTTP_HOST=ADMIN_TEST_HOST)
    request.user = admin_user
    response = SnapshotView.render_live_index(request, snapshot)
    assert response.status_code == 200
    live_html = response.content.decode()
    assert 'data-output-group="article_text"' in live_html
    assert 'id="snapshot-output-groups"' in live_html
    assert f'data-archive-result-ids="{result.id}"' in live_html
    assert 'title="Download output file"' in live_html
    assert 'title="Open output folder"' in live_html
    assert 'title="Delete this output"' in live_html

    request.user = AnonymousUser()
    assert 'title="Delete this output"' not in SnapshotView.render_live_index(request, snapshot).content.decode()

    snapshot.write_html_details()
    exported = (Path(snapshot.output_dir) / "index.html").read_text()
    assert 'data-output-group="article_text"' in exported
    assert 'href="./defuddle/content.html"' in exported
    assert 'title="Delete this output"' not in exported
    assert "initializeOutputStacks" in exported
    assert "localhost" not in exported


def test_filesystem_fallback_uses_directory_size_for_equal_outputs(snapshot):
    for plugin, count in (("gallerydl", 1), ("git", 3)):
        directory = Path(snapshot.output_dir) / plugin
        directory.mkdir(parents=True)
        for index in range(count):
            shutil.copyfile(FIXTURE, directory / f"page-{index}.html")
    context = snapshot.get_html_details_context()
    media = [output for output in context["archiveresults"] if output["output_group"] == "embedded_media"]
    assert [output["name"] for output in media] == ["git", "gallerydl"]
    assert media[0]["size"] == 3 * FIXTURE.stat().st_size
