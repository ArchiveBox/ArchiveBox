import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Tag


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    tags = [Tag.objects.create(name=f"api-basic-tag-{i}", created_by=api_admin_user) for i in range(5)]

    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/v1/core/tags", **api_headers)

    assert response.status_code == 200, response.content
    items = {item["id"]: item for item in response.json()["items"]}
    for tag in tags:
        assert items[tag.id]["created_by_id"] == str(api_admin_user.pk)
        assert items[tag.id]["created_by_username"] == api_admin_user.username
    # Tag ownership is already joined into the queryset; serialization must not
    # fetch the same user again for each card.
    owner_queries = [query["sql"] for query in queries if 'FROM "auth_user"' in query["sql"]]
    assert len(owner_queries) <= 1, owner_queries
