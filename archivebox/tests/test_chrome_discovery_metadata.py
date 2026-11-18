"""Native browser keeps discovered Chrome output in its Metadata stack."""

from urllib.parse import urlsplit
import pytest


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("declared", [False, True])
def test_chrome_discovery_metadata(snapshot, live_server, browser_runtime, declared):
    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.status = "sealed"
    snapshot.save(update_fields=["permissions", "status"])
    folder = snapshot.output_dir / "chrome"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "frame_loads.json").write_text('{"frames": []}')
    (snapshot.output_dir / "notes.txt").write_text("Local notes")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="chrome",
        hook_name="on_Snapshot__02_chrome_navigate",
        status="succeeded",
        output_str="chrome/navigation.json" if declared else "",
        output_files={"navigation.json": {"size": 20, "mimetype": "application/json"}} if declared else {},
        output_size=20,
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        with page.expect_response(lambda r: "discover_outputs=1" in r.url) as discovery:
            page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}")
        assert discovery.value.status == 200
        expect(page.locator(".thumb-card[data-discover-files] .discovery-status")).to_have_text("")
        metadata = page.get_by_role("button", name="Metadata, 1 outputs", exact=True)
        expect(metadata).to_be_visible()
        page.get_by_role("button", name="Other files, 1 outputs", exact=True).click()
        expect(page.locator(".stack-tray")).to_be_visible()
        assert page.locator('.stack-tray .thumb-card[data-plugin-name="Chrome"]').count() == 0
        metadata.click()
        cards = page.locator('.stack-tray .thumb-card[data-output-group="metadata"]')
        expect(cards).to_have_count(1)
        assert cards.first.get_attribute("data-plugin-name").lower() == "chrome"

        browser.close()
