"""Discovered saved files remain usable when moving between output stacks."""

import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from archivebox.core.models import ArchiveResult
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_discovered_cards_and_browse_all_files(snapshot, live_server, browser_runtime):
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.save(update_fields=["permissions"])
    fixture = Path(__file__).parent / "fixtures/consolelog_preview.html"
    for plugin in ("title", "git"):
        root = snapshot.output_dir / plugin
        root.mkdir(parents=True)
        shutil.copyfile(fixture, root / "content.html")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="title",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="content.html",
        output_files={"content.html": {"size": fixture.stat().st_size, "mimetype": "text/html"}},
    )
    # Legacy successful results can lack the file map populated by newer hooks.
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="git",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="",
        output_size=fixture.stat().st_size,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=["--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            shell = f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html"
            page.goto(shell, wait_until="domcontentloaded")
            page.locator(".output-stack-other").click()
            discovered = page.locator('#stack-tray .thumb-card[data-plugin-name="git"]')
            expect(discovered).to_be_visible()
            expect(page.locator("#stack-tray .discovery-status")).to_have_text("")
            page.get_by_role("button", name="Collapse stack", exact=True).click()
            expect(discovered).not_to_be_visible()
            page.locator(".output-stack-other").click()
            expect(discovered).to_be_visible()
            files_card = page.locator("#stack-tray [data-other-files]")
            with page.expect_popup() as popup:
                files_card.get_by_role("link", name="📁 Browse all files", exact=True).click()
            files = popup.value
            files.wait_for_load_state("domcontentloaded")
            expect(files.locator(".directory-title")).to_have_text("/")
            files.get_by_role("link", name="git/", exact=True).click()
            expect(files.locator(".directory-title")).to_have_text("git/")
            expect(files.get_by_role("link", name="content.html", exact=True)).to_be_visible()
            assert not errors
        finally:
            browser.close()
