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


def test_ranked_page_rechecks_prior_batches_without_limiting_action_membership(admin_client, crawl):
    from django.core.cache import cache
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.core.models import SnapshotTag, Tag
    from archivebox.search.views import get_admin_search_cache_key

    original = Folder.objects.create(name="Scoped search")
    moved = Folder.objects.create(name="Outside search")
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://www.amazon.com/product/{i:04}",
                title=f"Group {i // 15:04}",
                timestamp=str(1900000000 + i),
                crawl=crawl,
                folder=original,
                config={"PERMISSIONS": "public"},
            )
            for i in range(624)
        ],
    )
    tag = Tag.objects.create(name="Search scope tag")
    overlapping = Tag.objects.create(name="Overlapping search scope tag")
    SnapshotTag.objects.bulk_create([SnapshotTag(snapshot=s, tag=t) for s in snapshots for t in (tag, overlapping)])
    path = "/admin/core/snapshot/"
    params = {
        "q": "amazon.com",
        "search_mode": "meta",
        "folder": str(original.pk),
        "tag": str(tag.pk),
        # This second, multivalued join matches both tag links of each row.
        "tags__id__in": f"{tag.pk},{overlapping.pk}",
        "permissions": "public",
    }
    stream = admin_client.get(path + "search-stream/", {**params, "search_url": path + "?" + urlencode(params)}, HTTP_HOST=ADMIN_TEST_HOST)

    async def consume():
        return [int(chunk.strip()) async for chunk in stream.streaming_content]

    assert async_to_sync(consume)()[-1] == 624
    cache_key = get_admin_search_cache_key(stream.wsgi_request, path + "?" + urlencode(params))
    state = cache.get(cache_key)
    assert state["done"]
    by_hex = {s.pk.hex: s.pk for s in snapshots}
    ranked = [by_hex[ident] for ident in state["ids"]]
    assert len(ranked) == 624 and set(ranked) == set(by_hex.values())
    original_ranks = {ident: index for index, ident in enumerate(ranked)}
    # Skip a complete cache batch: pagination must count live matches, not
    # offsets in the unvalidated sequence, and rank classes must not be renumbered.
    Snapshot.objects.filter(pk__in=ranked[:512]).update(folder=moved)
    Snapshot.objects.filter(pk__in=ranked[512:518]).delete()
    Snapshot.objects.filter(pk=ranked[519]).update(config={"PERMISSIONS": "private"})
    assert Snapshot.objects.get(pk=ranked[519]).permissions == "private"
    SnapshotTag.objects.filter(snapshot_id=ranked[520], tag=tag).delete()
    expected = [ident for ident in ranked[518:] if ident not in ranked[519:521]]
    for page in (1, 2, 3):
        with CaptureQueriesContext(connection) as queries:
            response = admin_client.get(path, {**params, "p": str(page)}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        cl = response.context["cl"]
        start = (page - 1) * 50
        assert cl.queryset.query.distinct
        assert [row.pk for row in cl.result_list] == expected[start : start + 50]
        assert [row.search_rank for row in cl.result_list] == [original_ranks[ident] for ident in expected[start : start + 50]]
        # Display pagination must not build or execute the catalog-wide rank.
        assert not any("ORDER BY" in q["sql"] and q["sql"].count("WHEN") > 100 for q in queries)
        # This is the full queryset handed to select-across/admin actions.
        assert list(cl.queryset.values_list("pk", flat=True)) == expected
        assert cl.queryset.count() == 104
    sorted_page = admin_client.get(path, {**params, "p": "2", "o": "4"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert sorted_page.status_code == 200
    cl = sorted_page.context["cl"]
    explicitly_sorted = list(cl.queryset.values_list("pk", flat=True))
    assert len(explicitly_sorted) == len(expected) and set(explicitly_sorted) == set(expected)
    assert [row.pk for row in cl.result_list] == explicitly_sorted[50:100]
    assert all(row.search_rank == original_ranks[row.pk] for row in cl.result_list)

    multisort_page = admin_client.get(path, {**params, "p": "3", "o": "-4.5"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert multisort_page.status_code == 200
    cl = multisort_page.context["cl"]
    full = list(cl.queryset.values_list("pk", flat=True))
    assert len(full) == 104 and set(full) == set(expected)
    assert [row.pk for row in cl.result_list] == full[100:]

    action = admin_client.post(
        path + "?" + urlencode(params),
        {"action": "add_tags", "select_across": "1", "_selected_action": [str(pk) for pk in expected[:50]], "index": "0", "tags": "Across"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert action.status_code == 302
    assert set(SnapshotTag.objects.filter(tag__name="Across").values_list("snapshot_id", flat=True)) == set(expected)
