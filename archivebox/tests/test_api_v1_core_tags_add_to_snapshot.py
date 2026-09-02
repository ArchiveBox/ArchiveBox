import pytest
from django.db import IntegrityError, connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Snapshot, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/tag-add", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/tag-add", crawl=crawl)
    tag = Tag.objects.create(name="api-basic-add-tag", created_by=api_admin_user)

    with CaptureQueriesContext(connection) as queries:
        response = api_client_request(
            client,
            "post",
            "/api/v1/core/tags/add-to-snapshot/",
            payload={"snapshot_id": str(snapshot.id), "tag_id": tag.id},
            headers=api_headers,
        )

    assert response.status_code == 200, response.content
    assert response.json()["success"] is True
    assert snapshot.tags.filter(pk=tag.pk).exists()
    if connection.vendor == "sqlite":
        transaction_queries = [query["sql"] for query in queries if query["sql"].strip().upper() in {"BEGIN", "COMMIT"}]
        assert transaction_queries == []


def test_add_tag_ids_reraises_non_duplicate_integrity_errors(snapshot):
    with pytest.raises(IntegrityError):
        snapshot.add_tag_ids([2**31 - 1])


def test_add_tag_ids_treats_existing_snapshot_tag_as_idempotent(snapshot, admin_user):
    tag = Tag.objects.create(name="already-attached", created_by=admin_user)

    snapshot.add_tag_ids([tag.pk])
    snapshot.add_tag_ids([tag.pk])

    assert snapshot.tags.filter(pk=tag.pk).count() == 1


def test_save_tags_without_creator_uses_tag_model_default(snapshot):
    snapshot.save_tags(["model-default-creator"])

    tag = Tag.objects.get(name="model-default-creator")
    assert tag.created_by_id is not None
