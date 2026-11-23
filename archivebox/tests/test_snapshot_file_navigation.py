"""File browsing keeps the snapshot URL and browser history in sync."""

import zipfile
from urllib.parse import quote, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("surface", ["snapshot", "web", "same-origin"])
@pytest.mark.parametrize("viewport", [(1280, 720), (390, 844), (844, 390)])
def test_snapshot_file_navigation(snapshot, live_server, browser_runtime, surface, viewport, tmp_path):
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    if surface == "same-origin":
        machine.config["SERVER_SECURITY_MODE"] = "unsafe-onedomain-noadmin"
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    root = snapshot.output_dir / "ytdlp"
    nested = root / "Nested %3A & café"
    nested.mkdir(parents=True)
    (nested / "note.txt").write_text("saved folder content")
    for index in range(40):
        (snapshot.output_dir / f"folder{index:02}").mkdir()
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    shell = (
        f"http://{host}:{port}/index.html"
        if surface == "snapshot"
        else f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html"
    )
    if surface == "same-origin":
        shell = f"http://archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page(accept_downloads=True, viewport={"width": viewport[0], "height": viewport[1]})
        page.goto(f"{shell}#?files=1")
        shell = page.url.split("#")[0]
        files = page.frame_locator("#main-frame")
        files.get_by_role("link", name="ytdlp/", exact=True).click()
        expect(page).to_have_url(f"{shell}#ytdlp/?files=1")
        expect(files.locator(".directory-title")).to_have_text("ytdlp/")
        files.get_by_role("link", name=f"{nested.name}/", exact=True).click()
        expect(page).to_have_url(f"{shell}#ytdlp/{quote(nested.name)}/?files=1")
        nested_url = page.url
        assert "Nested%20%253A%20%26%20caf%C3%A9/" in nested_url
        page.reload()
        expect(files.locator(".directory-title")).to_have_text(f"ytdlp/{nested.name}/")
        files.get_by_role("link", name="note.txt", exact=True).click()
        expect(page).to_have_url(f"{shell}#ytdlp/{quote(nested.name)}/note.txt")
        page.reload()
        expect(files.locator("body")).to_contain_text("saved folder content")
        page.go_back()
        expect(page).to_have_url(nested_url)
        expect(files.locator(".directory-title")).to_have_text(f"ytdlp/{nested.name}/")
        expect(files.locator('a[href*="download=zip"]')).to_have_count(0)
        with page.expect_download() as downloaded:
            files.get_by_role("button", name="⬇ Download Zip", exact=True).press("Enter")
        assert downloaded.value.failure() is None
        with zipfile.ZipFile(downloaded.value.path()) as archive:
            assert archive.namelist() == ["Nested-3A-caf/note.txt"]
            assert archive.read("Nested-3A-caf/note.txt") == b"saved folder content"
        assert page.url == nested_url
        files.get_by_role("link", name="↩ Up One Level", exact=True).click()
        expect(page).to_have_url(f"{shell}#ytdlp/?files=1")
        page.go_back()
        expect(page).to_have_url(nested_url)
        expect(files.locator(".directory-title")).to_have_text(f"ytdlp/{nested.name}/")
        page.go_forward()
        expect(page).to_have_url(f"{shell}#ytdlp/?files=1")
        expect(files.locator(".directory-title")).to_have_text("ytdlp/")
        files.get_by_role("link", name="↩ Up One Level", exact=True).click()
        expect(page).to_have_url(f"{shell}#?files=1")
        expect(files.locator(".directory-title")).to_have_text("/")
        # Generated file views share the outer page's scroll, including when
        # navigation shrinks the directory below the selected preview's minimum.
        child = page.locator("#main-frame").element_handle().content_frame()
        child.wait_for_function(
            "minimum => Math.abs(innerHeight - Math.max(Math.ceil(document.body.getBoundingClientRect().height), minimum)) <= 1",
            arg=viewport[1] * 0.4,
        )
        frame_box = page.locator("#main-frame-wrapper").bounding_box()
        assert frame_box["height"] > viewport[1]
        assert child.evaluate("document.documentElement.scrollHeight <= innerHeight + 1 && scrollY === 0")
        assert page.evaluate("document.documentElement.scrollHeight > innerHeight")
        header = page.locator("header").bounding_box()
        assert frame_box["y"] >= header["y"] + header["height"] - 1
        page.evaluate("scrollTo(0, 0)")
        page.screenshot(path=str(tmp_path / "file-browser-long.png"))
        page.mouse.move(viewport[0] / 2, viewport[1] / 2)
        page.mouse.wheel(0, 10000)
        page.wait_for_function("scrollY > 0")
        assert child.evaluate("scrollY") == 0
        standalone = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
        standalone.goto(child.url)
        expect(standalone.locator(".directory-title")).to_have_text("/")
        assert standalone.evaluate("document.documentElement.scrollHeight > innerHeight")
        standalone.mouse.wheel(0, 600)
        standalone.wait_for_function("scrollY > 0")
        standalone.close()
        files.get_by_role("link", name="ytdlp/", exact=True).click()
        expect(files.locator(".directory-title")).to_have_text("ytdlp/")
        child = page.locator("#main-frame").element_handle().content_frame()
        child.wait_for_function(
            "minimum => Math.abs(innerHeight - Math.max(Math.ceil(document.body.getBoundingClientRect().height), minimum)) <= 1",
            arg=viewport[1] * 0.4,
        )
        assert page.locator("#main-frame-wrapper").bounding_box()["height"] < frame_box["height"]
        assert child.evaluate("document.documentElement.scrollHeight <= innerHeight + 1 && scrollY === 0")
        header = page.locator("header").bounding_box()
        assert page.locator("#main-frame").bounding_box()["y"] >= header["y"] + header["height"] - 1
        page.screenshot(path=str(tmp_path / "file-browser.png"))
        files.get_by_role("link", name="⌂ Snapshot Page", exact=True).click()
        expect(page).to_have_url(shell)
        expect(page.locator("header .header-toggle")).to_have_count(1)
        assert page.frame_locator("#main-frame").locator("#main-frame").count() == 0
        browser.close()
