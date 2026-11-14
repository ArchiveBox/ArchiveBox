"""Shared derived exports through real API requests and CLI subprocesses."""

import csv
import gzip
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlencode
from xml.etree import ElementTree

import pytest
from django.contrib.auth import get_user_model

from archivebox.core.models import ArchiveResult, Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST, API_TEST_HOST, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def exported_ids(response, format):
    if format == "rss":
        return {item.findtext("guid") for item in ElementTree.fromstring(response.content).findall("./channel/item")}
    if format == "csv":
        return {row["id"] for row in csv.DictReader(io.StringIO(response.content.decode()))}
    return {json.loads(line)["id"] for line in response.content.splitlines()}


@pytest.mark.parametrize("format", ["rss", "csv", "jsonl"])
def test_api_and_list_exports_share_selection_and_permissions(client, admin_client, api_admin_user, api_headers, format):
    folder = Folder.objects.create(name="Research", created_by=api_admin_user)
    child = Folder.objects.create(name="Articles", parent=folder, created_by=api_admin_user)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=api_admin_user)
    visible = Snapshot.objects.create(
        url="https://news.ycombinator.com/",
        title="quartzneedle public",
        crawl=crawl,
        folder=child,
        config={"PERMISSIONS": "public"},
    )
    private = Snapshot.objects.create(
        url="https://news.ycombinator.com/newest",
        title="quartzneedle private",
        crawl=crawl,
        folder=child,
        config={"PERMISSIONS": "private"},
    )
    unlisted = Snapshot.objects.create(
        url="https://news.ycombinator.com/hidden",
        title="quartzneedle unlisted",
        crawl=crawl,
        folder=child,
        config={"PERMISSIONS": "unlisted"},
    )
    Snapshot.objects.create(
        url="https://news.ycombinator.com/ask",
        title="Other public",
        crawl=crawl,
        folder=child,
        config={"PERMISSIONS": "public"},
    )
    Snapshot.objects.create(
        url="https://news.ycombinator.com/show",
        title="quartzneedle unfiled",
        crawl=crawl,
        config={"PERMISSIONS": "public"},
    )
    query = {"folder": str(folder.pk), "q": "quartzneedle", "p": "9", "search_mode": "meta"}
    api_url = f"/api/v1/core/snapshots/export/{format}"
    web_url = f"/admin/core/snapshot/export.{format}"
    for http_client, url, headers, expected in (
        (client, api_url, {"HTTP_HOST": API_TEST_HOST}, {str(visible.pk)}),
        (admin_client, web_url, {"HTTP_HOST": ADMIN_TEST_HOST}, {str(visible.pk), str(private.pk), str(unlisted.pk)}),
    ):
        response = http_client.get(url, query, **headers)
        assert response.status_code == 200, response.content
        assert exported_ids(response, format) == expected
        assert "no-store" in response["Cache-Control"]
    keyed = client.get(api_url, query, **api_headers)
    assert keyed.status_code == 200, keyed.content
    assert exported_ids(keyed, format) == {str(visible.pk), str(private.pk), str(unlisted.pk)}
    for http_client, url, headers in ((admin_client, web_url, {"HTTP_HOST": ADMIN_TEST_HOST}), (client, api_url, api_headers)):
        response = http_client.get(url, {**query, "public_only": "1"}, **headers)
        assert response.status_code == 200
        assert exported_ids(response, format) == {str(visible.pk)}
    invalid = admin_client.get(api_url, {**query, "api_key": "invalid"}, HTTP_HOST=API_TEST_HOST)
    assert invalid.status_code == 401
    assert client.get(api_url, {"config__icontains": "private"}, HTTP_HOST=API_TEST_HOST).status_code == 400


