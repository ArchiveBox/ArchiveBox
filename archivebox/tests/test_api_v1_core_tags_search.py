import pytest
from django.contrib.auth import get_user_model
from django.db import connection, models
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.core.models import Snapshot, SnapshotTag, Tag
from archivebox.tests.conftest import ADMIN_TEST_HOST


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(params=[False, True])
def tag_membership_schema(request):
    if not request.param or connection.vendor != "sqlite":
        yield
        return
    original = SnapshotTag._meta.get_field("tag")
    legacy = models.CharField(max_length=32, db_column="tag_id", db_index=True)
    legacy.set_attributes_from_name("tag")
    with connection.schema_editor() as editor:
        editor.alter_field(SnapshotTag, original, legacy, strict=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(core_snapshot_tags)")
            assert next(row[2] for row in cursor.fetchall() if row[1] == "tag_id") == "varchar(32)"
        yield
    finally:
        with connection.schema_editor() as editor:
            editor.alter_field(SnapshotTag, legacy, original, strict=True)


@pytest.mark.parametrize("sort", ["snapshots_asc", "snapshots_desc", "name_asc", "name_desc"])
@pytest.mark.parametrize("has_snapshots", ["all", "yes", "no"])
def test_tag_count_sort_uses_membership_index(client, api_token, crawl, sort, has_snapshots, tag_membership_schema):
    tags = [Tag.objects.create(name=f"count-sort-{count}") for count in range(3)]
    snapshots = Snapshot.objects.bulk_create(
        [Snapshot(url=f"https://example.com/tag-sort/{index}", timestamp=str(1900500000 + index), crawl=crawl) for index in range(3)],
    )
    SnapshotTag.objects.bulk_create(
        [SnapshotTag(tag=tag, snapshot=snapshot) for count, tag in enumerate(tags) for snapshot in snapshots[:count]],
    )
    with CaptureQueriesContext(connection) as queries:
        response = client.get(
            "/api/v1/core/tags/search/",
            {"q": "count-sort-", "sort": sort, "has_snapshots": has_snapshots, "api_key": api_token.token},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
    assert response.status_code == 200
    counts = [count for count in range(3) if has_snapshots == "all" or (count > 0) == (has_snapshots == "yes")]
    if sort.endswith("_desc"):
        counts.reverse()
    assert [(card["id"], card["num_snapshots"]) for card in response.json()["tags"]] == [(tags[count].pk, count) for count in counts]
    if connection.vendor == "sqlite":
        membership_queries = [
            query["sql"]
            for query in queries
            if '"core_snapshot_tags"' in query["sql"] and ("COUNT(" in query["sql"] or "EXISTS(" in query["sql"])
        ]
        assert membership_queries
        with connection.cursor() as cursor:
            for query in membership_queries:
                cursor.execute("EXPLAIN QUERY PLAN " + query)
                plan = " ".join(str(row[-1]) for row in cursor.fetchall())
                assert "USING COVERING INDEX core_snapshot_tags_tag_id_" in plan, plan
                assert "count(DISTINCT)" not in plan, plan


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    Tag.objects.create(name="api-basic-tag", created_by=api_admin_user)

    response = client.get("/api/v1/core/tags/search/", {"q": "api-basic"}, **api_headers)

    assert response.status_code == 200, response.content


def test_tag_search_api_returns_card_payload(client, api_token, tagged_data):
    tag, snapshots = tagged_data

    response = client.get(
        "/api/v1/core/tags/search/",
        {"q": "Alpha", "api_key": api_token.token},
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sort"] == "created_desc"
    assert payload["created_by"] == ""
    assert payload["year"] == ""
    assert payload["has_snapshots"] == "all"
    # Snapshot creation also copies the crawl's newer "alpha" tag, which
    # matches this case-insensitive query and sorts ahead of Alpha Research.
    copied_tag = Tag.objects.get(name="alpha")
    assert [card["id"] for card in payload["tags"]] == [copied_tag.id, tag.id]
    assert [card["name"] for card in payload["tags"]] == ["alpha", "Alpha Research"]
    for card in payload["tags"]:
        assert card["num_snapshots"] == 2
        assert card["snapshots"] == []
        assert card["export_jsonl_url"] == f"/api/v1/core/snapshots/export/jsonl?tag={card['id']}"
        assert card["export_urls_url"] == f"/api/v1/core/snapshots/export/txt?tag={card['id']}"
        assert card["filter_url"] == f"/admin/core/snapshot/?tag={card['id']}"
    assert {snap.url for snap in snapshots} == {"https://example.com/one", "https://example.com/two"}


def test_tag_search_api_default_includes_empty_tags_and_counts_linked_snapshots(client, api_token, tagged_data, api_admin_user):
    linked_tag, _snapshots = tagged_data
    empty_tag = Tag.objects.create(name="Empty Tag", created_by=api_admin_user)

    response = client.get(
        "/api/v1/core/tags/search/",
        {"api_key": api_token.token},
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    payload = response.json()
    cards_by_name = {tag["name"]: tag for tag in payload["tags"]}
    assert payload["has_snapshots"] == "all"
    assert cards_by_name["Alpha Research"]["id"] == linked_tag.id
    assert cards_by_name["Alpha Research"]["num_snapshots"] == 2
    assert cards_by_name["Empty Tag"]["id"] == empty_tag.id
    assert cards_by_name["Empty Tag"]["num_snapshots"] == 0


def test_tag_search_api_respects_sort_and_filters(client, api_token, admin_user, crawl, tagged_data):
    from datetime import datetime

    other_user = get_user_model().objects.create_user(
        username="tagother",
        email="tagother@test.com",
        password="unused",
    )
    tag_with_snapshots = tagged_data[0]
    empty_tag = Tag.objects.create(name="Zulu Empty", created_by=other_user)
    alpha_tag = Tag.objects.create(name="Alpha Empty", created_by=other_user)
    Snapshot.objects.create(
        url="https://example.com/three",
        title="Example Three",
        crawl=crawl,
    ).tags.add(alpha_tag)

    Tag.objects.filter(pk=empty_tag.pk).update(created_at=timezone.make_aware(datetime(2024, 1, 1, 12, 0, 0)))
    Tag.objects.filter(pk=alpha_tag.pk).update(created_at=timezone.make_aware(datetime(2025, 1, 1, 12, 0, 0)))
    Tag.objects.filter(pk=tag_with_snapshots.pk).update(created_at=timezone.make_aware(datetime(2026, 1, 1, 12, 0, 0)))

    response = client.get(
        "/api/v1/core/tags/search/",
        {
            "sort": "name_desc",
            "created_by": str(other_user.pk),
            "year": "2024",
            "has_snapshots": "no",
            "api_key": api_token.token,
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sort"] == "name_desc"
    assert payload["created_by"] == str(other_user.pk)
    assert payload["year"] == "2024"
    assert payload["has_snapshots"] == "no"
    assert [tag["name"] for tag in payload["tags"]] == ["Zulu Empty"]
