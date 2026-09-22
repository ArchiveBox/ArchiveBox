import json

import pytest

from archivebox.tests.conftest import api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, api_headers):
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        payload={
            "extension_persona_id": "extension-api-persona-basic",
            "name": "api-persona-basic",
            "settings": {},
            "cookies_txt": "",
            "auth_json": {},
        },
        headers=api_headers,
    )

    assert response.status_code == 200, response.content
    assert response.json()["success"] is True


def test_sync_preserves_color_scheme_and_clears_explicitly_removed_cookies(client, api_headers):
    from archivebox.personas.models import Persona

    payload = {
        "extension_persona_id": "extension-settings-update",
        "name": "extension-settings-update",
        "settings": {"color_scheme": "dark"},
        "cookies_txt": "# Netscape HTTP Cookie File\nexample.com\tFALSE\t/\tTRUE\t0\tsession\ttest-session\n",
        "auth_json": {"cookies": [{"domain": "example.com", "name": "session", "value": "test-session", "path": "/"}]},
    }
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona = Persona.objects.get(pk=response.json()["persona"]["id"])
    assert persona.config["BROWSER_COLOR_SCHEME"] == "dark"
    assert "test-session" in (persona.path / "cookies.txt").read_text()
    assert json.loads((persona.path / "auth.json").read_text()) == payload["auth_json"]
    payload["settings"]["color_scheme"] = "light"
    payload["cookies_txt"] = ""
    payload["auth_json"] = {}
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona.refresh_from_db()
    assert persona.config["BROWSER_COLOR_SCHEME"] == "light"
    assert response.json()["created"] is False
    assert (persona.path / "cookies.txt").read_text() == ""
    assert json.loads((persona.path / "auth.json").read_text()) == {}
    assert response.json()["cookies_file_written"] is True
    assert response.json()["auth_file_written"] is True


def test_sync_omitted_auth_artifacts_preserves_existing_cookies(client, api_headers):
    from archivebox.personas.models import Persona

    payload = {
        "extension_persona_id": "extension-settings-only",
        "name": "extension-settings-only",
        "cookies_txt": "# Netscape HTTP Cookie File\nexample.com\tFALSE\t/\tTRUE\t0\tsession\ttest-session\n",
        "auth_json": {"cookies": [{"domain": "example.com", "name": "session", "value": "test-session", "path": "/"}]},
    }
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona = Persona.objects.get(pk=response.json()["persona"]["id"])
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        payload={"extension_persona_id": payload["extension_persona_id"], "name": payload["name"], "settings": {"language": "en-US"}},
        headers=api_headers,
    )
    assert response.status_code == 200, response.content
    assert (persona.path / "cookies.txt").read_text() == payload["cookies_txt"]
    assert json.loads((persona.path / "auth.json").read_text()) == payload["auth_json"]
    assert response.json()["cookies_file_written"] is False
    assert response.json()["auth_file_written"] is False


def test_sync_rejects_invalid_color_scheme(client, api_headers):
    from archivebox.personas.models import Persona

    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        payload={"extension_persona_id": "invalid-color-scheme", "name": "invalid-color-scheme", "settings": {"color_scheme": "purple"}},
        headers=api_headers,
    )
    assert response.status_code == 422, response.content
    assert not Persona.objects.filter(name="invalid-color-scheme").exists()


def test_sync_explicit_default_color_scheme_resets_override(client, api_headers):
    from archivebox.personas.models import Persona

    payload = {"extension_persona_id": "color-reset", "name": "color-reset", "settings": {"color_scheme": "dark"}}
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona = Persona.objects.get(pk=response.json()["persona"]["id"])
    payload["settings"] = {}
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona.refresh_from_db()
    assert persona.config["BROWSER_COLOR_SCHEME"] == "dark"
    payload["settings"] = {"color_scheme": ""}
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona.refresh_from_db()
    assert persona.config["BROWSER_COLOR_SCHEME"] == ""
