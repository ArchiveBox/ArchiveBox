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
from django.test import Client

from archivebox.core.models import ArchiveResult, Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST, API_TEST_HOST, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db
from archivebox.tests.export_helpers import export_action_urls

pytestmark = pytest.mark.django_db(transaction=True)


def exported_ids(response, format):
    return exported_body_ids(response.getvalue(), format)


def exported_body_ids(body, format):
    if format == "rss":
        return {item.findtext("guid") for item in ElementTree.fromstring(body).findall("./channel/item")}
    if format == "csv":
        return {row["id"] for row in csv.DictReader(io.StringIO(body.decode()))}
    return {json.loads(line)["id"] for line in body.splitlines()}


@pytest.mark.parametrize("format", ["rss", "csv", "jsonl"])
def test_api_and_list_exports_share_selection_and_permissions(admin_client, api_admin_user, api_headers, format):
    # admin_client authenticates the shared client fixture. Public exports need
    # a separate cookie jar now that API exports also honor browser sessions.
    client = Client()
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
        (admin_client, api_url, {"HTTP_HOST": API_TEST_HOST}, {str(visible.pk), str(private.pk), str(unlisted.pk)}),
        (admin_client, web_url, {"HTTP_HOST": ADMIN_TEST_HOST}, {str(visible.pk), str(private.pk), str(unlisted.pk)}),
    ):
        response = http_client.get(url, query, **headers)
        assert response.status_code == 200
        assert exported_ids(response, format) == expected
        assert "no-store" in response["Cache-Control"]
    keyed = client.get(api_url, query, **api_headers)
    assert keyed.status_code == 200
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


@pytest.mark.parametrize("view", ["admin", "public", "public-early-open"])
def test_streamed_search_updates_live_export_links(live_server, admin_user, browser_runtime, settings, view):
    import re
    from urllib.parse import parse_qs, quote_plus, urlsplit
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
        if view == "public-early-open":
            page.add_init_script("""(() => {
                const observer = new MutationObserver(() => {
                    const menu = document.getElementById('snapshot-export-menu-sidebar');
                    if (!menu?.querySelector('a[data-export-format]')) return;
                    observer.disconnect();
                    menu.dataset.moduleLoadedOnOpen = String(Boolean(window.archiveboxExportURL));
                    document.querySelector('[popovertarget="snapshot-export-menu-sidebar"]').click();
                });
                observer.observe(document, {childList: true, subtree: true});
            })()""")
        response = page.goto(url)
        assert response.status == 200
        export_action_urls(response.text(), public=view != "admin")
        if view == "public":
            expect(page.locator("a[data-export-format][href]")).to_have_count(0)
        if view == "public-early-open":
            early_menu = page.locator("#snapshot-export-menu-sidebar")
            expect(early_menu).to_have_attribute("data-module-loaded-on-open", "false")
            expect(early_menu).to_be_visible()
            expect(early_menu.locator("a[data-export-format][href]")).to_have_count(5)
            page.keyboard.press("Escape")
        expect(page.locator("#folder-sidebar .folder-actions a[data-export-format]")).to_have_count(6 if view == "admin" else 5)
        menu = page.locator(f"#folder-menu-{parent.pk}")
        menu_link = menu.locator('a[data-export-format="jsonl"]')
        existing_link = menu_link.element_handle()
        for term in ("quartzneedle", "zirconneedle"):
            query = f"title:{term}"
            field = page.locator('#changelist-search [role="combobox"]')
            field.fill(query)
            field.press("Escape")
            field.press("Enter")
            expect(menu_link).to_have_attribute("data-export-query", re.compile(r"(?:^|&)q=" + re.escape(quote_plus(query)) + r"(?:&|$)"))
            assert existing_link.evaluate("node => node.isConnected")
            page.locator(f'.folder-row[data-folder-id="{parent.pk}"]').hover()
            page.get_by_role("button", name="Actions for Research", exact=True).click()
            expect(menu).to_be_visible()
            assert menu.locator("a[data-export-format]:not([href])").count() == 0
            copy_link = menu.get_by_role("menuitem", name="RSS (Private)", exact=True) if view == "admin" else menu_link
            copy_url = copy_link.evaluate("link => link.href")
            copy_link.evaluate("""link => link.addEventListener('contextmenu', event => {
                link.dataset.contextHref = event.target.closest('a[href]')?.href || '';
                event.preventDefault();
            }, {once: true})""")
            copy_link.click(button="right")
            expect(copy_link).to_have_attribute("data-context-href", copy_url)
            for link in page.locator("a[data-export-format]").all():
                parsed = parse_qs(link.get_attribute("data-export-query"))
                assert parsed.get("q") == [query], link.evaluate("node => node.outerHTML")
                assert parsed["search_mode"] == ["query"]
            parsed = parse_qs(urlsplit(menu_link.get_attribute("href")).query)
            assert parsed["folder"] == [str(parent.pk)]
            ordinary = page.locator('.folder-actions a[data-export-format="jsonl"]').first
            parsed = parse_qs(ordinary.get_attribute("data-export-query"))
            assert parsed["folder"] == [str(child.pk)]
            direct_url = menu_link.get_attribute("href")
            with page.expect_download() as download:
                menu_link.press("Enter")
            assert download.value.failure() is None
            content = Path(download.value.path()).read_bytes()
            assert [json.loads(line)["title"] for line in content.splitlines()] == [term]
            direct = page.request.get(direct_url)
            assert direct.status == 200
            assert direct.body() == content
            page.keyboard.press("Escape")
        browser.close()


