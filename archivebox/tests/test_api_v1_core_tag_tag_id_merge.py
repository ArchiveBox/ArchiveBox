import pytest

from archivebox.core.models import Snapshot, Tag
from archivebox.core.tag_util import merge_tags
from archivebox.tests.conftest import api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def _make_snapshots(crawl, count):
    return [Snapshot.objects.create(url=f"https://example.com/merge-{i}", crawl=crawl) for i in range(count)]


def test_basic_success_case_request(client, api_admin_user, api_headers):
    source = Tag.objects.create(name="api-merge-source", created_by=api_admin_user)
    target = Tag.objects.create(name="api-merge-target", created_by=api_admin_user)

    response = api_client_request(
        client,
        "post",
        f"/api/v1/core/tag/{source.id}/merge",
        payload={"target": target.id},
        headers=api_headers,
    )

    assert response.status_code == 200, response.content
    assert response.json()["target_tag_id"] == target.id


def test_merge_moves_snapshots_without_duplicating_links(client, crawl, api_admin_user, api_headers):
    source = Tag.objects.create(name="Dupe Tag", created_by=api_admin_user)
    target = Tag.objects.create(name="canonical", created_by=api_admin_user)
    only_source, both, only_target = _make_snapshots(crawl, 3)
    only_source.tags.add(source)
    both.tags.add(source, target)
    only_target.tags.add(target)

    response = api_client_request(
        client,
        "post",
        f"/api/v1/core/tag/{source.id}/merge",
        payload={"target": "CANONICAL"},
        headers=api_headers,
    )

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["success"] is True
    assert body["source_tag_id"] == source.id
    assert body["target_tag_name"] == "canonical"
    assert body["snapshots_retagged"] == 2
    assert not Tag.objects.filter(pk=source.pk).exists()
    assert set(target.snapshot_set.values_list("pk", flat=True)) == {only_source.pk, both.pk, only_target.pk}
    assert both.tags.filter(name="canonical").count() == 1
    assert not both.tags.filter(name="Dupe Tag").exists()


def test_merge_into_self_is_rejected(client, api_admin_user, api_headers):
    tag = Tag.objects.create(name="api-merge-self", created_by=api_admin_user)

    response = api_client_request(
        client,
        "post",
        f"/api/v1/core/tag/{tag.id}/merge",
        payload={"target": tag.id},
        headers=api_headers,
    )

    assert response.status_code == 400
    assert Tag.objects.filter(pk=tag.pk).exists()


def test_merge_with_unknown_tags_returns_404(client, api_admin_user, api_headers):
    tag = Tag.objects.create(name="api-merge-known", created_by=api_admin_user)

    missing_target = api_client_request(
        client,
        "post",
        f"/api/v1/core/tag/{tag.id}/merge",
        payload={"target": "does-not-exist"},
        headers=api_headers,
    )
    missing_source = api_client_request(
        client,
        "post",
        f"/api/v1/core/tag/{tag.id + 1000}/merge",
        payload={"target": tag.id},
        headers=api_headers,
    )

    assert missing_target.status_code == 404
    assert missing_source.status_code == 404
    assert Tag.objects.filter(pk=tag.pk).exists()


def test_merge_tags_service_merges_several_sources(crawl, api_admin_user):
    first = Tag.objects.create(name="merge-a", created_by=api_admin_user)
    second = Tag.objects.create(name="merge-b", created_by=api_admin_user)
    target = Tag.objects.create(name="merge-target", created_by=api_admin_user)
    one, two = _make_snapshots(crawl, 2)
    one.tags.add(first, second)
    two.tags.add(second)

    assert merge_tags([first, second, target], target) == 2

    assert not Tag.objects.filter(name__in=["merge-a", "merge-b"]).exists()
    assert Tag.objects.filter(pk=target.pk).exists()
    assert set(target.snapshot_set.values_list("pk", flat=True)) == {one.pk, two.pk}
    assert merge_tags([target], target) == 0
