"""Real search stream must remain busy until its delayed table response lands."""

from urllib.parse import urlsplit
import pytest


@pytest.mark.django_db(transaction=True)
def test_search_waits_for_final_table(live_server, admin_user, crawl, browser_runtime):
    from playwright.sync_api import expect, sync_playwright
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}",
    }
    machine.save(update_fields=["config"])
    Snapshot.objects.create(
        url="https://rendercompletion.example/",
        title="Rendercompletion",
        timestamp="1900000000",
        crawl=crawl,
    )
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=browser_runtime["chrome_args"],
        )
        page = browser.new_page()
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.wait_for_load_state("networkidle")
        cdp = page.context.new_cdp_session(page)
        cdp.send(
            "Network.emulateNetworkConditionsByRule",
            {
                "offline": False,
                "matchedNetworkConditions": [
                    {
                        "urlPattern": f"{admin_url}/admin/core/snapshot/?*",
                        "latency": 1500,
                        "downloadThroughput": -1,
                        "uploadThroughput": -1,
                    },
                ],
            },
        )
        page.locator('#changelist-search [role="combobox"]').fill("rendercompletion")
        with page.expect_event(
            "requestfinished",
            predicate=lambda request: "/search-stream/" in request.url,
        ):
            page.locator('#changelist-search [role="combobox"]').press("Enter")
        expect(page.locator("#changelist-search")).to_have_attribute("aria-busy", "true")
        expect(page.locator("#result_list input.action-select")).to_have_count(1)
        expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")
        browser.close()
