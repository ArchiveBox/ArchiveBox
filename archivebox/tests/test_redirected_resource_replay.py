"""Original resource URLs must resolve recorded bodies after HTTP redirects."""

import gzip
import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.django_db(transaction=True)
def test_redirected_image_replays_in_article_card_and_full_view(snapshot, live_server, browser_runtime, tmp_path):
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Machine

    fixture = Path(__file__).parent / "fixtures/redirected-image"
    record = json.loads((fixture / "response.json").read_text())
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.url = "https://github.com/baidu/Unlimited-OCR"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["url", "permissions"])
    output = snapshot.output_dir / "defuddle/content.html"
    output.parent.mkdir(parents=True)
    source_html = gzip.decompress((fixture / "content.html.gz").read_bytes())
    output.write_bytes(source_html)
    body = snapshot.output_dir / "responses" / record["path"]
    body.parent.mkdir(parents=True)
    shutil.copyfile(fixture / "image.png", body)
    (snapshot.output_dir / "responses/index.jsonl").write_text(json.dumps(record) + "\n")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="defuddle",
        hook_name="on_Snapshot__66_defuddle.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="content.html",
        output_files={"content.html": {"size": output.stat().st_size, "mimetype": "text/html"}},
        output_size=output.stat().st_size,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(
            f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html#defuddle/content.html",
            wait_until="domcontentloaded",
        )
        full = page.frame_locator("#main-frame").frame_locator("iframe")
        image = full.locator('img[alt="Baidu Inc."]')
        image.wait_for()
        assert image.evaluate("async img => {try {await img.decode(); return img.naturalWidth > 0;} catch {return false;}}")
        image_url = image.evaluate("img => img.src")
        response = page.request.get(image_url)
        assert response.status == 200
        assert hashlib.sha256(response.body()).hexdigest() == record["responseSha256"]
        assert urlsplit(image_url).hostname.endswith(".archivebox.localhost")
        # Cards load the same saved article in their own frame. Redirect lookup
        # must work there too, without fetching the original site or changing bytes.
        card = page.locator('iframe[title="defuddle card"]').first.content_frame
        card_image = card.frame_locator("iframe").frame_locator("iframe").locator('img[alt="Baidu Inc."]')
        card_image.wait_for()
        assert card_image.evaluate("async img => {await img.decode(); return img.naturalWidth > 0;}")
        assert output.read_bytes() == source_html
        page.screenshot(path=str(tmp_path / "redirected-image-cards.png"))
        image.scroll_into_view_if_needed()
        page.screenshot(path=str(tmp_path / "redirected-image-full.png"))
        content_frame = next(frame for frame in page.frames if frame.locator('img[alt="Baidu Inc."]').count())
        (tmp_path / "redirected-image-timing.json").write_text(
            json.dumps(
                content_frame.evaluate("""() => {
            const navigation = performance.getEntriesByType('navigation')[0];
            return {ttfb_ms: navigation.responseStart - navigation.requestStart, dom_ready_ms: navigation.domContentLoadedEventEnd};
        }"""),
            ),
        )
        # Redirect aliases must retain the existing successful-GET and archive
        # containment rules; a recorded error or POST cannot stand in for an image.
        outside = snapshot.output_dir / "outside.png"
        shutil.copyfile(fixture / "image.png", outside)
        for change in ({"status": 404}, {"method": "POST"}, {"requestMethod": "POST"}, {"path": "../outside.png"}):
            (snapshot.output_dir / "responses/index.jsonl").write_text(json.dumps({**record, **change}) + "\n")
            served = page.request.get(content_frame.url)
            assert served.status == 200
            assert 'src="/baidu/Unlimited-OCR/raw/main/assets/baidu.png"' in served.text()
        browser.close()