def test_list_exports_reuse_query_and_writers_with_native_cli_filters(initialized_archive, tmp_path):
    captures = Path(__file__).parent / "fixtures/original-domain-replay"
    records = json.loads((captures / "captures.json").read_text())
    with use_archivebox_db(initialized_archive):
        user = get_user_model().objects.create_user(username="derived-export-cli")
        folder = Folder.objects.create(name="Saved news", created_by=user)
        child = Folder.objects.create(name="Recent", parent=folder, created_by=user)
        crawl = Crawl.objects.create(urls="\n".join(record["url"] for record in records), created_by=user)
        for record in records:
            body = gzip.decompress((captures / record["file"]).read_bytes())
            snapshot = Snapshot.objects.create(url=record["url"], title="Hacker News", crawl=crawl, folder=child)
            file = snapshot.output_dir / "dom/output.html"
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(body)
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="dom",
                hook_name="on_Snapshot__53_dom.js",
                status="succeeded",
                output_str="dom/output.html",
                output_files={"dom/output.html": {"size": len(body)}},
                output_size=len(body),
            )
        query = urlencode({"folder": str(folder.pk), "q": "Hacker News", "search_mode": "meta"})
        expected = str(Snapshot.objects.filter(folder=child).order_by("url").first().pk)
    base = ["list", "--export-query", query, "--sort", "url", "--limit", "1"]
    for format in ("rss", "csv", "jsonl"):
        output = tmp_path / f"snapshots.{format}"
        result = run_archivebox_cmd([*base, "--format", format, "--output", str(output)], timeout=30)
        assert result.returncode == 0, result.stderr
        if format == "rss":
            assert [item.findtext("guid") for item in ElementTree.fromstring(output.read_bytes()).findall("./channel/item")] == [expected]
        else:
            rows = (
                list(csv.DictReader(io.StringIO(output.read_text())))
                if format == "csv"
                else [json.loads(line) for line in output.read_text().splitlines()]
            )
            assert [row["id"] for row in rows] == [expected]
            assert "config" not in rows[0] and "notes" not in rows[0]
    destination = tmp_path / "compiled"
    result = run_archivebox_cmd([*base, "--format", "html_zip", "--output", str(destination)], timeout=30)
    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(destination / "site.zip") as bundle:
        manifest = json.loads(bundle.read("pages.json"))
        assert len(manifest) == 1
        assert expected in manifest[0]["path"]
        assert b"Hacker News" in bundle.read(manifest[0]["path"])


@pytest.mark.parametrize("view", ["admin", "public"])
def test_streamed_search_updates_live_export_links(live_server, admin_user, browser_runtime, settings, view):
    import re
    from urllib.parse import parse_qs, urlsplit
    from playwright.sync_api import sync_playwright, expect
    from archivebox.machine.models import Machine

    base_url = f"http://archivebox.localhost:{urlsplit(live_server.url).port}"
    settings.CONFIG = settings.CONFIG.model_copy(update={"BASE_URL": base_url, "PUBLIC_INDEX": True})
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base_url, "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    parent = Folder.objects.create(name="Research", created_by=admin_user)
    child = Folder.objects.create(name="Articles", parent=parent, created_by=admin_user)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    for path, title in [("newest", "quartzneedle"), ("show", "zirconneedle")]:
        Snapshot.objects.create(
            url=f"https://news.ycombinator.com/{path}",
            title=title,
            crawl=crawl,
            folder=child,
            config={"PERMISSIONS": "public"},
        )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        admin_url = base_url.replace("//archivebox", "//admin.archivebox")
        if view == "admin":
            page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            url = f"{admin_url}/admin/core/snapshot/?folder={child.pk}"
        else:
            url = base_url.replace("//archivebox", "//web.archivebox") + f"/public/?folder={child.pk}"
        assert page.goto(url).status == 200
        expect(page.locator("#folder-sidebar .folder-actions a[data-export-format]")).to_have_count(6 if view == "admin" else 5)
        menu = page.locator(f"#folder-menu-{parent.pk}")
        menu_link = menu.locator('a[data-export-format="jsonl"]')
        existing_link = menu_link.element_handle()
        for query in ("quartzneedle", "zirconneedle"):
            page.locator('#changelist-search [name="search_mode"]').select_option("meta")
            page.locator('#changelist-search [name="q"]').fill(query)
            page.locator('#changelist-search [name="q"]').press("Enter")
            expect(menu_link).to_have_attribute("href", re.compile(r"[?&]q=" + query + r"(?:&|$)"))
            assert existing_link.evaluate("node => node.isConnected")
            page.locator(f'.folder-row[data-folder-id="{parent.pk}"]').hover()
            page.get_by_role("button", name="Actions for Research", exact=True).click()
            expect(menu).to_be_visible()
            for link in page.locator("a[data-export-format]").all():
                parsed = parse_qs(urlsplit(link.get_attribute("href")).query)
                assert parsed.get("q") == [query], link.evaluate("node => node.outerHTML")
                assert parsed["search_mode"] == ["meta"]
            parsed = parse_qs(urlsplit(menu_link.get_attribute("href")).query)
            assert parsed["folder"] == [str(parent.pk)]
            ordinary = page.locator('.folder-actions a[data-export-format="jsonl"]').first
            parsed = parse_qs(urlsplit(ordinary.get_attribute("href")).query)
            assert parsed["folder"] == [str(child.pk)]
            response = ordinary.evaluate(
                "async node => { const response = await fetch(node.href); return {status: response.status, text: await response.text()}; }",
            )
            assert response["status"] == 200
            assert [json.loads(line)["title"] for line in response["text"].splitlines()] == [query]
            page.keyboard.press("Escape")
        browser.close()


