import pytest

from .conftest import (
    api_client_request,
    init_archive,
)

pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_headers):
    init_archive(tmp_path)

    response = api_client_request(
        client,
        "post",
        "/api/v1/cli/add",
        payload={
            "urls": ["https://example.com/api-cli-add-basic"],
            "depth": 0,
            "parser": "url_list",
            "plugins": "__archivebox_test_no_plugins__",
            "start_paused": True,
        },
        headers=api_headers,
    )

    assert response.status_code == 200, response.content
    assert response.json()["success"] is True
