import pytest

from archivebox.tests.conftest import API_TEST_HOST, api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_token):
    response = api_client_request(
        client,
        "post",
        "/api/v1/auth/check_api_token",
        payload={"token": api_token.token},
        headers={"HTTP_HOST": API_TEST_HOST},
    )

    assert response.status_code == 200, response.content
    assert response.json()["success"] is True


def test_success_returns_token_owner_identity(client, tmp_path, api_token):
    response = api_client_request(
        client,
        "post",
        "/api/v1/auth/check_api_token",
        payload={"token": api_token.token},
        headers={"HTTP_HOST": API_TEST_HOST},
    )

    assert response.status_code == 200, response.content
    assert response.json()["user_id"] == str(api_token.created_by.pk)
    assert response.json()["username"] == api_token.created_by.username


def test_invalid_token_returns_no_identity(client, tmp_path, api_token):
    response = api_client_request(
        client,
        "post",
        "/api/v1/auth/check_api_token",
        payload={"token": "not-a-real-token"},
        headers={"HTTP_HOST": API_TEST_HOST},
    )

    assert response.status_code == 200, response.content
    assert response.json() == {"success": False, "user_id": None, "username": None}
