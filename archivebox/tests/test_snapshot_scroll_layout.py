"""The snapshot shell and its preview must not nest viewport scrollbars."""

import hashlib
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("same_origin", [False, True])
@pytest.mark.parametrize(
    "viewport",
    [(320, 568), (390, 844), (844, 390), (768, 1024), (1024, 768), (1366, 768), (1920, 1080), (2560, 1440), (1280, 480), (640, 240)],
)
def test_expanded_header_and_preview_share_outer_scroll(snapshot, live_server, browser_runtime, same_origin, viewport):
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    if same_origin:
        machine.config["SERVER_SECURITY_MODE"] = "unsafe-onedomain-noadmin"
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    output = snapshot.output_dir / "singlefile" / "singlefile.html"
    output.parent.mkdir(parents=True)
    output.write_text("<!doctype html><title>Long saved page</title>" + "<p>Archived paragraph</p>" * 400)
    original = hashlib.sha256(output.read_bytes()).hexdigest()
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="singlefile",
        status="succeeded",
        output_str="singlefile/singlefile.html",
        output_files={"singlefile.html": {"size": output.stat().st_size, "mimetype": "text/html"}},
        output_size=output.stat().st_size,
    )
    snapshot.write_index_jsonl()
    host = "archivebox.localhost" if same_origin else "web.archivebox.localhost"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        page.goto(f"http://{host}:{port}{snapshot.get_absolute_url()}/index.html#singlefile/singlefile.html")
        preview = page.frame_locator("#main-frame").frame_locator("#document")
        expect(preview.locator("p")).to_have_count(400)
        toggle = page.get_by_role("button", name="Toggle saved outputs", exact=True)
        expect(toggle).to_have_attribute("aria-expanded", "true")
        for expanded in (True, False, True):
            page.evaluate("scrollTo(0, 0)")
            if toggle.get_attribute("aria-expanded") != str(expanded).lower():
                toggle.click()
            page.wait_for_function("document.getElementById('main-frame').clientHeight > 10000")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            frame = page.locator("#main-frame").bounding_box()
            header = page.locator("header").bounding_box()
            assert frame["y"] >= header["y"] + header["height"] - 1
            assert page.locator(".header-bottom").evaluate("e => e.scrollHeight <= e.clientHeight + 1")
            preview_frame = page.locator("#main-frame").element_handle().content_frame()
            document_frame = preview_frame.locator("#document").element_handle().content_frame()
            for child in (preview_frame, document_frame):
                assert child.evaluate("document.documentElement.scrollHeight <= innerHeight + 1")
                assert child.evaluate("scrollY") == 0
            if evidence := os.environ.get("REPLAY_VISUAL_DIR"):
                target = Path(evidence)
                target.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(target / f"html-{viewport[0]}x{viewport[1]}-{expanded}.png"))
            page.evaluate("y => scrollTo(0, y)", frame["y"])
            previous_scroll = page.evaluate("scrollY")
            page.mouse.move(viewport[0] / 2, viewport[1] / 2)
            page.mouse.wheel(0, 600)
            page.wait_for_function("previous => scrollY > previous", arg=previous_scroll)
            assert document_frame.evaluate("scrollY") == 0
            assert preview_frame.evaluate("scrollY") == 0
        preview.locator("p").last.scroll_into_view_if_needed()
        assert page.evaluate("scrollY > 10000")
        assert document_frame.evaluate("scrollY") == 0
        assert hashlib.sha256(output.read_bytes()).hexdigest() == original
        browser.close()