@pytest.mark.parametrize("format", ["rss", "csv", "jsonl"])
def test_smart_folder_exports_keep_visibility_and_extra_filters(client, api_headers, api_admin_user, format):
    from archivebox.tests.test_smart_folders import leaf
    from archivebox.tests.conftest import API_TEST_HOST

    inbox_rules = {"op": "NOT", "rules": [{"field": "folder", "lookup": "in_folder", "value": "*"}]}

    folder = Folder.objects.create(name="News", rules=leaf("domain", "exact", "news.ycombinator.com"))
    hidden = Folder.objects.create(name="Private matches", rules=leaf("title", "exact", "secret"))
    inbox = Folder.objects.filter(rules=inbox_rules).first() or Folder.objects.create(name="📥 Inbox", rules=inbox_rules)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=api_admin_user)
    public = Snapshot.objects.create(url=crawl.urls, title="news", crawl=crawl, config={"PERMISSIONS": "public"})
    private = Snapshot.objects.create(
        url="https://news.ycombinator.com/newest",
        title="secret",
        crawl=crawl,
        config={"PERMISSIONS": "private"},
    )
    visible = {entry.pk for entry in Folder.tree(public=True)}
    assert folder.pk in visible and inbox.pk in visible and hidden.pk not in visible
    url = f"/api/v1/core/snapshots/export/{format}"
    response = client.get(url, {"folder": str(folder.pk)}, HTTP_HOST=API_TEST_HOST)
    assert response.status_code == 200, response.content
    assert exported_ids(response, format) == {str(public.pk)}
    response = client.get(url, {"folder": str(folder.pk)}, **api_headers)
    assert response.status_code == 200
    assert exported_ids(response, format) == {str(public.pk), str(private.pk)}
    response = client.get(url, {"folder": str(folder.pk), "url__icontains": "newest"}, **api_headers)
    assert exported_ids(response, format) == {str(private.pk)}


