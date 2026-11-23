"""Plugin previews use the same registered template tags as detail cards."""

import shutil
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import get_snapshot_host


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
def test_wacz_preview_uses_served_mount_and_portable_replay_base(snapshot, client, browser_runtime, tmp_path, mode):
    from urllib.parse import urlsplit
    from django.core.management import call_command
    from archivebox.core.routes_util import build_snapshot_url
    from archivebox.machine.models import Machine

    from abx_plugins import get_plugins_dir
    from archivebox.tests.conftest import resolve_abxpkg_binary_env

    resolve_abxpkg_binary_env(
        browser_runtime["lib_dir"],
        deps_from=Path(get_plugins_dir()) / "archivewebpage" / "config.json",
    )
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": "http://archivebox.localhost:8000", "SERVER_SECURITY_MODE": mode}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.url = "http://localhost:20000/"
    snapshot.save(update_fields=["permissions", "url"])
    fixture = Path(__file__).parent / "fixtures/memento/iframetest.wacz"
    output = snapshot.output_dir / "legacy-capture.wacz"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture, output)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="archivewebpage",
        status="succeeded",
        output_str=output.name,
        output_files={output.name: {"size": output.stat().st_size, "root_relative": True}},
    )
    route = urlsplit(build_snapshot_url(str(snapshot.id), output.name))
    response = client.get(route.path + "?preview=1", HTTP_HOST=route.netloc)
    assert response.status_code == 200
    replay_base = route.path.rsplit("/", 1)[0] + "/replay/"
    assert f'<script src="{replay_base}ui.js"></script>'.encode() in response.content
    assert f'data-replaybase="{replay_base}"'.encode() in response.content
    asset = client.get(replay_base + "ui.js", HTTP_HOST=route.netloc)
    assert asset.status_code == 200
    destination = tmp_path / "portable-replay"
    call_command("site_export", query=f"id__in={snapshot.pk}", format="html", destination=str(destination))
    root = destination / snapshot.static_archive_path
    viewers = list((root / "_archivebox").glob("*-full.html"))
    assert len(viewers) == 1
    replay_script = "viewers/archivewebpage/replay/ui.js"
    assert f'<script src="{replay_script}"></script>' in viewers[0].read_text()
    assert (viewers[0].parent / replay_script).is_file()
    assert (root / output.name).read_bytes() == fixture.read_bytes() == output.read_bytes()


