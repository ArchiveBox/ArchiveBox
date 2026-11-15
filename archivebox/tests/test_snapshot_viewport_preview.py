"""Saved HTML must not recursively expand a viewport-dependent layout."""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from archivebox.core.models import ArchiveResult
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("sizing", ["min-height:100vh", "height:calc(100dvh - 64px)", "min-height:100%"])
def test_saved_html_viewport_sizing_cannot_feed_back_into_frame_height(snapshot, live_server, browser_runtime, sizing):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    output = Path(snapshot.output_dir) / "singlefile/content.html"
    output.parent.mkdir(parents=True)
    output.write_text(f"""<!doctype html><html><head><style>
        html,body {{ height:100%; margin:0 }} main {{ {sizing} }} footer {{ height:220px }}
        </style></head><body><main><h1>Viewport-sized page</h1>
        <button onclick="this.parentNode.style.minHeight='2000px'">Add content</button>
        </main><footer>End of saved page</footer></body></html>""")
    original = output.read_bytes()
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="singlefile",
        status="succeeded",
        output_str=output.name,
        output_files={output.name: {"size": output.stat().st_size, "mimetype": "text/html"}},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html", wait_until="load")
            frame = page.locator("#main-frame")
            document = frame.content_frame.frame_locator("#document")
            assert document.locator("h1").inner_text() == "Viewport-sized page"
            # Observe real animation frames, not a wall-clock sleep that could
            # accidentally stop before the ResizeObserver feedback appears.
            heights = page.evaluate("""async () => {
                const heights = [];
                for (let i = 0; i < 30; i++) {
                    await new Promise(requestAnimationFrame);
                    heights.push(document.getElementById('main-frame').getBoundingClientRect().height);
                }
                return heights;
            }""")
            assert max(heights) - min(heights) <= 1, heights
            assert max(heights) <= 1200, heights
            if "vh" in sizing:
                assert frame.get_attribute("data-size-mode") == "viewport"
                document.get_by_role("button", name="Add content").click()
                document.locator("footer").scroll_into_view_if_needed()
                assert document.locator("footer").is_visible()
                assert frame.bounding_box()["height"] <= 900
                page.set_viewport_size({"width": 390, "height": 700})
                page.wait_for_function("document.getElementById('main-frame').clientHeight === 560")
                assert frame.bounding_box()["height"] == 560
            assert output.read_bytes() == original
        finally:
            browser.close()
