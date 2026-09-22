import pytest

from archivebox.core.models import Tag
from archivebox.tests.conftest import ADMIN_TEST_HOST, api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    tag = Tag.objects.create(name="api-basic-tag", created_by=api_admin_user)

    response = api_client_request(
        client,
        "post",
        f"/api/v1/core/tag/{tag.id}/rename",
        payload={"name": "api-basic-renamed"},
        headers=api_headers,
    )

    assert response.status_code == 200, response.content


def test_tag_rename_api_updates_name(client, api_token, tagged_data):
    tag, _ = tagged_data

    response = api_client_request(
        client,
        "post",
        f"/api/v1/core/tag/{tag.id}/rename?api_key={api_token.token}",
        payload={"name": "Alpha Archive"},
        headers={"HTTP_HOST": ADMIN_TEST_HOST},
    )

    assert response.status_code == 200

    tag.refresh_from_db()
    assert tag.name == "Alpha Archive"
