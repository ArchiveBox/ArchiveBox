"""Proof viewers use installed templates and actual saved cryptographic evidence."""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from abx_plugins import get_plugins_dir
from playwright.sync_api import sync_playwright

pytestmark = pytest.mark.django_db(transaction=True)

PROOF_FIXTURE = Path(__file__).parent / "fixtures" / "tlsnotary" / "hacker-news"
LEGACY_PROOF_FIXTURE = Path(__file__).parent / "fixtures" / "legacy_proofs"


def run_plugin(name: str, snap: Path, **config: str):
    from abx_plugins.plugins.base.testing import get_hook_script, run_hook_and_parse

    plugins = Path(get_plugins_dir())
    hook = get_hook_script(plugins / name, "on_Snapshot__*")
    assert hook is not None
    return run_hook_and_parse(
        hook,
        "https://news.ycombinator.com/",
        None,
        cwd=snap,
        env={**os.environ, "SNAP_DIR": str(snap), **config},
        timeout=90,
    )


def test_tlsnotary_preview_verifies_saved_evidence_without_remote_requests(snapshot, client, live_server, tmp_path):
    from archivebox.core.models import ArchiveResult
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    evidence = snapshot.output_dir / "tlsnotary"
    fixture = PROOF_FIXTURE
    evidence.mkdir(parents=True)
    for name in ("receipt.json", "response.http", "metadata.json"):
        shutil.copyfile(fixture / name, evidence / name)
    (snapshot.output_dir / "chrome").mkdir()
    shutil.copyfile(fixture / "navigation.json", snapshot.output_dir / "chrome/navigation.json")
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="tlsnotary",
        start_ts=datetime.fromisoformat(json.loads((fixture / "navigation.json").read_text())["timestamp"]),
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
        assert len(page.locator("#summary .status-hash").inner_text()) == 64
        assert page.locator("#content").is_visible()
        topology = page.locator("#proof-tree")
        assert "SHA-256(response.http ∥ blinder)" in topology.inner_text()
        assert "server_name" in topology.inner_text()
        assert topology.locator(".participants .info-card").count() == 3
        assert topology.locator(".timeline-entry").count() == 4
        assert "Your ArchiveBox server generates 16 random hiding bytes" in topology.inner_text()
        assert "Signed response byte range" in topology.inner_text()
        assert topology.locator('a[href*="response.http"]').count() > 0
        assert topology.locator('a[href*="receipt.json"]').count() > 0
        assert page.locator("a", has_text="Verify independently").get_attribute("href") == "https://tlsnotary.zervice.io/"
        assert all(urlsplit(request).hostname == hostname for request in requests)
        page.screenshot(path=str(tmp_path / "tlsnotary-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "tlsnotary-mobile.png"), full_page=True)
        print(f"TLSNotary screenshots: {tmp_path}")
        page.goto(url)
        page.wait_for_function("document.querySelector('#status').classList.contains('verified')")
        assert page.locator("nav").is_visible()
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

    from abx_plugins.plugins.base.testing import install_required_binary_from_config

    from archivebox.core.models import ArchiveResult
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    plugins = Path(get_plugins_dir())
    shutil.copytree(PROOF_FIXTURE, snapshot.output_dir / "tlsnotary")
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
        page.wait_for_function("document.querySelector('#manifest-sha256')?.textContent.length === 64")
        assert page.locator("#manifest-sha256").inner_text() == hashlib.sha256(manifest).hexdigest()
        assert page.locator("#status > span").inner_text() == "Hashes submitted to opentimestamps.org"
        assert page.locator("#summary .status-hash").inner_text() == page.locator("#submitted-sha256").inner_text()
        topology = page.locator("#proof-tree")
        assert "Hash submitted to OpenTimestamps" in topology.inner_text()
        inventory = topology.locator("#manifest-sha256")
        assert inventory.get_attribute("href").endswith("#hashes")
        assert topology.locator("details").count() == 0
        nonce = bytes.fromhex(page.locator("#submission-nonce").inner_text())
        assert len(nonce) == 16
        assert page.locator("#submitted-sha256").inner_text() == hashlib.sha256(hashlib.sha256(manifest).digest() + nonce).hexdigest()
        page.wait_for_function("document.querySelector('#submission-tree').textContent.includes('POST /digest')")
        page.get_by_text("Recorded submission details", exact=True).click()
        assert "POST /digest" in page.locator("#submission-tree").inner_text()
        assert "Blinded digest, source IP, request timing and HTTP client headers" in page.locator("#submission-tree").inner_text()
        page.screenshot(path=str(tmp_path / "opentimestamps-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "opentimestamps-mobile.png"), full_page=True)
        print(f"OpenTimestamps screenshots: {tmp_path}")
        manifest_link = topology.get_by_role("link", name="hashes.json", exact=True).get_attribute("href")
        assert "preview=1" in manifest_link and "raw=1" in manifest_link
        page.goto(manifest_link)
        assert page.locator("pre").inner_text() == manifest.decode()
        page.goto(f"http://{hostname}:{port}{path}")
        page.goto(f"http://{hostname}:{port}{path}")
        page.wait_for_function("document.querySelector('#manifest-sha256')?.textContent.length === 64")
        assert page.locator("nav").is_visible()
        assert page.locator("#status").is_visible()
        browser.close()


@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
def test_legacy_proof_cards_and_viewers_on_canonical_snapshot_origin(snapshot, live_server, client, mode):
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine
    from django.utils import timezone

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": mode,
    }
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    for plugin in ("tlsnotary", "opentimestamps"):
        shutil.copytree(LEGACY_PROOF_FIXTURE / plugin, snapshot.output_dir / plugin)
    paths = {
        "tlsnotary": "tlsnotary/capture-82e4bf62f426a03f80f8f4fb7c6d7b0c634a9ae4fd78b5f4c06e398311a727c4/index.html",
        "opentimestamps": "opentimestamps/stamp-tc1mgx85/index.html",
    }
    results = {}
    for plugin, path in paths.items():
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin=plugin,
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            start_ts=timezone.now(),
            output_str=path,
        )
        assert result.update_output_metadata_from_filesystem(full_scan=True)
        results[plugin] = result
    assert {output["name"] for output in snapshot.get_html_details_context()["archiveresults"]} >= set(paths)

    other = Snapshot.objects.create(url="https://other.example", crawl=snapshot.crawl)
    other.permissions = "public"
    other.save(update_fields=["permissions"])
    foreign_path = (
        f"/snapshot/{other.id}/_card/{results['tlsnotary'].id}"
        if mode == "safe-onedomain-nojsreplay"
        else f"/_card/{results['tlsnotary'].id}"
    )
    assert client.get(foreign_path, HTTP_HOST=get_snapshot_host(str(other.id))).status_code == 404

    web_host = "web.archivebox.localhost" if mode == "safe-subdomains-fullreplay" else "archivebox.localhost"
    snapshot_host = (
        f"snap-{str(snapshot.id).replace('-', '')[-12:]}.archivebox.localhost" if mode == "safe-subdomains-fullreplay" else web_host
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1, MAP archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page()
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        page.goto(f"http://{web_host}:{port}/{snapshot.url_path}/index.html")
        assert urlsplit(page.url).hostname == web_host
        tls_status = page.frame_locator('.output-stack-metadata .stack-cover iframe[title="tlsnotary card"]').locator("#status.success")
        tls_status.wait_for(state="visible")
        assert "trusted verifier key" in tls_status.inner_text()
        page.locator(".output-stack-metadata").click()
        stamp_status = page.frame_locator('.stack-tray iframe[title="opentimestamps card"]').locator("#status.legacy")
        stamp_status.wait_for(state="visible")
        assert "Legacy timestamp proof saved" in stamp_status.inner_text()
        assert all(urlsplit(url).hostname == snapshot_host for url in requests if "receipt.json" in url or "hashes.json" in url)

        selected_output = "#opentimestamps/stamp-tc1mgx85/index.html"
        page.goto(f"http://{web_host}:{port}/{snapshot.url_path}/index.html{selected_output}")
        assert urlsplit(page.url).hostname == web_host
        assert urlsplit(page.url).fragment == selected_output.removeprefix("#")

        preview_root = "" if mode == "safe-subdomains-fullreplay" else f"/snapshot/{snapshot.id}"
        page.goto(f"http://{snapshot_host}:{port}{preview_root}/{paths['tlsnotary']}?preview=1")
        page.locator("#status.verified").wait_for()
        assert "trusted verifier key" in page.locator("#status").inner_text()
        page.goto(f"http://{snapshot_host}:{port}{preview_root}/{paths['opentimestamps']}?preview=1")
        page.locator("#status.legacy").wait_for()
        assert "Legacy timestamp proof saved" in page.locator("#status").inner_text()
        browser.close()
