"""Exercise the real editor routes, native auth, persisted hooks and previews."""

import json

import pytest
from django.test import Client
from django.conf import settings

pytestmark = pytest.mark.django_db(transaction=True)
HOST = "admin.archivebox.localhost:5797"
BASE = "/admin/webhooks/"


def webhook_input(**overrides):
    return {
        "name": "Editor subscription",
        "ref": "archivebox.core.models.Snapshot",
        "signal": "BEFORE_CAPTURE",
        "enabled": False,
        "folder_id": None,
        "actions": [{"type": "add_tags", "add_tags": "Reviewed"}],
        "stop_processing": False,
        "stop_on_failure": True,
        **overrides,
    }


def post(client, path, value):
    return client.post(BASE + path, data=json.dumps(value), content_type="application/json", HTTP_HOST=HOST)


def test_editor_requires_superuser_and_csrf(admin_user, django_user_model):
    client = Client(enforce_csrf_checks=True)
    assert client.get(BASE, HTTP_HOST=HOST).status_code == 302
    assert client.get(BASE + "data/", HTTP_HOST=HOST).status_code == 302
    assert post(client, "save/", webhook_input()).status_code == 403
    password = "local-webhook-ui-test"
    admin_user.set_password(password)
    admin_user.save()
    login = client.get("/admin/login/", HTTP_HOST=HOST)
    assert login.status_code == 200
    response = client.post(
        "/admin/login/",
        {
            "username": admin_user.username,
            "password": password,
            "next": BASE,
            "csrfmiddlewaretoken": client.cookies[settings.CSRF_COOKIE_NAME].value,
        },
        HTTP_HOST=HOST,
    )
    assert response.status_code == 302
    assert client.get(BASE, HTTP_HOST=HOST).status_code == 200
    assert post(client, "save/", webhook_input()).status_code == 403
    response = client.post(
        BASE + "save/",
        data=json.dumps(webhook_input()),
        content_type="application/json",
        HTTP_HOST=HOST,
        HTTP_X_CSRFTOKEN=client.cookies[settings.CSRF_COOKIE_NAME].value,
    )
    assert response.status_code == 200, response.content
    from archivebox.api.models import OutboundWebhook

    hook = OutboundWebhook.objects.get(pk=response.json()["hook"]["id"])
    assert hook.created_by == admin_user and hook.actions == webhook_input()["actions"]
    ordinary = django_user_model.objects.create_user("webhook-staff", password=password, is_staff=True)
    client.logout()
    client.get("/admin/login/", HTTP_HOST=HOST)
    response = client.post(
        "/admin/login/",
        {
            "username": ordinary.username,
            "password": password,
            "next": BASE,
            "csrfmiddlewaretoken": client.cookies[settings.CSRF_COOKIE_NAME].value,
        },
        HTTP_HOST=HOST,
    )
    assert response.status_code == 302
    for path in (BASE, BASE + "data/"):
        assert client.get(path, HTTP_HOST=HOST).status_code == 403
    response = client.post(
        BASE + "save/",
        data=json.dumps(webhook_input()),
        content_type="application/json",
        HTTP_HOST=HOST,
        HTTP_X_CSRFTOKEN=client.cookies[settings.CSRF_COOKIE_NAME].value,
    )
    assert response.status_code == 403


