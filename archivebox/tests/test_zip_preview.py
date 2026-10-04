"""ZIP outputs use the generic static-file explorer and bounded range reads."""

import zipfile
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db(transaction=True)
def test_zip64_browser_seeks_saved_output_from_any_plugin(snapshot, live_server):
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    output = snapshot.output_dir / "staticfile" / "nested" / "contents.zip"
    output.parent.mkdir(parents=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("folder/readme.txt", "Seekable ZIP64 preview content")
        archive.writestr("folder/page.html", '<script>document.title="unsafe"</script>')
        archive.writestr("../unsafe.txt", "never listed")
        for i in range(65536):
            archive.writestr(f"bulk/{i}.txt", "ZIP64 entry")
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=[f"--host-resolver-rules=MAP {host} 127.0.0.1"])
        page = browser.new_page()
        reads = []
        page.on(
            "response",
            lambda response: (
                reads.append((response.status, response.request.headers.get("range"), response.headers.get("content-length")))
                if response.request.headers.get("range")
                else None
            ),
        )
        page.goto(f"http://{host}:{port}/staticfile/nested/?files=1")
        page.get_by_role("link", name="contents.zip", exact=False).click()
        expect(page.locator("#entries")).to_contain_text("folder")
        expect(page.locator("#entries")).not_to_contain_text("unsafe.txt")
        page.get_by_role("button", name="folder", exact=False).click()
        page.get_by_role("button", name="readme.txt", exact=False).click()
        expect(page.locator("#content")).to_have_text("Seekable ZIP64 preview content")
        page.get_by_role("button", name="page.html", exact=False).click()
        expect(page.locator("#content pre")).to_contain_text("<script>")
        assert page.title() == "contents.zip"
        assert reads and all(status == 206 and byte_range for status, byte_range, _ in reads)
        assert max(int(length) for _, _, length in reads) <= 256 * 1024
        assert sum(int(length) for _, _, length in reads) < output.stat().st_size
        expect(page.locator("#error")).to_be_empty()
        browser.close()
