"""Real browser polling against Django under slow and disconnected transport."""

import re
import time
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db(transaction=True)
def test_empty_snapshot_preserves_progress_details_preference(snapshot, live_server, browser_runtime, tmp_path):
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.status = "queued"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["status", "permissions"])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page()
        page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}")
        monitor = page.locator("#progress-monitor")
        toggle = page.locator("#progress-collapse")
        expect(page.get_by_role("heading", name="Queued for archiving")).to_be_visible()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(monitor).not_to_have_class(re.compile(r"\bcollapsed\b"))
        expect(page.locator("#idle-message")).not_to_be_visible()
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        page.reload()
        expect(toggle).to_have_attribute("aria-expanded", "false")
        assert "collapsed" in (monitor.get_attribute("class") or "").split()
        with page.expect_response(
            lambda response: urlsplit(response.url).path == "/progress.json" and "tree=0" in response.url,
        ) as summary_info:
            pass
        assert summary_info.value.status == 200
        assert "active_crawls" not in summary_info.value.json()
        page.screenshot(path=str(tmp_path / "queued-collapsed.png"))
        with page.expect_response(
            lambda response: urlsplit(response.url).path == "/progress.json" and "tree=0" not in response.url,
        ) as details_info:
            toggle.click()
        assert details_info.value.status == 200
        assert "active_crawls" in details_info.value.json()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        assert "collapsed" not in (monitor.get_attribute("class") or "").split()
        expect(page.locator("#idle-message")).not_to_be_visible()
        expect(monitor.locator(f'.snapshot-item[data-snapshot-id="{snapshot.pk}"]')).to_be_visible()
        page.screenshot(path=str(tmp_path / "queued-expanded.png"))
        browser.close()


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
            # Live progress must bypass Chromium's shared HTTP-cache entry lock,
            # even before the server's private/no-store response arrives.
            assert response.request.header_value("cache-control") == "no-cache"
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("collapsed", [False, True])
@pytest.mark.parametrize("with_output", [False, True])
def test_empty_snapshot_loads_finished_results_from_scoped_poll(snapshot, live_server, browser_runtime, tmp_path, collapsed, with_output):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connections
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine
    from archivebox.tests.test_snapshot_output_stacks import save_output

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.status = "queued"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["status", "permissions"])

    def finish_capture(other=False):
        try:
            if other:
                Snapshot.objects.create(url="https://example.org/other", crawl=snapshot.crawl, status="sealed", permissions="public")
            else:
                if with_output:
                    save_output(snapshot, "singlefile", "singlefile.html")
                snapshot.status = "sealed"
                snapshot.title = "Finished capture from live poll"
                snapshot.save(update_fields=["status", "title"])
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as writer, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page()
        navigations = []
        page.on(
            "request",
            lambda request: (
                navigations.append(request.url) if request.is_navigation_request() and request.frame == page.main_frame else None
            ),
        )
        page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}")
        expect(page.get_by_role("heading", name="Queued for archiving")).to_be_visible()
        if collapsed:
            page.locator("#progress-collapse").click()
        initial_navigations = len(navigations)
        # A different completed snapshot must not refresh this still-queued page.
        writer.submit(finish_capture, True).result()
        with page.expect_response(lambda response: urlsplit(response.url).path == "/progress.json"):
            pass
        expect(page.get_by_role("heading", name="Queued for archiving")).to_be_visible()
        assert len(navigations) == initial_navigations

        writer.submit(finish_capture).result()
        expect(page).to_have_title("Finished capture from live poll")
        if with_output:
            expect(page.locator("#snapshot-empty-state")).to_have_count(0)
            page.get_by_role("button", name=re.compile("^HTML, 1 outputs")).click()
            expect(page.locator('.stack-tray .thumb-card[data-plugin-name="singlefile"]')).to_be_visible()
            expect(page.frame_locator("#main-frame").get_by_role("heading", name="ArchiveBox consolelog preview fixture")).to_be_visible()
        else:
            expect(page.get_by_role("heading", name="No archive outputs yet")).to_be_visible()
            expect(page.locator("#main-frame")).to_have_count(0)
        expect(page.locator("#progress-monitor")).to_have_count(0)
        # A terminal empty capture must not reload repeatedly.
        page.wait_for_timeout(2200)
        assert len(navigations) == initial_navigations + 1
        page.screenshot(path=str(tmp_path / f"finished-{with_output}-{collapsed}.png"))
        browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("open_files", [False, True])
def test_sealing_snapshot_preserves_open_output_or_files(snapshot, live_server, browser_runtime, open_files):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connections
    from archivebox.machine.models import Machine
    from archivebox.tests.test_snapshot_output_stacks import save_output

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.status = "started"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["status", "permissions"])
    if not open_files:
        save_output(snapshot, "singlefile", "singlefile.html")

    def seal():
        try:
            snapshot.status = "sealed"
            snapshot.save(update_fields=["status"])
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as writer, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        page = browser.new_page()
        navigations = []
        page.on(
            "request",
            lambda request: (
                navigations.append(request.url) if request.is_navigation_request() and request.frame == page.main_frame else None
            ),
        )
        page.goto(f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}")
        if open_files:
            page.get_by_role("button", name=re.compile("^Other files,")).click()
        expect(page.locator("#main-frame")).to_be_visible()
        frame_source = page.locator("#main-frame").get_attribute("src")
        initial_navigations = len(navigations)
        writer.submit(seal).result()
        # Allow two normal polling ticks; neither open view may be replaced.
        page.wait_for_timeout(2200)
        assert len(navigations) == initial_navigations
        assert page.locator("#main-frame").get_attribute("src") == frame_source
        browser.close()