@pytest.mark.django_db(transaction=True)
def test_html_export_matches_loose_recordings_during_copy(snapshot, browser_runtime, tmp_path):
    from zipfile import ZipFile
    from lxml import html
    from abx_plugins import get_plugins_dir
    from django.core.management import call_command
    from archivebox.tests.conftest import resolve_abxpkg_binary_env

    resolve_abxpkg_binary_env(browser_runtime["lib_dir"], deps_from=Path(get_plugins_dir()) / "archivewebpage/config.json")
    directory = snapshot.output_dir / "legacy" / "recordings"
    directory.mkdir(parents=True)
    (directory / "notes.warc.gz.txt").write_text("notes")
    plain = tmp_path / "plain"
    call_command("site_export", query=f"id__in={snapshot.pk}", format="html", destination=str(plain))
    assert not (plain / snapshot.static_archive_path / "_archivebox/viewers").exists()
    assert not (plain / "_archivebox/viewers").exists()

    with ZipFile(Path(__file__).parent / "fixtures/memento/iframetest.wacz") as fixture:
        recording = fixture.read("archive/data.warc.gz")
    (directory / "page.WARC.GZ").write_bytes(recording)
    original_script = snapshot.output_dir / "replay/ui.js"
    original_script.parent.mkdir()
    original_script.write_text("// saved script")
    portable = tmp_path / "portable"
    call_command("site_export", query=f"id__in={snapshot.pk}", format="html", destination=str(portable))
    root = portable / snapshot.static_archive_path
    assert (root / "legacy/recordings/page.WARC.GZ").read_bytes() == recording
    assert (root / "replay/ui.js").read_bytes() == original_script.read_bytes()
    player = root / "_archivebox/viewers/archivewebpage/replay"
    assert (player / "ui.js").stat().st_size > 0
    assert (player / "sw.js").stat().st_size > 0
    (viewer,) = (root / "_archivebox").glob("*-full.html")
    assert "../legacy/recordings/page.WARC.GZ" in viewer.read_text()
    assert f"../../_archivebox/{viewer.name}" in (root / "legacy/recordings/index.html").read_text()
    details = html.fromstring((root / "index.html").read_bytes())
    (href,) = details.xpath('//div[@class="loose-items"]/a[contains(., "page.WARC.GZ")]/@href')
    assert (root / href).resolve() == viewer


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
def test_chrome_full_preview_loads_plugin_ui_tags(snapshot, client, live_server, browser_runtime, tmp_path, mode):
    import json
    import re
    from urllib.parse import urlsplit
    from django.core.management import call_command
    from django.urls import reverse
    from playwright.sync_api import sync_playwright
    from archivebox.core.routes_util import build_admin_url, build_snapshot_url
    from archivebox.machine.models import Machine, Process

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}", "SERVER_SECURITY_MODE": mode}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    captured = Path(__file__).parent / "fixtures/tlsnotary/hacker-news/navigation.json"
    output = Path(snapshot.output_dir) / "chrome/navigation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(captured, output)
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="chrome",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="chrome/navigation.json",
        output_files={"navigation.json": {"size": output.stat().st_size, "mimetype": "application/json"}},
        process=Process.current(),
    )
    snapshot.write_index_jsonl()

    url = build_snapshot_url(str(snapshot.id), "chrome/navigation.json")
    route = urlsplit(url)
    preview = client.get(route.path + "?preview=1", HTTP_HOST=route.netloc)
    assert preview.status_code == 200
    assert b"chrome-window" in preview.content
    assert b".chrome-window .omnibox" in preview.content
    assert b"{% plugin_ui" not in preview.content
    assert b"{% load" not in preview.content
    record_urls = json.loads(
        re.search(r'<script id="record-urls" type="application/json">(.*?)</script>', preview.content.decode(), re.DOTALL)[1],
    )
    result_url = build_admin_url(reverse("admin:core_archiveresult_change", args=[result.pk]))
    assert record_urls["ArchiveResult"][str(result.pk)] == result_url
    assert record_urls["Process"][str(result.process_id)] == build_admin_url(
        reverse("admin:machine_process_change", args=[result.process_id]),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page()
        page.goto(url + "?preview=1")
        assert page.locator(f'a[title="result {result.pk}"]').get_attribute("href") == result_url
        browser.close()

    raw = client.get(route.path + "?raw=1", HTTP_HOST=route.netloc)
    assert raw.status_code == 200
    assert b"".join(raw.streaming_content) == captured.read_bytes()
    destination = tmp_path / "portable"
    call_command("site_export", query=f"id__in={snapshot.pk}", format="html", destination=str(destination))
    viewers = list((destination / snapshot.static_archive_path / "_archivebox").glob("*-full.html"))
    assert len(viewers) == 1
    portable = viewers[0].read_text()
    assert '<script id="record-urls" type="application/json">{}</script>' in portable
    assert "/admin/" not in portable


@pytest.mark.django_db(transaction=True)
def test_opendataloader_full_preview_preserves_requested_format(snapshot, live_server, browser_runtime, tmp_path):
    import hashlib
    import json
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    root = Path(snapshot.output_dir) / "opendataloader"
    (root / "document_images").mkdir(parents=True)
    image = Path(__file__).parents[2] / "publicsite/assets/social-card.png"
    shutil.copyfile(image, root / "document_images/imageFile1.png")
    markdown = (
        "# Extracted paper\n\nA **valuable** paragraph.\n\n"
        "![](<document_images/imageFile1.png>)\n\n"
        "| Column | Value |\n| --- | --- |\n| Preserved | Yes |\n\n"
        "<script>parent.document.body.dataset.archivedScript='executed'</script>\n\n"
        "## Conclusion\n\nThe complete final paragraph.\n"
    )
    (root / "content.md").write_text(markdown)
    (root / "content.txt").write_text("# Literal text heading\nText remains plain, including **asterisks**.\n")
    (root / "content.json").write_text(json.dumps({"files": [{"source_file": "paper.pdf"}], "sources_processed": 1}))
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir() if path.is_file()}
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="opendataloader",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="opendataloader/content.md",
        output_files={
            path.name: {"size": path.stat().st_size, "mimetype": mime}
            for path, mime in [
                (root / "content.txt", "text/plain"),
                (root / "content.md", "text/markdown"),
                (root / "content.json", "application/json"),
            ]
        },
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[f"--host-resolver-rules=MAP {host} 127.0.0.1"],
        )
        page = browser.new_page(viewport={"width": 1100, "height": 850})
        base = f"http://{host}:{port}/opendataloader/"
        page.goto(base + "content.md?preview=1", wait_until="networkidle")
        expect(page.locator("#document")).to_have_value("content.md")
        reader = page.frame_locator("#reader")
        expect(reader.locator("h1")).to_have_text("Extracted paper")
        expect(reader.locator("strong")).to_have_text("valuable")
        expect(reader.locator("table")).to_contain_text("Preserved")
        expect(reader.locator("body")).to_contain_text("The complete final paragraph.")
        assert reader.locator("img").evaluate("img => img.complete && img.naturalWidth > 0")
        assert page.locator("body").get_attribute("data-archived-script") is None
        assert "allow-scripts" not in page.locator("#reader").get_attribute("sandbox")
        page.screenshot(path=str(tmp_path / "opendataloader-markdown.png"), full_page=True)
        assert page.locator("#download").get_attribute("href") == base + "content.md?raw=1"
        page.locator("#document").select_option("content.txt")
        expect(page.locator("#article")).to_have_text("# Literal text heading\nText remains plain, including **asterisks**.")
        expect(page.locator("#reader")).to_be_hidden()
        assert page.locator("#download").get_attribute("href") == base + "content.txt?raw=1"
        assert page.locator("#raw").get_attribute("href") == base + "content.txt?preview=1&raw=1"
        page.locator("#document").select_option("content.json")
        expect(page.locator("#article")).to_contain_text("Sources processed: 1")
        expect(page.locator("#article")).to_contain_text("paper.pdf")
        page.goto(base + "content.txt?preview=1", wait_until="networkidle")
        expect(page.locator("#document")).to_have_value("content.txt")
        expect(page.locator("#article")).to_contain_text("**asterisks**")
        raw = page.request.get(base + "content.md?raw=1")
        assert raw.status == 200
        assert raw.body() == markdown.encode()
        browser.close()
    assert before == {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir() if path.is_file()}
