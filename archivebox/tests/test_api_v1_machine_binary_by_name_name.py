import pytest

from archivebox.machine.models import Machine
from archivebox.tests.conftest import install_real_binary


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_headers):
    machine = Machine.current(refresh=True)
    binary = install_real_binary("python3", machine=machine)

    response = client.get("/api/v1/machine/binary/by-name/python3", **api_headers)

    assert response.status_code == 200, response.content
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(binary.id)
    assert payload[0]["abspath"] == binary.abspath
    assert payload[0]["version"] == binary.version