def test_sidebar_exports_follow_live_search_filters_and_order(live_server, admin_user, browser_runtime, settings):
    from urllib.parse import parse_qs, urlsplit
    from playwright.sync_api import sync_playwright, expect

    from archivebox.machine.models import Machine

    base_url = f"http://archivebox.localhost:{urlsplit(live_server.url).port}"
    settings.CONFIG = settings.CONFIG.model_copy(update={"BASE_URL": base_url})
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base_url}
    machine.save(update_fields=["config"])
    folder = Folder.objects.create(name="Export Research", created_by=admin_user)
    crawl = Crawl.objects.create(urls="https://export.example/", created_by=admin_user)
    for path, title, status, tagged in (
        ("z", "quartzneedle Zulu", Snapshot.StatusChoices.SEALED, True),
        ("a", "quartzneedle Alpha", Snapshot.StatusChoices.SEALED, True),
        ("queued", "quartzneedle Queued", Snapshot.StatusChoices.QUEUED, True),
        ("untagged", "quartzneedle Untagged", Snapshot.StatusChoices.SEALED, False),
        ("nomatch", "Other result", Snapshot.StatusChoices.SEALED, True),
    ):
        snapshot = Snapshot.objects.create(
            url=f"https://export.example/{path}",
            title=title,
            crawl=crawl,
            folder=folder,
            status=status,
        )
        if tagged:
            snapshot.save_tags(["export tag"])
    tag_id = str(Snapshot.objects.get(url="https://export.example/a").tags.get(name="export tag").pk)
    selection = {"folder": str(folder.pk), "tag": tag_id, "domain": "export.example", "snapshot_status": "sealed"}
    expected = ["quartzneedle Alpha", "quartzneedle Zulu"]
    admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        assert page.goto(f"{admin_url}/admin/core/snapshot/?{urlencode(selection)}").status == 200
        sort_link = page.locator("th.column-title_str .text a")
        with page.expect_navigation():
            sort_link.click()
        assert parse_qs(urlsplit(page.url).query)["o"]

        previous_query = None
        for i, (mode, label, trigger) in enumerate(
            (("folders", "Folders", "Export Research"), ("tags", "Tags", "export tag"), ("domains", "Domains", "export.example")),
        ):
            if i:
                page.get_by_role("button", name="Choose sidebar view").click()
                with page.expect_navigation():
                    page.locator("#library-mode-menu").get_by_role("menuitem", name=label, exact=True).click()
            expect(page.locator("#folder-sidebar")).to_have_attribute("data-mode", mode)
            if previous_query:
                params = parse_qs(urlsplit(page.url).query)
                assert params["q"] == [previous_query]
                assert params["o"]
                assert all(params.get(key) == [value] for key, value in selection.items())

            # Re-submit via the real stream on every mode, after its menu was initialized.
            query = ("title:quartzneedle", 'title:"quartzneedle"', "title:quartzneedle OR title:zirconneedle")[i]
            field = page.locator('#changelist-search [role="combobox"]')
            field.fill(query)
            field.press("Escape")
            field.press("Enter")
            expect(page.locator("#result_list tbody .field-title_str")).to_contain_text(expected)
            expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")

            page.locator("#folder-sidebar .folder-mobile-toggle").click()
            page.locator('button[popovertarget="snapshot-export-menu-list"]').click()
            page.keyboard.press("Escape")
            page.locator(".folder-sidebar-reopen").click()
            footer = page.locator("#snapshot-export-menu-sidebar")
            page.locator('#folder-sidebar button[popovertarget="snapshot-export-menu-sidebar"]').click()
            expect(footer).to_be_visible()
            page.keyboard.press("Escape")
            menu = page.locator(f"#folder-menu-{folder.pk}" if mode == "folders" else "#library-entry-menu")
            entry_button = page.get_by_role("button", name=f"Actions for {trigger}", exact=True)
            page.locator(".folder-row,.library-entry").filter(has=entry_button).hover()
            entry_button.click()
            expect(menu).to_be_visible()
            for group in (footer, page.locator("#snapshot-export-menu-list"), menu):
                link = group.locator('a[data-export-format="jsonl"]')
                params = parse_qs(urlsplit(link.get_attribute("href")).query)
                assert {key: params[key] for key in selection} == {key: [value] for key, value in selection.items()}
                assert params["q"] == [query]
                assert params["search_mode"] == ["query"]
                assert params["sort"] == ["title,-created_at,-id"]
                assert "o" not in params and "api_key" not in params
                response = page.request.get(link.evaluate("node => node.href"))
                assert response.status == 200
                assert [json.loads(line)["title"] for line in response.text().splitlines()] == expected
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
    assert response.status_code == 200
    assert exported_ids(response, format) == {str(public.pk)}
    response = client.get(url, {"folder": str(folder.pk)}, **api_headers)
    assert response.status_code == 200
    assert exported_ids(response, format) == {str(public.pk), str(private.pk)}
    response = client.get(url, {"folder": str(folder.pk), "url__icontains": "newest"}, **api_headers)
    assert exported_ids(response, format) == {str(private.pk)}


