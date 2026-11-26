"""Repeat replay should use the engine's persistent archived-response cache."""

import shutil
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from abx_plugins import get_plugins_dir
from playwright.sync_api import sync_playwright

from archivebox.core.models import ArchiveResult
from archivebox.core.context_processors import get_static_cache_key
from archivebox.core.routes_util import build_snapshot_url
from archivebox.machine.models import Machine
from archivebox.tests.conftest import resolve_abxpkg_binary_env


@pytest.mark.django_db
@pytest.mark.parametrize("permissions", ["public", "unlisted"])
@pytest.mark.parametrize("hash_state", ["missing", "failed", "malformed", "complete"])
def test_replay_cache_policy_uses_hash_result_without_manifest_reads(snapshot, client, permissions, hash_state):
    from html import unescape
    from django.template import Context, Template
    from archivebox.misc.serve_static import _load_file_inventory

    snapshot.config = {**snapshot.config, "PERMISSIONS": permissions}
    snapshot.save(update_fields=["config"])
    output = snapshot.output_dir / "archivewebpage/capture.wacz"
    output.parent.mkdir(parents=True)
    content = (Path(__file__).parent / "fixtures/memento/iframetest.wacz").read_bytes()
    output.write_bytes(content)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="archivewebpage",
        status="succeeded",
        output_str=output.name,
        output_files={output.name: {"size": len(content)}},
    )
    hashed = hash_state == "complete"
    if hash_state != "missing":
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="hashes",
            status="failed" if hash_state == "failed" else "succeeded",
            output_str="Hash result",
            output_files={"hashes.json": "invalid" if hash_state == "malformed" else {"size": 100}},
        )
    route = urlsplit(build_snapshot_url(str(snapshot.id), "archivewebpage/capture.wacz"))
    link = Template('{% load core_tags %}{% snapshot_preview_url snapshot_id "archivewebpage/capture.wacz" %}').render(
        Context({"snapshot_id": str(snapshot.id)}),
    )
    assert parse_qs(urlsplit(unescape(link)).query) == {"preview": ["1"], "_abx_rev": [get_static_cache_key()]}
    manifest_reads = []

    def trace(frame, event, arg):
        if event == "call" and frame.f_code is _load_file_inventory.__code__:
            manifest_reads.append(frame.f_code.co_name)

    previous = sys.getprofile()
    sys.setprofile(trace)
    try:
        response = client.get(route.path, HTTP_HOST=route.netloc, HTTP_RANGE="bytes=0-15")
    finally:
        sys.setprofile(previous)
    assert response.status_code == 206
    assert b"".join(response.streaming_content) == content[:16]
    assert not manifest_reads
    policy = "public" if permissions == "public" else "private"
    assert response["Cache-Control"] == f"{policy}, " + (
        "max-age=31536000, immutable" if hashed else "max-age=60, stale-while-revalidate=300"
    )
    if hashed:
        cached = client.get(route.path, HTTP_HOST=route.netloc, HTTP_IF_NONE_MATCH=response["ETag"])
        assert cached.status_code == 304
        assert cached["Cache-Control"] == response["Cache-Control"]

    preview = client.get(route.path, {"preview": "1"}, HTTP_HOST=route.netloc)
    assert preview.status_code == 200
    assert "no-cache" in preview["Cache-Control"]
    for change in ("size", "mtime"):
        old_source = re.search(rb'data-source="([^"]+)"', preview.content)
        assert old_source is not None
        before = output.stat()
        if change == "size":
            with zipfile.ZipFile(output, "a") as archive:
                archive.comment = b"replacement"
            os.utime(output, ns=(before.st_atime_ns, before.st_mtime_ns))
            assert output.stat().st_mtime_ns == before.st_mtime_ns
            assert output.stat().st_size != before.st_size
        else:
            os.utime(output, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
            assert output.stat().st_size == before.st_size
        # A browser's conditional reload must get the new collection even when
        # the completed hash row and second-resolution source validator remain.
        preview = client.get(
            route.path,
            {"preview": "1"},
            HTTP_HOST=route.netloc,
            HTTP_IF_NONE_MATCH=response.get("ETag", '"old-source"'),
            HTTP_IF_MODIFIED_SINCE=response["Last-Modified"],
        )
        assert preview.status_code == 200
        assert old_source.group(0) not in preview.content
        assert "no-cache" in preview["Cache-Control"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("hash_state", ["missing", "failed", "malformed", "complete", "broken_manifest"])
def test_repeat_replay_reuses_archived_payloads(snapshot, live_server, browser_runtime, hash_state):
    resolve_abxpkg_binary_env(browser_runtime["lib_dir"], deps_from=Path(get_plugins_dir()) / "archivewebpage/config.json")
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.url = "http://localhost:20000/"
    snapshot.permissions = "public"
    snapshot.status = "sealed"
    snapshot.save(update_fields=["url", "permissions", "status"])
    output = snapshot.output_dir / "archivewebpage/archivewebpage.wacz"
    output.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parent / "fixtures/memento/iframetest.wacz", output)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="archivewebpage",
        status="succeeded",
        output_str=output.name,
        output_files={output.name: {"size": output.stat().st_size, "mimetype": "application/wacz"}},
    )
    manifest = output.parent.parent / "hashes/hashes.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps({"files": [{"path": "archivewebpage/archivewebpage.wacz", "hash": hashlib.sha256(output.read_bytes()).hexdigest()}]}),
    )
    if hash_state != "missing":
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="hashes",
            status="failed" if hash_state == "failed" else "succeeded",
            output_str="Hash result",
            output_files={
                "hashes.json": "invalid"
                if hash_state == "malformed"
                else {"size": manifest.stat().st_size, "mimetype": "application/json"},
            },
        )
    if hash_state == "broken_manifest":
        manifest.write_text("{broken JSON")
    elif hash_state == "missing":
        manifest.unlink()
    url = build_snapshot_url(str(snapshot.id), "archivewebpage/archivewebpage.wacz") + "?preview=1"
    path = "archivewebpage/archivewebpage.wacz"
    detail_url = build_snapshot_url(str(snapshot.id), "index.html") + f"#{path}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            context = browser.new_context()
            ranges = []
            context.on(
                "request",
                lambda request: ranges.append(request.url) if ".wacz" in request.url and request.headers.get("range") else None,
            )
            page = context.new_page()
            for attempt in range(2):
                ranges.clear()
                if attempt:
                    page.reload(wait_until="load")
                else:
                    page.goto(url, wait_until="load")
                page.wait_for_function("window.archiveboxReplayReady && !window.archiveboxReplayError")
                replay = next(frame for frame in page.frames if "/replay/w/" in frame.url)
                assert "Outside iframe" in replay.locator("body").inner_text()
                # Valid ZIP metadata versions the replay even when the optional
                # hashes result is absent, failed, or malformed.
                if attempt:
                    assert not ranges, f"Repeat replay fetched WACZ bytes again: {ranges}"
                else:
                    assert ranges, "An uncached replay must load real archived response bytes"
                    # This complete archive fits within one bounded range read;
                    # dependent iframe resources should reuse those same bytes.
                    assert len(ranges) == 1, ranges

            # Shared hashes select the generated viewer's deployment URL, but
            # keep the output selection itself stable across releases.
            page.goto(detail_url, wait_until="load")
            page.frame_locator("#main-frame").locator("#replay-root").wait_for()
            viewer = next(frame for frame in page.frames if ".wacz?" in frame.url and "preview=1" in frame.url)
            viewer.wait_for_function("window.archiveboxReplayReady && !window.archiveboxReplayError")
            replay = next(frame for frame in page.frames if "/replay/w/" in frame.url)
            assert "Outside iframe" in replay.locator("body").inner_text()
            revision = parse_qs(urlsplit(viewer.url).query)["_abx_rev"]
            assert revision[0].endswith(f"-{get_static_cache_key()}")
            link = page.locator('.thumb-card[data-plugin-name="archivewebpage"] a[target="preview"]').first
            assert parse_qs(urlsplit(link.get_attribute("href")).query)["_abx_rev"] == revision
            link.click()
            assert page.evaluate("location.hash") == f"#{path}"
        finally:
            browser.close()
