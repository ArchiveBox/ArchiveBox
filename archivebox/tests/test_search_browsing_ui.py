"""Real completed Meta search preserves native pagination and ordering."""

from urllib.parse import urlsplit
import pytest


@pytest.mark.django_db(transaction=True)
def test_completed_search_browsing(live_server, admin_user, crawl, browser_runtime):
    from playwright.sync_api import expect, sync_playwright
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(url=f"https://www.amazon.com/item/{i}", title=f"Product {i:03}", timestamp=str(1900000000 + i), crawl=crawl)
            for i in range(65)
        ],
    )
    expected = [str(row.pk) for row in rows]
    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        streams = []
        page.on("request", lambda request: streams.append(request.url) if "/search-stream/" in request.url else None)
        page.goto(f"{origin}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.locator('#changelist-search [role="combobox"]').fill("meta:amazon.com")
        page.locator('#changelist-search [role="combobox"]').press("Enter")
        expect(page.locator("#result_list input.action-select")).to_have_count(50)
        expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")
        page.wait_for_load_state("networkidle")
        assert len(streams) == 1

        # The last streamed row uses the panel's one permission menu template.
        expect(page.locator("template[data-snapshot-permissions-menu]")).to_have_count(1)
        expect(page.locator(".snapshot-permissions-menu")).to_have_count(0)
        row = page.locator("#result_list tbody tr").last
        snapshot_id = row.get_attribute("data-snapshot-id")
        permissions = row.locator(".snapshot-permissions-quick")
        current = permissions.get_attribute("data-current-permissions")
        selected = "private" if current != "private" else "unlisted"
        action_url = permissions.get_attribute("data-permissions-url")
        permissions.locator(".snapshot-permissions-button").click()
        expect(permissions.get_by_role("menuitemradio", name=current.title())).to_have_attribute("aria-checked", "true")
        with page.expect_response(
            lambda response: urlsplit(response.url).path == action_url and response.request.method == "POST",
        ) as saved:
            permissions.get_by_role("menuitemradio", name=selected.title()).click()
        assert saved.value.ok
        expect(permissions).to_have_attribute("data-current-permissions", selected)
        expect(page.locator(".snapshot-permissions-menu")).to_have_count(0)

        def ids():
            return page.locator("#result_list input.action-select").evaluate_all("(els)=>els.map(e=>e.value)")

        initial = ids()
        page.locator(".paginator").get_by_role("link", name="Next", exact=True).click()
        expect(page.locator("#result_list input.action-select")).to_have_count(15)
        page.wait_for_load_state("networkidle")
        second = ids()
        assert set(initial).isdisjoint(second)
        assert set(initial + second) == set(expected)
        assert len(streams) == 1, f"Pagination restarted search: {len(streams)}"
        page.locator("th.column-title_str .text a").click()
        expect(page.locator("#result_list input.action-select")).to_have_count(50)
        page.wait_for_load_state("networkidle")
        ascending = ids()
        assert ascending == expected[:50], ascending
        page.locator("th.column-title_str .text a").click()
        page.wait_for_load_state("networkidle")
        descending = ids()
        assert descending == list(reversed(expected))[:50], descending
        assert len(streams) == 1, f"Sorting restarted search: {len(streams)}"
        page.go_back()
        page.wait_for_load_state("networkidle")
        assert ids() == ascending
        page.go_forward()
        page.wait_for_load_state("networkidle")
        assert ids() == descending
        assert len(streams) == 1, f"History restarted search: {len(streams)}"
        print("Completed search: 65 matches, pages50/15, title asc/desc exact, Back/Forward exact, total streams=1")
        browser.close()
    assert Snapshot.objects.get(pk=snapshot_id).permissions == selected
