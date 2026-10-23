"""Plugin previews use the same registered template tags as detail cards."""

import shutil
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import get_snapshot_host


@pytest.mark.django_db
def test_chrome_full_preview_loads_plugin_ui_tags(snapshot, client):
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    captured = Path(__file__).parent / "fixtures/tlsnotary/hacker-news/navigation.json"
    output = Path(snapshot.output_dir) / "chrome/navigation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(captured, output)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="chrome",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="chrome/navigation.json",
        output_files={"navigation.json": {"size": output.stat().st_size, "mimetype": "application/json"}},
    )

    host = get_snapshot_host(str(snapshot.id))
    preview = client.get("/chrome/navigation.json?preview=1", HTTP_HOST=host)
    assert preview.status_code == 200
    assert b"chrome-window" in preview.content
    assert b".chrome-window .omnibox" in preview.content
    assert b"{% plugin_ui" not in preview.content
    assert b"{% load" not in preview.content

    raw = client.get("/chrome/navigation.json?raw=1", HTTP_HOST=host)
    assert raw.status_code == 200
    assert b"".join(raw.streaming_content) == captured.read_bytes()


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
