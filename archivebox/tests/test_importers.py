"""Import UI and real standalone connectors against a real static HTTP server."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def import_site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    (root / "article.html").write_text("<html><title>Imported article</title><body>Real imported content.</body></html>")
    (root / "feed.xml").write_text(
        f'<rss version="2.0"><channel><title>Reading list</title><item><guid>article-1</guid>'
        f"<title>Imported article</title><link>{url}/article.html</link></item></channel></rss>",
    )
    (root / "links.csv").write_text(f"URL,Title\n{url}/article.html,Imported article\n")
    try:
        yield root, url
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_import_catalog_is_rendered_from_real_plugins(admin_client):
    response = admin_client.get("/admin/importers/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"Importers" in response.content
    assert b"RSS" in response.content
    assert b"Spreadsheet" in response.content


def test_import_preview_and_run_preserve_checkpoint_and_queue_real_crawl(admin_client, import_site):
    from archivebox.crawls.models import Crawl
    from archivebox.importers.models import ImporterRun, ImporterSource
    from archivebox.importers.service import run_next_importer

    _, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Reading list", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50", "schedule": ""},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Reading list")
    response = admin_client.post(f"/admin/importers/{source.pk}/preview/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    assert run_next_importer()
    source.refresh_from_db()
    preview = source.runs.get()
    assert preview.status == ImporterRun.Status.SUCCEEDED, preview.message
    assert preview.items[0]["url"] == f"{url}/article.html"
    assert source.checkpoint == {}
    assert Crawl.objects.count() == 0

    admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    source.refresh_from_db()
    run = source.runs.get(action="import")
    assert run.status == ImporterRun.Status.SUCCEEDED, run.message
    assert source.checkpoint
    assert run.crawl.status == Crawl.StatusChoices.QUEUED
    from archivebox.services.runner import run_crawl

    run_crawl(str(run.crawl_id), selected_plugins=["title", "wget"])
    snapshots = list(run.crawl.snapshot_set.all())
    assert len(snapshots) == 1
    assert snapshots[0].url == f"{url}/article.html"
    assert snapshots[0].title == "Imported article"
    assert snapshots[0].archiveresult_set.filter(plugin="wget", status="succeeded").exists()

    admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    repeat = source.runs.order_by("-created_at").first()
    assert repeat.status == ImporterRun.Status.SUCCEEDED, repeat.message
    assert repeat.items == []
    assert repeat.crawl_id is None


def test_import_routes_require_admin_and_post(admin_client):
    from django.test import Client

    response = Client().get("/admin/importers/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    response = admin_client.get("/admin/importers/00000000-0000-0000-0000-000000000000/import/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 405


def test_spreadsheet_reordering_and_new_rows(admin_client, import_site):
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    root, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_sheets/rows/",
        {"name": "Sheet", "setting_IMPORTER_SHEETS_URL": f"{url}/links.csv", "setting_IMPORTER_SHEETS_COLUMN": "URL", "limit": "50"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Sheet")
    endpoint = f"/admin/importers/{source.pk}/import/"
    admin_client.post(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    first = source.runs.first()
    assert first.status == "succeeded", first.message
    assert [item["url"] for item in first.items] == [f"{url}/article.html"]
    (root / "links.csv").write_text(f"URL,Title\n{url}/new.html,New\n{url}/article.html,Imported article\n")
    admin_client.post(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    second = source.runs.first()
    assert second.status == "succeeded", second.message
    assert [item["url"] for item in second.items] == [f"{url}/new.html"]
    (root / "links.csv").write_text(f"URL,Title\n{url}/article.html,Imported article\n{url}/new.html,New\n")
    admin_client.post(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    third = source.runs.first()
    assert third.status == "succeeded", third.message
    assert third.items == []


def test_failed_source_does_not_advance_progress_or_create_crawl(admin_client, import_site):
    from archivebox.crawls.models import Crawl
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    root, url = import_site
    admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Feed", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "1"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    source = ImporterSource.objects.get()
    endpoint = f"/admin/importers/{source.pk}/import/"
    admin_client.post(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    source.refresh_from_db()
    checkpoint = source.checkpoint
    assert checkpoint
    (root / "feed.xml").write_text("<html><title>Please sign in</title></html>")
    admin_client.post(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    source.refresh_from_db()
    assert source.runs.first().status == "failed"
    assert source.checkpoint == checkpoint
    assert Crawl.objects.count() == 1


def test_schedule_and_pause_use_one_durable_run(admin_client, import_site):
    from datetime import timedelta

    from django.utils import timezone

    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import enqueue_due, run_next_importer

    _, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Daily", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50", "schedule": "daily"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get()
    ImporterSource.objects.filter(pk=source.pk).update(next_run_at=timezone.now() - timedelta(minutes=1))
    enqueue_due()
    enqueue_due()
    assert source.runs.count() == 1
    admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST)
    assert source.runs.count() == 1
    admin_client.post(f"/admin/importers/{source.pk}/pause/", HTTP_HOST=ADMIN_TEST_HOST)
    source.refresh_from_db()
    assert not source.enabled
    assert source.next_run_at is None
    assert source.runs.get().status == "cancelled"
    assert not run_next_importer()
    admin_client.post(f"/admin/importers/{source.pk}/resume/", HTTP_HOST=ADMIN_TEST_HOST)
    source.refresh_from_db()
    assert source.enabled
    assert source.next_run_at > timezone.now()


def test_run_pages_escape_imported_content_and_export_provenance(admin_client, import_site):
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    root, url = import_site
    (root / "feed.xml").write_text(
        f'<rss version="2.0"><channel><title>Feed</title><item><title>&lt;script&gt;alert(1)&lt;/script&gt;</title>'
        f"<link>{url}/article.html</link></item></channel></rss>",
    )
    admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Feed", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    source = ImporterSource.objects.get()
    admin_client.post(f"/admin/importers/{source.pk}/preview/", HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    run = source.runs.get()
    assert run.status == "succeeded", run.message
    for path in (source.get_absolute_url(), f"/admin/importers/runs/{run.pk}/", "/admin/importers/"):
        response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert b"<script>alert(1)</script>" not in response.content
    data = admin_client.get(f"/admin/importers/runs/{run.pk}/items.json", HTTP_HOST=ADMIN_TEST_HOST).json()
    assert data["items"][0]["metadata"]["relationship"] == "feed entry"
    assert "checkpoint" not in data


def test_staff_cannot_access_importers_and_mutations_require_csrf(admin_user):
    from django.contrib.auth import get_user_model
    from django.test import Client

    staff = get_user_model().objects.create_user("importer-staff", is_staff=True, password="testpassword")
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff)
    assert client.get("/admin/importers/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    client.force_login(admin_user)
    assert client.post("/admin/importers/new/importer_rss/feed/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 403


def test_pause_cancels_a_real_inflight_import(admin_client, blocking_http_server):
    from concurrent.futures import ThreadPoolExecutor

    from django.db import connections

    from archivebox.crawls.models import Crawl
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Blocked feed", "setting_IMPORTER_RSS_URL": blocking_http_server.url, "limit": 5},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Blocked feed")
    admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST)

    def run():
        try:
            return run_next_importer()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(run)
        try:
            assert blocking_http_server.request_started.wait(20), "Importer did not request its real feed"
            response = admin_client.post(f"/admin/importers/{source.pk}/pause/", HTTP_HOST=ADMIN_TEST_HOST)
            assert response.status_code == 302
            assert pending.result(timeout=20)
        finally:
            blocking_http_server.release_response.set()
    source.refresh_from_db()
    assert source.runs.get().status == "cancelled"
    assert source.checkpoint == {}
    assert not source.enabled
    assert not Crawl.objects.exists()


def test_simple_setup_defaults_and_advanced_errors(admin_client, import_site):
    from archivebox.importers.models import ImporterSource

    _, url = import_site
    path = "/admin/importers/new/importer_rss/feed/"
    response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"Advanced options" in response.content
    assert b"How to connect" in response.content
    assert [field.name for field in response.context["form"].basic_fields] == ["setting_IMPORTER_RSS_URL"]
    response = admin_client.post(path, {"setting_IMPORTER_RSS_URL": f"{url}/feed.xml"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    source = ImporterSource.objects.get()
    assert source.limit == 100
    assert source.name == "RSS & Atom · Feed articles"
    response = admin_client.post(path, {"setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": -1}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.context["form"].advanced_errors
    assert b'class="advanced" open' in response.content


def test_plugin_setup_images_are_real_and_admin_only(admin_client):
    from django.test import Client

    path = "/admin/importers/guide/importers_browser/x_bookmarks/1/"
    assert Client().get(path, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert b"".join(response.streaming_content).startswith(b"\x89PNG\r\n\x1a\n")
    assert admin_client.get("/admin/importers/guide/importers_browser/x_bookmarks/100/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 404


def test_importer_brands_and_setup_assets(admin_client):
    import re

    response = admin_client.get("/admin/importers/", HTTP_HOST=ADMIN_TEST_HOST)
    html = response.content.decode()
    assert html.count('class="provider-card"') == 6
    providers = {group["name"]: group for group in response.context["providers"]}
    assert len(providers["Google"]["feeds"]) == 4
    assert len(providers["X"]["feeds"]) == 5
    icons = re.findall(r'class="brand-icon" src="([^"]+)"', html)
    assert len(icons) == 6
    for url in icons:
        image = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
        assert image.status_code == 200
        assert image["Content-Type"].startswith("image/")
        assert b"".join(image.streaming_content)
    assert 'action="/admin/importers/custom/" class="custom-importer"' in html

    setup = admin_client.get("/admin/importers/new/importers_browser/x_bookmarks/", HTTP_HOST=ADMIN_TEST_HOST)
    html = setup.content.decode()
    assert '<details class="advanced" >' in html
    basic, advanced = html.split('<details class="advanced"', 1)
    assert 'name="persona"' in basic
    assert 'name="setting_IMPORTERS_BROWSER_ACCOUNT"' in basic
    advanced = advanced.split("</details>", 1)[0]
    assert set(re.findall(r'name="([^"]+)"', advanced)) == {
        "name",
        "limit",
        "tags",
        "schedule",
        "setting_IMPORTERS_BROWSER_URL",
    }
    images = re.findall(r'<img src="([^"]+)"', html.split('<aside class="setup-guide">', 1)[1])
    assert len(images) >= 2
    for url in images:
        response = admin_client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert b"".join(response.streaming_content).startswith(b"\x89PNG")


def test_importer_minimal_setup_uses_defaults(admin_client, import_site):
    from archivebox.importers.models import ImporterSource

    _, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {
            "setting_IMPORTER_RSS_URL": f"{url}/feed.xml",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get()
    assert source.name == "RSS & Atom · Feed articles"
    assert source.limit == 100
    assert source.schedule == ""
    assert source.settings == {"IMPORTER_RSS_URL": f"{url}/feed.xml"}


def test_custom_importer_requires_post_and_csrf(admin_client, admin_user):
    from django.test import Client

    assert admin_client.get("/admin/importers/custom/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    assert client.post("/admin/importers/custom/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 403


def test_import_all_drains_every_batch_and_skips_existing_items(admin_client, import_site):
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    root, url = import_site
    (root / "links.csv").write_text("URL,Title\n" + "\n".join(f"{url}/article-{i}.html,Article {i}" for i in range(7)))
    response = admin_client.post(
        "/admin/importers/new/importer_sheets/rows/",
        {"setting_IMPORTER_SHEETS_URL": f"{url}/links.csv", "setting_IMPORTER_SHEETS_COLUMN": "URL", "limit": 2},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get()
    admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST)
    for _ in range(4):
        assert run_next_importer()
    assert not run_next_importer()
    runs = list(source.runs.order_by("created_at"))
    assert [len(run.items) for run in runs] == [2, 2, 2, 1]
    assert all(run.status == "succeeded" and run.crawl_id for run in runs)
    assert len({item["id"] for run in runs for item in run.items}) == 7
    assert [run.result["has_more"] for run in runs] == [True, True, True, False]
    admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    assert source.runs.first().items == []
    (root / "links.csv").write_text((root / "links.csv").read_text() + f"\n{url}/added.html,New addition\n")
    admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    assert [item["url"] for item in source.runs.first().items] == [f"{url}/added.html"]
