"""Proof viewers use installed templates and actual saved cryptographic evidence."""

import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from abx_plugins import get_plugins_dir
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.django_db(transaction=True)


def test_tlsnotary_preview_verifies_saved_evidence_without_remote_requests(snapshot, client, live_server, tmp_path):
    from archivebox.core.models import ArchiveResult
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    plugins = Path(get_plugins_dir())
    evidence = snapshot.output_dir / "tlsnotary"
    shutil.copytree(plugins / "tlsnotary/tests/fixtures/hacker-news", evidence)
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="tlsnotary",
        status="succeeded",
        output_str="tlsnotary/receipt.json",
    )
    host = get_snapshot_host(str(snapshot.id))
    path = f"/{result.output_str}?preview=1"
    preview = client.get(path, HTTP_HOST=host)
    assert preview.status_code == 200
    assert b"export async function verifyReceipt" in preview.content
    assert b"{% include" not in preview.content
    assert b"<iframe" not in preview.content
    assert b"Verify independently" in preview.content
    raw = client.get(f"/{result.output_str}", HTTP_HOST=host)
    assert raw.status_code == 200
    assert b"".join(raw.streaming_content) == (evidence / "receipt.json").read_bytes()

    port = urlsplit(live_server.url).port
    hostname = host.split(":")[0]
    url = f"http://{hostname}:{port}{path}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=[f"--host-resolver-rules=MAP {hostname} 127.0.0.1"])
        page = browser.new_page()
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        page.goto(url)
        page.wait_for_function("document.querySelector('#status').classList.contains('verified')")
        assert "news.ycombinator.com" in page.locator("#summary").inner_text()
        assert page.locator("#content").is_visible()
        topology = page.locator("#proof-tree")
        assert "SHA-256(response.http ∥ blinder)" in topology.inner_text()
        assert "server_name" in topology.inner_text()
        assert "Verifier → your archive" in topology.inner_text()
        assert "Your extension generates 16 random hiding bytes" in topology.inner_text()
        assert "start" in topology.inner_text() and "end" in topology.inner_text()
        assert topology.locator('a[href*="response.http"]').count() > 0
        assert topology.locator('a[href*="receipt.json"]').count() > 0
        assert page.locator("a", has_text="Verify independently").get_attribute("href") == "https://tlsnotary.zervice.io/"
        assert all(urlsplit(request).hostname == hostname for request in requests)
        page.screenshot(path=str(tmp_path / "tlsnotary-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "tlsnotary-mobile.png"), full_page=True)
        print(f"TLSNotary screenshots: {tmp_path}")
        page.goto(url + "&card=1")
        page.wait_for_function("document.querySelector('#status').classList.contains('verified')")
        assert page.locator("nav").is_hidden()
        assert page.locator("#summary").is_visible()

        response_path = evidence / "response.http"
        original = response_path.read_bytes()
        response_path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        page.goto(url)
        page.wait_for_function("document.querySelector('#status').classList.contains('failed')")
        assert "commitment" in page.locator("#status").inner_text()
        assert page.locator("#content").is_hidden()
        assert page.locator("#details").inner_text() == ""
        assert page.locator("#proof-tree").inner_text() == ""
        assert all(urlsplit(request).hostname == hostname for request in requests)
        browser.close()


def test_opentimestamps_preview_reads_raw_proof_generation(snapshot, client, live_server, tmp_path):
    import hashlib
    import json

    from abx_plugins.plugins.base.testing import install_required_binary_from_config
    from abx_plugins.plugins.opentimestamps.tests.test_opentimestamps import run_plugin

    from archivebox.core.models import ArchiveResult
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    plugins = Path(get_plugins_dir())
    shutil.copytree(plugins / "tlsnotary/tests/fixtures/hacker-news", snapshot.output_dir / "tlsnotary")
    code, record, stderr = run_plugin("hashes", snapshot.output_dir, HASHES_ENABLED="true")
    assert code == 0 and record["status"] == "succeeded", stderr
    binary = install_required_binary_from_config(plugins / "opentimestamps", "ots")
    code, record, stderr = run_plugin(
        "opentimestamps",
        snapshot.output_dir,
        HASHES_ENABLED="true",
        OPENTIMESTAMPS_ENABLED="true",
        OPENTIMESTAMPS_BINARY=str(binary.abspath),
    )
    assert code == 0 and record["status"] == "succeeded", stderr
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="opentimestamps",
        status=record["status"],
        output_str=record["output_str"],
    )
    evidence = snapshot.output_dir / "opentimestamps"
    assert {path.name for path in evidence.iterdir()} == {"hashes.json", "hashes.json.ots", "submission.json", "proof-info.txt"}
    manifest = (evidence / "hashes.json").read_bytes()
    host = get_snapshot_host(str(snapshot.id))
    path = f"/{result.output_str}?preview=1"
    preview = client.get(path, HTTP_HOST=host)
    assert preview.status_code == 200
    assert b"<iframe" not in preview.content
    raw = client.get(f"/{result.output_str}", HTTP_HOST=host)
    assert raw.status_code == 200
    assert b"".join(raw.streaming_content) == (evidence / "hashes.json.ots").read_bytes()
    hostname = host.split(":")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=[f"--host-resolver-rules=MAP {hostname} 127.0.0.1"])
        page = browser.new_page()
        page.goto(f"http://{hostname}:{port}{path}")
        page.wait_for_function("document.querySelector('#manifest-sha256').textContent.length === 64")
        assert page.locator("#root-hash").inner_text() == json.loads(manifest)["root_hash"]
        assert page.locator("#manifest-sha256").inner_text() == hashlib.sha256(manifest).hexdigest()
        assert page.locator("#status").inner_text() == "Timestamp proof saved · Bitcoin confirmation not checked"
        topology = page.locator("#proof-tree")
        for field in ("root_hash", "tree_levels", "files", "metadata", "timestamp", "file_count", "total_size", "tree_depth"):
            assert field in topology.inner_text()
        assert page.locator("#root-hash").get_attribute("href").endswith("#hashes")
        page.wait_for_function("document.querySelector('#submission-tree').textContent.includes('Calendar servers combine')")
        assert "POST /digest" in page.locator("#submission-tree").inner_text()
        assert "no manifest JSON" in page.locator("#submission-tree").inner_text()
        page.screenshot(path=str(tmp_path / "opentimestamps-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "opentimestamps-mobile.png"), full_page=True)
        print(f"OpenTimestamps screenshots: {tmp_path}")
        manifest_link = page.locator("#manifest-sha256").get_attribute("href")
        assert "preview=1" in manifest_link and "raw=1" in manifest_link
        page.goto(manifest_link)
        assert page.locator("pre").inner_text() == manifest.decode()
        page.goto(f"http://{hostname}:{port}{path}")
        page.goto(f"http://{hostname}:{port}{path}&card=1")
        page.wait_for_function("document.querySelector('#manifest-sha256').textContent.length === 64")
        assert page.locator("nav").is_hidden()
        assert page.locator("#status").is_visible()
        browser.close()
