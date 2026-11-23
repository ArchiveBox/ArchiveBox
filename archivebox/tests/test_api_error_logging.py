"""API failures retain Django exception logging and client-error semantics."""

import logging

import pytest
from django.conf import settings
from django.core.exceptions import RequestDataTooBig

from archivebox.tests.conftest import api_client_request


@pytest.mark.django_db(transaction=True)
def test_oversized_persona_sync_logs_exception_without_retryable_response(client, api_headers, caplog):
    from archivebox.personas.models import Persona

    before = set(Persona.objects.values_list("pk", flat=True))
    response = api_client_request(
        client,
        "post",
        "/api/v1/personas/sync",
        payload={
            "extension_persona_id": "oversized-sync",
            "name": "oversized-sync",
            "cookies_txt": "x" * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1),
        },
        headers=api_headers,
    )

    assert response.status_code == 400, response.content[:500]
    assert response.json()["succeeded"] is False
    assert response.json()["message"].startswith("RequestDataTooBig:")
    assert set(Persona.objects.values_list("pk", flat=True)) == before
    records = [record for record in caplog.records if record.name == "archivebox.api.v1_api"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None
    assert isinstance(records[0].exc_info[1], RequestDataTooBig)
    assert records[0].exc_info[2] is not None
    assert "cookies_txt" not in records[0].getMessage()
