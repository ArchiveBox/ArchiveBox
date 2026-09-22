import pytest

from archivebox.tests.conftest import API_TEST_HOST, api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user):
    response = api_client_request(
        client,
        "post",
        "/api/v1/auth/get_api_token",
        payload={
            "username": api_admin_user.username,
            "password": "testpass123",
        },
        headers={"HTTP_HOST": API_TEST_HOST},
    )

    assert response.status_code == 200, response.content
    assert response.json()["success"] is True
