import pytest

from archivebox.machine.models import Machine


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_headers):
    Machine.current(refresh=True)

    response = client.get("/api/v1/machine/machines", **api_headers)

    assert response.status_code == 200, response.content
