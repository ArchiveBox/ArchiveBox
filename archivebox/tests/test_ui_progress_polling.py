"""Real browser polling against Django under slow and disconnected transport."""

import time
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.django_db(transaction=True)
def test_progress_poll_serializes_slow_requests_and_recovers_after_disconnect(admin_user, snapshot, live_server, browser_runtime):
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.status = "queued"
    snapshot.save(update_fields=["status"])
    origin = f"http://admin.archivebox.localhost:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{origin}/admin/login/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.wait_for_url(f"{origin}/admin/")
        # Leave the first monitor before measuring the new document's requests.
        page.goto("about:blank")
        pending = set()
        overlaps = []
        started = {}
        durations = []

        def requested(request):
            if urlsplit(request.url).path == "/progress.json":
                if pending:
                    overlaps.append(len(pending))
                pending.add(request)
                started[request] = time.monotonic()

        def finished(request):
            if request in pending:
                durations.append(time.monotonic() - started.pop(request))
                pending.remove(request)

        page.on("request", requested)
        page.on("requestfinished", finished)
        page.on("requestfailed", finished)
        cdp = context.new_cdp_session(page)
        # Delay actual HTTP transport beyond the one-second poll interval;
        # Django still handles every request and supplies unmodified responses.
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 2200, "downloadThroughput": -1, "uploadThroughput": -1})
        page.goto(f"{origin}/admin/core/snapshot/", wait_until="domcontentloaded")
        for _ in range(2):
            with page.expect_response(lambda response: urlsplit(response.url).path == "/progress.json") as response_info:
                pass
            response = response_info.value
            assert response.status == 200
            assert response.json()["snapshots_queued"] >= 1
            response.finished()
        assert durations and min(durations) > 1, durations
        assert not overlaps, f"Started new progress requests while {overlaps} requests were pending"

        cdp.send("Network.emulateNetworkConditions", {"offline": True, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
        page.locator("#metric-web").filter(has_text="Web unavailable").wait_for()
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 0, "downloadThroughput": -1, "uploadThroughput": -1})
        with page.expect_response(lambda response: urlsplit(response.url).path == "/progress.json") as recovered_info:
            pass
        recovered = recovered_info.value
        assert recovered.status == 200
        assert recovered.json()["snapshots_queued"] >= 1
        page.locator("#metric-web").filter(has_text="Web unavailable").wait_for(state="hidden")
        assert "HTTP 200" in (page.locator("#metric-web").get_attribute("title") or "")
        assert not overlaps
        browser.close()
