import json

import pytest

from archivebox.tests.conftest import api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_sync_persona_settings_reach_runtime_and_explicit_clearing(client, api_headers):
    from archivebox.config.common import get_config
    from archivebox.personas.models import Persona

    payload = {
        "extension_persona_id": "runtime-settings",
        "name": "runtime-settings",
        "settings": {
            "user_agent": "PersonaBrowser/1.0",
            "viewport_size": "1100,750",
            "viewport_device_scale_factor": 2,
            "language": "fr-FR",
            "timezone": "Europe/Paris",
            "platform": "MacIntel",
            "user_agent_metadata": {"platform": "macOS", "platformVersion": "27.0.0", "architecture": "arm", "model": "", "mobile": False},
            "color_scheme": "dark",
            "geolocation": {"latitude": 48.85, "longitude": 2.35, "accuracy": 10},
        },
    }
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona = Persona.objects.get(pk=response.json()["persona"]["id"])
    expected = {
        "CHROME_USER_AGENT": "PersonaBrowser/1.0",
        "CHROME_RESOLUTION": "1100,750",
        "BROWSER_DEVICE_SCALE_FACTOR": 2,
        "BROWSER_LANGUAGE": "fr-FR",
        "BROWSER_TIMEZONE": "Europe/Paris",
        "BROWSER_PLATFORM": "MacIntel",
        "BROWSER_USER_AGENT_METADATA": payload["settings"]["user_agent_metadata"],
        "BROWSER_COLOR_SCHEME": "dark",
        "BROWSER_GEOLOCATION": payload["settings"]["geolocation"],
    }
    config = get_config(persona=persona).model_dump(mode="json")
    assert {key: config.get(key) for key in expected} == expected
    payload["settings"] = {}
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona.refresh_from_db()
    assert {key: persona.config.get(key) for key in expected} == expected
    payload["settings"] = {
        "language": "",
        "timezone": "",
        "platform": "",
        "user_agent_metadata": None,
        "geolocation": None,
        "viewport_device_scale_factor": None,
    }
    response = api_client_request(client, "post", "/api/v1/personas/sync", payload=payload, headers=api_headers)
    assert response.status_code == 200, response.content
    persona.refresh_from_db()
    config = get_config(persona=persona).model_dump(mode="json")
    assert config["BROWSER_LANGUAGE"] == ""
    assert config["BROWSER_TIMEZONE"] == ""
    assert config["BROWSER_PLATFORM"] == ""
    assert config["BROWSER_USER_AGENT_METADATA"] == {}
    assert config["BROWSER_GEOLOCATION"] == {}
    assert config["BROWSER_DEVICE_SCALE_FACTOR"] == 1
    assert config["CHROME_USER_AGENT"] == "PersonaBrowser/1.0"


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


def test_sync_preserves_browser_storage_above_old_request_limit(client, api_headers):
    from archivebox.personas.models import Persona

    value = "saved-browser-record:" + "x" * (26 * 1024 * 1024)
    auth = {
        "origins": [
            {
                "origin": "https://example.com",
                "indexedDB": [
                    {
                        "name": "Documents",
                        "version": 1,
                        "stores": [
                            {
                                "name": "documents",
                                "keyPath": "id",
                                "autoIncrement": False,
                                "indexes": [],
                                "records": [{"value": {"id": 1, "content": value}}],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        payload={
            "extension_persona_id": "large-browser-state",
            "name": "large-browser-state",
            "auth_json": auth,
        },
        headers=api_headers,
    )
    assert response.status_code == 200, response.content[:500]
    persona = Persona.objects.get(pk=response.json()["persona"]["id"])
    assert json.loads((persona.path / "auth.json").read_text()) == auth


def test_sync_light_and_indexeddb_updates_preserve_omitted_state_and_explicit_clears(client, api_headers):
    from archivebox.personas.models import Persona

    identity = {"extension_persona_id": "split-browser-state", "name": "split-browser-state"}
    cookies_txt = "# Netscape HTTP Cookie File\nexample.com\tFALSE\t/\tTRUE\t0\tsession\tfirst-session\n"
    cookies = [{"domain": "example.com", "name": "session", "value": "first-session", "path": "/", "httpOnly": True, "sameSite": "Lax"}]
    database = {"name": "saved-state", "version": 1, "stores": [{"name": "entries", "records": [{"key": 1, "value": "preserved"}]}]}
    original = {
        "cookies": cookies,
        "origins": [
            {"origin": "https://example.com", "localStorage": [{"name": "account", "value": "first"}], "indexedDB": [database]},
            {"origin": "https://removed.example", "localStorage": [], "indexedDB": [database]},
        ],
        "tabs": [{"url": "https://example.com/tab", "sessionStorage": [{"name": "tab", "value": "kept"}]}],
    }
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "settings": {"user_agent": "PersonaBrowser/1.0", "color_scheme": "dark"},
            "cookies_txt": cookies_txt,
            "auth_json": original,
        },
    )
    assert response.status_code == 200, response.content
    persona = Persona.objects.get(pk=response.json()["persona"]["id"])
    auth_path = persona.path / "auth.json"
    light_origin = {"origin": "https://example.com", "localStorage": [{"name": "account", "value": "updated"}]}
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "auth_json": {"origins": [light_origin]},
        },
    )
    assert response.status_code == 200, response.content
    saved = json.loads(auth_path.read_text())
    assert saved == {**original, "origins": [{**light_origin, "indexedDB": [database]}]}
    assert response.json()["cookies_file_written"] is False
    assert (persona.path / "cookies.txt").read_text() == cookies_txt

    replacement = {**database, "version": 2}
    rejected = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "settings": {"color_scheme": "invalid"},
            "auth_json": {"origins": [{"origin": light_origin["origin"], "indexedDB": [replacement]}]},
        },
    )
    assert rejected.status_code == 422, rejected.content
    assert json.loads(auth_path.read_text()) == saved
    assert (persona.path / "cookies.txt").read_text() == cookies_txt
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "auth_json": {"origins": [{"origin": light_origin["origin"], "indexedDB": [replacement]}]},
        },
    )
    assert response.status_code == 200, response.content
    assert json.loads(auth_path.read_text()) == {**saved, "origins": [{**light_origin, "indexedDB": [replacement]}]}
    assert (persona.path / "cookies.txt").read_text() == cookies_txt
    persona.refresh_from_db()
    assert persona.config["CHROME_USER_AGENT"] == "PersonaBrowser/1.0"
    assert persona.config["BROWSER_COLOR_SCHEME"] == "dark"

    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "auth_json": {"origins": [{"origin": light_origin["origin"], "indexedDB": []}]},
        },
    )
    assert response.status_code == 200, response.content
    assert json.loads(auth_path.read_text()) == {**saved, "origins": [{**light_origin, "indexedDB": []}]}
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "auth_json": {"origins": [], "tabs": []},
        },
    )
    assert response.status_code == 200, response.content
    assert json.loads(auth_path.read_text()) == {"cookies": cookies, "origins": [], "tabs": []}


