"""Saved plain-text articles flow through the snapshot page without nested scrolling."""

import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from archivebox.core.models import ArchiveResult
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("plugin", ["trafilatura", "htmltotext"])
@pytest.mark.parametrize("fixture_name", ["model-preview/LICENSE.txt", "crontab-resources/OFL.txt"])
def test_text_article_full_view_uses_outer_page_scroll(snapshot, live_server, browser_runtime, plugin, fixture_name, tmp_path):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    output = Path(snapshot.output_dir) / plugin / "content.txt"
    output.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parent / "fixtures" / fixture_name, output)
    original = output.read_bytes()
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="content.txt",
        output_files={"content.txt": {"size": len(original), "mimetype": "text/plain"}},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            shell = f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html"
            page.goto(f"{shell}#{plugin}/content.txt", wait_until="domcontentloaded")
            frame = page.locator("#main-frame")
            viewer = frame.content_frame
            article = viewer.locator(".article-body" if plugin == "trafilatura" else "#article")
            expect(article).to_have_js_property("textContent", original.decode().strip())
            heights = []
            for width, height in ((1440, 900), (390, 844), (768, 1024), (844, 390), (320, 700), (1440, 900)):
                page.set_viewport_size({"width": width, "height": height})
                viewer.locator("body").evaluate("async () => { await document.fonts.ready; }")
                frame.element_handle().content_frame().wait_for_function(
                    "minimum => Math.abs(innerHeight - Math.max(Math.ceil(document.body.getBoundingClientRect().height), minimum)) <= 1",
                    arg=height * 0.4,
                    polling=100,
                )
                assert viewer.locator("html").evaluate("e => e.scrollHeight <= e.clientHeight + 1"), (fixture_name, width)
                assert viewer.locator("html").evaluate("e => e.scrollWidth <= e.clientWidth"), (fixture_name, width)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                heights.append(frame.bounding_box()["height"])
                if fixture_name.endswith("OFL.txt"):
                    page.evaluate("() => window.scrollTo(0, document.getElementById('main-frame').getBoundingClientRect().top + scrollY)")
                    before = page.evaluate("scrollY")
                    page.mouse.move(width / 2, height / 2)
                    page.mouse.wheel(0, 300)
                    page.wait_for_function("before => scrollY > before", arg=before)
                    assert viewer.locator("html").evaluate("e => e.scrollTop === 0")
                page.screenshot(path=str(tmp_path / f"{plugin}-{width}x{height}.png"))
            assert abs(heights[0] - heights[-1]) <= 1
            if fixture_name.endswith("OFL.txt"):
                assert heights[0] > 900
            assert output.read_bytes() == original
        finally:
            browser.close()
