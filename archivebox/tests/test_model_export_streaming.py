"""Authenticated Folder and Importer exports keep native bytes while spooling."""

from io import StringIO
from pathlib import Path

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


def test_admin_model_export_links_work_without_javascript(live_server, admin_user, browser_runtime, settings):
    from playwright.sync_api import sync_playwright
    from archivebox.machine.models import Machine

    folder = Folder.objects.create(name="Export selection", created_by=admin_user)
    source = ImporterSource.objects.create(name="Export feed", plugin="feeds", feed="rss", created_by=admin_user, folder=folder)
    ImporterRun.objects.create(source=source, status=ImporterRun.Status.SUCCEEDED, result={"saved": 1})
    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    base_url = live_server.url.replace("localhost", "archivebox.localhost")
    settings.CONFIG = settings.CONFIG.model_copy(update={"BASE_URL": base_url})
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base_url}
    machine.save(update_fields=["config"])
    pages = (
        (
            reverse("admin:core_folder_changelist") + "?q=selection",
            "admin:core_folder_export",
            [],
            "?q=selection",
            b"Export selection",
        ),
        (reverse("importers:index"), "importers:export", [], "", b"Export feed"),
        (reverse("importers:detail", args=[source.pk]), "importers:export-runs", [source.pk], "", b"succeeded"),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(java_script_enabled=False)
        page.goto(origin + "/admin/login/?next=/admin/core/folder/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        for path, route, args, query, expected in pages:
            response = page.goto(origin + path)
            assert response.status == 200
            for format in ("csv", "jsonl"):
                direct_url = reverse(route, args=[*args, format]) + query
                link = page.get_by_role("link", name=format.upper() if not args else f"History {format.upper()}", exact=True)
                assert link.get_attribute("href") == direct_url
                with page.expect_download() as download:
                    link.click()
                assert download.value.failure() is None
                body = Path(download.value.path()).read_bytes()
                assert expected in body
                direct = page.request.get(origin + direct_url)
                assert direct.status == 200
                assert direct.body() == body
        browser.close()
