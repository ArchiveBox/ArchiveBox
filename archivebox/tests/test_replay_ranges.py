"""Exercise WACZ read-ahead against real ArchiveBox responses and a service worker."""

import hashlib
import os
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from abx_plugins import get_plugins_dir
from playwright.sync_api import sync_playwright

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import build_snapshot_url
from archivebox.machine.models import Machine
from archivebox.tests.conftest import resolve_abxpkg_binary_env


@pytest.mark.django_db(transaction=True)
def test_replay_ranges_share_reads_preserve_bytes_and_recover(snapshot, live_server, browser_runtime):
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
    fixture = Path(__file__).parent / "fixtures/memento/iframetest.wacz"
    # Repackage the real recorded WARC beside stored copies of itself. Extra
    # members leave its replay unchanged while exercising multi-block ZIPs.
    with zipfile.ZipFile(fixture) as source, zipfile.ZipFile(output, "w") as archive:
        warc = next(source.read(entry) for entry in source.infolist() if entry.filename.startswith("archive/"))
        for entry in source.infolist():
            archive.writestr(entry, source.read(entry))
        for number in range(768):
            archive.writestr(f"archive/recording-{number}.warc.gz", warc)
    raw = output.read_bytes()
    assert len(raw) > 5 * 256 * 1024
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="archivewebpage",
        status="succeeded",
        output_str=output.name,
        output_files={output.name: {"size": len(raw), "mimetype": "application/wacz"}},
    )
    url = build_snapshot_url(str(snapshot.id), "archivewebpage/archivewebpage.wacz") + "?preview=1"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            context = browser.new_context()
            requests = []
            context.on(
                "request",
                lambda request: (
                    requests.append(request.headers["range"]) if ".wacz" in request.url and request.headers.get("range") else None
                ),
            )
            page = context.new_page()
            page.goto(url, wait_until="load")
            page.wait_for_function("window.archiveboxReplayReady && !window.archiveboxReplayError")
            replay = next(frame for frame in page.frames if "/replay/w/" in frame.url)
            assert "Outside iframe" in replay.locator("body").inner_text()
            source_url = page.locator("#replay-root").get_attribute("data-source")
            source_url = page.evaluate("source => new URL(source, location.href).href", source_url)
            worker = context.service_workers[0]

            def read_ranges(ranges, abort_first=False):
                return worker.evaluate(
                    """async ({url, ranges, abortFirst}) => {
                        const controller = new AbortController();
                        const reads = ranges.map(async ([start, end], i) => {
                            try {
                                const response = await fetch(url, {headers: {Range: `bytes=${start}-${end}`}, signal: i === 0 ? controller.signal : undefined});
                                const body = await response.arrayBuffer();
                                const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', body)), x => x.toString(16).padStart(2, '0')).join('');
                                return {status: response.status, range: response.headers.get('Content-Range'), hash};
                            } catch (error) { return {error: error.name}; }
                        });
                        if (abortFirst) controller.abort();
                        return Promise.all(reads);
                    }""",
                    {"url": source_url, "ranges": ranges, "abortFirst": abort_first},
                )

            def assert_bytes(result, start, end):
                assert result == {
                    "status": 206,
                    "range": f"bytes {start}-{end}/{len(raw)}",
                    "hash": hashlib.sha256(raw[start : end + 1]).hexdigest(),
                }

            block = 256 * 1024
            requests.clear()
            ranges = [(block + 10, block + 9000), (block + 5000, block + 15000)]
            for result, (start, end) in zip(read_ranges(ranges), ranges):
                assert_bytes(result, start, end)
            assert requests == [f"bytes={block}-{2 * block - 1}"]

            requests.clear()
            start, end = 2 * block - 50, 2 * block + 99
            assert_bytes(read_ranges([(start, end)])[0], start, end)
            assert requests == [f"bytes={2 * block}-{3 * block - 1}"]

            requests.clear()
            start, end = 3 * block + 123, 4 * block + 200
            assert_bytes(read_ranges([(start, end)])[0], start, end)
            assert requests == [f"bytes={start}-{end}"]

            requests.clear()
            ranges = [(4 * block + 10, 4 * block + 100), (4 * block + 50, 4 * block + 150)]
            cancelled, shared = read_ranges(ranges, abort_first=True)
            assert cancelled == {"error": "AbortError"}
            assert_bytes(shared, *ranges[1])
            assert requests == [f"bytes={4 * block}-{5 * block - 1}"]

            # A genuinely missing source must fail, then recover when the same
            # file returns; rejected requests must never remain in the block map.
            moved = output.with_suffix(".unavailable")
            output.rename(moved)
            try:
                failed = read_ranges([(5 * block, 5 * block + 100)])[0]
                assert "error" in failed
            finally:
                moved.rename(output)
            assert_bytes(read_ranges([(5 * block, 5 * block + 100)])[0], 5 * block, 5 * block + 100)

            # An already open viewer cannot combine blocks from two different
            # file versions. New viewer navigations receive a new source URL.
            original_stat = output.stat()
            os.utime(output, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns + 2_000_000_000))
            changed = read_ranges([(6 * block, 6 * block + 100)])[0]
            assert "error" in changed
            assert "error" in read_ranges([(block + 10, block + 100)])[0]
        finally:
            browser.close()
