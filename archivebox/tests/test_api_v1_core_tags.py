import pytest

from archivebox.core.models import Tag


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    Tag.objects.create(name="api-basic-tag", created_by=api_admin_user)

    response = client.get("/api/v1/core/tags", **api_headers)

    assert response.status_code == 200, response.content
