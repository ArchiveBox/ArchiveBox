import pytest

from archivebox.core.models import Tag


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("request_method", ("get", "delete"))
def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers, request_method):
    tag = Tag.objects.create(name="api-basic-tag", created_by=api_admin_user)

    response = getattr(client, request_method)(f"/api/v1/core/tag/{tag.id}", **api_headers)

    assert response.status_code == 200, response.content
