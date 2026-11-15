"""Crawl display totals must aggregate without hydrating capture history."""

from threading import enumerate as threads

import pytest
from django.core.cache import cache
from django.db import connection
from django.db.backends.signals import connection_created
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.progressmonitor.collection import crawl_summary


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("scope", ["crawl", "snapshot", "empty"])
def test_crawl_summary_aggregates_sealed_rows_once(crawl, scope):
    cache.clear()
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(
                crawl=crawl,
                url=f"https://example.com/crawl-summary/{index}",
                timestamp=str(1900500000 + index),
                status="sealed" if index < 201 else "queued",
                output_size=index,
                downloaded_at=timezone.now() if index % 3 else None,
            )
            for index in range(202)
        ],
    )
    snapshot_id = None if scope == "crawl" else snapshots[12 if scope == "snapshot" else -1].pk
    background_queries = []

    def record_query(execute, sql, params, many, context):
        background_queries.append(sql)
        return execute(sql, params, many, context)

    def record_connection(sender, connection, **kwargs):
        connection.execute_wrappers.append(record_query)

    connection_created.connect(record_connection)
    try:
        with CaptureQueriesContext(connection) as request_queries:
            assert crawl_summary(crawl.pk, snapshot_id=snapshot_id) is None
        for thread in threads():
            if thread.name == "crawl-summary":
                thread.join(timeout=10)
                assert not thread.is_alive()
    finally:
        connection_created.disconnect(record_connection)
    assert len(request_queries) == 0
    reads = [sql for sql in background_queries if 'FROM "core_snapshot"' in sql]
    assert len(reads) == 1, reads
    assert "COUNT(" in reads[0].upper() and "SUM(" in reads[0].upper(), reads
    summary = crawl_summary(crawl.pk, snapshot_id=snapshot_id)
    expected = {"crawl": (201, 67, 20100), "snapshot": (1, 1, 12), "empty": (0, 0, 0)}[scope]
    assert tuple(summary[key] for key in ("snapshots", "cancelled", "bytes")) == expected
    assert summary["sampled_at"] > 0
    Snapshot.objects.filter(pk=snapshots[12].pk).update(output_size=99999)
    with CaptureQueriesContext(connection) as cached_queries:
        assert crawl_summary(crawl.pk, snapshot_id=snapshot_id) == summary
    assert len(cached_queries) == 0
    cache.clear()
