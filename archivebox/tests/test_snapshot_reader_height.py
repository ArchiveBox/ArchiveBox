"""Article viewers use the snapshot page's scroller without changing saved bytes."""

import gzip
import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from archivebox.core.models import ArchiveResult
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("plugin", ["readability", "defuddle", "mercury"])
def test_article_viewer_height_grows_and_shrinks_without_nested_scrolling(snapshot, live_server, browser_runtime, plugin):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    root = Path(snapshot.output_dir) / plugin
    root.mkdir(parents=True)
    fixtures = Path(__file__).parent / "fixtures"
    shutil.copyfile(fixtures / "consolelog_preview.html", root / "short.html")
    shutil.copyfile(fixtures / "crontab-resources/page.html", root / "tall.html")
    (root / "table.html").write_bytes(gzip.decompress((fixtures / "original-domain-replay/front.html.gz").read_bytes()))
    original = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()}
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="tall.html",
        output_files={path.name: {"size": path.stat().st_size, "mimetype": "text/html"} for path in root.iterdir()},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            target = f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html"
            for filename in ("tall.html", "short.html", "table.html", "tall.html"):
                page.goto(f"{target}#{plugin}/{filename}?preview=1", wait_until="domcontentloaded")
                viewer = page.locator("#main-frame").content_frame
                article = viewer.locator("#reader").content_frame
                article.locator("body").wait_for()
                assert article.locator("body").inner_text()
                viewer_frame = viewer.locator("html").element_handle().owner_frame()
                heights = []
                for width, height in ((1440, 900), (390, 844), (844, 390), (320, 700), (1440, 900)):
                    page.set_viewport_size({"width": width, "height": height})
                    article.locator("body").evaluate("() => document.fonts.ready")
                    viewer_frame.wait_for_function(
                        """width => {
                            const reader = document.getElementById('reader');
                            const article = reader.contentDocument;
                            return innerWidth === width && reader.contentWindow.innerWidth === width
                                && [document.documentElement, article.documentElement].every(root => root.scrollHeight <= root.clientHeight + 1)
                                && Math.abs(reader.getBoundingClientRect().height - Math.ceil(article.body.getBoundingClientRect().height)) <= 1;
                        }""",
                        arg=width,
                        polling=100,
                    )
                    assert article.locator("html").evaluate("e => e.scrollHeight <= e.clientHeight + 1"), (plugin, filename, width)
                    assert viewer.locator("html").evaluate("e => e.scrollHeight <= e.clientHeight + 1"), (plugin, filename, width)
                    assert article.locator("html").evaluate("e => e.scrollWidth <= e.clientWidth + 1"), (plugin, filename, width)
                    if filename == "table.html":
                        assert article.locator("table").count() > 0
                        assert article.locator("table").evaluate_all(
                            "tables => tables.every(t => getComputedStyle(t).overflow === 'visible')",
                        )
                    content_height = viewer.locator("body").bounding_box()["height"]
                    page.wait_for_function(
                        "expected => Math.abs(document.getElementById('main-frame').getBoundingClientRect().height - Math.max(expected, innerHeight * .4)) <= 1",
                        arg=content_height,
                    )
                    frame_height = page.locator("#main-frame").bounding_box()["height"]
                    assert frame_height >= content_height - 1
                    heights.append(frame_height)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert abs(heights[0] - heights[-1]) <= 1, heights
                stable = page.evaluate("""async () => {
                    const values = [];
                    for (let index = 0; index < 30; index++) {
                        await new Promise(requestAnimationFrame);
                        values.push(document.getElementById('main-frame').getBoundingClientRect().height);
                    }
                    return values;
                }""")
                assert max(stable) - min(stable) <= 1, stable
                if filename == "short.html":
                    assert heights[-1] < 500
                else:
                    assert heights[-1] > 900
            assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()} == original
        finally:
            browser.close()
