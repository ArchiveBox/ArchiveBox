"""Real streamed search refreshes preserve the user's bulk selection."""

from uuid import UUID

import pytest


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("across", [False, True])
def test_search_waves_preserve_selection(archivebox_daemon_server, browser_runtime, across):
    from playwright.sync_api import expect, sync_playwright

    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.tests.test_orm_helpers import use_archivebox_db
    from django.contrib.auth import get_user_model

    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="ripgrep", BASE_URL="http://archivebox.localhost")
    server.wait_for_workers(("worker_uvicorn",))
    with use_archivebox_db(server.data_dir):
        owner = get_user_model().objects.create_superuser(username="selection-admin", password="testpassword")
        crawl = Crawl.objects.create(urls="https://streamselection.example", created_by=owner, status="sealed", retry_at=None)
        for index in range(62):
            late = index >= 60
            snap = Snapshot.objects.create(
                id=UUID(int=index + 1),
                url=f"https://streamselection.example/{index}",
                title=f"Archived file {index}" if late else f"Streamselection {index}",
                crawl=crawl,
                status="sealed",
                retry_at=None,
            )
            if late:
                path = snap.output_dir / "dom" / "late.txt"
                path.parent.mkdir(parents=True)
                with path.open("wb") as stream:
                    # The first file releases the early page. The second leaves
                    # time to make a selection before the final table arrives.
                    stream.seek((6 if index == 60 else 22) << 20)
                    stream.write(b"late-match")

    admin_url = f"http://admin.archivebox.localhost:{server.port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(owner.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.locator('#changelist-search [role="combobox"]').fill("title:Streamselection OR deep:late-match")
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
        sort_requests = []
        page.on("request", lambda request: sort_requests.append(request.url) if "/search-stream/" in request.url else None)
        page.locator("#result_list th.column-title_str .text a").click()
        # These late matches were outside the first page until sorting.
        expect(page.locator("#result_list td.field-title_str .status-fetched").first).to_have_text("Archived file 60")
        assert not sort_requests
        browser.close()
