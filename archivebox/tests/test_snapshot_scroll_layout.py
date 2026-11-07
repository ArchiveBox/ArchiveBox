"""The snapshot shell and its preview must not nest viewport scrollbars."""

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("same_origin", [False, True])
@pytest.mark.parametrize(
    "viewport",
    [(320, 568), (390, 844), (844, 390), (768, 1024), (1024, 768), (1366, 768), (1920, 1080), (2560, 1440), (1280, 480), (640, 240)],
)
def test_expanded_header_keeps_preview_inside_viewport(snapshot, live_server, browser_runtime, same_origin, viewport):
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
    ArchiveResult.objects.create(snapshot=snapshot, plugin="singlefile", status="succeeded", output_str="singlefile/singlefile.html")
    host = "archivebox.localhost" if same_origin else "web.archivebox.localhost"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        page.goto(f"http://{host}:{port}{snapshot.get_absolute_url()}/index.html#singlefile/singlefile.html")
        preview = page.frame_locator("#main-frame")
        expect(preview.locator("p")).to_have_count(400)
        toggle = page.get_by_role("button", name="Toggle saved outputs", exact=True)
        expect(toggle).to_have_attribute("aria-expanded", "true")
        for expanded in (True, False, True):
            if toggle.get_attribute("aria-expanded") != str(expanded).lower():
                toggle.click()
            assert page.evaluate("document.documentElement.scrollHeight <= innerHeight"), "The shell must not overflow its viewport"
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            frame = page.locator("#main-frame").bounding_box()
            assert frame["height"] > 0
            assert frame["y"] + frame["height"] <= viewport[1] + 1
            page.mouse.move(frame["x"] + frame["width"] / 2, frame["y"] + frame["height"] / 2)
            preview_frame = page.locator("#main-frame").element_handle().content_frame()
            previous_scroll = preview_frame.evaluate("scrollY")
            page.mouse.wheel(0, 600)
            preview_frame.wait_for_function("previous => scrollY > previous", arg=previous_scroll)
            assert page.evaluate("scrollY") == 0
            assert page.locator(".header-top").bounding_box()["y"] == 0
            expect(toggle).to_be_in_viewport()
        preview.locator("p").last.scroll_into_view_if_needed()
        preview_frame.wait_for_function("scrollY + innerHeight >= document.documentElement.scrollHeight - 20")
        page.mouse.wheel(0, 600)
        assert page.evaluate("scrollY") == 0
        assert page.locator(".header-top").bounding_box()["y"] == 0
        expect(toggle).to_be_in_viewport()
        browser.close()
