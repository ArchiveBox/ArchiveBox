import pytest

from archivebox.machine.models import Machine
from archivebox.tests.conftest import install_real_binary


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_headers):
    machine = Machine.current(refresh=True)
    binary = install_real_binary("python3", machine=machine)

    response = client.get(f"/api/v1/machine/binary/{binary.id}", **api_headers)

    assert response.status_code == 200, response.content
    assert response.json()["id"] == str(binary.id)
    assert response.json()["abspath"] == binary.abspath
    assert response.json()["version"] == binary.version
