import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Folder, Snapshot, SnapshotTag, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("ordering", ["4.-2", "-8.-2", "-5.-2"])
@pytest.mark.parametrize("filtered", [False, True])
def test_admin_sort_pages_hydrate_only_displayed_snapshot_ids(admin_client, admin_user, settings, ordering, filtered):
    settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 10})
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    folder = Folder.objects.create(name="Paged news")
    tags = [Tag.objects.create(name=f"Page tag {index}") for index in range(3)]
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://news.ycombinator.com/item?id={index}",
                timestamp=str(1900400000 + index),
                title=f"News {index % 7}",
                output_size=index % 9,
                crawl=crawl,
                folder=folder if index % 5 else None,
            )
            for index in range(35)
        ],
    )
    SnapshotTag.objects.bulk_create(
        [SnapshotTag(snapshot=snapshot, tag=tag) for index, snapshot in enumerate(snapshots) for tag in tags[: index % 3]],
    )
    params = {"o": ordering, "p": 2}
    if filtered:
        params["folder"] = str(folder.pk)
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/core/snapshot/", params, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    changelist = response.context["cl"]
    expected = list(changelist.queryset.values_list("pk", flat=True)[10:20])
    assert [snapshot.pk for snapshot in changelist.result_list] == expected
    with CaptureQueriesContext(connection) as row_queries:
        for snapshot in changelist.result_list:
            assert snapshot.crawl.created_by.username == admin_user.username
            snapshot_tags = list(snapshot.tags.all())
            if ordering == "-5.-2":
                assert snapshot.tag_count == len(snapshot_tags)
    assert len(row_queries) == 0
    assert changelist.next_page_url
    page_reads = [query["sql"] for query in queries if 'FROM "core_snapshot"' in query["sql"] and "LIMIT 11 OFFSET 10" in query["sql"]]
    assert len(page_reads) == 1
    selected_columns = page_reads[0].split(" FROM ")[0]
    assert '"url"' not in selected_columns, "Sorting and skipping rows must not read their payload columns"
    assert '"crawl_id"' not in selected_columns
    crawl_reads = [query["sql"] for query in queries if 'FROM "crawls_crawl"' in query["sql"] and " IN " in query["sql"]]
    assert len(crawl_reads) == 1


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
def test_display_count_refresh_aggregates_in_database_and_is_debounced(admin_user):
    from threading import enumerate as threads
    from django.db.backends.signals import connection_created
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
    background_queries = []

    def record_query(execute, sql, params, many, context):
        background_queries.append(sql)
        return execute(sql, params, many, context)

    def record_connection(sender, connection, **kwargs):
        connection.execute_wrappers.append(record_query)

    connection_created.connect(record_connection)
    try:
        with CaptureQueriesContext(connection) as queries:
            assert snapshot_list_count(queryset) is None
        for thread in threads():
            if thread.name == "snapshot-list-count":
                thread.join(timeout=10)
                assert not thread.is_alive()
    finally:
        connection_created.disconnect(record_connection)
    assert len(queries) == 0
    snapshot_reads = [sql for sql in background_queries if 'FROM "core_snapshot"' in sql]
    assert len(snapshot_reads) == 1, snapshot_reads
    assert "COUNT(" in snapshot_reads[0].upper(), "Return an aggregate, never hydrate every snapshot UUID to count it"
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
    expected = list(query.all())
    first = snapshot_page(query, base_queryset=base, start=0, size=10)
    second = snapshot_page(query, base_queryset=base, start=10, size=10)
    assert first + second == expected


