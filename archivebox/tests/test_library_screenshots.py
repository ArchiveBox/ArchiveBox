"""Gallery outcomes preserve real native status and reject missing evidence."""

import pytest
import json
import gzip
from pathlib import Path

from archivebox.core.models import ArchiveResult


@pytest.mark.django_db
@pytest.mark.parametrize(
    "message",
    [
        "OpenCode analysis failed: APIError: You have no credits remaining. Add credits to continue using the API at https://platform.openai.com/",
        "OpenCode analysis failed: APIError: Your credit balance is too low to access the Anthropic API",
    ],
)
def test_gallery_warns_for_terminal_native_plugin_failure(snapshot, capsys, message):
    from screenshot_gallery_helpers import validate_ai_result

    tags_before = list(snapshot.tags.values_list("pk", flat=True))
    result = ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="failed", output_str=message)
    assert validate_ai_result(snapshot, "autotag") is False
    assert "::warning::Native plugin autotag did not succeed" in capsys.readouterr().out
    result.refresh_from_db()
    assert result.status == "failed" and result.output_str == message
    assert list(snapshot.tags.values_list("pk", flat=True)) == tags_before


@pytest.mark.django_db
@pytest.mark.parametrize("message", ["OpenCode exited with status 1:", "Invalid API key", "Malformed provider output"])
def test_gallery_does_not_infer_availability_from_provider_message(snapshot, message):
    from screenshot_gallery_helpers import validate_ai_result

    ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="failed", output_str=message)
    assert validate_ai_result(snapshot, "autotag") is False


@pytest.mark.django_db
def test_gallery_requires_result_and_accepts_success(snapshot, capsys):
    from screenshot_gallery_helpers import validate_ai_result

    with pytest.raises(RuntimeError, match="no terminal autotag result"):
        validate_ai_result(snapshot, "autotag")
    ArchiveResult.objects.create(snapshot=snapshot, plugin="autotag", status="succeeded", output_str="autotag/tags.jsonl")
    assert validate_ai_result(snapshot, "autotag") is True
    assert not capsys.readouterr().out


@pytest.mark.django_db
def test_gallery_features_complete_captures_and_retains_blocked_results(crawl, tmp_path):
    from screenshot_gallery_helpers import native_library_source, select_gallery_snapshots
    from archivebox.core.models import Snapshot

    fixture = Path(__file__).parent / "fixtures"
    bodies = {
        "dom": ("output.html", gzip.decompress((fixture / "original-domain-replay/front.html.gz").read_bytes())),
        "screenshot": ("screenshot.png", (fixture / "redirected-image/image.png").read_bytes()),
        "archivewebpage": ("archivewebpage.wacz", (fixture / "memento/iframetest.wacz").read_bytes()),
    }
    urls = [f"https://example.com/{index}" for index in range(7)]
    snapshots = []
    for index, url in enumerate(urls):
        snapshot = Snapshot.objects.create(url=url, crawl=crawl, status="sealed", output_size=sum(len(body) for _, body in bodies.values()))
        snapshots.append(snapshot)
        for plugin, (filename, body) in bodies.items():
            output = snapshot.output_dir / plugin / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(body)
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin=plugin,
                status="succeeded",
                output_str=f"{plugin}/{filename}",
                output_files={filename: {"size": len(body)}},
                output_size=len(body),
            )
        navigation = snapshot.output_dir / "chrome/navigation.json"
        navigation.parent.mkdir()
        navigation.write_text(json.dumps({"url": url, "status": 403 if index == 1 else 200}))
    failed = ArchiveResult.objects.create(
        snapshot=snapshots[1],
        plugin="autotag",
        status="noresults",
        output_str="No saved text or HTML is available.",
    )
    featured, source = native_library_source(crawl, snapshots, urls, tmp_path)
    assert source == {
        "crawl_id": str(crawl.pk),
        "homepage": urls[0],
        "stories": [urls[index] for index in (2, 3, 4)],
        "replay_urls": {url: url for url in urls if url != urls[1]},
        "homepage_selector": "#hnmain",
        "title": "Hacker News",
    }
    assert [snapshot.url for snapshot in featured] == [urls[index] for index in (0, 2, 3, 4)]
    assert json.loads((tmp_path / "hacker-news-urls.json").read_text()) == [snapshot.url for snapshot in featured]
    records = json.loads((tmp_path / "hacker-news-captures.json").read_text())
    assert len(records) == 7 and records[1]["browser_status"] == 403 and not records[1]["eligible"]
    assert [record["replay_url"] for record in records] == urls
    assert records[1]["results"]["autotag"] == "noresults"
    failed.refresh_from_db()
    assert failed.status == "noresults"
    homepage_navigation = snapshots[0].output_dir / "chrome/navigation.json"
    homepage_navigation.write_text(json.dumps({"url": urls[0], "status": 403}))
    with pytest.raises(RuntimeError, match="successful homepage"):
        select_gallery_snapshots(snapshots, urls, tmp_path)
    homepage_navigation.write_text(json.dumps({"url": urls[0], "status": 200}))
    for snapshot in snapshots[4:]:
        (snapshot.output_dir / "archivewebpage/archivewebpage.wacz").unlink()
    with pytest.raises(RuntimeError, match="three captured stories"):
        select_gallery_snapshots(snapshots, urls, tmp_path)


