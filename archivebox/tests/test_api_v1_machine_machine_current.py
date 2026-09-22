import pytest


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_headers):
    response = client.get("/api/v1/machine/machine/current", **api_headers)

    assert response.status_code == 200, response.content
