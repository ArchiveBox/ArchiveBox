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
    assert summary["storage"] is None
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
    with CaptureQueriesContext(connection) as queries:
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
                assert payload["snapshots_active"] == 1
                assert payload["active_crawls"][0]["completed_snapshots"] == 23
    assert not any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries)
    assert len(queries) <= 22 * 200
    print(
        "large crawl poll benchmark "
        + json.dumps(
            {
                "requests": 200,
                "queries_per_request": len(queries) / 200,
                "without_metrics": {"wall_median_ms": statistics.median(elapsed[False]), "cpu_mean_ms": statistics.mean(cpu[False])},
                "with_metrics": {"wall_median_ms": statistics.median(elapsed[True]), "cpu_mean_ms": statistics.mean(cpu[True])},
                "added_cpu_percent": 100 * (statistics.mean(cpu[True]) / statistics.mean(cpu[False]) - 1),
                "bytes": len(response.content),
            },
        ),
    )
    assert statistics.mean(cpu[True]) <= 1.10 * statistics.mean(cpu[False])
