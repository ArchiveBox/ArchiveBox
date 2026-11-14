"""Shared model previews read original saved geometry without a plugin-specific route."""

import json
import shutil
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("extension", ["glb", "gltf"])
def test_model_directory_preview_orbit_download_and_saved_sidecars(snapshot, live_server, browser_runtime, extension, tmp_path):
    from django.core.management import call_command
    from archivebox.core.models import ArchiveResult
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    root = snapshot.output_dir / "staticfile" / "models"
    shutil.copytree(Path(__file__).parent / "fixtures/model-preview", root)
    original = (root / f"Box.{extension}").read_bytes()
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    base = f"http://{host}:{port}/staticfile/models/"
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="staticfile",
        hook_name="on_Snapshot__50_staticfile.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str=f"models/Box.{extension}",
        output_files={f"models/{file.name}": {"size": file.stat().st_size} for file in root.iterdir()},
    )
    destination = tmp_path / "export"
    call_command("site_export", query=f"id__exact={snapshot.pk}", public_only=True, format="html_zip", destination=str(destination))
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(destination / "site.zip") as archive:
        archive.extractall(extracted)
    exported = extracted / snapshot.static_archive_path / "staticfile/models"
    assert (exported / f"Box.{extension}").read_bytes() == original
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], f"--host-resolver-rules=MAP {host} 127.0.0.1"],
        )
        page = browser.new_page(accept_downloads=True, viewport={"width": 1000, "height": 800})
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        page.goto(base + "?files=1")
        page.locator(".directory-link").filter(has_text=f"Box.{extension}").click()
        canvas = page.locator("#model")
        expect(canvas).to_have_attribute("data-state", "ready")
        expect(canvas).to_have_attribute("data-triangles", "12")
        expect(canvas).to_have_attribute("data-rendered-triangles", "12")
        before = canvas.screenshot()
        page.mouse.move(500, 400)
        page.mouse.down()
        page.mouse.move(660, 460, steps=12)
        page.mouse.up()
        after_orbit = canvas.screenshot()
        assert before != after_orbit
        page.mouse.wheel(0, -200)
        assert canvas.screenshot() != after_orbit
        page.get_by_role("button", name="Reset view").click()
        assert canvas.screenshot() == before
        with page.expect_download() as downloaded:
            page.get_by_role("link", name=f"Download Box.{extension}", exact=True).click()
        assert Path(downloaded.value.path()).read_bytes() == original
        raw = page.request.get(base + f"Box.{extension}?raw=1")
        assert raw.status == 200 and raw.body() == original
        ranged = page.request.get(base + f"Box.{extension}?preview=1&raw=1", headers={"Range": "bytes=0-83"})
        assert ranged.status == 206 and ranged.body() == original[:84]
        cached_range = page.evaluate("""async () => {
            const response = await fetch(location.href, {headers: {Range: 'bytes=0-83'}});
            return {status: response.status, bytes: Array.from(new Uint8Array(await response.arrayBuffer()))};
        }""")
        assert cached_range["status"] == 206 and bytes(cached_range["bytes"]) == original[:84]
        assert all(urlsplit(url).netloc == f"{host}:{port}" for url in requests)
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=extracted))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            requests.clear()
            page.goto(f"http://127.0.0.1:{server.server_port}/{snapshot.static_archive_path}/staticfile/models/")
            page.locator(".directory-link").filter(has_text=f"Box.{extension}").click()
            expect(canvas).to_have_attribute("data-state", "ready")
            expect(canvas).to_have_attribute("data-rendered-triangles", "12")
            assert all(urlsplit(url).netloc == f"127.0.0.1:{server.server_port}" for url in requests)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
        if extension == "gltf":
            assert any("Box0.bin" in url for url in requests)
            model = json.loads((root / "Box.gltf").read_text())
            model["buffers"][0]["uri"] = "https://example.com/never-fetch-live.bin"
            (root / "External.gltf").write_text(json.dumps(model))
            page.goto(base + "External.gltf?preview=1&raw=1")
            expect(canvas).to_have_attribute("data-state", "error")
            expect(page.get_by_role("alert")).to_contain_text("outside its saved directory")
            assert not any(urlsplit(url).hostname == "example.com" for url in requests)
        browser.close()
