"""Plugin replay declarations drive native replay and portable export selection."""

import json

import pytest
from django.core.management import call_command

from archivebox.plugins.discovery import get_plugin_catalog, get_replay_asset_bundle, get_snapshot_role_names
from archivebox.tests.test_original_domain_replay import DOMAIN_HOST, saved_site as saved_site

pytestmark = pytest.mark.django_db(transaction=True)


def test_html_replay_roles_cover_saved_page_and_article_producers():
    assert get_snapshot_role_names("html_replay") == (
        "singlefile",
        "chrome_extension_singlefile",
        "dom",
        "wget",
        "readability",
        "defuddle",
        "mercury",
        "trafilatura",
    )


def test_replay_bundle_is_declared_by_its_provider():
    declaration = get_plugin_catalog()["archivewebpage"].manifest["replay_assets"]
    assert declaration["wacz"] == ["replay/ui.js", "replay/sw.js", "replay/sw-index.js", "replay/replay.html"]
    assert get_replay_asset_bundle("wacz") == ("archivewebpage", tuple(declaration["wacz"]))
    assert get_replay_asset_bundle("wacz", provider="archivewebpage") == ("archivewebpage", tuple(declaration["wacz"]))
    with pytest.raises(ValueError, match="No plugin provides"):
        get_replay_asset_bundle("wacz", provider="singlefile")
    with pytest.raises(ValueError, match="Unknown replay asset provider"):
        get_replay_asset_bundle("wacz", provider="nonexistent")


@pytest.mark.parametrize("plugin", ["chrome_extension_singlefile", "mercury", "trafilatura"])
def test_original_replay_and_export_use_declared_saved_outputs(client, saved_site, tmp_path, plugin):
    # Existing captures remain usable when only a legacy or article output exists.
    for snapshot, original, body in saved_site:
        output = snapshot.output_dir / plugin / "content.html"
        output.parent.mkdir(parents=True, exist_ok=True)
        original.rename(output)
        result = snapshot.archiveresult_set.get()
        result.plugin = plugin
        result.output_str = f"{plugin}/content.html"
        result.output_files = {"content.html": {"size": len(body), "mimetype": "text/html"}}
        result.save(update_fields=["plugin", "output_str", "output_files"])
    response = client.get("/newest", HTTP_HOST=DOMAIN_HOST)
    assert response.status_code == 200
    assert b"New Links" in response.content
    destination = tmp_path / "export"
    call_command("site_export", scope="news.ycombinator.com", format="html", destination=str(destination))
    pages = json.loads((destination / "pages.json").read_text())
    assert len(pages) == len(saved_site)
    assert all(f"/{plugin}/content.html" in page["path"] for page in pages)
    for snapshot, _original, body in saved_site:
        assert (snapshot.output_dir / plugin / "content.html").read_bytes() == body


def test_wget_mirror_resources_use_native_snapshot_replay(client, crawl, httpserver, tmp_path):
    import os
    from urllib.parse import urlsplit

    from abx_plugins.plugins.base.testing import install_required_binary_from_config, run_hook_and_parse
    from archivebox.core.models import Snapshot
    from archivebox.core.routes_util import build_snapshot_url

    body = b"body { color: rebeccapurple; }"
    httpserver.expect_request("/").respond_with_data(
        '<html><head><link rel="stylesheet" href="/style.css"></head><body>Saved</body></html>',
        content_type="text/html",
    )
    httpserver.expect_request("/style.css").respond_with_data(body, content_type="text/css")
    plugin = get_plugin_catalog()["wget"]
    binary = install_required_binary_from_config(plugin.path, "wget")
    snapshot = Snapshot.objects.create(url=httpserver.url_for("/"), crawl=crawl, permissions="public", output_size=1)
    snapshot.output_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "SNAP_DIR": str(snapshot.output_dir), "WGET_BINARY": str(binary.loaded_abspath), "WGET_WARC_ENABLED": "False"}
    code, record, stderr = run_hook_and_parse(next(plugin.path.glob("on_Snapshot__*_wget.*")), snapshot.url, None, cwd=tmp_path, env=env)
    assert code == 0 and record["status"] == "succeeded", stderr
    css = next((snapshot.output_dir / "wget").rglob("style.css"))
    assert css.read_bytes() == body
    target = urlsplit(build_snapshot_url(str(snapshot.pk), "style.css"))
    response = client.get(target.path, HTTP_HOST=target.netloc)
    assert response.status_code == 200, (response.status_code, record, css)
    assert b"".join(response.streaming_content) == body
    assert css.read_bytes() == body


@pytest.mark.parametrize("loop", [False, True])
def test_replay_root_symlink_cannot_escape_snapshot(client, saved_site, tmp_path, loop):
    from urllib.parse import urlsplit
    from archivebox.core.routes_util import build_snapshot_url

    snapshot = saved_site[0][0]
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("Outside snapshot")
    responses = snapshot.output_dir / "responses"
    responses.mkdir()
    (responses / "news.ycombinator.com").symlink_to("news.ycombinator.com" if loop else outside, target_is_directory=True)
    target = urlsplit(build_snapshot_url(str(snapshot.pk), "secret.txt"))
    response = client.get(target.path, HTTP_HOST=target.netloc)
    assert response.status_code == 404
    assert (outside / "secret.txt").read_text() == "Outside snapshot"
