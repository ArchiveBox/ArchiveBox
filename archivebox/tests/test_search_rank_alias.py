from urllib.parse import urlencode

import pytest
from asgiref.sync import async_to_sync

from archivebox.core.models import Folder, Snapshot
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


def test_rank_alias_revalidates_moved_deleted_ids_and_keeps_original_ranks(admin_client, crawl):
    folder = Folder.objects.create(name="Original rank scope")
    other = Folder.objects.create(name="Moved out of scope")
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://www.amazon.com/{i:03}",
                title=f"Title {59 - i:03}",
                timestamp=str(1900000000 + i),
                crawl=crawl,
                folder=folder,
            )
            for i in range(60)
        ],
    )
    params = {"q": "amazon.com", "search_mode": "meta", "folder": str(folder.pk)}
    path = "/admin/core/snapshot/"
    stream = admin_client.get(path + "search-stream/", {**params, "search_url": path + "?" + urlencode(params)}, HTTP_HOST=ADMIN_TEST_HOST)

    async def consume():
        return b"".join([chunk async for chunk in stream.streaming_content])

    async_to_sync(consume)()
    Snapshot.objects.filter(pk__in=[s.pk for s in snapshots[:10]]).update(folder=other)
    Snapshot.objects.filter(pk__in=[s.pk for s in snapshots[10:15]]).delete()
    page = admin_client.get(path, params, HTTP_HOST=ADMIN_TEST_HOST)
    cl = page.context["cl"]
    assert [row.pk for row in cl.result_list] == [row.pk for row in snapshots[15:]]
    assert [row.search_rank for row in cl.result_list] == list(range(15, 60))
    assert cl.result_count_exact and cl.result_count == 45
    assert cl.queryset.count() == 45
    for index in range(15, 60):
        assert f'class="search-rank-{index}"'.encode() in page.content
    assert b'class="search-rank-0"' not in page.content
    sorted_page = admin_client.get(path, {**params, "o": "4"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert [row.pk for row in sorted_page.context["cl"].result_list] == [row.pk for row in reversed(snapshots[15:])]
    assert [row.search_rank for row in sorted_page.context["cl"].result_list] == list(reversed(range(15, 60)))

    # SQLite real execution above; PostgreSQL compilation only, with no server
    # or network access. Use Django's actual backend compiler, not a fake one.
    from django.db.backends.postgresql.base import DatabaseWrapper

    postgres = DatabaseWrapper({"ENGINE": "django.db.backends.postgresql", "NAME": "compile_only", "OPTIONS": {}}, alias="compile_only")
    ordered_sql, _ = cl.queryset.values_list("pk", flat=True).query.get_compiler(connection=postgres).as_sql()
    assert "CASE" in ordered_sql.split("ORDER BY", 1)[1]
    assert "CASE" not in ordered_sql.split("FROM", 1)[0]
    hydrated = cl.queryset.filter(pk__in=[s.pk for s in snapshots[15:]]).order_by()
    hydration_sql, _ = hydrated.query.get_compiler(connection=postgres).as_sql()
    count_identity_sql, _ = (
        cl.queryset.order_by().prefetch_related(None).select_related(None).query.get_compiler(connection=postgres).as_sql()
    )
    assert "CASE" not in hydration_sql
    assert "CASE" not in count_identity_sql
