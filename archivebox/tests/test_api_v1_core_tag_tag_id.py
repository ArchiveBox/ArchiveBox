import pytest

from archivebox.core.models import Tag


pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("request_method", ("get", "delete"))
def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers, request_method):
    tag = Tag.objects.create(name="api-basic-tag", created_by=api_admin_user)

    response = getattr(client, request_method)(f"/api/v1/core/tag/{tag.id}", **api_headers)

    assert response.status_code == 200, response.content


def test_tag_card_delete_uses_canonical_route_without_a_saved_tag(client, api_headers):
    from types import SimpleNamespace

    from archivebox.core.tag_util import build_tag_card
    from archivebox.tests.conftest import ADMIN_TEST_HOST

    missing_id = 2147483647
    assert not Tag.objects.filter(pk=missing_id).exists()
    card = build_tag_card(SimpleNamespace(pk=missing_id, name="Example", slug="example", num_snapshots=0))
    headers = {**api_headers, "HTTP_HOST": ADMIN_TEST_HOST}
    response = client.delete(card["delete_url"], **headers)
    assert response.status_code == 404
    assert response.json() == {"detail": "Tag not found"}
    assert not Tag.objects.filter(pk=missing_id).exists()
