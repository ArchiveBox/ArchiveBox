"""Real streamed search refreshes preserve the user's bulk selection."""

from urllib.parse import urlsplit

import pytest


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("across", [False, True])
def test_search_waves_preserve_selection(live_server, browser_runtime, admin_user, crawl, across):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://streamselection.example/{index}",
                title=f"Streamselection {index}",
                timestamp=str(1900000000 + index),
                crawl=crawl,
            )
            for index in range(60)
        ],
    )
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        # Slow only the real progress stream, so a user can select the first
        # rendered page before later waves arrive. No response is intercepted.
        cdp = page.context.new_cdp_session(page)
        cdp.send(
            "Network.emulateNetworkConditionsByRule",
            {
                "offline": False,
                "matchedNetworkConditions": [
                    {
                        "urlPattern": f"{admin_url}/admin/core/snapshot/search-stream/*",
                        "latency": 0,
                        "downloadThroughput": 3072,
                        "uploadThroughput": -1,
                    },
                ],
            },
        )
        page.locator('#changelist-search [role="combobox"]').fill("meta:streamselection")
        page.locator('#changelist-search [role="combobox"]').press("Enter")
        checkboxes = page.locator("#result_list input.action-select")
        expect(checkboxes).to_have_count(50)
        old_row = page.locator("#result_list tbody tr").first.element_handle()
        selected_id = checkboxes.first.input_value()
        if across:
            page.locator(".action-total-select").click()
            expect(page.locator("input.select-across")).to_have_value("1")
        else:
            checkboxes.first.check()
        page.wait_for_function("row => !row.isConnected", arg=old_row)
        expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")
        page.wait_for_load_state("networkidle")
        expect(page.locator(f'input.action-select[value="{selected_id}"]')).to_be_checked()
        expect(page.locator("input.action-select:checked")).to_have_count(50 if across else 1)
        expect(page.locator("input.select-across")).to_have_value("1" if across else "0")
        expect(page.locator("#result_list tbody tr").first).to_have_attribute("draggable", "true")
        browser.close()
