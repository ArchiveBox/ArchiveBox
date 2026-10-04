"""Replay actual recorded HTML at a different DPR, without a live-site fallback."""

import os
import gzip
import hashlib
import zlib
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

from .conftest import localhost_session


@pytest.mark.django_db(transaction=True)
def test_archived_srcset_recovers_only_missing_image_candidates(snapshot, live_server, browser_runtime):
    from abx_plugins import get_plugins_dir
    from abx_plugins.plugins.base.testing import install_required_binary_from_config
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    install_required_binary_from_config(Path(get_plugins_dir()) / "archivewebpage", "archivewebpage", env=dict(os.environ))
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.url = "https://drive.google.com/drive/folders/1KpLl_1tcK0eeehzN980zbG-3M2nhbVks"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["url", "permissions"])
    fixture = Path(__file__).parent / "fixtures/responsive-images/google-drive.wacz"
    (snapshot.output_dir / "archivewebpage").mkdir(parents=True)
    with zipfile.ZipFile(fixture) as archive:
        recorded_responses = archive.read("archive/data.warc.gz")
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    origin = f"http://{host}:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], f"--host-resolver-rules=MAP {host} 127.0.0.1"],
        )
        for density, archive_format, include_logo in (
            (1, "warc", True),
            (2, "warc", True),
            (2, "warc", False),
            (1, "wacz", True),
            (2, "wacz", True),
        ):
            # zlib reads the first gzip member only: the same unmodified HTML
            # record, without the image record. No candidate should then work.
            recorded = gzip.decompress(recorded_responses) if include_logo else zlib.decompress(recorded_responses, wbits=31)
            if archive_format == "wacz":
                recorded = fixture.read_bytes()
            output = snapshot.output_dir / f"archivewebpage/google-drive.{archive_format}"
            output.write_bytes(recorded)
            context = browser.new_context(device_scale_factor=density)
            page = context.new_page()
            requests, responses = [], []
            context.on("request", lambda request: requests.append(request.url))
            page.on("response", lambda response: responses.append(response))
            page.goto(f"{origin}/archivewebpage/google-drive.{archive_format}?preview=1", wait_until="domcontentloaded")
            page.wait_for_function("window.archiveboxReplayReady")
            frame = next(frame for frame in page.frames if "/https://drive.google.com/drive/folders/" in frame.url)
            logo = frame.locator('img[srcset*="logo_drive_2026_color"]')
            logo.wait_for()
            decoded = logo.evaluate("async img => {try {await img.decode(); return img.naturalWidth > 0;} catch {return false;}}")
            assert decoded is include_logo
            images = [
                response for response in responses if "logo_drive_2026_color" in response.url and response.request.resource_type == "image"
            ]
            assert images, [(response.url, response.status) for response in responses]
            rendered = images[-1]
            assert rendered.status == (200 if include_logo else 404)
            if include_logo:
                assert hashlib.sha256(rendered.body()).hexdigest() == "c7469a9f91bd4d5a7f0f85e7e346a01d5962ee0c15b484fac90c197029cb9261"
            if density == 2 and include_logo:
                assert "2x_web_48dp.png" in rendered.url
                assert rendered.headers["x-archivebox-image-fallback"].endswith("1x_web_48dp.png")
                # The repair applies to image loads only, not arbitrary requests
                # for a missing URL, and never changes the archived bytes.
                assert frame.evaluate("url => fetch(url).then(r => r.status)", rendered.url) == 404
            else:
                assert "x-archivebox-image-fallback" not in rendered.headers
                if density == 1:
                    assert "1x_web_48dp.png" in rendered.url
            assert all(url.startswith((origin, "data:", "blob:")) for url in requests), requests
            with localhost_session() as session:
                raw = session.get(f"{origin}/archivewebpage/google-drive.{archive_format}?raw=1")
                assert raw.status_code == 200
                assert raw.content == recorded
            context.close()
        browser.close()