def test_preview_uses_real_parent_folder_membership_without_running_actions(admin_client, admin_user, tmp_path):
    from archivebox.api.models import OutboundWebhook
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Process

    parent = Folder.objects.create(name="News", created_by=admin_user)
    child = Folder.objects.create(name="Hacker News", parent=parent, created_by=admin_user)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://news.ycombinator.com/", title="Hacker News", crawl=crawl, folder=child)
    marker = tmp_path / "must-not-execute.txt"
    before_folders = list(Folder.objects.values("id", "name", "parent_id", "rules"))
    before_processes, before_hooks = Process.objects.count(), OutboundWebhook.objects.count()
    response = post(
        admin_client,
        "preview/",
        webhook_input(
            signal="FOLDER_ENTERED",
            folder_id=str(parent.pk),
            actions=[
                {"type": "folder", "folder_id": str(parent.pk)},
                {"type": "python", "code": f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')"},
            ],
        ),
    )
    assert response.status_code == 200, response.content
    objects = response.json()["objects"]
    assert [item["id"] for item in objects] == [str(snapshot.pk)]
    assert objects[0]["payload"]["url"] == snapshot.url
    assert objects[0]["payload"]["folder_id"] == str(parent.pk)
    assert objects[0]["payload"]["event"] == "FOLDER_ENTERED"
    assert list(Folder.objects.values("id", "name", "parent_id", "rules")) == before_folders
    assert Process.objects.count() == before_processes and OutboundWebhook.objects.count() == before_hooks
    assert not marker.exists()
    snapshot.refresh_from_db()
    assert snapshot.folder_id == child.pk


def test_editor_preserves_encrypted_legacy_authorization_without_exposing_it(admin_client, admin_user):
    from archivebox.api.models import OutboundWebhook
    from django.db import connection

    token = "Bearer webhook-editor-regression"
    hook = OutboundWebhook.objects.create(
        name="Legacy delivery",
        created_by=admin_user,
        ref="archivebox.core.models.Snapshot",
        signal="UPDATE",
        enabled=False,
        endpoint="https://example.com/events",
        auth_token=token,
    )
    response = admin_client.get(BASE + "data/", HTTP_HOST=HOST)
    item = next(item for item in response.json()["hooks"] if item["id"] == str(hook.pk))
    assert token not in response.content.decode() and item["has_auth_token"]
    assert "auth_token" not in item
    assert item["actions"] == [{"type": "http_request", "method": "POST", "endpoint": hook.endpoint, "headers": {}}]
    assert token not in admin_client.get(BASE, HTTP_HOST=HOST).content.decode()
    payload = webhook_input(id=str(hook.pk), name=hook.name, signal=hook.signal, actions=item["actions"], auth_token="")
    response = post(admin_client, "save/", payload)
    assert response.status_code == 200, response.content
    hook.refresh_from_db()
    assert hook.auth_token == token
    with connection.cursor() as cursor:
        cursor.execute("SELECT auth_token FROM api_outboundwebhook WHERE id = %s", [str(hook.pk)])
        assert token not in cursor.fetchone()[0]
    response = post(admin_client, "save/", {**payload, "clear_auth_token": "false"})
    assert response.status_code == 400, response.content
    hook.refresh_from_db()
    assert hook.auth_token == token
    response = post(admin_client, "save/", {**payload, "clear_auth_token": True})
    assert response.status_code == 200, response.content
    hook.refresh_from_db()
    assert hook.auth_token == ""


def test_editor_catalog_and_openapi_are_generated_from_installed_models(admin_client):
    from archivebox.api.webhook_events import event_catalog
    from archivebox.plugins.discovery import get_plugin_catalog

    response = admin_client.get(BASE + "data/", HTTP_HOST=HOST)
    assert response.status_code == 200
    data = response.json()
    assert data["models"] == event_catalog()
    assert data["plugins"] == sorted(get_plugin_catalog())
    assert all(model["emoji"] and model["events"] for model in data["models"])
    html = admin_client.get(BASE, HTTP_HOST=HOST).content.decode()
    assert "<h1>Webhooks</h1>" in html
    assert 'data-api-url="/api/v1/openapi.json"' in html
    assert "archivebox-webhook-mockup" not in html and "Interactive mockup" not in html
    response = admin_client.get("/api/v1/openapi.json", HTTP_HOST=HOST)
    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"] and schema["paths"]
    assert any("snapshot" in path and "get" in methods for path, methods in schema["paths"].items())


@pytest.mark.parametrize("body", ["{", "[]", "null", '{"actions": "not a list"}', '{"auth_token": {"invalid": "object"}}'])
def test_malformed_editor_input_never_persists(admin_client, body):
    from archivebox.api.models import OutboundWebhook

    before = OutboundWebhook.objects.count()
    for path in ("save/", "preview/"):
        response = admin_client.post(BASE + path, data=body, content_type="application/json", HTTP_HOST=HOST)
        assert response.status_code == 400, response.content
    assert OutboundWebhook.objects.count() == before
