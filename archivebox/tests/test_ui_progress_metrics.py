"""Real progress polling workload and operational badge integration checks."""

import json
import statistics
import time
from datetime import timedelta

import pytest
from django.db import connection
from django.core.cache import cache
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def await_metrics(user, **scope):
    from archivebox.progressmonitor.metrics import progress_metrics

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        metrics = progress_metrics(user, **scope)
        if metrics is not None:
            return metrics
        time.sleep(0.02)
    pytest.fail("Real progress metrics did not populate within five seconds")


def test_metrics_scope_finished_attempts_and_cached_read_only_access(admin_user, crawl, snapshot):
    from django.contrib.auth import get_user_model
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.progressmonitor.metrics import progress_metrics

    cache.clear()
    now = timezone.now()
    Snapshot.objects.filter(pk=snapshot.pk).update(status=Snapshot.StatusChoices.SEALED, modified_at=now, downloaded_at=now)
    rows = []
    for index, (minutes, status) in enumerate([(40, "sealed"), (80, "sealed"), (10, "started"), (10, "queued"), (10, "sealed")]):
        rows.append(Snapshot.objects.create(crawl=crawl, url=f"https://example.com/metrics-scoped/{index}", status=status))
        Snapshot.objects.filter(pk=rows[-1].pk).update(
            modified_at=now,
            downloaded_at=now - timedelta(minutes=minutes) if index < 2 else None,
        )
    other = get_user_model().objects.create_user(username="other-metrics-owner", is_staff=True)
    other_crawl = Crawl.objects.create(created_by=other, urls="https://example.org/other-metrics")
    other_snapshot = Snapshot.objects.create(crawl=other_crawl, url="https://example.org/other-metrics", status="sealed", downloaded_at=now)
    assert other_snapshot.modified_at >= now

    summary = await_metrics(admin_user)
    assert summary["throughput"] == {"last_hour": 3, "last_30_minutes": 2}
    system = summary["system"]
    assert system["cpu_count"] > 0
    assert len(system["load_avg"]) == 3
    assert 0 <= system["memory_available_bytes"] <= system["memory_total_bytes"]
    assert system["disk_free_bytes"] > 0
    assert "storage" not in summary
    from archivebox.progressmonitor.metrics import system_metrics_path

    assert json.loads(system_metrics_path().read_text()) == system
    assert await_metrics(admin_user, crawl_id=str(crawl.pk))["throughput"] == {"last_hour": 2, "last_30_minutes": 1}
    assert await_metrics(admin_user, snapshot_id=str(snapshot.pk))["throughput"] == {"last_hour": 1, "last_30_minutes": 1}
    assert await_metrics(other)["throughput"] == {"last_hour": 1, "last_30_minutes": 1}
    assert await_metrics(other, crawl_id=str(crawl.pk))["throughput"] == {"last_hour": 0, "last_30_minutes": 0}

    with CaptureQueriesContext(connection) as queries:
        started = time.process_time()
        for _ in range(100):
            assert progress_metrics(admin_user) == summary
        print(f"cached metrics accessor CPU: {(time.process_time() - started) * 10:.3f}ms/call")
    assert len(queries) == 0
    Snapshot.objects.filter(pk=snapshot.pk).update(status="queued", downloaded_at=None)
    assert progress_metrics(admin_user) == summary
    cache.clear()
    assert await_metrics(admin_user)["throughput"] == {"last_hour": 2, "last_30_minutes": 1}


def test_live_system_stats_reads_real_counters_without_database(tmp_path):
    from archivebox.machine.detect import get_live_system_stats

    with CaptureQueriesContext(connection) as queries:
        first = get_live_system_stats(tmp_path)
        # A real file write and OS flush provide work between real counter samples.
        import os

        with (tmp_path / "io-sample").open("wb") as stream:
            stream.write(b"archivebox-progress-metrics" * 4096)
            stream.flush()
            os.fsync(stream.fileno())
        second = get_live_system_stats(tmp_path)
    assert len(queries) == 0
    assert second["sampled_at"] > first["sampled_at"]
    assert second["io"]["operations_per_second"] >= 0
    assert second["io"]["bytes_per_second"] >= 0
    assert second["memory_total_bytes"] > 0


