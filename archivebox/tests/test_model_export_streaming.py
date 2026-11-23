"""Authenticated Folder and Importer exports keep native bytes while spooling."""

from io import StringIO

import pytest
from django.urls import reverse

from archivebox.core.models import Folder
from archivebox.importers.models import ImporterRun, ImporterSource
from archivebox.misc.jsonl import write_record_table
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("format", ["json", "jsonl", "csv", "tsv"])
def test_admin_model_exports_preserve_filters_and_record_bytes(admin_client, admin_user, format):
    folder = Folder.objects.create(name="Café selection", created_by=admin_user)
    Folder.objects.create(name="Other folder", created_by=admin_user)
    source = ImporterSource.objects.create(name="Café feed", plugin="feeds", feed="rss", created_by=admin_user, folder=folder)
    run = ImporterRun.objects.create(
        source=source,
        items=[{"url": "https://example.com/document", "title": "Café"}],
        result={"saved": 1},
        status=ImporterRun.Status.SUCCEEDED,
    )
    for url, query, filename, records in (
        (reverse("admin:core_folder_export", args=[format]), {"q": "selection"}, "folders", [folder.to_json()]),
        (reverse("importers:export-runs", args=[source.pk, format]), {}, "importer-runs", [run.to_json()]),
    ):
        output = StringIO()
        write_record_table(records, format=format, stream=output)
        expected = output.getvalue().encode()
        response = admin_client.get(url, query, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert response.streaming
        assert response["Content-Disposition"] == f'attachment; filename="{filename}.{format}"'
        assert int(response["Content-Length"]) == len(expected)
        assert response.getvalue() == expected
        response.close()


def test_api_model_export_empty_json_remains_downloadable(client, api_headers):
    response = client.get("/api/v1/importers/runs", {"format": "json"}, secure=True, **api_headers)
    assert response.status_code == 200
    assert response.streaming
    assert response["Cache-Control"] == "no-store"
    assert response["Content-Disposition"] == 'attachment; filename="importer-runs.json"'
    assert response.getvalue() == b"[]\n"
    response.close()