@pytest.mark.parametrize("format", ["html_zip", "wacz", "html"])
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
    if format == "html":
        assert public.status_code == 403
    else:
        assert public.status_code == 200
        assert public.json()["count"] == 1


@pytest.mark.parametrize("surface", ["users", "importer-run"])
def test_export_controls_preserve_request_and_csrf_context(admin_user, surface):
    import re
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
        response = client.get(reverse("importers:run", args=[run.pk]), HTTP_HOST=ADMIN_TEST_HOST)
        body = response.content.decode()
    assert response.status_code == 200
    controls = re.search(r'<span class="snapshot-export-links[^>]*>', body).group()
    assert 'data-export-session="1"' in controls
    csrf = re.search(r'data-export-csrf="([^"]+)"', controls).group(1)
    assert csrf and csrf != "NOTPROVIDED"
    url = next(url for url, format in export_action_urls(body) if format == "html_zip")
    post = {"session": "1", "directory": "relative/path", "format": "html_zip"}
    assert client.post(url, post, HTTP_HOST=ADMIN_TEST_HOST).status_code == 403
    response = client.post(url, post, HTTP_HOST=ADMIN_TEST_HOST, HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 400
    assert b"absolute server directory" in response.content


def test_feed_url_is_keyless_and_honors_caller_permissions(admin_client, admin_user):
    from urllib.parse import parse_qs, urlsplit
    from django.test import Client
    from archivebox.api.auth import get_or_create_api_token

    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    folder = Folder.objects.create(name="RFC feeds", created_by=admin_user)
    snapshots = {
        visibility: Snapshot.objects.create(
            url=f"https://example.com/{visibility}",
            title=f"rssneedle {visibility}",
            crawl=crawl,
            folder=folder,
            config={"PERMISSIONS": visibility},
        )
        for visibility in ("public", "unlisted", "private")
    }
    # o=4 is the signed-in Title header; the rendered feed must use a stable field sort instead.
    filters = {"folder": str(folder.pk), "q": "rssneedle", "search_mode": "meta", "o": "4"}
    response = admin_client.get("/admin/core/snapshot/", filters, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    body = response.content.decode()
    urls = {format: url for url, format in export_action_urls(body) if format in {"rss", "rss_public"}}
    assert set(urls) == {"rss", "rss_public"}
    for url in urls.values():
        params = parse_qs(urlsplit(url).query)
        assert "api_key" not in params
        assert params["folder"] == [str(folder.pk)]
        assert params["q"] == ["rssneedle"]
        assert params["search_mode"] == ["meta"]
        assert params["sort"] == ["title,-id"]
    external_reader = Client()
    feed = admin_client.get(urls["rss"], HTTP_HOST=ADMIN_TEST_HOST)
    assert feed.status_code == 200
    assert exported_ids(feed, "rss") == {str(snapshot.pk) for snapshot in snapshots.values()}
    assert feed["Referrer-Policy"] == "no-referrer"
    for http_client, href in (
        (admin_client, urls["rss_public"]),
        (external_reader, urls["rss"]),
        (external_reader, urls["rss_public"]),
    ):
        public = http_client.get(href, HTTP_HOST=ADMIN_TEST_HOST)
        assert public.status_code == 200
        assert exported_ids(public, "rss") == {str(snapshots["public"].pk)}
    token = get_or_create_api_token(admin_user)
    headers = {"HTTP_HOST": ADMIN_TEST_HOST, "HTTP_X_ARCHIVEBOX_API_KEY": token.token}
    authenticated = external_reader.get(urls["rss"], **headers)
    assert authenticated.status_code == 200
    body = authenticated.getvalue()
    assert token.token.encode() not in body
    assert exported_body_ids(body, "rss") == {str(snapshot.pk) for snapshot in snapshots.values()}
    token.delete()
    assert external_reader.get(urls["rss"], **headers).status_code == 401

    # A copied href is a live query, not a frozen result or session-bearing URL.
    added = Snapshot.objects.create(
        url="https://example.com/a",
        title="rssneedle added",
        crawl=crawl,
        folder=folder,
        config={"PERMISSIONS": "public"},
    )
    Snapshot.objects.create(
        url="https://example.com/nonmatch",
        title="Another title",
        crawl=crawl,
        folder=folder,
        config={"PERMISSIONS": "public"},
    )
    Snapshot.objects.create(
        url="https://elsewhere.example/match",
        title="rssneedle outside the folder",
        crawl=crawl,
        config={"PERMISSIONS": "public"},
    )
    for http_client, href, ordered in (
        (admin_client, urls["rss"], [added, snapshots["private"], snapshots["public"], snapshots["unlisted"]]),
        (admin_client, urls["rss_public"], [added, snapshots["public"]]),
        (external_reader, urls["rss"], [added, snapshots["public"]]),
    ):
        feed = http_client.get(href, HTTP_HOST=ADMIN_TEST_HOST)
        assert feed.status_code == 200
        assert "no-store" in feed["Cache-Control"]
        assert [item.findtext("guid") for item in ElementTree.fromstring(feed.getvalue()).findall("./channel/item")] == [
            str(snapshot.pk) for snapshot in ordered
        ]


def test_folder_export_defaults_to_configured_content_search(admin_client, admin_user, cached_abxpkg_lib_dir):
    from archivebox.tests.test_search import configure_sqlite_search_backend, index_text

    configure_sqlite_search_backend()
    folder = Folder.objects.create(name="Content search", created_by=admin_user)
    crawl = Crawl.objects.create(urls="https://example.com/", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, title="Unrelated title", crawl=crawl, folder=folder)
    output = snapshot.output_dir / "dom/output.html"
    output.parent.mkdir(parents=True)
    index_text(snapshot, "folderdeepneedle")
    response = admin_client.get(
        "/admin/core/snapshot/export.jsonl",
        {"folder": str(folder.pk), "q": "folderdeepneedle"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert exported_ids(response, "jsonl") == {str(snapshot.pk)}


def test_feed_links_keep_the_dropdown_and_use_request_permissions(live_server, admin_user, browser_runtime, settings):
    from urllib.parse import parse_qs, urlsplit
    from playwright.sync_api import sync_playwright
    from archivebox.machine.models import Machine

    base_url = f"http://archivebox.localhost:{urlsplit(live_server.url).port}"
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": base_url, "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    settings.CONFIG = settings.CONFIG.model_copy(update={"BASE_URL": base_url, "PUBLIC_INDEX": True})
    admin_url = base_url.replace("//archivebox", "//admin.archivebox")
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    public = Snapshot.objects.create(url=crawl.urls, crawl=crawl, config={"PERMISSIONS": "public"})
    private_snapshot = Snapshot.objects.create(
        url="https://news.ycombinator.com/newest",
        crawl=crawl,
        config={"PERMISSIONS": "private"},
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        try:
            page = browser.new_page()
            page.goto(f"{admin_url}/admin/login/?next=/admin/auth/user/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            page.wait_for_url(f"{admin_url}/admin/auth/user/")
            for format in ("rss_public", "csv", "jsonl"):
                action = page.locator(f'a[data-export-format="{format}"]').first
                action.focus()
                url = action.get_attribute("href")
                query = parse_qs(urlsplit(url).query)
                assert not {"api_key", "token", "password"}.intersection(query)
                if format == "rss_public":
                    assert query["public_only"] == ["1"]
                response = page.evaluate(
                    "async url => { const response = await fetch(url, {credentials: 'omit'}); return {status: response.status, body: await response.text()}; }",
                    url,
                )
                assert response["status"] == 200
                body = response["body"]
                if format == "rss_public":
                    ids = {item.findtext("guid") for item in ElementTree.fromstring(body).findall("./channel/item")}
                else:
                    rows = csv.DictReader(io.StringIO(body)) if format == "csv" else (json.loads(line) for line in body.splitlines())
                    ids = {row["id"] for row in rows}
                assert str(public.pk) in ids
                assert str(private_snapshot.pk) not in ids
            private = page.locator('a[data-export-format="rss"]').first
            private.focus()
            url = private.get_attribute("href")
            assert "api_key=" not in url
            for credentials, expected in (("same-origin", {str(public.pk), str(private_snapshot.pk)}), ("omit", {str(public.pk)})):
                body = page.evaluate(
                    "async ([url, credentials]) => (await fetch(url, {credentials})).text()",
                    [url, credentials],
                )
                ids = {item.findtext("guid") for item in ElementTree.fromstring(body).findall("./channel/item")}
                assert expected <= ids
                if credentials == "omit":
                    assert str(private_snapshot.pk) not in ids
            with page.expect_navigation() as opened:
                private.click()
            assert opened.value.status == 200
            page = browser.new_page()
            page.goto(base_url.replace("//archivebox", "//web.archivebox") + "/public/")
            assert page.locator("[data-private-feed]").count() == 0
            assert page.locator('a[data-export-format="rss_public"]').count() > 0
        finally:
            browser.close()


@pytest.mark.parametrize("surface", ["folders", "users"])
def test_private_feed_links_do_not_use_stored_keys(admin_client, admin_user, surface):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.api.auth import get_or_create_api_token

    token = get_or_create_api_token(admin_user)
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

    urls = [url for url, format in export_action_urls(response.content) if format == "rss"]
    assert len(urls) >= 20
    assert all("api_key=" not in url and token.token not in url for url in urls)
    # Other admin widgets may resolve a key for API requests; export menus never add a per-row lookup.
    assert len(key_queries) <= 2


def test_public_folder_export_links_keep_query_and_configured_content_search(admin_user, cached_abxpkg_lib_dir, settings):
    from django.test import Client
    from urllib.parse import parse_qs, urlsplit
    from archivebox.machine.models import Machine
    from archivebox.tests.conftest import WEB_TEST_HOST
    from archivebox.tests.test_search import configure_sqlite_search_backend, consume_streaming_response, index_text

    configure_sqlite_search_backend()
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
        index_text(snapshot, "publicfolderdeepneedle")
        snapshots.append(snapshot)
    client = Client()
    query = {"q": "publicfolderdeepneedle", "folder": str(folder.pk)}
    stream = client.get("/public/search-stream/", {**query, "search_url": "/public/?" + urlencode(query)}, HTTP_HOST=WEB_TEST_HOST)
    assert stream.status_code == 200
    assert consume_streaming_response(stream)
    response = client.get("/public/", query, HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    assert [snapshot.pk for snapshot in response.context["object_list"]] == [snapshots[0].pk]
    exported_folder = next(entry for entry in response.context["sidebar_folder_tree"] if entry.pk == folder.pk)
    url = exported_folder.export_urls["jsonl"]
    params = parse_qs(urlsplit(url).query)
    assert params["search_mode"] == ["query"]
    assert params["q"] == [query["q"]]
    exported = client.get(url, HTTP_HOST=API_TEST_HOST)
    assert exported.status_code == 200
    assert exported_ids(exported, "jsonl") == {str(snapshots[0].pk)}


def test_export_selection_stays_lazy_without_building_admin_results(admin_user):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.config.common import get_config
    from archivebox.core.exports import get_export_queryset

    crawl = Crawl.objects.create(urls="https://example.com/selection", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, title="selection needle", crawl=crawl)
    config = get_config()
    with CaptureQueriesContext(connection) as queries:
        selection = get_export_queryset({"title__icontains": "needle"}, user=admin_user, public_only=False, config=config)
    assert len(queries) == 0, [entry["sql"] for entry in queries]
    assert list(selection.values_list("pk", flat=True)) == [snapshot.pk]


@pytest.mark.parametrize("ordering", ["-2", "4.-2", "-7", "-5"])
def test_exports_preserve_admin_ordering_and_repeated_filters(admin_client, admin_user, ordering):
    from django.utils import timezone
    from datetime import timedelta
    from archivebox.core.models import Tag

    crawl = Crawl.objects.create(urls="https://example.com/selection", created_by=admin_user)
    snapshots = []
    for index, title in enumerate(("B", "A", "A")):
        snapshot = Snapshot.objects.create(
            url=f"{crawl.urls}/{index}",
            title=title,
            crawl=crawl,
            downloaded_at=None if index == 0 else timezone.now(),
        )
        Snapshot.objects.filter(pk=snapshot.pk).update(created_at=timezone.now() - timedelta(days=index))
        for number in range(index):
            ArchiveResult.objects.create(snapshot=snapshot, plugin=("screenshot", "title")[number], status="succeeded")
            snapshot.tags.add(Tag.objects.create(name=f"selection-{index}-{number}"))
        snapshots.append(snapshot)
    pairs = [("id__exact", str(snapshot.pk)) for snapshot in snapshots[1:]] + [("o", ordering), ("downloaded_at__isnull", "0")]
    query = urlencode(pairs)
    listing = admin_client.get(f"/admin/core/snapshot/?{query}", HTTP_HOST=ADMIN_TEST_HOST)
    assert listing.status_code == 200
    expected = [str(snapshot.pk) for snapshot in listing.context["cl"].result_list]
    exported = admin_client.get(f"/admin/core/snapshot/export.jsonl?{query}", HTTP_HOST=ADMIN_TEST_HOST)
    assert exported.status_code == 200
    assert [json.loads(line)["id"] for line in exported.getvalue().splitlines()] == expected
    assert set(expected) == {str(snapshot.pk) for snapshot in snapshots[1:]}


@pytest.mark.parametrize(
    "lookup",
    [
        "crawl__created_by__password__icontains",
        "crawl__created_by_id__password__icontains",
        "crawl_id__created_by__password__icontains",
        "crawl__config__icontains",
        "crawl__persona__config__icontains",
        "crawl__persona_id__config__icontains",
    ],
)
def test_private_exports_reject_related_credentials(admin_client, admin_user, lookup):
    crawl = Crawl.objects.create(urls="https://example.com/private-export", created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    rejected = admin_client.get("/admin/core/snapshot/export.jsonl", {lookup: "secret"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert rejected.status_code == 400
    allowed = admin_client.get(
        "/admin/core/snapshot/export.jsonl",
        {"crawl__created_by__id__exact": str(admin_user.pk)},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert allowed.status_code == 200
    assert exported_ids(allowed, "jsonl") == {str(snapshot.pk)}


def test_exports_preserve_named_filter_last_value_and_invalid_status(admin_client, admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/permissions", created_by=admin_user)
    snapshots = [
        Snapshot.objects.create(url=f"{crawl.urls}/{value}", crawl=crawl, config={"PERMISSIONS": value}) for value in ("public", "private")
    ]
    query = urlencode([("permissions", "public"), ("permissions", "private"), ("snapshot_status", "invalid")])
    listing = admin_client.get(f"/admin/core/snapshot/?{query}", HTTP_HOST=ADMIN_TEST_HOST)
    assert listing.status_code == 200
    expected = [str(snapshot.pk) for snapshot in listing.context["cl"].result_list]
    exported = admin_client.get(f"/admin/core/snapshot/export.jsonl?{query}", HTTP_HOST=ADMIN_TEST_HOST)
    assert exported.status_code == 200
    assert [json.loads(line)["id"] for line in exported.getvalue().splitlines()] == expected == [str(snapshots[1].pk)]


def test_saved_operator_export_urls_refresh_results_and_preserve_public_scope(client, admin_user, tmp_path):
    from urllib.parse import parse_qs, urlsplit

    from django.core.management import call_command
    from django.test import Client

    from archivebox.core.routes_util import build_snapshot_export_urls

    crawl = Crawl.objects.create(urls="https://solarcity.com/", created_by=admin_user)

    def capture(title, url, tag, visibility="public"):
        snapshot = Snapshot.objects.create(url=url, title=title, crawl=crawl, config={"PERMISSIONS": visibility})
        snapshot.save_tags([tag])
        return snapshot

    alpha = capture("Alpha", "https://solarcity.com/a", "solar-pv")
    zulu = capture("Zulu", "https://solarcity.com/z", "solar")
    capture("Draft", "https://solarcity.com/d", "solar", "private")
    capture("Other domain", "https://other.example/a", "solar")
    capture("Other tag", "https://solarcity.com/b", "lunar")
    params = {"q": "tags:solar site:solarcity.com", "sort": "-title,id", "public_only": "1"}
    urls = build_snapshot_export_urls(params, api=True)
    for key in ("csv", "rss_public", "html_zip"):
        assert parse_qs(urlsplit(urls[key]).query) == {k: [v] for k, v in params.items()}
    expected = [str(zulu.pk), str(alpha.pk)]
    csv_response = client.get(urls["csv"], HTTP_HOST=API_TEST_HOST)
    assert csv_response.status_code == 200
    assert [row["id"] for row in csv.DictReader(io.StringIO(csv_response.getvalue().decode()))] == expected

    def read_feed():
        response = Client().get(urls["rss_public"], HTTP_HOST=API_TEST_HOST)
        assert response.status_code == 200
        return [item.findtext("guid") for item in ElementTree.fromstring(response.getvalue()).findall("./channel/item")]

    assert read_feed() == expected
    zip_response = client.get(urls["html_zip"], HTTP_HOST=API_TEST_HOST)
    assert zip_response.status_code == 200
    assert zip_response.json()["count"] == len(expected)
    # The same query string drives the existing site-export job. Inspect the
    # archive's manifest because the HTTP GET only estimates the job size.
    destination = tmp_path / "exported-site"
    call_command("site_export", query=urlsplit(urls["html_zip"]).query, public_only=True, format="html_zip", destination=str(destination))
    with zipfile.ZipFile(destination / "site.zip") as bundle:
        assert [json.loads(line)["id"] for line in bundle.read("index.jsonl").splitlines()] == expected

    delta = capture("Delta", "https://solarcity.com/new", "SOLAR power")
    assert read_feed() == [str(zulu.pk), str(delta.pk), str(alpha.pk)]
