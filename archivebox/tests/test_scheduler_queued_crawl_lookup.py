"""Queued-crawl priority checks must not walk an unrelated running backlog."""

import time
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.base_models.models import get_or_create_system_user_pk
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.services.runner import _higher_priority_crawl_waiting, _next_queued_crawl_snapshot_id


@pytest.mark.django_db
def test_empty_queued_crawl_priority_check_does_not_page_started_backlog():
    now = timezone.now()
    crawl = Crawl.objects.create(
        urls="https://example.com/backlog",
        created_by_id=get_or_create_system_user_pk(),
        status=Crawl.StatusChoices.STARTED,
        retry_at=now + timedelta(minutes=1),
    )
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                crawl=crawl,
                url=f"https://example.com/backlog/{index}",
                timestamp=str(now.timestamp() + index),
                status=Snapshot.StatusChoices.QUEUED,
                retry_at=now - timedelta(hours=1),
            )
            for index in range(10_000)
        ],
        batch_size=1000,
    )
    active_snapshots = Snapshot.objects.filter(
        retry_at__lte=now,
        crawl__status__in=Crawl.RUNNABLE_STATES,
        status__in=Snapshot.RUNNABLE_STATES,
    )
    started = time.perf_counter()
    with CaptureQueriesContext(connection) as queries:
        assert _next_queued_crawl_snapshot_id(active_snapshots) is None
        assert not _higher_priority_crawl_waiting(str(crawl.id), [])
    print(f"queued-crawl negative lookup: {len(queries)} queries, {time.perf_counter() - started:.4f}s")
    # With no queued parents, the answer only needs indexed Crawl reads.
    # Walking the thousands of due Snapshot rows is unnecessary scheduler work.
    assert not any('"core_snapshot"' in query["sql"] for query in queries)

    # A queued parent's future claim does not hide its due child. Only the
    # winning parent's children should be ordered, preserving URL FIFO.
    submitted = Crawl.objects.create(
        urls="https://example.com/new/first\nhttps://example.com/new/second",
        created_by_id=crawl.created_by_id,
        status=Crawl.StatusChoices.QUEUED,
        retry_at=now + timedelta(minutes=1),
    )
    first = Snapshot.objects.create(crawl=submitted, url="https://example.com/new/first", retry_at=now - timedelta(seconds=2))
    second = Snapshot.objects.create(crawl=submitted, url="https://example.com/new/second", retry_at=now - timedelta(seconds=1))
    assert _next_queued_crawl_snapshot_id(active_snapshots) == first.id
    assert _higher_priority_crawl_waiting(str(crawl.id), [])
    assert not _higher_priority_crawl_waiting(str(submitted.id), [])
    assert not _higher_priority_crawl_waiting(str(crawl.id), [str(first.id), str(second.id)])
    for status in (Crawl.StatusChoices.PAUSED, Crawl.StatusChoices.SEALED):
        submitted.status = status
        submitted.save(update_fields=["status"])
        assert _next_queued_crawl_snapshot_id(active_snapshots) is None
        assert not _higher_priority_crawl_waiting(str(crawl.id), [])
