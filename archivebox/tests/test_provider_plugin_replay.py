"""Capture real public provider documents with the CLI, then replay through the UI.

These network acceptance tests deliberately fail when a public fixture changes
or its owner revokes access. Plugin-local tests assert provider-specific content.
"""

import hashlib
import json
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from abx_plugins import get_plugins_dir
from playwright.sync_api import expect, sync_playwright

from .conftest import cli_env, get_free_port, run_archivebox_cmd, start_archivebox_server, stop_archivebox_process


DOCUMENT_PROVIDERS = {"microsoft365", "notion", "figma", "tldraw", "excalidraw", "drawio", "miro", "canva", "protondocs", "iwork"}


@pytest.mark.parametrize(
    "plugin",
    [
        "nextcloud",
        "drawio",
        "protondocs",
        "protondrive",
        "box",
        "tldraw",
        "excalidraw",
        "notion",
        "onedrive",
        "microsoft365",
        "iclouddrive",
        "iwork",
        "wetransfer",
    ],
)
def test_public_provider_capture_and_replay(plugin, initialized_archive, browser_runtime):
    capture_and_replay(plugin, initialized_archive, browser_runtime)


def capture_and_replay(plugin, root, browser_runtime, *, headless=True):
    """Exercise the CLI and browser UI for public and authenticated providers."""
    plugin_dir = Path(get_plugins_dir()) / plugin
    recipe = json.loads((plugin_dir / "screenshot.json").read_text())
    port = get_free_port()
    env = cli_env(
        ABXPKG_LIB_DIR=str(browser_runtime["lib_dir"]),
        CHROME_BINARY=str(browser_runtime["chrome_binary"]),
        CHROME_HEADLESS=str(headless),
        BASE_URL=f"http://archivebox.localhost:{port}",
        BIND_ADDR=f"127.0.0.1:{port}",
    )
    captured = run_archivebox_cmd(["add", f"--plugins={plugin},title", recipe["url"]], cwd=root, env=env, timeout=240)
    (root / "capture.log").write_text(captured.stdout + captured.stderr)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    listed = run_archivebox_cmd(["list", "--json"], cwd=root, env=env, timeout=30)
    assert listed.returncode == 0, listed.stderr
    snapshots, _ = json.JSONDecoder().raw_decode(listed.stdout.lstrip())
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    output = Path(snapshot["output_dir"]) / plugin
    manifest = json.loads((output / "downloads.json").read_text())
    assert manifest["files"], captured.stdout
    for item in manifest["files"]:
        data = (output / item["path"]).read_bytes()
        assert len(data) == item["size"] > 0
        assert hashlib.sha256(data).hexdigest() == item["sha256"]

    server = start_archivebox_server(root, port=port, env=env, log_name="server.log")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
            page.goto(f"http://web.archivebox.localhost:{port}/public/")
            # Discover and follow the real snapshot link rendered by the index.
            snapshot_link = page.locator(f'a[href*="/web/"][href*="{snapshot["id"]}"]').first
            snapshot_link.click()
            stack = page.get_by_role("button", name="Embedded media,", exact=False)
            stack.click()
            card = page.locator(f'.thumb-card[data-plugin-name="{plugin}"]')
            card.locator('a[target="preview"]').first.click()
            preview = page.frame_locator("#main-frame")
            if plugin in DOCUMENT_PROVIDERS:
                formats = preview.locator("#formats button.format")
                expect(formats).to_have_count(len(manifest["files"]))
                for item in manifest["files"]:
                    button = preview.get_by_role("button", name=item["format"].upper(), exact=True)
                    button.click()
                    expect(button).to_have_attribute("aria-pressed", "true")
                    expect(preview.locator("#preview-title")).to_have_text(item["filename"])
                    # Each format button must expose its actual original file.
                    with page.expect_download() as original:
                        preview.locator("#download").click()
                    assert original.value.failure() is None
                    assert Path(original.value.path()).read_bytes() == (output / item["path"]).read_bytes()
                preview.get_by_role("link", name="View all files", exact=True).click()
                expect(preview.get_by_role("searchbox", name="Filter files")).to_be_visible()
                # The manifest URL stays in iframe.src after the viewer's own
                # navigation. Clicking its card must still reopen the toolbar.
                card.locator('a[target="preview"]').first.click()
                expect(formats).to_have_count(len(manifest["files"]))
                preview.get_by_role("link", name="View all files", exact=True).click()
            expect(preview.get_by_role("searchbox", name="Filter files")).to_be_visible()

            # Browse actual downloaded folders, then download an original again
            # through the replayer and compare its bytes with the capture.
            selected = min(
                manifest["files"],
                key=lambda item: (item["format"] not in {"png", "svg", "jpeg", "jpg"}, item["format"] not in {"md", "txt"}, item["size"]),
            )
            if plugin == "notion":
                # Keep Markdown as an original download; its accompanying HTML
                # preserves tables in the stock replayer's document view.
                selected = next(item for item in manifest["files"] if item["format"] == "html")
            relative = Path(selected["path"]).relative_to("files")
            for directory in relative.parts[:-1]:
                preview.get_by_role("link", name=directory + "/", exact=True).click()
            expect(preview.locator(".entry-name").filter(has_text=relative.name)).to_be_visible()
            with page.expect_download() as downloaded:
                preview.get_by_role("link", name="Download " + relative.name, exact=True).click()
            assert downloaded.value.failure() is None
            assert Path(downloaded.value.path()).read_bytes() == (output / selected["path"]).read_bytes()

            if selected["format"] in {"png", "svg", "jpeg", "jpg"}:
                # Large originals intentionally have no directory thumbnail.
                # Open the real saved image through its normal file link.
                with page.expect_event(
                    "framenavigated",
                    predicate=lambda frame: unquote(urlsplit(frame.url).path).endswith("/" + relative.as_posix()),
                ) as navigated:
                    preview.locator(".directory-link").filter(has_text=relative.name).click()
                navigated.value.wait_for_load_state("load")
                rendered = preview.locator("svg, img").first
                expect(rendered).to_be_visible()
                assert rendered.evaluate(
                    "el => el.tagName.toLowerCase() === 'svg' ? el.getBoundingClientRect().width > 0 : el.complete && el.naturalWidth > 0",
                )
                assert rendered.bounding_box()["width"] <= page.locator("#main-frame").bounding_box()["width"]
            elif selected["format"] in {"md", "txt"} and selected["size"] < 65536:
                expect(preview.locator("pre").filter(has_text=(output / selected["path"]).read_text().strip()[:60])).to_be_visible()
                if selected["format"] == "md":
                    preview.locator(".directory-link").filter(has_text=relative.name).click()
                    expect(preview.locator("body")).to_contain_text(manifest["title"])
            elif selected["format"] == "html":
                preview.locator(".directory-link").filter(has_text=relative.name).click()
                expect(preview.get_by_role("table")).to_have_count(4)
                expect(preview.locator("body")).to_contain_text(manifest["title"])
            elif selected["format"] == "zip":
                with zipfile.ZipFile(output / selected["path"]) as archive:
                    assert archive.testzip() is None
                    picture = min(
                        (item for item in archive.infolist() if Path(item.filename).suffix.lower() in {".jpg", ".jpeg", ".png"}),
                        key=lambda item: item.file_size,
                    )
                    expected_image = archive.read(picture)
                preview.locator(".directory-link").filter(has_text=relative.name).click()
                for directory in Path(picture.filename).parts[:-1]:
                    preview.locator("button.entry").filter(has_text=directory + "/").click()
                preview.locator("button.entry").filter(has_text=Path(picture.filename).name).click()
                saved_image = preview.locator("#content img")
                expect(saved_image).to_be_visible()
                assert saved_image.evaluate("el => el.complete && el.naturalWidth > 0")
                with page.expect_download() as zip_download:
                    preview.get_by_role("button", name="Download", exact=True).click()
                assert zip_download.value.failure() is None
                assert Path(zip_download.value.path()).read_bytes() == expected_image
            elif selected["format"] == "pdf":
                with (
                    page.expect_response(
                        lambda response: (
                            unquote(urlsplit(response.url).path).endswith("/" + relative.as_posix())
                            and response.headers.get("content-type", "").startswith("application/pdf")
                        ),
                    ) as pdf_response,
                    page.expect_event(
                        "framenavigated",
                        predicate=lambda frame: frame.url == "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html",
                    ) as pdf_viewer,
                ):
                    preview.locator(".directory-link").filter(has_text=relative.name).click()
                assert pdf_response.value.status == 200
                # Chrome renders PDFs in its built-in extension's child frame.
                # Verify the actual viewer and a loaded page thumbnail.
                viewer = pdf_viewer.value
                expect(viewer.get_by_role("textbox", name="Page number", exact=True)).to_have_value("1")
                expect(viewer.get_by_role("tab", name="Thumbnail for page 1", exact=True)).to_be_visible()
                # Chrome displays an embedded PDF /Title when one is present.
                pdf_title = {
                    "box": "Microsoft Word - registration.docx",
                    "microsoft365": "The Child Welfare Research-to-Policy Network",
                    "iwork": "CoT-zuzalu-final",
                    "canva": 'Copy of Public Access - Certificate v1 (Bleed) - 8.5 x 11"',
                }.get(plugin, relative.name)
                expect(viewer.locator("viewer-toolbar")).to_contain_text(pdf_title)

            if plugin in DOCUMENT_PROVIDERS:
                # A bookmarked raw manifest must retain the replay sandbox,
                # even though this same path also has a trusted full viewer.
                shell = page.url.split("#", 1)[0]
                page.goto(f"{shell}#{plugin}/downloads.json?preview=1&raw=1")
                expect(preview.locator("pre")).to_be_visible()
                assert json.loads(preview.locator("pre").inner_text()) == manifest
                assert page.locator("#main-frame").get_attribute("sandbox") is not None
                pdf = next((item for item in manifest["files"] if item["format"] == "pdf"), None)
                if pdf:
                    with page.expect_event(
                        "framenavigated",
                        predicate=lambda frame: frame.url == "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html",
                    ) as best_viewer:
                        card.locator('a[target="preview"]').first.click()
                    expect(best_viewer.value.get_by_role("textbox", name="Page number", exact=True)).to_have_value("1")
                    expect(best_viewer.value.get_by_role("tab", name="Thumbnail for page 1", exact=True)).to_be_visible()
                    # Gallery URLs and bookmarked replays must also load the
                    # native PDF when entering the document viewer directly.
                    assert page.locator("#main-frame").get_attribute("sandbox") is None
                    with page.expect_event(
                        "framenavigated",
                        predicate=lambda frame: frame.url == "chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html",
                    ) as reloaded_viewer:
                        page.reload()
                    expect(reloaded_viewer.value.get_by_role("textbox", name="Page number", exact=True)).to_have_value("1")
                    expect(reloaded_viewer.value.get_by_role("tab", name="Thumbnail for page 1", exact=True)).to_be_visible()
                else:
                    card.locator('a[target="preview"]').first.click()
                    saved_preview = preview.frame_locator("#preview")
                    if plugin == "notion":
                        expect(saved_preview.get_by_role("table")).to_have_count(4)
                    elif plugin in {"tldraw", "excalidraw", "drawio"}:
                        expect(saved_preview.locator("img, svg").first).to_be_visible()
                    else:
                        expect(saved_preview.locator("body")).to_contain_text("artists")
                expect(preview.locator('#formats button[aria-pressed="true"]')).to_have_count(1)
            page.get_by_role("button", name="Toggle saved outputs", exact=True).click()
            page.locator("body").press("Control+Home")
            expect(page.get_by_role("banner")).to_be_visible()
            for label, width, height in (("desktop", 1600, 1000), ("tablet", 1024, 1366), ("mobile", 390, 844)):
                page.set_viewport_size({"width": width, "height": height})
                page.screenshot(path=str(root / f"{plugin}-{label}.jpg"), type="jpeg", quality=85)
            browser.close()
    finally:
        stop_archivebox_process(server)
