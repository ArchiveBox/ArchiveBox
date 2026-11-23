"""Changing snapshot layout must retain the search just submitted."""

from urllib.parse import parse_qs, urlsplit

import pytest


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("initial_view", ["list", "grid"])
def test_view_toggle_preserves_search_while_response_is_in_flight(live_server, browser_runtime, admin_user, crawl, initial_view):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    for title, url in (("Capture Optimizer", "https://www.sqlite.org/optoverview.html"), ("Capture Python", "https://docs.python.org/")):
        Snapshot.objects.create(url=url, title=title, crawl=crawl, status="sealed", config={"PERMISSIONS": "public"})

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        path = "/admin/core/snapshot/" if initial_view == "list" else "/admin/core/snapshot/grid/"
        page.goto(f"{admin_url}/admin/login/?next={path}")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.goto(f"{admin_url}{path}?q=meta%3ACapture&status__exact=sealed&o=2")
        expect(page.locator("input.action-select")).to_have_count(2)

        # Delay real HTTP responses through Chrome's network stack, keeping the
        # old toolbar visible while the submitted query is still being resolved.
        network = page.context.new_cdp_session(page)
        network.send("Network.enable")
        network.send(
            "Network.emulateNetworkConditions",
            {"offline": False, "latency": 1000, "downloadThroughput": -1, "uploadThroughput": -1},
        )
        query = "meta:Capture ~title:Optimizer"
        editor = page.locator('#changelist-search [role="combobox"]')
        editor.fill(query)
        editor.press("Enter")
        destination = "grid" if initial_view == "list" else "list"
        page.get_by_role("button", name=f"Switch to {destination} view", exact=True).click()
        page.wait_for_url(lambda url: urlsplit(url).path != path)
        parameters = parse_qs(urlsplit(page.url).query)
        assert parameters["q"] == [query]
        assert parameters["status__exact"] == ["sealed"]
        assert parameters["o"] == ["2"]
        expect(page.locator("input.action-select")).to_have_count(1)
        expect(page.locator("#changelist")).to_contain_text("Capture Python")
        expect(page.locator("#changelist")).not_to_contain_text("Capture Optimizer")
        browser.close()