@pytest.mark.parametrize("origins", [None, {}, [{}], [None], [{"origin": []}], [{"origin": "https://example.com", "indexedDB": None}]])
def test_sync_rejects_malformed_origins_before_any_artifact_changes(client, api_headers, origins):
    from archivebox.personas.models import Persona

    identity = {"extension_persona_id": "invalid-origin-state", "name": "invalid-origin-state"}
    created = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "cookies_txt": "preserved-cookie-file",
            "auth_json": {"cookies": []},
        },
    )
    assert created.status_code == 200
    persona = Persona.objects.get(pk=created.json()["persona"]["id"])
    config = persona.config.copy()
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "settings": {"language": "changed"},
            "cookies_txt": "changed",
            "auth_json": {"origins": origins},
        },
    )
    assert response.status_code == 422, response.content
    assert (persona.path / "cookies.txt").read_text() == "preserved-cookie-file"
    assert json.loads((persona.path / "auth.json").read_text()) == {"cookies": []}
    persona.refresh_from_db()
    assert persona.config == config


@pytest.mark.parametrize("contents", ["not-json", "[]", "null"])
def test_sync_preserves_corrupt_saved_artifact_until_explicit_clear(client, api_headers, contents):
    from archivebox.personas.models import Persona

    identity = {"extension_persona_id": "corrupt-saved-state", "name": "corrupt-saved-state"}
    created = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "cookies_txt": "preserved-cookie-file",
            "auth_json": {},
        },
    )
    assert created.status_code == 200
    persona = Persona.objects.get(pk=created.json()["persona"]["id"])
    config = persona.config.copy()
    (persona.path / "auth.json").write_text(contents)
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "settings": {"language": "changed"},
            "cookies_txt": "changed",
            "auth_json": {"cookies": []},
        },
    )
    assert response.status_code == 409, response.content
    assert (persona.path / "cookies.txt").read_text() == "preserved-cookie-file"
    assert (persona.path / "auth.json").read_text() == contents
    persona.refresh_from_db()
    assert persona.config == config
    cleared = api_client_request(client, "post", "/api/v1/personas/sync", headers=api_headers, payload={**identity, "auth_json": {}})
    assert cleared.status_code == 200, cleared.content
    assert json.loads((persona.path / "auth.json").read_text()) == {}


@pytest.mark.parametrize("prior_origins", [None, [{}, None, {"origin": ["invalid"]}]])
def test_sync_updates_origins_with_malformed_legacy_entries(client, api_headers, prior_origins):
    from archivebox.personas.models import Persona

    identity = {"extension_persona_id": "legacy-origin-state", "name": "legacy-origin-state"}
    created = api_client_request(client, "post", "/api/v1/personas/sync", headers=api_headers, payload=identity)
    assert created.status_code == 200
    persona = Persona.objects.get(pk=created.json()["persona"]["id"])
    database = {"name": "preserved", "stores": []}
    valid_origin = {"origin": "https://example.com", "indexedDB": [database]}
    if isinstance(prior_origins, list):
        prior_origins.append(valid_origin)
    (persona.path / "auth.json").write_text(json.dumps({"cookies": [], "origins": prior_origins}))
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        headers=api_headers,
        payload={
            **identity,
            "auth_json": {"origins": [{"origin": valid_origin["origin"], "localStorage": []}]},
        },
    )
    assert response.status_code == 200, response.content
    expected_origin = {"origin": valid_origin["origin"], "localStorage": []}
    if isinstance(prior_origins, list):
        expected_origin["indexedDB"] = [database]
    assert json.loads((persona.path / "auth.json").read_text()) == {"cookies": [], "origins": [expected_origin]}