@pytest.mark.django_db
def test_native_plugin_outcomes_are_scoped_to_opened_snapshots_and_exact_owner(snapshot):
    from screenshot_gallery_helpers import native_plugin_output_unavailable
    from archivebox.core.models import Snapshot

    plugin = "future_output"
    healthy_sibling = "another_plugin"
    assert not native_plugin_output_unavailable(snapshot.pk, plugin)
    Snapshot.objects.filter(pk=snapshot.pk).update(status=Snapshot.StatusChoices.SEALED)
    ArchiveResult.objects.create(snapshot=snapshot, plugin=plugin, status="noresults")
    ArchiveResult.objects.create(snapshot=snapshot, plugin=healthy_sibling, status="succeeded")
    assert not native_plugin_output_unavailable(snapshot.pk, plugin)
    ArchiveResult.objects.create(snapshot=snapshot, plugin="chrome", hook_name="on_Snapshot__30_chrome_navigate", status="succeeded")
    assert native_plugin_output_unavailable(snapshot.pk, plugin)
    assert not native_plugin_output_unavailable(snapshot.pk, healthy_sibling)
    assert not native_plugin_output_unavailable(snapshot.pk, "missing_plugin")
    assert native_plugin_output_unavailable(snapshot.pk, "missing_plugin", default_view=True)
    ArchiveResult.objects.create(snapshot=snapshot, plugin=plugin, hook_name="on_Snapshot__90_second_hook", status="succeeded")
    assert not native_plugin_output_unavailable(snapshot.pk, plugin)


@pytest.mark.django_db
def test_native_library_failed_wacz_and_screenshot_still_yield_owned_app_replay(tmp_path, monkeypatch, admin_client):
    import io
    import zipfile
    from contextlib import nullcontext
    from types import SimpleNamespace

    from warcio.archiveiterator import ArchiveIterator
    import screenshot_gallery_helpers as gallery
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.domains.exports import write_wacz_site
    from archivebox.tests.conftest import ADMIN_TEST_HOST

    urls = ["https://news.ycombinator.com/", *(f"https://stories.example/{index}" for index in range(6))]
    evidence = tmp_path / "evidence"
    outcomes = tmp_path / "unavailable"
    outcomes.touch()
    monkeypatch.setenv("UI_SCREENSHOT_UNAVAILABLE_OUT", str(outcomes))
    monkeypatch.setattr(gallery, "news_urls", lambda: urls)
    monkeypatch.setattr(gallery, "library_capture_plugins", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(gallery, "homepage_capture_budget", lambda *args, **kwargs: nullcontext())

    def failed_native_crawl(*args, **kwargs):
        crawl = Crawl.objects.create(urls="\n".join(urls), status=Crawl.StatusChoices.SEALED)
        for url in urls:
            snapshot = Snapshot.objects.create(url=url, crawl=crawl, status="sealed", output_size=4)
            navigation = snapshot.output_dir / "chrome/navigation.json"
            navigation.parent.mkdir(parents=True)
            navigation.write_text(json.dumps({"url": url, "status": 200}))
            for plugin in ("archivewebpage", "screenshot"):
                ArchiveResult.objects.create(snapshot=snapshot, plugin=plugin, status="failed")

    monkeypatch.setattr(gallery, "subprocess", SimpleNamespace(run=failed_native_crawl))
    crawl_id = gallery.prepare_library(evidence)
    native_records = json.loads((evidence / "hacker-news-captures.json").read_text())
    assert native_records and all(
        not row["eligible"] and row["results"] == {"archivewebpage": "failed", "screenshot": "failed"} for row in native_records
    )
    assert not (evidence / "hacker-news-urls.json").exists()
    assert ArchiveResult.objects.filter(plugin="archivewebpage", status="failed").count() == len(urls)

    source = json.loads((evidence / "gallery-library-source.json").read_text())
    assert source["crawl_id"] == crawl_id and source["title"] == "Field Notes"
    assert source["homepage"] != urls[0]
    snapshots = Snapshot.objects.filter(crawl_id=crawl_id)
    folder = Folder.objects.create(name=source["title"])
    Folder.move_snapshots(snapshots, folder.pk, notify=False)
    response = admin_client.get("/admin/core/snapshot/", {"folder": str(folder.pk)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200 and b"A digital field journal" in response.content
    assert snapshots.filter(permissions="public").count() == 4
    assert snapshots.filter(url=source["homepage"], archiveresult__output_size__gt=1024).exists()
    domains = admin_client.get("/admin/domains/", {"table": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert domains.status_code == 200
    assert b'aria-label="Actions for field-notes.example"' in domains.content
    assert b'aria-label="Actions for design-notes.example"' in domains.content
    assert write_wacz_site(tmp_path, snapshots, title=folder.name, progress=lambda _: None) == 4
    with zipfile.ZipFile(tmp_path / "site.wacz") as bundle:
        index = json.loads(bundle.read("datapackage.json"))
        assert index["mainPageUrl"] == source["homepage"]
        pages = {}
        for resource in index["resources"]:
            with zipfile.ZipFile(io.BytesIO(bundle.read(resource["path"]))) as child:
                record = next(ArchiveIterator(io.BytesIO(child.read("archive/data.warc.gz"))))
                pages[record.rec_headers.get_header("WARC-Target-URI")] = record.content_stream().read()
    assert set(pages) == {source["homepage"], *source["stories"]}
    assert all(f'href="{story}"'.encode() in pages[source["homepage"]] for story in source["stories"])
