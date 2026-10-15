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


def test_daemon_discovers_work_after_capture_dispatch_stops_ticking(admin_client, import_site):
    import time

    from archivebox.importers import service
    from archivebox.importers.models import ImporterSource

    _, url = import_site
    # The capture runner ticks once before entering a potentially long crawl.
    service.tick(daemon=True)
    try:
        response = admin_client.post(
            "/admin/importers/new/importer_rss/feed/",
            {"name": "Concurrent feed", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50"},
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 302
        source = ImporterSource.objects.get(name="Concurrent feed")
        response = admin_client.post(f"/admin/importers/{source.pk}/preview/", HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 302
        run = source.runs.get()
        deadline = time.monotonic() + 20
        while run.status in service.ACTIVE_STATUSES and time.monotonic() < deadline:
            time.sleep(0.1)
            run.refresh_from_db()
        assert run.status == "succeeded", (run.status, run.message)
        assert [item["url"] for item in run.items] == [f"{url}/article.html"]
        source.refresh_from_db()
        assert source.checkpoint == {}
        assert run.crawl_id is None
    finally:
        service.shutdown()


def test_import_preview_and_run_preserve_checkpoint_and_queue_real_crawl(admin_client, import_site):
    from django.urls import reverse

    from archivebox.crawls.models import Crawl
    from archivebox.importers.models import ImporterRun, ImporterSource
    from archivebox.importers.service import run_next_importer
    from archivebox.personas.models import Persona

    _, url = import_site
    persona = Persona.get_or_create_named("Importer navigation")
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Reading list", "persona": persona.pk, "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50", "schedule": ""},
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

    persona_url = reverse("admin:personas_persona_change", args=[persona.pk])
    crawl_url = reverse("admin:crawls_crawl_change", args=[run.crawl_id])
    snapshots_url = reverse("admin:core_snapshot_changelist") + f"?crawl_id={run.crawl_id}"
    for path in (source.get_absolute_url(), reverse("importers:run", args=[run.pk])):
        response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        html = response.content.decode()
        assert f'href="{persona_url}"' in html
        assert f'href="{crawl_url}"' in html
        assert f'href="{snapshots_url}"' in html
        assert 'http-equiv="refresh"' not in html
    activity = admin_client.get(reverse("importers:run-activity", args=[run.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert activity.status_code == 200
    assert activity.json()["active"] is False
    assert "No AI session recorded" in activity.json()["html"]

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


def test_initial_import_requires_recheck_after_nonempty_preview_becomes_empty(admin_client, import_site):
    from archivebox.crawls.models import Crawl
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    root, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Preview evidence", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Preview evidence")
    preview_url = f"/admin/importers/{source.pk}/preview/"
    import_url = f"/admin/importers/{source.pk}/import/"
    assert admin_client.post(preview_url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next_importer()
    preview = source.runs.first()
    assert preview.status == "succeeded" and len(preview.items) == 1

    (root / "feed.xml").write_text('<rss version="2.0"><channel><title>Empty feed</title></channel></rss>')
    assert admin_client.post(import_url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next_importer()
    failed = source.runs.first()
    assert failed.status == "failed", failed.message
    assert "nonempty preview" in failed.message
    assert failed.request["preview_count"] == 1
    assert failed.items == [] and failed.crawl_id is None
    source.refresh_from_db()
    assert source.checkpoint == {} and Crawl.objects.count() == 0

    # A fresh real empty preview clears the contradiction; empty sources remain
    # supported without weakening the failed first run or changing its progress.
    assert admin_client.post(preview_url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next_importer()
    empty_preview = source.runs.first()
    assert empty_preview.status == "succeeded" and empty_preview.items == []
    assert admin_client.post(import_url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next_importer()
    empty_import = source.runs.first()
    assert empty_import.status == "succeeded", empty_import.message
    assert empty_import.request["preview_count"] == 0
    assert empty_import.items == [] and empty_import.crawl_id is None
    failed.refresh_from_db()
    assert failed.status == "failed" and Crawl.objects.count() == 0


def test_changed_source_does_not_inherit_the_previous_preview_count(admin_client, import_site):
    from archivebox.crawls.models import Crawl
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    root, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Changed source", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Changed source")
    assert admin_client.post(f"/admin/importers/{source.pk}/preview/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next_importer()
    assert len(source.runs.first().items) == 1
    (root / "empty.xml").write_text('<rss version="2.0"><channel><title>Another feed</title></channel></rss>')
    response = admin_client.post(
        f"/admin/importers/{source.pk}/edit/",
        {"name": source.name, "setting_IMPORTER_RSS_URL": f"{url}/empty.xml"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    assert admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert run_next_importer()
    run = source.runs.first()
    assert run.status == "succeeded", run.message
    assert "preview_count" not in run.request
    assert run.items == [] and run.crawl_id is None and Crawl.objects.count() == 0


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
    assert 'name="setting_IMPORTERS_BROWSER_ACCOUNT"' not in basic
    advanced = advanced.split("</details>", 1)[0]
    assert set(re.findall(r'name="([^"]+)"', advanced)) == {
        "name",
        "limit",
        "tags",
        "schedule",
        "setting_IMPORTERS_BROWSER_ACCOUNT",
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


def test_browser_importer_discovers_account_from_selected_persona(admin_client):
    from archivebox.importers.models import ImporterSource
    from archivebox.personas.models import Persona

    persona = Persona.get_or_create_named("Importers browser setup")
    path = "/admin/importers/new/importers_browser/reddit_saves/"
    response = admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
    assert [field.name for field in response.context["form"].basic_fields] == ["persona"]
    response = admin_client.post(path, {"persona": persona.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    source = ImporterSource.objects.get()
    assert source.persona == persona
    assert source.settings["IMPORTERS_BROWSER_ACCOUNT"] == ""
    assert source.account == {}
    assert source.checkpoint == {}


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


def test_every_declared_importer_setup_renders_with_available_images(admin_client):
    from archivebox.importers.catalog import get_importers

    definitions = get_importers()
    assert len(definitions) >= 20
    for definition in definitions.values():
        response = admin_client.get(f"/admin/importers/new/{definition.plugin}/{definition.feed}/", HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200, (definition.plugin, definition.feed)
        if definition.auth == "persona":
            assert {field.name for field in response.context["form"].basic_fields} == {"persona"}
            assert not response.context["form"].fields["setting_IMPORTERS_BROWSER_ACCOUNT"].required
        for step, guide in enumerate(definition.setup):
            if guide.get("image"):
                response = admin_client.get(
                    f"/admin/importers/guide/{definition.plugin}/{definition.feed}/{step}/",
                    HTTP_HOST=ADMIN_TEST_HOST,
                )
                assert response.status_code == 200, (definition.plugin, definition.feed, step)
                assert response["Content-Type"].startswith("image/")
                assert b"".join(response.streaming_content)


def test_malformed_importer_ids_are_not_server_errors(admin_client):
    for suffix in ("", "edit/", "import/"):
        path = f"/admin/importers/{'-' * 32}/{suffix}"
        assert admin_client.get(path, HTTP_HOST=ADMIN_TEST_HOST).status_code == 404


def test_reset_learned_code_uses_worker_and_preserves_progress(admin_client, import_site):
    from archivebox.config.constants import CONSTANTS
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    _, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Reset code", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Reset code")
    admin_client.post(f"{source.get_absolute_url()}import/", HTTP_HOST=ADMIN_TEST_HOST)
    assert run_next_importer()
    source.refresh_from_db()
    checkpoint = source.checkpoint
    imported = source.runs.get()
    assert imported.status == "succeeded", imported.message
    assert imported.crawl_id
    root = CONSTANTS.DATA_DIR / "importers" / str(source.pk)
    state = root / "state"
    (state / "harness").mkdir(parents=True)
    (state / "harness" / "notes.txt").write_text("Local notes to reset")
    # A user's independent version control and run history must survive reset.
    import subprocess

    subprocess.run(["git", "init", "--quiet", str(state)], check=True)
    history = root / str(imported.pk) / "harness.log"
    history.write_text("Previous run log")
    html = admin_client.get(source.get_absolute_url(), HTTP_HOST=ADMIN_TEST_HOST).content.decode()
    assert str(state) in html
    assert "Reset learned code" in html
    assert "version control" in html

    endpoint = f"{source.get_absolute_url()}reset_code/"
    response = admin_client.post(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    reset = source.runs.get(action="reset_code")
    assert reset.status == "queued"
    assert (state / "harness" / "notes.txt").exists()
    # A second action cannot start while the reset owns this source.
    admin_client.post(f"{source.get_absolute_url()}preview/", HTTP_HOST=ADMIN_TEST_HOST)
    assert source.runs.filter(status="queued").count() == 1
    assert run_next_importer()
    reset.refresh_from_db()
    source.refresh_from_db()
    assert reset.status == "succeeded", reset.message
    assert not (state / "harness").exists()
    assert (state / ".git" / "HEAD").is_file()
    assert history.read_text() == "Previous run log"
    assert source.checkpoint == checkpoint
    assert source.runs.get(pk=imported.pk).crawl_id == imported.crawl_id
    assert reset.crawl_id is None


def test_run_activity_links_recorded_sessions_and_protects_logs(admin_client, import_site, tmp_path):
    import json
    from pathlib import Path
    from django.test import Client
    from django.urls import reverse
    from archivebox.importers.diagnostics import run_directory
    from archivebox.importers.models import ImporterSource

    _, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Run activity", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Run activity")
    admin_client.post(f"{source.get_absolute_url()}check/", HTTP_HOST=ADMIN_TEST_HOST)
    run = source.runs.get()
    directory = run_directory(run)
    directory.mkdir(parents=True)
    events = json.loads((Path(__file__).parent / "fixtures/importers/opencode_sessions.json").read_text())
    for name, event in events.items():
        (directory / name).write_text(json.dumps(event) + "\n")
    # Real PNG bytes exercise private artifact serving independently of the
    # browser plugin's live capture test.
    screenshot = (Path(__file__).parents[1] / "templates/static/chrome_extension_icon.png").read_bytes()
    (directory / "failure-1.png").write_bytes(screenshot)
    screenshot_url = f"/admin/importers/runs/{run.pk}/screenshots/failure-1.png"
    for endpoint in (reverse("importers:source-activity", args=[source.pk]), reverse("importers:run-activity", args=[run.pk])):
        response = admin_client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        assert response.json()["active"] is True
        for event in events.values():
            assert f"/admin/agent/?session={event['sessionID']}" in response.json()["html"]
        assert f'src="{screenshot_url}"' in response.json()["html"]
        assert "Failure screen" in response.json()["html"]
        assert Client().get(endpoint, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    response = admin_client.get(screenshot_url, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert "no-store" in response["Cache-Control"]
    assert b"".join(response.streaming_content) == screenshot
    assert Client().get(screenshot_url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    name = "learning-1.jsonl"
    endpoint = reverse("importers:run-log", args=[run.pk, name])
    response = admin_client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == (directory / name).read_bytes()
    assert Client().get(endpoint, HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    private = tmp_path / "not-a-run-log"
    private.write_text("Not served")
    (directory / "failure.log").symlink_to(private)
    (directory / "failure-2.png").symlink_to(private)
    for name in ("failure-2.png", "request.json", "failure-99.png", "../request.json"):
        assert admin_client.get(f"/admin/importers/runs/{run.pk}/screenshots/{name}", HTTP_HOST=ADMIN_TEST_HOST).status_code == 404
    for name in ("failure.log", "request.json"):
        assert admin_client.get(reverse("importers:run-log", args=[run.pk, name]), HTTP_HOST=ADMIN_TEST_HOST).status_code == 404


def test_importer_navigation_table_and_paginated_history(admin_client, import_site):
    import re
    from archivebox.importers.models import ImporterSource

    _, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "History", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="History")
    for _ in range(21):
        assert admin_client.post(f"{source.get_absolute_url()}check/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
        assert admin_client.post(f"{source.get_absolute_url()}pause/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    admin_client.post(f"{source.get_absolute_url()}check/", HTTP_HOST=ADMIN_TEST_HOST)
    html = admin_client.get(source.get_absolute_url(), HTTP_HOST=ADMIN_TEST_HOST).content.decode()
    assert html.split("<tbody>")[1].split("</tbody>")[0].count("<tr>") == 20
    response = admin_client.get(f"{source.get_absolute_url()}activity/?page=2", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.json()["active"] is True  # Active run may be on another page.
    assert response.json()["html"].split("<tbody>")[1].split("</tbody>")[0].count("<tr>") == 2
    html = admin_client.get("/admin/importers/", HTTP_HOST=ADMIN_TEST_HOST).content.decode()
    assert f'href="{source.get_absolute_url()}"' in html.split("<tbody>")[1].split("</tbody>")[0]
    home = admin_client.get("/admin/", HTTP_HOST=ADMIN_TEST_HOST).content.decode()
    row = re.search(r'abx-admin-flow__row--child">(.*?)abx-admin-flow__row--grandchild', home, re.S).group(1)
    assert 'href="/admin/core/snapshot/"' in row
    assert 'href="/admin/importers/"' in row


@pytest.mark.parametrize("status", ["queued", "running", "succeeded", "failed", "needs_login", "cancelled"])
def test_run_without_message_displays_its_lifecycle(admin_client, import_site, status):
    from django.urls import reverse
    from django.utils import timezone
    from archivebox.importers.models import ImporterSource

    _, url = import_site
    response = admin_client.post(
        "/admin/importers/new/importer_rss/feed/",
        {"name": "Lifecycle status", "setting_IMPORTER_RSS_URL": f"{url}/feed.xml", "limit": "50"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Lifecycle status")
    assert admin_client.post(f"{source.get_absolute_url()}check/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    run = source.runs.get()
    run.status = status
    # Cancelled queued work can finish without ever starting.
    run.started_at = timezone.now() if status not in ("queued", "cancelled") else None
    run.finished_at = timezone.now() if status not in ("queued", "running") else None
    run.save()
    paths = [source.get_absolute_url(), reverse("importers:run", args=[run.pk])]
    endpoints = [reverse("importers:source-activity", args=[source.pk]), reverse("importers:run-activity", args=[run.pk])]
    for endpoint in paths + endpoints:
        response = admin_client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        html = response.json()["html"] if endpoint in endpoints else response.content.decode()
        if status == "queued":
            assert "Waiting for the ArchiveBox worker." in html
        else:
            assert "Waiting for the ArchiveBox worker." not in html
            assert ">Waiting for worker" not in html
        if status == "running":
            assert "Importer is running. No activity update yet." in html
        if status == "cancelled":
            assert "Not started" in html
