import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_snapshot_page_does_not_count_all_matches(admin_client, admin_user, settings):
    settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 10})
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    folder = Folder.objects.create(name="News", rules={"field": "title", "lookup": "icontains", "value": "news"})
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(url=f"https://news.ycombinator.com/item?id={i}", timestamp=str(1900000000 + i), title="news", crawl=crawl)
            for i in range(25)
        ],
    )
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/core/snapshot/", {"folder": folder.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert len(response.context["cl"].result_list) == 10
    assert not any("COUNT(" in query["sql"].upper() and "core_snapshot" in query["sql"] for query in queries)
    assert b"Select all matching snapshots" in response.content
    for page, expected in [(2, 10), (3, 5)]:
        response = admin_client.get("/admin/core/snapshot/", {"folder": folder.pk, "p": page}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert len(response.context["cl"].result_list) == expected
    assert response.context["cl"].display_result_count == len(snapshots)


@pytest.mark.django_db(transaction=True)
def test_display_count_refresh_is_bounded_and_debounced(admin_user):
    from threading import enumerate as threads
    from archivebox.progressmonitor.collection import snapshot_list_count

    folder = Folder.objects.create(name="Count refresh")
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    Snapshot.objects.bulk_create(
        [
            Snapshot(url=f"https://news.ycombinator.com/item?id={i}", timestamp=str(1900100000 + i), crawl=crawl, folder=folder)
            for i in range(1001)
        ],
        batch_size=100,
    )
    queryset = Snapshot.objects.filter(folder=folder)
    with CaptureQueriesContext(connection) as queries:
        assert snapshot_list_count(queryset) is None
    assert len(queries) == 0
    for thread in threads():
        if thread.name == "snapshot-list-count":
            thread.join(timeout=10)
            assert not thread.is_alive()
    summary = snapshot_list_count(queryset)
    assert summary["count"] == 1001
    Snapshot.objects.filter(pk=queryset.first().pk).update(folder=None)
    assert snapshot_list_count(queryset) == summary
    assert queryset.count() == 1000


def test_ordered_page_probe_preserves_sparse_filters_and_order(admin_user):
    from archivebox.misc.paginators import snapshot_page

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    folder = Folder.objects.create(name="Sparse")
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://news.ycombinator.com/item?id={i}",
                timestamp=str(1900200000 + i),
                crawl=crawl,
                title="match" if i % 29 == 0 else "exclude",
                folder=folder,
            )
            for i in range(400)
        ],
        batch_size=100,
    )
    base = Snapshot.objects.order_by("-created_at", "-pk")
    query = base.filter(title="match", folder=folder)
    expected = list(query)
    first = snapshot_page(query, base_queryset=base, start=0, size=10)
    second = snapshot_page(query, base_queryset=base, start=10, size=10)
    assert first + second == expected
