import pytest

from archivebox.personas.models import Persona
from archivebox.tests.conftest import api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_personas_api_returns_paginated_envelope(client, api_headers):
    for name in ("api-persona-alpha", "api-persona-bravo", "api-persona-charlie"):
        create_response = api_client_request(
            client,
            "post",
            "/api/v1/personas/sync",
            payload={
                "extension_persona_id": f"extension-{name}",
                "name": name,
                "settings": {},
                "cookies_txt": "",
                "auth_json": {},
            },
            headers=api_headers,
        )
        assert create_response.status_code == 200, create_response.content
        assert create_response.json()["created"] is True

    total_personas = Persona.objects.count()
    response = client.get(
        "/api/v1/personas/personas?limit=1",
        **api_headers,
    )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert isinstance(payload, dict)
    assert set(payload) >= {"items", "count", "total_items", "total_pages", "page", "limit", "offset", "num_items"}
    assert payload["count"] == total_personas
    assert payload["total_items"] == total_personas
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["num_items"] == 1
    assert len(payload["items"]) == 1

    limit_two_response = client.get(
        "/api/v1/personas/personas?limit=2",
        **api_headers,
    )
    assert limit_two_response.status_code == 200, limit_two_response.content
    limit_two_payload = limit_two_response.json()
    assert isinstance(limit_two_payload, dict)
    assert limit_two_payload["count"] == total_personas
    assert limit_two_payload["total_items"] == total_personas
    assert limit_two_payload["limit"] == 2
    assert limit_two_payload["offset"] == 0
    assert limit_two_payload["num_items"] == 2
    assert len(limit_two_payload["items"]) == 2
