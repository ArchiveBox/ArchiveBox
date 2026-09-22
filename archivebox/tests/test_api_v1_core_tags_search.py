import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from archivebox.core.models import Snapshot, Tag
from archivebox.tests.conftest import ADMIN_TEST_HOST


pytestmark = pytest.mark.django_db(transaction=True)


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
    assert payload["tags"][0]["id"] == tag.id
    assert payload["tags"][0]["name"] == "Alpha Research"
    assert payload["tags"][0]["num_snapshots"] == 2
    assert payload["tags"][0]["snapshots"] == []
    assert payload["tags"][0]["export_jsonl_url"].endswith(f"/api/v1/core/tag/{tag.id}/snapshots.jsonl")
    assert payload["tags"][0]["filter_url"].endswith(f"/admin/core/snapshot/?tags__id__exact={tag.id}")
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
