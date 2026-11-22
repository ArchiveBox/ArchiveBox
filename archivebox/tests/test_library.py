"""Library organization exercised through the real admin and database."""

import pytest

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("view", ["/admin/core/snapshot/", "/admin/core/snapshot/grid/", "/admin/core/snapshot/?_embedded=crawl"])
def test_move_destination_labels_match_refreshed_folder_paths(admin_client, view):
    from archivebox.core.models import Folder
    from archivebox.core.smart_folders import CHILDREN_RULES

    parent = Folder.objects.create(name="2026", rules=CHILDREN_RULES, position=0)
    child = Folder.objects.create(name="OneTab", parent=parent)
    nested = Folder.objects.create(name="Reading", parent=child)
    other = Folder.objects.create(name="2025", position=1)
    duplicate = Folder.objects.create(name="OneTab", parent=other)
    smart = Folder.objects.create(name="Smart", rules={"field": "url", "lookup": "icontains", "value": "example"}, position=2)
    limited = Folder.objects.create(name="Limited", rules={**CHILDREN_RULES, "sort": "-created_at", "limit": 2})
    expected = [
        ("", "No folder"),
        (parent.pk, "2026"),
        (child.pk, "2026 / OneTab"),
        (nested.pk, "2026 / OneTab / Reading"),
        (other.pk, "2025"),
        (duplicate.pk, "2025 / OneTab"),
    ]
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get(view, HTTP_HOST=ADMIN_TEST_HOST)
    folder_reads = [query["sql"] for query in queries if 'FROM "core_folder"' in query["sql"]]
    assert len(folder_reads) == 1, folder_reads
    assert response.status_code == 200
    field = response.context["action_form"].fields["folder_destination"]
    import html
    import re

    def choices(response):
        select = re.search(r'<select[^>]*name="folder_destination"[^>]*>(.*?)</select>', response.content.decode(), re.DOTALL)
        assert select is not None
        return [
            (html.unescape(value), html.unescape(label))
            for value, label in re.findall(r'<option value="([^"]*)">(.*?)</option>', select[1])
        ]

    assert choices(response) == [(str(value), label) for value, label in expected]
    assert field.queryset.filter(pk=parent.pk).exists()
    assert not field.queryset.filter(pk=smart.pk).exists()
    assert not field.queryset.filter(pk=limited.pk).exists()

    renamed = admin_client.post(
        "/admin/core/folder/save/",
        {"folder_id": str(child.pk), "name": "Bookmarks", "parent": str(parent.pk), "refresh_tree": "1"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert renamed.status_code == 200, renamed.content
    tree = renamed.json()["folder_html"]
    assert renamed.json()["path_label"] == "2026 / Bookmarks"
    assert dict(renamed.json()["folder_choices"])[str(nested.pk)] == "2026 / Bookmarks / Reading"
    assert str(smart.pk) not in dict(renamed.json()["move_folder_choices"])
    # Preserve the existing live-refresh eligibility (broader than the initial
    # action field for containers carrying sort/limit metadata).
    assert str(limited.pk) in dict(renamed.json()["move_folder_choices"])
    assert 'title="2026 / Bookmarks"' in tree
    children = admin_client.get("/admin/core/snapshot/sidebar/", {"parent": child.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert children.status_code == 200
    assert 'title="2026 / Bookmarks / Reading"' in children.json()["html"]
    updated = admin_client.get(view, HTTP_HOST=ADMIN_TEST_HOST)
    labels = dict(choices(updated))
    assert labels[str(child.pk)] == "2026 / Bookmarks"
    assert labels[str(nested.pk)] == "2026 / Bookmarks / Reading"


def test_initial_folder_sidebar_reuses_picker_tree_and_limits_roots(admin_client):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from archivebox.core.models import Folder
    from archivebox.core.smart_folders import CHILDREN_RULES

    roots = Folder.objects.bulk_create([Folder(name=f"Folder {i:03d}", position=i, rules=CHILDREN_RULES) for i in range(105)])
    selected = Folder.objects.create(name="Nested", parent=roots[-1])
    with CaptureQueriesContext(connection) as queries:
        initial = admin_client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    assert initial.status_code == 200
    assert sum('FROM "core_folder"' in query["sql"] for query in queries) == 1
    assert len(initial.context["sidebar_folder_tree"]) == 100
    response = admin_client.get("/admin/core/snapshot/", {"folder": selected.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    visible = response.context["sidebar_folder_tree"]
    assert len(visible) == 102
    assert [folder.pk for folder in visible[-2:]] == [roots[-1].pk, selected.pk]
    assert response.context["sidebar_next"]
    assert len(response.context["folder_choices"]) == 107


def test_folder_path_choices_and_admin_foreign_keys(admin_client, snapshot):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.core.models import Folder

    parent = Folder.objects.create(name="2026")
    child = Folder.objects.create(name="OneTab", parent=parent)
    grandchild = Folder.objects.create(name="Research", parent=child)
    other = Folder.objects.create(name="2025")
    duplicate = Folder.objects.create(name="OneTab", parent=other)
    tree = Folder.tree()
    with CaptureQueriesContext(connection) as queries:
        choices = Folder.path_choices(folder for folder in tree if folder.pk != parent.pk)
    assert len(queries) == 0
    assert dict(choices)[child.pk] == "2026 / OneTab"
    assert dict(choices)[grandchild.pk] == "2026 / OneTab / Research"
    assert dict(choices)[duplicate.pk] == "2025 / OneTab"

    response = admin_client.get(f"/admin/core/snapshot/{snapshot.pk}/change/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    field = response.context["adminform"].form.fields["folder"]
    assert dict(field.choices)[child.pk] == "2026 / OneTab"
    assert field.queryset.filter(pk=child.pk).exists()
    response = admin_client.get(f"/admin/core/folder/{child.pk}/change/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    field = response.context["adminform"].form.fields["parent"]
    assert dict(field.choices)[duplicate.pk] == "2025 / OneTab"
    assert child.pk not in dict(field.choices)
    assert grandchild.pk not in dict(field.choices)
    assert not field.queryset.filter(pk__in=[child.pk, grandchild.pk]).exists()


def test_nested_folders_filter_and_export(admin_client, admin_user):
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(
        url="https://example.com/paper",
        title="A paper",
        crawl=crawl,
        folder=child,
        config={"PERMISSIONS": "public"},
    )
    Snapshot.objects.create(url="https://example.com/unfiled", title="Unfiled", crawl=crawl)
    response = admin_client.get("/admin/core/snapshot/", {"folder": parent.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert list(response.context["cl"].queryset.values_list("pk", flat=True)) == [snapshot.pk]
    assert b'aria-label="Folders"' in response.content
    assert b"Research" in response.content and b"Papers" in response.content
    response = admin_client.get("/admin/core/snapshot/", {"folder": child.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [folder.pk for folder in response.context["folder_breadcrumbs"]] == [parent.pk, child.pk]
    html = response.content.decode()
    assert 'class="library-breadcrumbs"' not in html
    assert 'class="library-context"' not in html
    assert '<span class="folder-current">Papers</span>' in html
    assert 'aria-label="Add folder in Research"' in html
    assert "Add subfolder" in html
    from html import unescape
    from urllib.parse import parse_qs, urlsplit
    import re

    response = admin_client.get(
        "/admin/core/snapshot/",
        {"folder": child.pk, "q": "A paper", "search_mode": "meta"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    menu = response.content.decode().split(f'id="folder-menu-{parent.pk}"', 1)[1].split("</div>", 1)[0]
    links = re.findall(r'<a href="([^"]+)" data-export-format="([^"]+)"', menu)
    assert {format for _, format in links} == {"rss", "rss_public", "csv", "jsonl", "html_zip", "wacz"}
    for url, _format in links:
        parameters = parse_qs(urlsplit(unescape(url)).query)
        if _format == "rss":
            assert "api_key" not in parameters
        elif _format == "rss_public":
            assert parameters.pop("public_only") == ["1"]
        assert parameters == {"folder": [str(parent.pk)], "q": ["A paper"], "search_mode": ["meta"]}
    response = admin_client.get("/admin/core/snapshot/export.rss", {"folder": parent.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/rss+xml")
    body = response.getvalue()
    assert b"A paper" in body and b"Unfiled" not in body


def test_folder_cycles_rejected_and_deletion_preserves_snapshots(admin_client, admin_user):
    from django.core.exceptions import ValidationError
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    parent.parent = child
    with pytest.raises(ValidationError, match="cycle"):
        parent.save()
    parent.refresh_from_db()
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/paper", crawl=crawl, folder=child)
    child.delete()
    snapshot.refresh_from_db()
    assert snapshot.folder_id is None


def test_bulk_move_snapshots_to_folder(admin_client, admin_user):
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    folder = Folder.objects.create(name="Read later")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/paper", crawl=crawl)
    response = admin_client.post(
        "/admin/core/snapshot/",
        {
            "action": "move_to_folder",
            "folder_destination": folder.pk,
            "_selected_action": str(snapshot.pk),
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    snapshot.refresh_from_db()
    assert snapshot.folder_id == folder.pk


def test_public_only_folder_feed_stays_public_even_with_admin_session(admin_client, admin_user):
    from xml.etree import ElementTree
    from django.test import Client
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    for permissions in ("public", "unlisted", "private"):
        Snapshot.objects.create(
            url=f"https://example.com/{permissions}",
            title=permissions,
            crawl=crawl,
            config={"PERMISSIONS": permissions},
        )
    response = Client().get("/admin/core/snapshot/export.rss", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [item.findtext("title") for item in ElementTree.fromstring(response.getvalue()).findall("./channel/item")] == ["public"]
    response = admin_client.get("/admin/core/snapshot/export.rss", {"public_only": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert [item.findtext("title") for item in ElementTree.fromstring(response.getvalue()).findall("./channel/item")] == ["public"]


def test_folder_feed_search_resolves_without_browser_cache(admin_client, admin_user):
    from xml.etree import ElementTree

    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    folder = Folder.objects.create(name="RSS research")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    matching = Snapshot.objects.create(
        url="https://example.com/feed-query-match",
        title="Matching story",
        crawl=crawl,
        folder=folder,
        config={"PERMISSIONS": "public"},
    )
    Snapshot.objects.create(url="https://example.com/unrelated", title="Unrelated story", crawl=crawl, folder=folder)
    Snapshot.objects.create(url="https://example.com/feed-query-match-outside", title="Outside folder", crawl=crawl)
    response = admin_client.get(
        "/admin/core/snapshot/export.rss",
        {"folder": folder.pk, "q": "feed-query-match", "search_mode": "meta"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    items = ElementTree.fromstring(response.getvalue()).findall("./channel/item")
    assert [item.findtext("title") for item in items] == [matching.title]


def test_list_rss_is_a_native_link_without_export_state(admin_client, api_token):
    from django.apps import apps
    from urllib.parse import parse_qs, urlsplit
    from archivebox.api.models import APIToken

    admin_client.get("/admin/", HTTP_HOST=ADMIN_TEST_HOST)
    tokens_before = APIToken.objects.count()
    response = admin_client.get("/admin/core/snapshot/", {"q": "Hacker News", "search_mode": "meta"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    links = response.context["list_export_urls"]
    link = urlsplit(links["rss"])
    assert link.path == "/admin/core/snapshot/export.rss"
    assert parse_qs(link.query) == {"q": ["Hacker News"], "search_mode": ["meta"], "sort": ["-created_at,-id"]}
    assert set(links) == {"rss", "rss_public", "csv", "jsonl", "html_zip", "wacz"}
    for format, url in links.items():
        assert api_token.token not in url
        assert parse_qs(urlsplit(url).query) == {**parse_qs(link.query), **({"public_only": ["1"]} if format == "rss_public" else {})}
    assert APIToken.objects.count() == tokens_before
    assert not apps.is_installed("archivebox.feeds")


def test_native_rss_uses_current_filters_and_existing_api_auth(client, api_token, api_admin_user, django_user_model):
    from xml.etree import ElementTree
    from django.utils import timezone

    from archivebox.core.models import Folder, Snapshot, Tag
    from archivebox.crawls.models import Crawl

    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="News", parent=parent)
    tag = Tag.objects.create(name="RSS topic", created_by=api_admin_user)
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=api_admin_user)
    first = Snapshot.objects.create(
        url="https://news.ycombinator.com/",
        title="Matching story",
        crawl=crawl,
        folder=child,
        config={"PERMISSIONS": "private"},
    )
    first.tags.add(tag)
    Snapshot.objects.create(url="https://example.com/outside", title="Matching outside", crawl=crawl)
    other = django_user_model.objects.create_user("other-rss-owner")
    other_crawl = Crawl.objects.create(urls="https://example.com/other", created_by=other)
    wrong_owner = Snapshot.objects.create(url=other_crawl.urls, title="Matching other owner", crawl=other_crawl, folder=child)
    wrong_owner.tags.add(tag)
    query = {"folder": parent.pk, "tag": tag.pk, "crawl__created_by__id__exact": api_admin_user.pk, "q": "Matching", "search_mode": "meta"}
    endpoint = "/admin/core/snapshot/export.rss"
    public_response = client.get(endpoint, query, HTTP_HOST=ADMIN_TEST_HOST)
    assert public_response.status_code == 200
    assert ElementTree.fromstring(public_response.getvalue()).findall("./channel/item") == []
    response = client.get(endpoint, query, HTTP_HOST=ADMIN_TEST_HOST, HTTP_AUTHORIZATION=f"Bearer {api_token.token}")
    assert response.status_code == 200
    assert response["Cache-Control"].find("no-store") >= 0
    assert response["Referrer-Policy"] == "no-referrer"
    items = ElementTree.fromstring(response.getvalue()).findall("./channel/item")
    assert [item.findtext("guid") for item in items] == [str(first.pk)]
    second = Snapshot.objects.create(
        url="https://news.ycombinator.com/newest",
        title="Matching new story",
        crawl=crawl,
        folder=child,
        config={"PERMISSIONS": "private"},
    )
    second.tags.add(tag)
    response = client.get(endpoint, {**query, "api_key": api_token.token, "p": "999"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    body = response.getvalue()
    assert api_token.token.encode() not in body
    assert {item.findtext("guid") for item in ElementTree.fromstring(body).findall("./channel/item")} == {
        str(first.pk),
        str(second.pk),
    }
    api_token.expires = timezone.now() - timezone.timedelta(seconds=1)
    api_token.save(update_fields=["expires"])
    assert client.get(endpoint, {**query, "api_key": api_token.token}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 401


def test_native_rss_rejects_writes_and_invalid_filters(admin_client):
    endpoint = "/admin/core/snapshot/export.rss"
    assert admin_client.post(endpoint, HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    assert admin_client.get(endpoint, {"not_a_snapshot_field": "x"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400


def test_feed_key_does_not_inherit_browser_privileges(admin_client, django_user_model):
    from archivebox.api.models import APIToken

    user = django_user_model.objects.create_user("no-feed-permission")
    token = APIToken.objects.create(created_by=user)
    response = admin_client.get("/admin/core/snapshot/export.rss", {"api_key": token.token}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 403


def test_public_feed_cannot_query_sensitive_config(client, admin_user):
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl

    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    Snapshot.objects.create(url=crawl.urls, crawl=crawl, config={"PERMISSIONS": "public"})
    response = client.get("/admin/core/snapshot/export.rss", {"config__contains": "secret"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 400


@pytest.mark.parametrize("format", ["csv", "jsonl"])
def test_native_list_downloads_are_complete_and_public_only_when_requested(admin_client, api_token, api_admin_user, format):
    import csv
    import io
    import json

    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    folder = Folder.objects.create(name="Exports")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=api_admin_user)
    expected_ids = set()
    title = 'A "quoted", multiline\nUnicode café title'
    for index in range(501):
        snapshot = Snapshot.objects.create(
            url=f"https://example.com/export/{index}",
            title=title,
            crawl=crawl,
            folder=folder,
            config={"PERMISSIONS": "public", "PRIVATE_VALUE": "not-for-export"},
            notes="private notes",
        )
        expected_ids.add(str(snapshot.pk))
    private = Snapshot.objects.create(url="https://example.com/private", crawl=crawl, folder=folder, config={"PERMISSIONS": "private"})
    Snapshot.objects.create(url="https://example.com/outside", crawl=crawl, config={"PERMISSIONS": "public"})
    endpoint = f"/admin/core/snapshot/export.{format}"

    def records(response):
        assert response.status_code == 200
        assert "no-store" in response["Cache-Control"]
        assert response["Content-Disposition"] == f'attachment; filename="snapshots.{format}"'
        content = response.getvalue().decode()
        assert "not-for-export" not in content and "private notes" not in content and api_token.token not in content
        return list(csv.DictReader(io.StringIO(content))) if format == "csv" else [json.loads(line) for line in content.splitlines()]

    public = records(admin_client.get(endpoint, {"folder": folder.pk, "p": 999, "public_only": "1"}, HTTP_HOST=ADMIN_TEST_HOST))
    assert {row["id"] for row in public} == expected_ids
    assert {row["title"] for row in public} == {'A "quoted", multiline Unicode café title'}
    authorized = records(admin_client.get(endpoint, {"folder": folder.pk, "api_key": api_token.token}, HTTP_HOST=ADMIN_TEST_HOST))
    assert {row["id"] for row in authorized} == expected_ids | {str(private.pk)}
    assert admin_client.get(endpoint, {"api_key": "invalid"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 401
    assert admin_client.get(endpoint, {"config__contains": "private", "public_only": "1"}, HTTP_HOST=ADMIN_TEST_HOST).status_code == 400


def test_view_only_staff_cannot_move_snapshots_to_folder(client, admin_user, django_user_model):
    from django.contrib.auth.models import Permission

    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    user = django_user_model.objects.create_user("library-viewer", password="testpassword", is_staff=True)
    user.user_permissions.add(Permission.objects.get(content_type__app_label="core", codename="view_snapshot"))
    folder = Folder.objects.create(name="Restricted destination")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/view-only", crawl=crawl)
    client.force_login(user)
    response = client.post(
        "/admin/core/snapshot/",
        {"action": "move_to_folder", "folder_destination": folder.pk, "_selected_action": str(snapshot.pk)},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    snapshot.refresh_from_db()
    assert snapshot.folder_id is None
    response = client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert b'value="move_to_folder"' not in response.content
    response = client.post("/admin/core/folder/move/", {"folder_id": folder.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 403


def test_inline_folder_save_rejects_cycles(admin_client):
    from archivebox.core.models import Folder

    response = admin_client.post("/admin/core/folder/save/", {"name": "Research"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    parent = response.json()["id"]
    response = admin_client.post("/admin/core/folder/save/", {"name": "Papers", "parent": parent}, HTTP_HOST=ADMIN_TEST_HOST)
    child = response.json()["id"]
    response = admin_client.post(
        "/admin/core/folder/save/",
        {"folder_id": parent, "name": "Research", "parent": child},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 400 and "cycle" in response.json()["error"]
    assert Folder.objects.get(pk=parent).parent_id is None


def test_inline_folder_save_validates_normalized_name(admin_client):
    from archivebox.core.models import Folder

    response = admin_client.post("/admin/core/folder/save/", {"name": "<b></b>"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 400
    assert "name" in response.json()["error"].lower()
    assert list(Folder.objects.values_list("name", "rules")) == [
        ("📥 Inbox", {"op": "NOT", "rules": [{"field": "folder", "lookup": "in_folder", "value": "*"}]}),
    ]
    response = admin_client.post("/admin/core/folder/save/", {"name": "  <b>Reading list</b>  "}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.json()["name"] == "Reading list"
    assert Folder.objects.get(pk=response.json()["id"]).name == "Reading list"


@pytest.mark.django_db(transaction=True)
def test_public_folder_browser_keeps_navigation_readonly(live_server, admin_user, browser_runtime):
    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine
    from urllib.parse import urlsplit

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}", "PUBLIC_INDEX": True}
    machine.save(update_fields=["config"])
    folder = Folder.objects.create(name="Published research")
    other = Folder.objects.create(name="Other reading")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshot = Snapshot.objects.create(
        url="https://example.com/paper",
        title="Public paper",
        crawl=crawl,
        folder=folder,
        permissions="public",
    )
    Snapshot.objects.create(url="https://example.com/other", title="Other paper", crawl=crawl, folder=other, permissions="public")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        response = page.goto(f"http://archivebox.localhost:{port}/public/?folder={folder.pk}")
        assert response.status == 200
        expect(page.locator(".snapshot-title")).to_have_text([snapshot.title])
        expect(page.locator(".folder-new,.folder-edit,.folder-drop-target,#folder-dialog,[draggable=true]")).to_have_count(0)
        page.get_by_role("button", name="Find a folder", exact=True).click()
        page.get_by_role("searchbox", name="Find a folder").fill(folder.name)
        expect(page.locator(f'[data-folder-id="{folder.pk}"]')).to_be_visible()
        expect(page.locator(f'[data-folder-id="{other.pk}"]')).not_to_be_visible()
        page.locator(f'[data-folder-id="{folder.pk}"]').hover()
        page.get_by_role("button", name=f"Actions for {folder.name}", exact=True).click()
        menu = page.locator(f"#folder-menu-{folder.pk}")
        expect(menu).to_be_visible()
        assert menu.locator("a[data-export-format]").count() > 0
        expect(menu.get_by_role("button")).to_have_count(0)
        assert not errors
        browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("view", ["table", "grid"])
def test_browser_drag_single_and_checked_snapshots(live_server, admin_user, browser_runtime, view):
    from django.core import signing
    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine
    from urllib.parse import urlsplit

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshots = [Snapshot.objects.create(url=f"https://example.com/{i}", title=f"Capture {i}", crawl=crawl) for i in range(3)]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        if view == "grid":
            page.goto(f"{admin_url}/admin/core/snapshot/grid/")
        row_selector, drag_selector = (".cards .card", ".card-title") if view == "grid" else ("#result_list tbody tr", ".field-title_str")
        source = page.locator(row_selector).filter(has_text="Capture 0")
        expect(source).to_have_attribute("draggable", "true")
        page.get_by_role("button", name="Expand Research", exact=True).click()
        source.locator(drag_selector).drag_to(page.locator(f'.folder-row[data-folder-id="{child.pk}"]'))
        expect(page.locator(".messagelist")).to_contain_text("Moved 1 snapshot(s) to Papers")
        for snapshot in snapshots[1:]:
            page.locator(f'input.action-select[value="{snapshot.pk}"]').check()
        page.locator(row_selector).filter(has_text="Capture 1").locator(drag_selector).drag_to(
            page.locator(f'.folder-row[data-folder-id="{parent.pk}"]'),
        )
        expect(page.locator(".messagelist")).to_contain_text("Moved 2 snapshot(s) to Research")
        page.locator(f'.folder-row[data-folder-id="{parent.pk}"]').hover()
        page.get_by_role("button", name="Actions for Research", exact=True).click()
        menu = page.locator(f"#folder-menu-{parent.pk}")
        expect(menu).to_be_visible()
        expect(menu.get_by_role("menuitem", name="Rename", exact=True)).to_be_focused()
        page.keyboard.press("ArrowDown")
        expect(menu.get_by_role("menuitem", name="Move...", exact=True)).to_be_focused()
        page.keyboard.press("Escape")
        expect(menu).to_be_hidden()
        page.get_by_role("button", name="Actions for Research", exact=True).click()
        menu.get_by_role("menuitem", name="Rename", exact=True).click()
        expect(page.locator("#folder-name")).to_have_value("Research")
        page.locator(".folder-dialog-close").first.click()
        page.get_by_role("button", name="Actions for Research", exact=True).click()
        menu.get_by_role("menuitem", name="Add subfolder", exact=True).click()
        expect(page.locator("#folder-parent")).to_have_value(str(parent.pk))
        navigation_start = page.evaluate("performance.timeOrigin")
        page.locator("#folder-name").fill("Design inspiration")
        save_started = page.evaluate("performance.now()")
        page.get_by_role("button", name="Save folder", exact=True).click()
        expect(page.locator(".folder-tree")).to_contain_text("Design inspiration")
        expect(page.locator("#folder-dialog")).not_to_be_visible()
        assert page.evaluate("performance.timeOrigin") == navigation_start
        print(
            "folder create timings",
            page.evaluate(
                """started => ({
            visibleMs: performance.now() - started,
            requestMs: performance.getEntriesByType('resource').filter(entry => entry.name.includes('/core/folder/save/')).at(-1).duration,
        })""",
                save_started,
            ),
        )
        expect(page.get_by_role("button", name="Add folder in Research", exact=True)).to_be_visible()
        page.get_by_role("button", name="Find a folder", exact=True).click()
        page.get_by_role("searchbox", name="Find a folder").fill("Design")
        expect(page.locator(f'.folder-row[data-folder-id="{child.pk}"]')).to_be_hidden()
        expect(page.locator(f'.folder-row[data-folder-id="{parent.pk}"]')).to_be_visible()
        expect(page.locator(".folder-tree")).to_contain_text("Design inspiration")
        with page.expect_response(
            lambda response: urlsplit(response.url).path.endswith("/sidebar/") and "sidebar_q=" in urlsplit(response.url).query.split("&"),
        ) as reset:
            page.keyboard.press("Escape")
        assert reset.value.ok
        page.get_by_role("button", name="Expand Research", exact=True).click()
        page.locator(f'.folder-row[data-folder-id="{child.pk}"] .folder-link').drag_to(page.get_by_role("link", name="All folders"))
        expect(page.locator(f'.folder-row[data-folder-id="{child.pk}"]')).to_have_attribute("data-parent-id", "")
        page.locator(f'.folder-row[data-folder-id="{parent.pk}"]').hover()
        page.get_by_role("button", name="Actions for Research", exact=True).click()
        menu.get_by_role("menuitem", name="Delete snapshots", exact=True).click()
        expect(page.locator('input[name="post"][value="yes"]')).to_have_count(1)
        confirmation = page.get_by_role("main", name="Confirm snapshot deletion", exact=True)
        cancel = confirmation.get_by_role("link", name="Cancel", exact=True)
        expect(cancel).to_be_visible()
        selection = signing.loads(
            confirmation.locator('input[name="selection"]').input_value(),
            salt="archivebox.snapshot-delete-selection",
            max_age=3600,
        )
        assert set(selection["ids"]) == {str(snapshot.pk) for snapshot in snapshots[1:]}
        assert set(confirmation.locator("li").all_text_contents()) == {snapshot.url for snapshot in snapshots[1:]}
        cancel.click()
        expect(page.locator("#changelist-form")).to_be_visible()
        browser.close()
    for snapshot in snapshots:
        snapshot.refresh_from_db()
        assert snapshot.status == Snapshot.INITIAL_STATE
    assert snapshots[0].folder_id == child.pk
    items = parent.children.get(name="Items")
    assert {snapshot.folder_id for snapshot in snapshots[1:]} == {items.pk}
    assert Folder.objects.get(name="Design inspiration").parent_id == parent.pk


def test_folder_reparent_reorder_and_cycle_protection(admin_client):
    from archivebox.core.models import Folder

    first = Folder.objects.create(name="First")
    last = Folder.objects.create(name="Last")
    child = Folder.objects.create(name="Child", parent=first)
    response = admin_client.post(
        "/admin/core/folder/move/",
        {"folder_id": last.pk, "target_id": first.pk, "placement": "before"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 200
    assert list(Folder.objects.filter(parent=None).values_list("pk", flat=True)) == [
        last.pk,
        first.pk,
        Folder.objects.get(name="📥 Inbox").pk,
    ]
    response = admin_client.post("/admin/core/folder/move/", {"folder_id": first.pk, "target_id": child.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 400 and "cycle" in response.json()["error"]
    response = admin_client.post("/admin/core/folder/move/", {"folder_id": child.pk, "target_id": last.pk}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    child.refresh_from_db()
    assert child.parent_id == last.pk


def test_folder_tree_labels_without_snapshot_counts(admin_user):
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl

    parent = Folder.objects.create(name="Research")
    child = Folder.objects.create(name="Papers", parent=parent)
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    Snapshot.objects.create(url="https://example.com/paper", folder=child, crawl=crawl)
    tree = Folder.tree()
    assert [folder.path_label for folder in tree] == ["Research", "Research / Papers", "📥 Inbox"]
    assert all(not hasattr(folder, "snapshot_count") for folder in tree)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("view", ["table", "grid"])
def test_browser_folder_reordering_and_nesting(live_server, admin_user, browser_runtime, view):
    import re
    from concurrent.futures import ThreadPoolExecutor

    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import Folder
    from archivebox.machine.models import Machine
    from urllib.parse import urlsplit

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    first = Folder.objects.create(name="First", position=1)
    second = Folder.objects.create(name="Second", position=2)
    smart = Folder.objects.create(name="Smart", position=3, rules={"field": "url", "lookup": "icontains", "value": "news"})
    child = Folder.objects.create(name="Child", parent=first, position=0)
    sibling = Folder.objects.create(name="Sibling", parent=first, position=1)
    inbox = Folder.objects.filter(name="📥 Inbox").first()
    roots = [inbox] if inbox else []
    with ThreadPoolExecutor(max_workers=1) as db, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        if view == "grid":
            page.goto(f"{admin_url}/admin/core/snapshot/grid/")

        def row(folder):
            return page.locator(f'.folder-row[data-folder-id="{folder.pk}"]')

        def reveal(folder):
            records = db.submit(lambda: dict(Folder.objects.values_list("pk", "parent_id"))).result()
            ids, parent_id = [], records[folder.pk]
            while parent_id:
                ids.append(parent_id)
                parent_id = records[parent_id]
            for branch_id in reversed(ids):
                toggle = page.locator(f'.folder-row[data-folder-id="{branch_id}"] .folder-toggle')
                expect(toggle).to_be_visible()
                if toggle.get_attribute("aria-expanded") == "false":
                    toggle.click()
            expect(row(folder)).to_be_visible()

        def drag(source, target, placement):
            reveal(source)
            reveal(target)
            box = row(target).bounding_box()
            y = {"before": 2, "inside": box["height"] / 2, "after": box["height"] - 2}[placement]
            with page.expect_navigation():
                row(source).locator(".folder-link").drag_to(row(target), target_position={"x": 80, "y": y})
            reveal(source)
            expect(row(source)).to_have_attribute(
                "data-parent-id",
                db.submit(lambda: str(Folder.objects.get(pk=source.pk).parent_id or "")).result(),
            )

        def order(parent, expected):
            for folder in expected:
                reveal(folder)
            assert db.submit(lambda: list(Folder.objects.filter(parent=parent).values_list("pk", flat=True))).result() == [
                f.pk for f in expected
            ]
            expect(
                page.locator(f'.folder-row[data-parent-id="{parent.pk if parent else ""}"] .folder-link>span:not(.folder-title-emoji)'),
            ).to_have_text(
                [f.name.removeprefix("📥 ") for f in expected],
            )

        drag(smart, first, "before")
        order(None, roots + [smart, first, second])
        drag(smart, second, "after")
        order(None, roots + [first, second, smart])
        drag(sibling, child, "before")
        order(first, [sibling, child])
        drag(sibling, child, "after")
        order(first, [child, sibling])
        drag(second, child, "inside")
        order(child, [second])
        drag(smart, second, "before")
        order(child, [smart, second])
        drag(smart, first, "after")
        order(None, roots + [first, smart])
        reveal(second)
        with page.expect_navigation():
            row(second).locator(".folder-link").drag_to(page.get_by_role("link", name="All folders", exact=True))
        order(None, roots + [first, smart, second])
        drag(smart, child, "inside")
        order(child, [smart])
        drag(second, smart, "inside")
        assert db.submit(lambda: Folder.objects.get(parent=smart, name="Items").rules).result() == smart.rules
        reveal(smart)
        with page.expect_navigation():
            row(smart).locator(".folder-link").drag_to(page.get_by_role("link", name="All folders", exact=True))
        reveal(second)
        expect(row(second)).to_have_attribute("data-parent-id", str(smart.pk))
        with page.expect_navigation():
            row(second).locator(".folder-link").drag_to(page.get_by_role("link", name="All folders", exact=True))
        expect(row(first).locator(".folder-toggle")).to_have_attribute("aria-expanded", "false")
        expect(row(child)).to_be_hidden()
        source = row(second).locator(".folder-link").bounding_box()
        target = row(first).bounding_box()
        page.mouse.move(source["x"] + 45, source["y"] + source["height"] / 2)
        page.mouse.down()
        page.mouse.move(target["x"] + 80, target["y"] + target["height"] / 2, steps=12)
        page.mouse.move(target["x"] + 81, target["y"] + target["height"] / 2)
        expect(row(first)).to_have_class(re.compile("drop-active"))
        expect(row(child)).to_be_visible()
        with page.expect_navigation():
            page.mouse.up()
        order(first, [child, sibling, second])
        expect(row(second)).to_be_visible()
        expect(row(child)).to_be_visible()
        # The UI must reject a parent dropped into its own subtree, without a request.
        invalid_moves = []
        page.on("request", lambda request: invalid_moves.append(request.url) if request.url.endswith("/folder/move/") else None)
        source = row(first).locator(".folder-link").bounding_box()
        target = row(child).bounding_box()
        page.mouse.move(source["x"] + 45, source["y"] + source["height"] / 2)
        page.mouse.down()
        page.mouse.move(target["x"] + 80, target["y"] + target["height"] / 2, steps=12)
        page.mouse.move(target["x"] + 81, target["y"] + target["height"] / 2)
        expect(row(child)).not_to_have_class(re.compile("drop-active"))
        page.mouse.up()
        expect(page.locator(".folder-drop-status")).to_be_empty()
        assert invalid_moves == []
        browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("view", ["table", "grid"])
def test_browser_snapshot_drop_on_smart_folder_clears_assignment(live_server, admin_user, browser_runtime, view):
    from playwright.sync_api import sync_playwright, expect
    from urllib.parse import urlsplit
    from archivebox.core.models import Folder, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    source = Folder.objects.create(name="Saved")
    target = Folder.objects.create(name="News", rules={"field": "title", "lookup": "icontains", "value": "news"})
    unassigned, _ = Folder.objects.get_or_create(
        name="📥 Inbox",
        defaults={"rules": {"op": "NOT", "rules": [{"field": "folder", "lookup": "in_folder", "value": "*"}]}},
    )
    crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=admin_user)
    snapshots = [
        Snapshot.objects.create(url=f"https://news.ycombinator.com/item?id={i}", title=title, crawl=crawl, folder=source)
        for i, title in enumerate(["News story", "Other story", "Another story", "Leave saved"])
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        suffix = "grid/" if view == "grid" else ""
        page.goto(f"{admin_url}/admin/core/snapshot/{suffix}?folder={source.pk}")
        row_selector, drag_selector = (".cards .card", ".card-title") if view == "grid" else ("#result_list tbody tr", ".field-title_str")

        def capture(snapshot):
            return page.locator(row_selector).filter(has=page.locator(f'input.action-select[value="{snapshot.pk}"]'))

        with page.expect_navigation():
            capture(snapshots[0]).locator(drag_selector).drag_to(page.locator(f'.folder-row[data-folder-id="{target.pk}"]'))
        expect(page.locator(".messagelist")).to_contain_text("Moved 1 snapshot(s) to No folder")
        expect(capture(snapshots[0])).to_have_count(0)
        for snapshot in snapshots[1:3]:
            page.locator(f'input.action-select[value="{snapshot.pk}"]').check()
        with page.expect_navigation():
            capture(snapshots[1]).locator(drag_selector).drag_to(page.locator(f'.folder-row[data-folder-id="{target.pk}"]'))
        expect(page.locator(".messagelist")).to_contain_text("Moved 2 snapshot(s) to No folder")
        expect(page.locator(row_selector)).to_have_count(1)
        page.locator(f'.folder-row[data-folder-id="{unassigned.pk}"] .folder-link').click()
        for snapshot in snapshots[:3]:
            expect(capture(snapshot)).to_be_visible()
        page.locator(f'.folder-row[data-folder-id="{target.pk}"] .folder-link').click()
        expect(capture(snapshots[0])).to_be_visible()
        expect(capture(snapshots[1])).to_have_count(0)
        browser.close()
    assert list(Snapshot.objects.filter(folder=source).values_list("pk", flat=True)) == [snapshots[3].pk]
    assert set(Snapshot.objects.filter(folder=None).values_list("pk", flat=True)) == {s.pk for s in snapshots[:3]}
    target.refresh_from_db()
    assert target.rules == {"field": "title", "lookup": "icontains", "value": "news"}
    assert not target.children.exists()


@pytest.mark.django_db(transaction=True)
def test_browser_drag_checked_preview_after_streamed_search(live_server, admin_user, browser_runtime):
    from pathlib import Path
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from archivebox.core.models import ArchiveResult, Folder, Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{urlsplit(live_server.url).port}"}
    machine.save(update_fields=["config"])
    destination = Folder.objects.create(name="Drag destination")
    crawl = Crawl.objects.create(urls="https://example.com", created_by=admin_user)
    snapshots = [
        Snapshot.objects.create(url=f"https://example.com/streamdrag/{i}", title=f"Streamdrag capture {i}", crawl=crawl) for i in range(2)
    ]
    png = (Path(__file__).parents[1] / "templates/static/archive.png").read_bytes()
    for snapshot in snapshots:
        path = Path(snapshot.output_dir) / "screenshot/screenshot.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="screenshot",
            status="succeeded",
            output_str="screenshot/screenshot.png",
            output_files={"screenshot.png": {"size": len(png), "mimetype": "image/png"}},
            output_size=len(png),
        )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        admin_url = live_server.url.replace("localhost", "admin.archivebox.localhost")
        page.goto(f"{admin_url}/admin/login/?next=/admin/core/snapshot/")
        page.locator('[name="username"]').fill(admin_user.username)
        page.locator('[name="password"]').fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        page.get_by_role("textbox", name="Search").fill("streamdrag")
        page.locator('select[name="search_mode"]').select_option("meta")
        page.locator('#changelist-search input[name="q"]').press("Enter")
        rows = page.locator("#result_list tbody tr")
        expect(rows).to_have_count(2)
        expect(page.locator("#changelist-search")).not_to_have_attribute("aria-busy", "true")
        expect(rows.first).to_have_attribute("draggable", "true")
        for snapshot in snapshots:
            page.locator(f'input.action-select[value="{snapshot.pk}"]').check()
        image = rows.first.frame_locator(".field-preview_icon iframe").get_by_role("img", name="Screenshot of page", exact=True)
        expect(image).to_be_visible()
        assert rows.first.locator(".field-preview_icon > a").get_attribute("draggable") == "false"
        rows.first.locator(".field-preview_icon").drag_to(page.locator(f'.folder-row[data-folder-id="{destination.pk}"]'))
        expect(page.locator(".messagelist")).to_contain_text("Moved 2 snapshot(s) to Drag destination")
        browser.close()
    assert set(Snapshot.objects.filter(pk__in=[snapshot.pk for snapshot in snapshots]).values_list("folder_id", flat=True)) == {
        destination.pk,
    }
