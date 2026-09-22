import pytest

from archivebox.core.models import Tag


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_token):
    Tag.objects.create(name="api-basic-tag", created_by=api_admin_user)

    response = client.get(
        "/api/v1/core/tags/autocomplete/",
        {"q": "api-basic", "api_key": api_token.token},
        HTTP_HOST="api.archivebox.localhost:5797",
    )

    assert response.status_code == 200, response.content
