import pytest

from archivebox.tests.conftest import api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, api_headers):
    response = api_client_request(
        client,
        "post",
        "/api/v1/core/tags/create/",
        payload={"name": "api-basic-created-tag"},
        headers=api_headers,
    )

    assert response.status_code == 200, response.content
    assert response.json()["success"] is True
