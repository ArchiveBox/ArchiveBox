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
    query = {"folder": str(folder.pk), "q": "quartzneedle", "p": "9"}
    api_url = f"/api/v1/core/snapshots/export/{format}"
    web_url = f"/admin/core/snapshot/export.{format}"
    for http_client, url, headers in (
        (client, api_url, {"HTTP_HOST": API_TEST_HOST}),
        (admin_client, web_url, {"HTTP_HOST": ADMIN_TEST_HOST}),
    ):
        response = http_client.get(url, query, **headers)
        assert response.status_code == 200, response.content
        assert exported_ids(response, format) == {str(visible.pk)}
        assert "no-store" in response["Cache-Control"]
    keyed = client.get(api_url, query, **api_headers)
    assert keyed.status_code == 200, keyed.content
    assert exported_ids(keyed, format) == {str(visible.pk), str(private.pk)}
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
        query = urlencode({"folder": str(folder.pk), "q": "Hacker News"})
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
        expect(page.locator("#folder-sidebar .folder-actions a[data-export-format]")).to_have_count(5)
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
            ordinary = page.locator('.snapshot-export-links:not(.snapshot-export-menu) a[data-export-format="jsonl"]').first
            parsed = parse_qs(urlsplit(ordinary.get_attribute("href")).query)
            assert parsed["folder"] == [str(child.pk)]
            response = page.request.get(ordinary.evaluate("node => node.href"))
            assert response.status == 200
            assert [json.loads(line)["title"] for line in response.text().splitlines()] == [query]
            page.keyboard.press("Escape")
        browser.close()
