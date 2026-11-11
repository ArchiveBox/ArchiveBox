import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_save_rss_list_filters_and_revoke(admin_client, admin_user, client):
    from django.test import Client
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.feeds.models import SavedFeed

    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    visible = Snapshot.objects.create(
        url="https://example.com/article",
        title="Research paper",
        crawl=crawl,
        config={"PERMISSIONS": "public"},
    )
    Snapshot.objects.create(url="https://example.com/secret", title="Research secret", crawl=crawl, config={"PERMISSIONS": "private"})
    Snapshot.objects.create(url="https://example.com/unrelated", title="Other", crawl=crawl, config={"PERMISSIONS": "public"})
    response = admin_client.post(
        "/admin/feeds/export/?q=Research&search_mode=meta",
        {"name": "Research reading list"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    feed = SavedFeed.objects.get(name="Research reading list")
    client = Client()
    response = client.get(feed.get_absolute_url(), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert str(visible.pk).encode() in response.content
    assert b"Research secret" not in response.content and b"Other" not in response.content
    assert admin_client.post(f"/admin/feeds/{feed.pk}/revoke/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
    assert client.get(feed.get_absolute_url(), HTTP_HOST=ADMIN_TEST_HOST).status_code == 404


def test_subscribe_creates_real_scheduled_importer(admin_client):
    from archivebox.importers.models import ImporterSource

    response = admin_client.post(
        "/admin/feeds/",
        {
            "name": "Hacker News",
            "url": "https://news.ycombinator.com/rss",
            "schedule": "daily",
            "tags": "news",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get(name="Hacker News")
    assert source.plugin == "importer_rss" and source.feed == "feed"
    assert source.settings == {"IMPORTER_RSS_URL": "https://news.ycombinator.com/rss"}
    assert source.schedule == "0 0 * * *" and source.next_run_at is not None


def test_rsshub_route_is_on_selected_server(admin_client):
    from archivebox.importers.models import ImporterSource

    response = admin_client.post(
        "/admin/feeds/",
        {
            "name": "Custom bridge",
            "url": "https://rss.example.org/base/",
            "rsshub_route": "/github/issue/ArchiveBox/ArchiveBox",
            "schedule": "hourly",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    assert (
        ImporterSource.objects.get(name="Custom bridge").settings["IMPORTER_RSS_URL"]
        == "https://rss.example.org/base/github/issue/ArchiveBox/ArchiveBox"
    )


def test_rsshub_route_preserves_server_path_and_query(admin_client):
    from archivebox.importers.models import ImporterSource

    response = admin_client.post(
        "/admin/feeds/",
        {
            "name": "Bridge with query",
            "url": "https://rss.example.org/base/?key=reader#section",
            "rsshub_route": "/github/issue/ArchiveBox/ArchiveBox?limit=10",
            "schedule": "",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    source = ImporterSource.objects.get()
    assert source.settings["IMPORTER_RSS_URL"] == "https://rss.example.org/base/github/issue/ArchiveBox/ArchiveBox?key=reader&limit=10"
    assert source.schedule == "" and source.next_run_at is None


@pytest.mark.parametrize("route", ["https://[", "//outside.example/feed", "../outside"])
def test_rsshub_invalid_route_is_a_form_error(admin_client, route):
    from archivebox.importers.models import ImporterSource

    response = admin_client.post(
        "/admin/feeds/",
        {
            "name": "Invalid route",
            "url": "https://rss.example.org/",
            "rsshub_route": route,
            "schedule": "",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert response.context["form"].errors["rsshub_route"]
    assert not ImporterSource.objects.exists()


def test_feed_configuration_requires_admin(client):
    response = client.get("/admin/feeds/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302


def test_impossible_feed_schedule_is_a_form_error(admin_client):
    from archivebox.importers.models import ImporterSource

    response = admin_client.post(
        "/admin/feeds/",
        {
            "name": "Impossible schedule",
            "url": "https://news.ycombinator.com/rss",
            "schedule": "0 0 31 2 *",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert response.context["form"].errors["schedule"]
    assert not ImporterSource.objects.exists()


@pytest.mark.parametrize("include_private", [False, True])
def test_saved_feed_permissions_and_owner_revocation(admin_client, admin_user, include_private):
    from xml.etree import ElementTree
    from django.test import Client

    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.feeds.models import SavedFeed

    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    for visibility in ("public", "unlisted", "private"):
        Snapshot.objects.create(
            url=f"https://example.com/{visibility}",
            title=f"Story {visibility}",
            crawl=crawl,
            config={"PERMISSIONS": visibility},
        )
    payload = {"name": "Permission checks", **({"include_private": "on"} if include_private else {})}
    response = admin_client.post("/admin/feeds/export/", payload, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 302
    feed = SavedFeed.objects.get()
    client = Client()
    response = client.get(feed.get_absolute_url(), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    titles = {item.findtext("title") for item in ElementTree.fromstring(response.content).findall("./channel/item")}
    assert titles == ({"Story public", "Story unlisted", "Story private"} if include_private else {"Story public"})
    assert response["Cache-Control"] == "private, no-store"
    assert response["Referrer-Policy"] == "no-referrer"
    admin_user.is_superuser = False
    admin_user.save(update_fields=["is_superuser"])
    assert client.get(feed.get_absolute_url(), HTTP_HOST=ADMIN_TEST_HOST).status_code == 404


def test_feed_configuration_rejects_view_only_staff(client, django_user_model):
    user = django_user_model.objects.create_user("feed-viewer", password="testpassword", is_staff=True)
    client.force_login(user)
    for path in ("/admin/feeds/", "/admin/feeds/export/"):
        assert client.get(path, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
        assert client.post(path, {"name": "Unauthorized"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403


def test_feed_list_prefetches_only_latest_run(admin_client, admin_user, django_assert_num_queries):
    from archivebox.importers.models import ImporterRun, ImporterSource

    sources = [ImporterSource.objects.create(name=f"Feed {i}", created_by=admin_user, plugin="importer_rss", feed="feed") for i in range(3)]
    latest_ids = []
    for source in sources:
        ImporterRun.objects.create(source=source, status="succeeded", message="Old success")
        latest_ids.append(ImporterRun.objects.create(source=source, status="failed", message="Feed returned HTTP 503").pk)
    response = admin_client.get("/admin/feeds/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    with django_assert_num_queries(0):
        displayed = list(response.context["sources"])
        assert [source.latest_runs[0].pk for source in displayed] == latest_ids
        assert all(len(source.latest_runs) == 1 for source in displayed)
    assert response.content.count(b'class="feed-badge feed-status-failed">Failed</span>') == 3
    assert b"Not fetched yet" not in response.content


@pytest.mark.django_db(transaction=True)
def test_browser_subscribe_with_only_name_and_url(live_server, admin_user, browser_runtime):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from archivebox.importers.models import ImporterSource
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/feeds/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        expect(page.locator(".feeds h1")).to_have_text("Feeds")
        page.locator("#id_name").fill("Hacker News daily")
        page.locator("#id_url").fill("https://news.ycombinator.com/rss")
        expect(page.locator("#id_schedule")).not_to_be_visible()
        page.get_by_role("button", name="Save feed", exact=False).click()
        expect(page.get_by_role("heading", name="Hacker News daily", exact=True)).to_be_visible()
        browser.close()
    source = ImporterSource.objects.get(name="Hacker News daily")
    assert source.settings == {"IMPORTER_RSS_URL": "https://news.ycombinator.com/rss"}
    assert source.schedule == "0 0 * * *"
    assert source.next_run_at is not None


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("import_tags", [False, True])
def test_real_feed_categories_reach_only_their_snapshot(admin_client, import_tags, tmp_path):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from archivebox.importers.models import ImporterSource
    from archivebox.importers.service import run_next_importer

    (tmp_path / "feed.xml").write_text(
        '<rss version="2.0"><channel><title>Categories</title><item><guid>one</guid><link>https://example.com/tagged</link><category>Science &amp; Society</category><category>Technology</category></item><item><guid>two</guid><link>https://example.com/untagged</link></item></channel></rss>',
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = admin_client.post(
            "/admin/feeds/",
            {
                "name": "Categories",
                "url": f"http://127.0.0.1:{server.server_port}/feed.xml",
                "tags": "Manual source tag",
                **({"import_tags": "on"} if import_tags else {}),
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        )
        assert response.status_code == 302
        source = ImporterSource.objects.get(name="Categories")
        assert source.settings.get("IMPORTER_RSS_IMPORT_TAGS", False) is import_tags
        assert admin_client.post(f"/admin/importers/{source.pk}/import/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
        assert run_next_importer()
        run = source.runs.get()
        assert run.status == "succeeded", run.message
        assert run.crawl_id
        assert run.items[0]["metadata"].get("tags", []) == (["Science & Society", "Technology"] if import_tags else []), run.items
        assert ("Science &amp; Society" in run.crawl.urls) is import_tags, run.crawl.urls
        snapshots = run.crawl.create_snapshots_from_urls()
        assert len(snapshots) == 2
        # Match the existing native Tag sanitizer (HTML entities remain escaped in stored names).
        tags = {snapshot.url: set(snapshot.tags.values_list("name", flat=True)) for snapshot in snapshots}
        assert tags["https://example.com/tagged"] == (
            {"Science &amp; Society", "Technology", "Manual source tag"} if import_tags else {"Manual source tag"}
        )
        assert tags["https://example.com/untagged"] == {"Manual source tag"}
        if not import_tags:
            assert run.crawl.urls == "https://example.com/tagged\nhttps://example.com/untagged"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
