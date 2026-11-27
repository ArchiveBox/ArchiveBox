from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("platform", ["ios", "android", "browser", "desktop"])
def test_server_owns_native_header_and_progress(platform, admin_user, snapshot, live_server, browser_runtime, tmp_path):
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.status = snapshot.StatusChoices.STARTED
    snapshot.save(update_fields=["permissions", "status"])
    admin = f"http://admin.archivebox.localhost:{port}"
    user_agent = {
        "ios": "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) ArchiveBoxNative/iOS",
        "android": "Mozilla/5.0 (Linux; Android 16) ArchiveBoxNative/Android",
        "browser": "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X)",
        "desktop": "Mozilla/5.0 (X11; Linux x86_64)",
    }[platform]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280 if platform == "desktop" else 440, "height": 844}, user_agent=user_agent)
        page.add_init_script(
            "window.webkit = {messageHandlers: {archiveBoxNativeHeader: {postMessage(value) { window.testNativeHeaderReady = value; }}}};",
        )
        page.goto(f"{admin}/admin/login/?next=/admin/domains/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.wait_for_url("**/admin/domains/")
        monitor = page.locator("#progress-monitor")
        expect(monitor).to_have_count(1)
        if platform in ("browser", "desktop"):
            expect(monitor).to_be_visible()
            expect(page.locator("#branding a")).not_to_have_attribute("href", "archivebox://back")
            assert page.evaluate("window.testNativeHeaderReady") is None
        else:
            expect(monitor).to_be_hidden()
            if platform == "ios":
                back = page.get_by_role("link", name="Back", exact=True)
                expect(back).to_have_attribute("href", "archivebox://back")
                expect(back.locator("img")).to_be_visible()
                expect(page.locator("#header .breadcrumbs")).to_contain_text("Domains")
                assert page.evaluate("window.testNativeHeaderReady") == "ready"
                assert back.bounding_box()["height"] >= 44
        page.locator("#header").screenshot(path=str(tmp_path / f"domains-{platform}.png"))

        page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html", wait_until="domcontentloaded")
        if platform == "ios":
            back = page.get_by_role("link", name="Back", exact=True)
            expect(back).to_have_attribute("href", "archivebox://back")
            expect(back.locator("img")).to_be_visible()
            assert page.evaluate("window.testNativeHeaderReady") == "ready"
            url = page.locator(".header-url-text").bounding_box()
            logo = back.bounding_box()
            assert url is not None and logo is not None and logo["x"] < url["x"]
            assert back.locator("img").evaluate(
                """image => {
                    const logo = image.getBoundingClientRect();
                    return document.elementFromPoint(logo.x + logo.width / 2, logo.y + logo.height / 2)
                        ?.closest('a') === image.parentElement;
                }""",
            )
        else:
            expect(page.locator(".header-archivebox")).not_to_have_attribute("href", "archivebox://back")
        if platform in ("ios", "android"):
            expect(page.locator("#progress-monitor")).to_be_hidden()
        page.locator(".header-top").screenshot(path=str(tmp_path / f"replay-{platform}.png"))
        if platform in ("ios", "android"):
            page.goto(f"{admin}/admin/activity/")
            expect(page.locator("#progress-monitor")).to_be_visible()
            back = page.get_by_role("link", name="Back", exact=True)
            if platform == "ios":
                expect(back).to_have_attribute("href", "archivebox://back")
                assert page.evaluate("window.testNativeHeaderReady") == "ready"
            else:
                expect(back).to_have_count(0)
            page.locator("main").screenshot(path=str(tmp_path / f"activity-{platform}.png"))
            page.goto(f"{admin}/admin/core/snapshot/", wait_until="domcontentloaded")
            editor = page.get_by_role("combobox", name="Search snapshots")
            expect(editor).not_to_be_focused()
            assert page.evaluate("window.archiveBoxFocusSearch()") is True
            expect(editor).to_be_focused()
        browser.close()
