"""Graph touch gestures through the real admin page and browser input pipeline."""

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_graph_pinch_continues_with_one_finger(admin_user, snapshot, live_server, browser_runtime, tmp_path):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/graph/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.locator('input[type="submit"]').click()
            page.wait_for_url("**/admin/graph/")
            expect(page.locator("#node-count")).not_to_have_text("0")
            canvas = page.locator("#graph canvas")
            expect(canvas).to_be_visible()
            box = canvas.bounding_box()
            x, y = box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.85
            cdp = page.context.new_cdp_session(page)
            for dimension in ("2D", "3D", "2D"):
                if page.locator("#dimensions").inner_text() != dimension:
                    page.locator("#dimensions").click()
                expect(page.locator("#dimensions")).to_have_text(dimension)
                # CDP sends trusted touch input. Lifting only one finger must
                # transition out of the two-pointer dolly state before moving.
                for kind, points in (
                    ("touchStart", [{"id": 1, "x": x - 30, "y": y}, {"id": 2, "x": x + 30, "y": y}]),
                    ("touchMove", [{"id": 1, "x": x - 45, "y": y}, {"id": 2, "x": x + 45, "y": y}]),
                    ("touchEnd", [{"id": 2, "x": x + 45, "y": y}]),
                    ("touchMove", [{"id": 1, "x": x - 50, "y": y + 20}]),
                    ("touchEnd", []),
                ):
                    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})
                assert errors == [], errors
            page.locator("#fit").click()
            expect(canvas).to_be_visible()
            page.screenshot(path=str(tmp_path / "networkgraph-touch.png"))
        finally:
            browser.close()
