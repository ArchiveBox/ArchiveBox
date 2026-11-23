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


def test_model_export_actions_create_links_only_on_interaction(live_server, admin_user, browser_runtime):
    from playwright.sync_api import expect, sync_playwright
    from archivebox.tests.export_helpers import export_action_urls

    folder = Folder.objects.create(name="Export selection", created_by=admin_user)
    source = ImporterSource.objects.create(name="Export feed", plugin="feeds", feed="rss", created_by=admin_user, folder=folder)
    ImporterRun.objects.create(source=source, status=ImporterRun.Status.SUCCEEDED, result={"saved": 1})
    origin = live_server.url.replace("localhost", "admin.archivebox.localhost")
    pages = (
        (
            reverse("admin:core_folder_changelist") + "?q=selection",
            reverse("admin:core_folder_export", args=["csv"]) + "?q=selection",
            b"Export selection",
        ),
        (reverse("importers:index"), reverse("importers:export", args=["csv"]), b"Export feed"),
        (reverse("importers:detail", args=[source.pk]), reverse("importers:export-runs", args=[source.pk, "csv"]), b"succeeded"),
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page()
        page.goto(origin + "/admin/login/?next=/admin/core/folder/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        for path, direct_url, expected in pages:
            response = page.goto(origin + path)
            assert response.status == 200
            export_action_urls(response.text())
            expect(page.locator("a[data-export-format][href]")).to_have_count(0)
            action = page.locator('a[data-export-format="csv"]').first
            action.focus()
            expect(action).to_have_attribute("href", origin + direct_url)
            with page.expect_download() as download:
                action.press("Enter")
            assert download.value.failure() is None
            body = Path(download.value.path()).read_bytes()
            assert expected in body
            direct = page.request.get(origin + direct_url)
            assert direct.status == 200
            assert direct.body() == body
        browser.close()