@pytest.mark.parametrize("sort", ["title", "-title", "-downloaded_at"])
@pytest.mark.parametrize("page", [2, 7])
def test_nullable_smart_folder_sort_uses_bounded_order_index(admin_client, admin_user, settings, sort, page):
    from datetime import timedelta

    from django.utils import timezone
    from archivebox.core.smart_folders import RuleQuery

    settings.CONFIG = settings.CONFIG.model_copy(update={"SNAPSHOTS_PER_PAGE": 10})
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    source = Folder.objects.create(name="Nullable source")
    folder = Folder.objects.create(
        name="Nullable sort",
        rules={"field": "folder", "lookup": "in_folder", "value": str(source.pk), "sort": sort},
    )
    now = timezone.now()
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://news.ycombinator.com/item?id={index}",
                timestamp=str(1900600000 + index),
                title=f"News {index // 4}" if index % 3 else None,
                downloaded_at=now - timedelta(minutes=index // 4) if index % 3 else None,
                crawl=crawl,
                folder=source if index % 5 else None,
            )
            for index in range(80)
        ],
    )
    start = (page - 1) * 10
    expected = list(
        Snapshot.objects.filter(folder=source).order_by(*RuleQuery.ordering(folder)).values_list("pk", flat=True)[start : start + 10],
    )
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/core/snapshot/", {"folder": folder.pk, "p": page}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [snapshot.pk for snapshot in response.context["cl"].result_list] == expected
    probes = [query["sql"] for query in queries if 'FROM "core_snapshot"' in query["sql"] and f"LIMIT {(start + 11) * 8})" in query["sql"]]
    assert len(probes) == 1, "Nullable sort fields must use the same bounded index probe as date ordering"
    assert "IN (SELECT" in probes[0], "Candidate IDs must remain inside SQL instead of being materialized and rebound in Python"
    assert "NULLS LAST" in probes[0]
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + probes[0])
            plan = " ".join(str(row[-1]) for row in cursor.fetchall())
        assert f"USING INDEX core_snapshot_{sort.lstrip('-')}_" in plan, plan


@pytest.mark.django_db(transaction=True)
def test_public_smart_witness_is_rechecked_after_visibility_changes(admin_user):
    from threading import enumerate as threads

    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    smart = Folder.objects.create(name="Older news", rules={"field": "title", "lookup": "exact", "value": "older"})
    older = Snapshot.objects.create(url="https://news.ycombinator.com/older", title="older", crawl=crawl, config={"PERMISSIONS": "public"})
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://news.ycombinator.com/recent/{i}",
                timestamp=str(1900300000 + i),
                crawl=crawl,
                config={"PERMISSIONS": "private"},
            )
            for i in range(150)
        ],
        batch_size=100,
    )
    # The first request starts discovery without scanning every smart query.
    Folder.tree(public=True)
    for thread in threads():
        if thread.name == "snapshot-list-count":
            thread.join(timeout=10)
            assert not thread.is_alive()
    # Another smart folder may have owned the shared refresh gate first.
    from archivebox.progressmonitor.collection import snapshot_list_count
    from archivebox.core.permissions import public_snapshots_queryset

    snapshot_list_count(public_snapshots_queryset(Folder.select_snapshots(Snapshot.objects.all(), smart.pk)), first_match=True)
    for thread in threads():
        if thread.name == "snapshot-list-count":
            thread.join(timeout=10)
            assert not thread.is_alive()
    assert smart.pk in {folder.pk for folder in Folder.tree(public=True)}
    older.config = {"PERMISSIONS": "private"}
    older.save(update_fields=["config"])
    assert smart.pk not in {folder.pk for folder in Folder.tree(public=True)}
    Snapshot.objects.create(url="https://news.ycombinator.com/new-match", title="older", crawl=crawl, config={"PERMISSIONS": "public"})
    assert smart.pk in {folder.pk for folder in Folder.tree(public=True)}


def test_referenced_folder_deletion_preserves_smart_folder_rules():
    source = Folder.objects.create(name="Removed folder")
    smart = Folder.objects.create(name="Reference", rules={"field": "folder", "lookup": "in_folder", "value": str(source.pk)})
    with pytest.raises(ValidationError, match="Update the rules in Reference"):
        source.delete()
    assert Folder.objects.filter(pk=source.pk).exists()
    smart.refresh_from_db()
    assert smart.rules == {"field": "folder", "lookup": "in_folder", "value": str(source.pk)}
    smart.rules = {"field": "title", "lookup": "exact", "value": "Reference"}
    smart.save(update_fields=["rules"])
    source_id = source.pk
    source.delete()
    assert not Folder.objects.filter(pk=source_id).exists()
    assert smart.pk not in {folder.pk for folder in Folder.tree(public=True)}
