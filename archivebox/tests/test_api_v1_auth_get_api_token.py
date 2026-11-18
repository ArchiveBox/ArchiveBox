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


@pytest.mark.parametrize("remaining_seconds", [None, 30 * 86400, 1, -1])
def test_login_key_lifetime_and_existing_keys(client, api_admin_user, remaining_seconds):
    from datetime import datetime, timedelta, timezone as datetime_timezone
    from unittest.mock import patch

    from archivebox.api.models import APIToken

    now = datetime(2026, 11, 18, 12, 0, tzinfo=datetime_timezone.utc)
    existing = None
    before = None
    if remaining_seconds is not None:
        existing = APIToken.objects.create(
            created_by=api_admin_user,
            created_at=now - timedelta(days=30),
            expires=now + timedelta(seconds=remaining_seconds),
        )
        before = APIToken.objects.filter(pk=existing.pk).values().get()

    # Freeze only the clock: authentication, request handling and DB writes are real.
    with patch("django.utils.timezone.now", return_value=now):
        response = api_client_request(
            client,
            "post",
            "/api/v1/auth/get_api_token",
            payload={"username": api_admin_user.username, "password": "testpass123"},
            headers={"HTTP_HOST": API_TEST_HOST},
        )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["success"] is True
    issued = APIToken.objects.get(token=payload["token"])
    if remaining_seconds is not None and remaining_seconds > 0:
        assert existing is not None
        assert issued.pk == existing.pk
        assert issued.expires == now + timedelta(seconds=remaining_seconds)
        assert APIToken.objects.filter(created_by=api_admin_user).count() == 1
    else:
        assert issued.expires == now + timedelta(days=120)
        assert APIToken.objects.filter(created_by=api_admin_user).count() == (2 if existing else 1)
        if existing is not None:
            assert issued.pk != existing.pk
    assert payload["expires"] == issued.expires.isoformat()
    if existing is not None:
        assert APIToken.objects.filter(pk=existing.pk).values().get() == before
