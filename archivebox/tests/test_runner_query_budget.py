"""Scheduler polling uses bounded queue reads and scalar schedule metadata."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

pytestmark = pytest.mark.django_db(transaction=True)


def test_idle_runner_checks_each_empty_queue_once():
    from archivebox.workers.runner import run_pending_crawls

    with CaptureQueriesContext(connection) as queries:
        assert run_pending_crawls(daemon=False) == 0

    for table in ("core_snapshot", "crawls_crawl"):
        due_reads = [query["sql"] for query in queries if f'FROM "{table}"' in query["sql"] and f'"{table}"."retry_at" <=' in query["sql"]]
        assert len(due_reads) == 1, due_reads


def test_schedule_last_run_reads_timestamp_without_crawl_intake():
    from archivebox.crawls.models import Crawl, CrawlSchedule

    created_at = timezone.now() - timedelta(days=1)
    intake = "https://example.com/scheduled\n" * 40000
    template = Crawl.objects.create(urls=intake, created_at=created_at, status=Crawl.StatusChoices.SEALED, retry_at=None)
    schedule = CrawlSchedule.objects.create(template=template, schedule="0 0 * * *")
    previous_run = Crawl.objects.create(
        urls=intake,
        schedule=schedule,
        created_at=created_at + timedelta(hours=1),
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
    )
    with CaptureQueriesContext(connection) as queries:
        assert schedule.last_run_at == previous_run.created_at
    assert len(queries) == 1, queries.captured_queries
    sql = queries[0]["sql"]
    projection = sql.split(" FROM ", 1)[0]
    assert '"created_at"' in projection
    assert '"urls"' not in projection, sql
    assert '"config"' not in projection, sql
    assert Crawl.objects.get(pk=previous_run.pk).urls == intake


def test_idle_queue_check_does_not_hide_new_scoped_snapshot_work():
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.workers.runner import run_pending_crawls
    from archivebox.workers.models import RETRY_AT_MAX

    crawl = Crawl.objects.create(urls="https://example.com/paused", status=Crawl.StatusChoices.PAUSED, retry_at=None)
    snapshot = Snapshot.objects.create(
        crawl=crawl,
        url="https://example.com/paused",
        status=Snapshot.StatusChoices.QUEUED,
        retry_at=timezone.now() + timedelta(hours=1),
    )
    assert run_pending_crawls(daemon=False, crawl_id=str(crawl.pk)) == 0
    snapshot.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.QUEUED

    # Cancellation/pause reconciliation can become due after an idle pass.
    # The next pass must re-read the DB even when its parent has no due lease.
    Snapshot.objects.filter(pk=snapshot.pk).update(retry_at=timezone.now())
    assert run_pending_crawls(daemon=False, crawl_id=str(crawl.pk)) == 0
    snapshot.refresh_from_db()
    assert snapshot.status == Snapshot.StatusChoices.PAUSED
    assert snapshot.retry_at == RETRY_AT_MAX


def test_schedule_poll_reuses_latest_run_timestamp_for_one_pass():
    from django.db.models import OuterRef, Subquery
    from archivebox.crawls.models import Crawl, CrawlSchedule

    now = timezone.now()
    template = Crawl.objects.create(urls="https://www.sqlite.org/", status="sealed", retry_at=None, created_at=now - timedelta(days=2))
    schedule = CrawlSchedule.objects.create(template=template, schedule="daily")
    previous = Crawl.objects.create(
        urls=template.urls,
        schedule=schedule,
        status="sealed",
        retry_at=None,
        created_at=now - timedelta(hours=1),
    )
    latest = Crawl.objects.filter(schedule_id=OuterRef("pk")).order_by("-created_at").values("created_at")[:1]
    with CaptureQueriesContext(connection) as queries:
        sampled = CrawlSchedule.objects.select_related("template").annotate(_last_run_created_at=Subquery(latest)).get(pk=schedule.pk)
        assert sampled.last_run_at == previous.created_at
        assert not sampled.is_due(now)
    assert len(queries) == 1, queries.captured_queries
    # Reusing this object after its own dispatch must see the new durable run.
    dispatched = sampled.enqueue(queued_at=now)
    assert sampled.last_run_at == dispatched.created_at
    # Ordinary reads and the next poll always see work created elsewhere too.
    later = Crawl.objects.create(urls=template.urls, schedule=schedule, created_at=now + timedelta(minutes=1))
    assert schedule.last_run_at == later.created_at
    assert CrawlSchedule.objects.annotate(_last_run_created_at=Subquery(latest)).get(pk=schedule.pk).last_run_at == later.created_at
