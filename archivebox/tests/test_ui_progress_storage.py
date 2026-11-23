"""Progress storage labels describe the recorded capture bytes at small sizes."""

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(("size", "label"), [(0, "0 B"), (13303, "13 KB"), (1500000, "1.4 MB")])
def test_progress_storage_uses_capture_size_units(live_server, browser_runtime, admin_user, crawl, size, label):
    from django.core.cache import cache
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Machine

    cache.clear()
    machine = Machine.current()
    port = urlsplit(live_server.url).port
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot = Snapshot.objects.create(url="https://example.com/storage", title="Stored capture", crawl=crawl, status="sealed")
    output = Path(snapshot.output_dir) / "title/title.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"x" * size)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="title",
        hook_name="on_Snapshot__54_title.js",
        status="succeeded",
        output_str="title/title.txt",
        output_size=output.stat().st_size,
        output_files={"title.txt": {"size": size, "mimetype": "text/plain"}},
    )
    snapshot.refresh_from_db()
    assert snapshot.output_size == size

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page.locator("#metric-storage .metric-text")).to_have_text(re.compile(rf"^{re.escape(label)} \("))
            browser.close()
    finally:
        cache.clear()
