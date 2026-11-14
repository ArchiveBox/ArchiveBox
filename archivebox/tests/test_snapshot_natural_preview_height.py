"""Generated text and image previews size the selected frame from real content."""

import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from archivebox.core.models import ArchiveResult
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_text_and_image_preview_heights_follow_content(snapshot, live_server, browser_runtime):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    root = Path(snapshot.output_dir) / "title"
    root.mkdir(parents=True)
    fixtures = Path(__file__).parent / "fixtures"
    shutil.copyfile(fixtures / "consolelog_preview.html", root / "short.txt")
    shutil.copyfile(fixtures / "crontab-resources/OFL.txt", root / "tall.txt")
    shutil.copyfile(Path(__file__).parents[2] / "publicsite/assets/social-card.png", root / "image.png")
    original = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()}
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="title",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="tall.txt",
        output_files={
            path.name: {"size": path.stat().st_size, "mimetype": "image/png" if path.suffix == ".png" else "text/plain"}
            for path in root.iterdir()
        },
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            console_messages = []
            page.on("console", lambda message: console_messages.append(message.text))
            shell = f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html"
            measured = {}
            for filename in ("tall.txt", "short.txt", "image.png", "tall.txt"):
                page.goto(f"{shell}#title/{filename}?preview=1&raw=1", wait_until="domcontentloaded")
                viewer = page.locator("#main-frame").content_frame
                viewer.locator(".archivebox-image-preview img" if filename.endswith(".png") else ".archivebox-text-preview").wait_for()
                heights = []
                for width, height in ((1440, 900), (390, 844), (768, 1024), (844, 390), (320, 700), (1440, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    viewer.locator("body").evaluate(
                        "async () => { await document.fonts.ready; await Promise.all([...document.images].map(image => image.decode())); }",
                    )
                    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                    page.locator("#main-frame").element_handle().content_frame().wait_for_function(
                        "minimum => Math.abs(innerHeight - Math.max(Math.ceil(document.body.getBoundingClientRect().height), minimum)) <= 1",
                        arg=height * 0.4,
                        polling=100,
                    )
                    assert viewer.locator("html").evaluate("e => e.scrollHeight <= e.clientHeight + 1"), (filename, width)
                    assert viewer.locator("html").evaluate("e => e.scrollWidth <= e.clientWidth"), (filename, width)
                    frame = page.locator("#main-frame").bounding_box()
                    assert frame["height"] >= viewer.locator("body").bounding_box()["height"] - 1
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    heights.append(frame["height"])
                assert abs(heights[0] - heights[-1]) <= 1, heights
                measured[filename] = heights[-1]
            assert "archivebox-consolelog-preview-fixture" not in console_messages
            assert measured["tall.txt"] > measured["short.txt"]
            assert measured["tall.txt"] > 900
            assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()} == original
        finally:
            browser.close()