@pytest.mark.parametrize("format", ["html_zip", "wacz", "html", "replay"])
def test_authorized_archive_export_scope_includes_private_and_unlisted(client, admin_client, admin_user, format):
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    for visibility in ("public", "unlisted", "private"):
        Snapshot.objects.create(url=f"https://example.com/{visibility}", crawl=crawl, config={"PERMISSIONS": visibility})
    url = f"/admin/core/snapshot/export.{format}"
    response = admin_client.get(url, {"crawl_id": str(crawl.pk)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.json()["count"] == 3
    from django.test import Client

    public = Client().get(url, {"crawl_id": str(crawl.pk)}, HTTP_HOST=ADMIN_TEST_HOST)
    if format in {"html", "replay"}:
        assert public.status_code == 403
    else:
        assert public.status_code == 200
        assert public.json()["count"] == 1


@pytest.mark.parametrize("surface", ["users", "importer-run"])
def test_export_controls_preserve_request_and_csrf_context(admin_user, surface):
    import re
    from html import unescape
    from django.test import Client
    from django.urls import reverse
    from archivebox.importers.models import ImporterSource, ImporterRun

    client = Client(enforce_csrf_checks=True)
    client.force_login(admin_user)
    if surface == "users":
        response = client.get(reverse("admin:auth_user_changelist"), HTTP_HOST=ADMIN_TEST_HOST)
        body = response.content.decode()
    else:
        crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
        source = ImporterSource.objects.create(name="Export source", plugin="importer_rss", feed="feed", created_by=admin_user)
        run = ImporterRun.objects.create(source=source, crawl=crawl, status="succeeded")
        response = client.get(reverse("importers:run-activity", args=[run.pk]), HTTP_HOST=ADMIN_TEST_HOST)
        body = response.json()["html"]
    assert response.status_code == 200
    controls = re.search(r'<span class="snapshot-export-links[^>]*>', body).group()
    assert 'data-export-session="1"' in controls
    csrf = re.search(r'data-export-csrf="([^"]+)"', controls).group(1)
    assert csrf and csrf != "NOTPROVIDED"
    url = unescape(re.search(r'href="([^"]+)" data-export-format="html_zip"', body).group(1))
    post = {"session": "1", "directory": "relative/path", "format": "html_zip"}
    assert client.post(url, post, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    response = client.post(url, post, HTTP_HOST=ADMIN_TEST_HOST, HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 400
    assert b"absolute server directory" in response.content


def test_private_feed_url_uses_revocable_existing_key_and_public_feed_stays_public(admin_client, admin_user):
    import re
    from html import unescape
    from urllib.parse import parse_qs, urlsplit
    from django.test import Client
    from archivebox.api.models import APIToken

    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    snapshots = {
        visibility: Snapshot.objects.create(url=f"https://example.com/{visibility}", crawl=crawl, config={"PERMISSIONS": visibility})
        for visibility in ("public", "unlisted", "private")
    }
    response = admin_client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    body = response.content.decode()
    urls = {format: unescape(url) for url, format in re.findall(r'href="([^"]+)" data-export-format="(rss|rss_public)"', body)}
    assert set(urls) == {"rss", "rss_public"}
    key = parse_qs(urlsplit(urls["rss"]).query)["api_key"][0]
    token = APIToken.objects.get(token=key, created_by=admin_user)
    assert "api_key" not in parse_qs(urlsplit(urls["rss_public"]).query)
    external_reader = Client()
    feed = external_reader.get(urls["rss"], HTTP_HOST=ADMIN_TEST_HOST)
    assert feed.status_code == 200
    assert exported_ids(feed, "rss") == {str(snapshot.pk) for snapshot in snapshots.values()}
    assert key.encode() not in feed.content
    assert feed["Referrer-Policy"] == "no-referrer"
    for http_client in (admin_client, external_reader):
        public = http_client.get(urls["rss_public"], HTTP_HOST=ADMIN_TEST_HOST)
        assert public.status_code == 200
        assert exported_ids(public, "rss") == {str(snapshots["public"].pk)}
        assert b"public_only=1" in public.content
    token.delete()
    assert external_reader.get(urls["rss"], HTTP_HOST=ADMIN_TEST_HOST).status_code == 401


def test_folder_export_defaults_to_configured_content_search(admin_client, admin_user, cached_abxpkg_lib_dir):
    from archivebox.tests.test_search import configure_ripgrep_search_backend

    configure_ripgrep_search_backend(cached_abxpkg_lib_dir)
    folder = Folder.objects.create(name="Content search", created_by=admin_user)
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, title="Unrelated title", crawl=crawl, folder=folder)
    output = snapshot.output_dir / "dom/output.html"
    output.parent.mkdir(parents=True)
    output.write_text("<!doctype html><p>folderdeepneedle</p>")
    response = admin_client.get(
        "/admin/core/snapshot/export.jsonl",
        {"folder": str(folder.pk), "q": "folderdeepneedle"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert exported_ids(response, "jsonl") == {str(snapshot.pk)}


def test_private_feed_warning_precedes_navigation_and_public_feed_needs_no_warning(live_server, admin_user, browser_runtime, settings):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright
    from archivebox.machine.models import Machine

    base_url = f"http://archivebox.localhost:{urlsplit(live_server.url).port}"
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base_url, "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    settings.CONFIG = settings.CONFIG.model_copy(update={"BASE_URL": base_url, "PUBLIC_INDEX": True})
    admin_url = base_url.replace("//archivebox", "//admin.archivebox")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page()
            page.goto(f"{admin_url}/admin/login/?next=/admin/auth/user/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.wait_for_url(f"{admin_url}/admin/auth/user/")
            dialogs = []

            def accept_warning(dialog):
                dialogs.append(dialog.message)
                assert "full administrator access" in dialog.message
                assert "admin password" in dialog.message
                assert "outside this feed" in dialog.message
                dialog.accept()

            page.on("dialog", accept_warning)
            private = page.locator('a[data-export-format="rss"]').first
            assert "api_key=" in private.get_attribute("href")
            private.click(button="right")
            assert len(dialogs) == 1
            page.keyboard.press("Escape")
            with page.expect_navigation() as opened:
                private.click()
            assert opened.value.status == 200
            assert len(dialogs) == 2
            page.go_back()
            with page.expect_navigation() as opened:
                page.locator('a[data-export-format="rss_public"]').first.click()
            assert opened.value.status == 200
            assert "api_key=" not in page.url
            assert len(dialogs) == 2
            page = browser.new_page()
            page.goto(base_url.replace("//archivebox", "//web.archivebox") + "/public/")
            assert page.locator("[data-private-feed]").count() == 0
            assert page.locator('a[data-export-format="rss_public"]').count() > 0
        finally:
            browser.close()


@pytest.mark.parametrize("surface", ["folders", "users"])
def test_private_feed_keys_are_resolved_once_per_render(admin_client, admin_user, surface):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.api.auth import get_or_create_api_token

    get_or_create_api_token(admin_user)
    if surface == "folders":
        for index in range(20):
            Folder.objects.create(name=f"Export folder {index}", created_by=admin_user)
        endpoint = "/admin/core/snapshot/"
    else:
        for index in range(20):
            get_user_model().objects.create_user(username=f"export-owner-{index}")
        endpoint = "/admin/auth/user/"
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get(endpoint, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.content.count(b'data-private-feed="1"') >= 20
    key_queries = [query["sql"] for query in queries if 'FROM "api_apitoken"' in query["sql"]]
    assert len(key_queries) == 2


def test_public_folder_export_links_keep_default_content_search(admin_user, cached_abxpkg_lib_dir, settings):
    from django.test import Client
    from urllib.parse import parse_qs, urlsplit
    from archivebox.machine.models import Machine
    from archivebox.tests.conftest import WEB_TEST_HOST
    from archivebox.tests.test_search import configure_ripgrep_search_backend, consume_streaming_response

    configure_ripgrep_search_backend(cached_abxpkg_lib_dir)
    settings.CONFIG = settings.CONFIG.model_copy(update={"PUBLIC_INDEX": True})
    machine = Machine.current()
    machine.config = {**machine.config, "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    folder = Folder.objects.create(name="Public content", created_by=admin_user)
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    snapshots = []
    for visibility in ("public", "private"):
        snapshot = Snapshot.objects.create(
            url=f"https://example.com/{visibility}",
            title="Unrelated title",
            crawl=crawl,
            folder=folder,
            config={"PERMISSIONS": visibility},
        )
        output = snapshot.output_dir / "dom/output.html"
        output.parent.mkdir(parents=True)
        output.write_text("<!doctype html><p>publicfolderdeepneedle</p>")
        snapshots.append(snapshot)
    client = Client()
    query = {"q": "publicfolderdeepneedle", "folder": str(folder.pk)}
    stream = client.get("/public/search-stream/", {**query, "search_url": "/public/?" + urlencode(query)}, HTTP_HOST=WEB_TEST_HOST)
    assert stream.status_code == 200
    assert consume_streaming_response(stream)
    response = client.get("/public/", query, HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert [snapshot.pk for snapshot in response.context["object_list"]] == [snapshots[0].pk]
    exported_folder = next(entry for entry in response.context["folder_tree"] if entry.pk == folder.pk)
    url = exported_folder.export_urls["jsonl"]
    assert parse_qs(urlsplit(url).query)["search_mode"] == ["deep:ripgrep"]
    exported = client.get(url, HTTP_HOST=API_TEST_HOST)
    assert exported.status_code == 200
    assert exported_ids(exported, "jsonl") == {str(snapshots[0].pk)}