def test_progress_metrics_are_admin_only(client, admin_user, snapshot):
    from archivebox.core.models import Snapshot

    cache.clear()
    Snapshot.objects.filter(pk=snapshot.pk).update(permissions="public", config={"PERMISSIONS": "public"})
    response = client.get("/progress.json", {"snapshot_id": str(snapshot.pk), "metrics": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    assert "metrics" not in response.json()
    client.force_login(admin_user)
    response = client.get("/progress.json", {"snapshot_id": str(snapshot.pk), "metrics": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    assert "metrics" in response.json()
    assert "metrics" not in client.get("/progress.json", HTTP_HOST=ADMIN_TEST_HOST).json()


def test_browser_reuses_telemetry_between_real_samples(admin_user, crawl, live_server, browser_runtime):
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import parse_qs, urlsplit
    from django.db import connections
    from playwright.sync_api import expect, sync_playwright
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    Snapshot.objects.create(crawl=crawl, url="https://example.com/metrics-cadence", status="sealed", downloaded_at=timezone.now())
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    cache.clear()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page()
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.locator('input[type="submit"]').click()
            page.wait_for_url("**/admin/")
            resources = page.locator("#metric-resources .metric-text")
            expect(resources).not_to_have_text("— · RAM —")
            before = resources.text_content()
            page.evaluate("""() => {
                window.telemetryMutations = 0;
                window.telemetryObserver = new MutationObserver(records => window.telemetryMutations += records.length);
                for (const id of ['resources', 'storage']) {
                    window.telemetryObserver.observe(document.querySelector(`#metric-${id} .metric-text`), {childList: true, subtree: true, characterData: true});
                }
            }""")
            with page.expect_response(lambda response: urlsplit(response.url).path == "/progress.json") as poll:
                pass
            response = poll.value
            assert "metrics" not in parse_qs(urlsplit(response.url).query)
            payload = response.json()
            assert "metrics" not in payload and "collection" not in payload
            assert "snapshots_queued" in payload
            page.evaluate("() => new Promise(requestAnimationFrame)")
            assert resources.text_content() == before
            assert page.evaluate("window.telemetryMutations") == 0
            page.locator("#metric-resources").focus()
            assert "seconds ago" in page.locator("#metric-resources").get_attribute("title")
            first_sample = json.loads(page.locator("#metric-resources").get_attribute("data-sample-times"))[0]

            def queue_capture():
                try:
                    return Snapshot.objects.create(
                        crawl_id=crawl.pk,
                        url="https://example.com/queued-during-telemetry-interval",
                        status="queued",
                    ).pk
                finally:
                    connections.close_all()

            # Playwright owns an event loop on this thread. Real collection
            # writes happen on a separate producer connection, as with a crawl.
            with ThreadPoolExecutor(max_workers=1) as producer:
                assert producer.submit(queue_capture).result()
            # Let the real minute-long sample expire. Capture polls must keep
            # flowing without telemetry, then deliver a new OS/throughput sample.
            quiet_polls = 1
            saw_new_queued_capture = False
            deadline = time.monotonic() + 75
            while time.monotonic() < deadline:
                with page.expect_response(lambda response: urlsplit(response.url).path == "/progress.json") as poll:
                    pass
                payload = poll.value.json()
                saw_new_queued_capture |= payload.get("snapshots_queued") == 1
                if "metrics" not in parse_qs(urlsplit(poll.value.url).query):
                    quiet_polls += 1
                    assert "metrics" not in payload
                elif (payload.get("metrics") or {}).get("system", {}).get("sampled_at", 0) > first_sample:
                    assert payload["metrics"]["throughput"]["last_hour"] == 1
                    expect(page.locator("#metric-io .metric-text")).not_to_have_text("I/O —")
                    break
            else:
                pytest.fail("The browser did not receive a fresh real telemetry sample after one minute")
            assert quiet_polls >= 5
            assert saw_new_queued_capture
            assert page.evaluate("window.telemetryMutations") > 0
        finally:
            browser.close()


def test_large_crawl_cached_progress_workload(client, admin_user, crawl):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    cache.clear()
    now = timezone.now()
    Crawl.objects.filter(pk=crawl.pk).update(status=Crawl.StatusChoices.STARTED)
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                crawl=crawl,
                url=f"https://example.com/metrics/{index}",
                timestamp=str(now.timestamp() + index),
                status=Snapshot.StatusChoices.SEALED
                if index < 23
                else Snapshot.StatusChoices.STARTED
                if index == 23
                else Snapshot.StatusChoices.QUEUED,
                downloaded_at=now - timedelta(minutes=index * 2) if index < 23 else None,
                output_size=1024 if index < 23 else 0,
            )
            for index in range(5000)
        ],
    )
    client.force_login(admin_user)
    for _ in range(10):
        response = client.get("/progress.json", {"collection": "1", "metrics": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200, response.content
        time.sleep(0.02)

    await_metrics(admin_user)
    elapsed = {False: [], True: []}
    cpu = {False: [], True: []}
    query_count = 0
    wrote = False

    def count_query(execute, sql, params, many, context):
        nonlocal query_count, wrote
        query_count += 1
        wrote |= sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        return execute(sql, params, many, context)

    # Count SQL without the debug cursor's cumulative formatted query log:
    # retaining thousands of test-only records skews timed cyclic GC.
    with connection.execute_wrapper(count_query):
        for index in range(100):
            # Alternate order each pair to balance CPU scheduling/cache noise.
            for enabled in (True, False) if index % 2 else (False, True):
                params = {"collection": "1", **({"metrics": "1"} if enabled else {})}
                started, cpu_started = time.perf_counter(), time.process_time()
                response = client.get("/progress.json", params, HTTP_HOST=ADMIN_TEST_HOST)
                elapsed[enabled].append((time.perf_counter() - started) * 1000)
                cpu[enabled].append((time.process_time() - cpu_started) * 1000)
                assert response.status_code == 200, response.content
                payload = response.json()
                assert ("metrics" in payload) is enabled
                assert payload["snapshots_queued"] == 4976
                # "Active" counts captures with a live hook process; this
                # STARTED row has none (e.g. interrupted), so it is not active.
                assert payload["snapshots_active"] == 0
                assert payload["active_crawls"][0]["completed_snapshots"] == 23
    assert not wrote
    assert query_count <= 22 * 200
    print(
        "large crawl poll benchmark "
        + json.dumps(
            {
                "requests": 200,
                "queries_per_request": query_count / 200,
                "without_metrics": {"wall_median_ms": statistics.median(elapsed[False]), "cpu_mean_ms": statistics.mean(cpu[False])},
                "with_metrics": {"wall_median_ms": statistics.median(elapsed[True]), "cpu_mean_ms": statistics.mean(cpu[True])},
                "added_cpu_percent": 100 * (statistics.mean(cpu[True]) / statistics.mean(cpu[False]) - 1),
                "bytes": len(response.content),
            },
        ),
    )
    assert statistics.mean(cpu[True]) <= 1.10 * statistics.mean(cpu[False])


@pytest.mark.parametrize(
    ("queued", "completed", "label"),
    [
        (15, 60, "15 queued (~15min)"),
        (870, 60, "870 queued (~14hr 30min)"),
        (1501, 60, "1,501 queued (~1d 1hr 1min)"),
        (15, 56, "15 queued (~17min)"),
        (15, 0, "15 queued"),
        (0, 60, "0 queued"),
    ],
)
def test_queue_eta_from_real_completion_rate(admin_user, crawl, live_server, browser_runtime, queued, completed, label):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import Snapshot
    from archivebox.machine.models import Machine

    now = timezone.now()
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                crawl=crawl,
                url=f"https://archivebox.io/tests/?eta={index}",
                timestamp=str(now.timestamp() + index),
                status="sealed" if index < completed else "queued",
                downloaded_at=now - timedelta(minutes=5) if index < completed else None,
            )
            for index in range(completed + queued)
        ],
    )
    cache.clear()
    assert await_metrics(admin_user)["throughput"]["last_hour"] == completed
    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    origin = f"http://admin.archivebox.localhost:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            page.goto(f"{origin}/admin/login/")
            page.locator("#id_username").fill(admin_user.username)
            page.locator("#id_password").fill("testpassword")
            page.locator('input[type="submit"]').click()
            page.wait_for_url(f"{origin}/admin/")
            expect(page.locator("#orchestrator-text")).to_have_text(f"0 - {label}")
        finally:
            browser.close()


