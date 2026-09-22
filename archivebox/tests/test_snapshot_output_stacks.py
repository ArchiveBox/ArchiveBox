"""Snapshot grouping uses real stored outputs, including portable exports."""

import shutil
from pathlib import Path

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template import Context
from django.test import RequestFactory

from archivebox.core.models import ArchiveResult
from archivebox.core.views import SnapshotView
from archivebox.config.common import ServerConfig
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db
FIXTURE = Path(__file__).parent / "fixtures" / "consolelog_preview.html"
IMAGE_FIXTURE = Path(__file__).parents[2] / "publicsite" / "screenshots" / "snapshot-view-responses-desktop.png"


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


def save_response_image(snapshot, filename="all/example.png"):
    path = Path(snapshot.output_dir) / "responses" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(IMAGE_FIXTURE, path)
    return ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="responses",
        hook_name="on_Snapshot__24_responses.daemon.bg.js",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str=filename,
        output_files={
            filename: {
                "size": path.stat().st_size,
                "mimetype": "image/png",
                "extension": "png",
            },
        },
        output_size=path.stat().st_size,
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
    assert list(groups) == ["html", "raster", "article_text", "embedded_media", "metadata", "other"]
    outputs = context["archiveresults"]

    def names(group):
        return [output["name"] for output in outputs if output["output_group"] == group]

    assert names("html") == ["archivewebpage", "singlefile", "chrome_mhtml", "wget", "dom", "responses_html"]
    assert names("raster") == ["screenshot", "pdf"]
    assert names("article_text") == ["defuddle", "readability", "mercury", "trafilatura", "htmltotext"]
    assert "liteparse" in names("embedded_media")
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
    context = snapshot.get_html_details_context(static_export_dir=Path(snapshot.output_dir))
    media = [output for output in context["archiveresults"] if output["output_group"] == "embedded_media"]
    assert [output["name"] for output in media] == ["git", "gallerydl"]
    assert media[0]["size"] == 3 * FIXTURE.stat().st_size


def test_responses_html_card_requires_saved_html_and_keeps_gallery(snapshot):
    result = save_output(snapshot, "responses")
    outputs = snapshot.get_html_details_context()["archiveresults"]
    cards = {output["name"]: output for output in outputs}
    assert cards["responses"]["output_group"] == "embedded_media"
    assert cards["responses_html"]["output_group"] == "html"
    assert cards["responses_html"]["path"] == "responses/content.html"
    assert cards["responses_html"]["direct_preview_path"] == "responses/content.html?card=responses_html"
    assert cards["responses_html"]["result"] is None
    assert sum(output["size"] for output in outputs) == result.output_size
    request = RequestFactory().get(f"/{snapshot.url_path}/index.html", HTTP_HOST=ADMIN_TEST_HOST)
    request.user = AnonymousUser()
    from django.template.loader import render_to_string

    html = render_to_string("core/snapshot_output_cards.html", snapshot.get_html_details_context(request=request), request=request)
    assert 'data-plugin-name="responses_html"' in html
    assert "responses/content.html?card=responses_html" in html
    assert "responses/content.html?preview=1" in html
    (Path(snapshot.output_dir) / "responses" / "data.json").write_text("{}")
    result.output_str = "data.json"
    result.output_files = {"data.json": {"size": 2, "mimetype": "application/json"}}
    result.save()
    assert "responses_html" not in {output["name"] for output in snapshot.get_html_details_context()["archiveresults"]}


@pytest.mark.parametrize(
    ("security_mode", "expected_host"),
    (
        ("safe-onedomain-nojsreplay", "archivebox.localhost:8937"),
        ("safe-subdomains-fullreplay", "snap-{snapshot_suffix}.archivebox.localhost:8937"),
    ),
)
def test_responses_card_preserves_request_origin_for_nested_preview_urls(snapshot, security_mode, expected_host):
    from archivebox.core.templatetags.core_tags import plugin_card

    result = save_response_image(snapshot)
    request = RequestFactory().get(
        f"/{snapshot.url_path}/index.html",
        secure=True,
        HTTP_HOST="archivebox.localhost:8937",
    )
    config = ServerConfig(BASE_URL="https://archivebox.localhost:8937", SERVER_SECURITY_MODE=security_mode)
    html = plugin_card(Context({"request": request, "CONFIG": config}), result)
    expected_host = expected_host.format(snapshot_suffix=str(snapshot.id)[-12:])
    assert f"https://{expected_host}/" in html
    assert "/responses/all/example.png?raw=1" in html


def test_responses_card_uses_relative_preview_urls_in_static_export(snapshot):
    from archivebox.core.templatetags.core_tags import plugin_card

    result = save_response_image(snapshot)
    html = plugin_card(
        Context({"STATIC_EXPORT": True, "STATIC_EXPORT_DIR": snapshot.output_dir}),
        result,
    )
    assert 'src="./responses/all/example.png?raw=1"' in html
    assert "localhost" not in html
