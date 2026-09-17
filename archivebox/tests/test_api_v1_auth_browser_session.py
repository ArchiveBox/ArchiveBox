from datetime import timedelta
from urllib.parse import urlsplit

import pytest
from django.contrib.sessions.models import Session
from django.utils import timezone

from archivebox.api.models import APIToken
from archivebox.tests.conftest import API_TEST_HOST, api_client_request

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("header", ["HTTP_AUTHORIZATION", "HTTP_X_ARCHIVEBOX_API_KEY"])
def test_browser_session_authenticates_admin_and_expires_with_key(client, api_admin_user, header):
    token = APIToken.objects.create(created_by=api_admin_user, expires=timezone.now() + timedelta(minutes=5))
    response = api_client_request(
        client,
        "post",
        "/api/v1/auth/browser_session",
        payload={},
        headers={
            "HTTP_HOST": API_TEST_HOST,
            header: f"Bearer {token.token}" if header == "HTTP_AUTHORIZATION" else token.token,
        },
    )
    assert response.status_code == 200, response.content
    assert response["Cache-Control"] == "no-store"
    data = response.json()
    session = Session.objects.get(session_key=data["cookie"]["value"])
    assert session.get_decoded()["_auth_user_id"] == str(api_admin_user.pk)
    assert timezone.now() < session.expire_date <= token.expires
    client.cookies.clear()
    client.cookies[data["cookie"]["name"]] = data["cookie"]["value"]
    response = client.get("/admin/", HTTP_HOST=urlsplit(data["admin_url"]).netloc)
    assert response.status_code == 200, response.content
    assert response.wsgi_request.user.pk == api_admin_user.pk


@pytest.mark.parametrize("kind", ["missing", "invalid", "expired", "inactive", "nonadmin", "query"])
def test_browser_session_rejects_invalid_credentials(client, api_admin_user, kind):
    token = APIToken.objects.create(created_by=api_admin_user, expires=timezone.now() + timedelta(minutes=5))
    if kind == "expired":
        token.expires = timezone.now() - timedelta(seconds=1)
        token.save()
    if kind in ("inactive", "nonadmin"):
        setattr(api_admin_user, "is_active" if kind == "inactive" else "is_superuser", False)
        api_admin_user.save()
    headers = {"HTTP_HOST": API_TEST_HOST}
    if kind not in ("missing", "query"):
        headers["HTTP_AUTHORIZATION"] = "Bearer " + ("invalid" if kind == "invalid" else token.token)
    path = "/api/v1/auth/browser_session" + (f"?api_key={token.token}" if kind == "query" else "")
    before = Session.objects.count()
    response = api_client_request(client, "post", path, payload={}, headers=headers)
    assert response.status_code in (401, 403), response.content
    assert Session.objects.count() == before