def test_monitor_poll_shares_tree_and_keeps_background_queries_cheap(client, admin_user, crawl, snapshot):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.contrib.auth import get_user_model
    from django.db import connections
    from django.test import Client
    from archivebox.core.models import Snapshot

    cache.clear()
    client.force_login(admin_user)
    with CaptureQueriesContext(connection) as cold:
        heartbeat = client.get("/progress.json", {"poll": 1, "background": 1}, HTTP_HOST=ADMIN_TEST_HOST).json()
    assert heartbeat["is_admin"] and "orchestrator_running" in heartbeat
    assert "active_crawls" not in heartbeat and "snapshots_queued" not in heartbeat
    assert all("core_archiveresult" not in q["sql"] and "COUNT(" not in q["sql"].upper() for q in cold)
    barrier = Barrier(10)

    def poll(_):
        viewer = Client()
        viewer.cookies.update(client.cookies)
        try:
            barrier.wait()
            with CaptureQueriesContext(connection) as queries:
                response = viewer.get("/progress.json", {"poll": 1}, HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == 200
            return response.content, any("core_archiveresult" in q["sql"] for q in queries)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=10) as pool:
        samples = list(pool.map(poll, range(10)))
    assert sum(built for body, built in samples) == 1
    assert len({body for body, built in samples}) == 1
    full = json.loads(samples[0][0])
    assert str(crawl.pk) in {c["id"] for c in full["active_crawls"]}
    with CaptureQueriesContext(connection) as warm:
        compact = client.get("/progress.json", {"tree": 0, "poll": 1}, HTTP_HOST=ADMIN_TEST_HOST).json()
    assert compact["snapshots_queued"] == full["snapshots_queued"]
    assert "active_crawls" not in compact
    assert all("core_archiveresult" not in q["sql"] and "COUNT(" not in q["sql"].upper() for q in warm)
    staff = Client()
    staff.force_login(get_user_model().objects.create_user(username="other-progress-viewer", is_staff=True))
    scoped = staff.get("/progress.json", {"poll": 1}, HTTP_HOST=ADMIN_TEST_HOST).json()
    assert scoped["active_crawls"] == [] and scoped["snapshots_queued"] == 0
    # The same URL must recheck current snapshot permissions even on a cache hit.
    Snapshot.objects.filter(pk=snapshot.pk).update(config={**snapshot.config, "PERMISSIONS": "public"})
    guest = Client()
    params = {"poll": 1, "snapshot_id": str(snapshot.pk)}
    public = guest.get("/progress.json", params, HTTP_HOST=ADMIN_TEST_HOST)
    assert public.status_code == 200 and not public.json()["is_admin"]
    Snapshot.objects.filter(pk=snapshot.pk).update(config={**snapshot.config, "PERMISSIONS": "private"})
    assert guest.get("/progress.json", params, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    cache.clear()
