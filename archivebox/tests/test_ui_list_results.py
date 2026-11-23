"""Snapshot list pages render every result link from value rows, shipping only the manifests they link from.

The fixture collection mirrors production shapes: wget/responses manifests with
thousands of entries, a responses result whose output_str names a directory (so
its link comes from the manifest fallback), a legacy root-relative singlefile,
a plugin with two hooks, a screenshot without a usable file (so the thumbnail
falls back to the next candidate) and failed/queued rows with large manifests.
Plugin icons use stored success/size and canonical card anchors. Favicons,
thumbnail selection and exact shared-file sizes still use full model metadata.
"""

import re
import json
from datetime import timedelta
from html import unescape

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from lxml.html import fromstring, tostring

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.routes_util import build_snapshot_detail_path
from archivebox.crawls.models import Crawl
from archivebox.plugins.discovery import (
    get_plugin_icon,
    get_plugin_icon_sprite,
    get_plugin_list_icon,
    get_plugin_name,
    get_snapshot_role_names,
    get_snapshot_thumbnail_card_order,
)
from archivebox.plugins.output_groups import plugin_icon_is_hidden, plugin_output_sizes, snapshot_thumbnail_result
from archivebox.tests.conftest import ADMIN_TEST_HOST, WEB_TEST_HOST

pytestmark = pytest.mark.django_db

BIG_MANIFEST_ENTRIES = 3000


def test_icon_existence_query_matches_stored_manifest_entries(list_collection):
    from archivebox.core.list_results_util import _HasSavedOutput

    snapshot = list_collection[0]
    cases = [
        {},
        {"stdout.log": {}},
        {"hook.SH": {}, "hook.pid": {}},
        {"hook.sh": {"message": 'commas, braces }{ and \\" quotes'}, "source.py": {}},
        {"bad.json": None, "array.json": [], "number": 42, "bool": True},
        {'escaped"name.json': {}, "later.log": {}},
        {"é.json": {}},
        {"only.log/": {}},
        {"file.log.gz": {}},
        {"first.py": {}, **{f"later/{i}.json": {"size": i} for i in range(BIG_MANIFEST_ENTRIES)}},
    ]
    for index, files in enumerate(cases):
        ArchiveResult.objects.create(snapshot=snapshot, plugin="manifest_check", hook_name=str(index), output_files=files)
    rows = ArchiveResult.objects.filter(snapshot=snapshot).values_list("output_files", _HasSavedOutput("output_files"))
    for files, actual in rows:
        expected = (
            None
            if not files
            else any(isinstance(value, dict) and not key.lower().endswith((".pid", ".log", ".sh")) for key, value in files.items())
        )
        assert actual == expected
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT archivebox_has_saved_output(output_files), CASE WHEN output_files = '{}' THEN NULL ELSE EXISTS ("
                "SELECT 1 FROM json_each(output_files) AS files WHERE files.type = 'object' "
                "AND LOWER(files.key) NOT LIKE %s AND LOWER(files.key) NOT LIKE %s AND LOWER(files.key) NOT LIKE %s) END "
                "FROM core_archiveresult WHERE snapshot_id = %s",
                ["%.pid", "%.log", "%.sh", snapshot.pk.hex],
            )
            values = cursor.fetchall()
        assert len(values) >= len(cases)
        assert all(actual == expected for actual, expected in values)


@pytest.mark.parametrize("language", ["en", "fr", "de"])
def test_admin_action_checkbox_matches_native_widget(snapshot, language):
    from django.contrib.admin import ModelAdmin, AdminSite
    from django.utils.translation import override
    from archivebox.core.admin_snapshots import SnapshotAdmin

    snapshot.title = 'Quotes " & <tags> and café'
    snapshot.url = 'https://example.com/?q="&x=<x>'
    site = AdminSite()
    with override(language):
        expected = str(ModelAdmin(Snapshot, site).action_checkbox(snapshot))
        actual = str(SnapshotAdmin(Snapshot, site).action_checkbox(snapshot))
    assert actual == expected


def test_thumbnail_query_selects_explicit_file_without_transferring_other_assets(client, admin_user, list_collection):
    snapshot = list_collection[0]
    result = snapshot.archiveresult_set.get(plugin="responses")
    result.output_str = "responses/all/20261012T000001__GET__article.html"
    result.save(update_fields=["output_str"])
    expected, card_id, sizes = _expected_links(snapshot)
    client.force_login(admin_user)
    url = reverse("admin:core_snapshot_changelist")
    assert client.get(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    row = _row(response.content.decode(), f'value="{snapshot.pk}"')
    assert _rendered_fragments(row) == expected
    assert f"_card/{card_id}" in row
    manifest = _manifests_shipped(captured.captured_queries)[("responses", "succeeded")]
    assert json.loads(manifest) == {
        "all/20261012T000001__GET__article.html": result.output_files["all/20261012T000001__GET__article.html"],
    }
    assert sizes["responses"] == result.output_size


@pytest.mark.parametrize(
    ("output", "files"),
    [
        ("responses/", {"responses/": {"root_relative": True}, "index.html": {"size": 2}}),
        ("responses/README", {"README": {"size": 1, "root_relative": True}, "index.html": {"size": 2}}),
        ("\u2003responses/README\u2003", {"README": {"size": 1}, "index.html": {"size": 2}}),
        ("responses/index.html", {"responses/index.html": {"size": 1, "root_relative": True}, "index.html": {"size": 2}}),
        ("README", {"responses/README": {"size": 1}}),
        ("responses/missing.pdf", {"source.py": {"size": 1}}),
        ("responses/legacy.pdf", {}),
        ("directory", {"a/INDEX.HTML/": {"size": 1}, "index.html": {"size": 2}}),
        ("directory", {"docs/é.html": {"size": 2}, "tie.html": {"size": 2}}),
        ("directory", {"first.pdf": {"size": "4"}, "last.pdf": {"size": 5}}),
        ("responses/../private.txt", {"../private.txt": {"size": 1}, "index.html": {"size": 2}}),
        ("directory", {"index.html": None, "index.pdf": {"size": 1}}),
        ('responses/a"b.html', {'a"b.html': {"size": 1}, "index.html": {"size": 2}}),
    ],
)
def test_thumbnail_projection_preserves_path_resolution(snapshot, output, files):
    from archivebox.core.list_results_util import load_snapshot_list_results

    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="responses",
        status="succeeded",
        output_str=output,
        output_files=files,
        output_size=10,
    )
    result.refresh_from_db()
    expected = ArchiveResult.resolve_embed_path("responses", output, result.output_files)
    summary = load_snapshot_list_results([snapshot])[snapshot.pk]
    assert summary.results[0].id == str(result.pk)
    assert summary.results[0].embed_path() == expected
    assert summary.output_sizes == {"responses": 10}


def test_thumbnail_projection_keeps_shared_file_sizes(list_collection):
    from archivebox.core.list_results_util import load_snapshot_list_results

    snapshot = list_collection[0]
    first = snapshot.archiveresult_set.get(plugin="responses")
    first.output_str = "responses/all/20261012T000001__GET__article.html"
    first.save(update_fields=["output_str"])
    _result(
        snapshot,
        "responses",
        hook="99",
        output_str="responses/new.html",
        output_files={"new.html": {"size": 50}, **first.output_files},
    )
    summary = load_snapshot_list_results([snapshot])[snapshot.pk]
    assert summary.output_sizes["responses"] == first.output_size + 50
    assert all(len(json.loads(row.output_files_json)) >= BIG_MANIFEST_ENTRIES for row in summary.results if row.plugin == "responses")


@pytest.mark.parametrize("plugin", ["git", "wget", "liteparse", "headers", "dns", "hashes"])
def test_plugin_icons_need_no_manifest(client, admin_user, list_collection, plugin):
    snapshot = list_collection[0]
    snapshot.archiveresult_set.filter(plugin=plugin).delete()
    result = _result(
        snapshot,
        plugin,
        output_str=plugin,
        output_files={f"repo/src/{i}.py": {"size": 100} for i in range(BIG_MANIFEST_ENTRIES)},
    )
    client.force_login(admin_user)
    url = reverse("admin:core_snapshot_changelist")
    assert client.get(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    row = _row(response.content.decode(), f'value="{snapshot.pk}"')
    assert _rendered_fragments(row)[plugin] == f"#{plugin}"
    assert _manifests_shipped(captured.captured_queries)[(plugin, "succeeded")] is None
    assert result.output_size == BIG_MANIFEST_ENTRIES * 100
    result.status = "failed"
    result.save(update_fields=["status"])
    response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    assert plugin not in _rendered_fragments(_row(response.content.decode(), f'value="{snapshot.pk}"'))


@override_settings(PUBLIC_INDEX=True)
def test_public_icon_retains_legacy_output_without_stored_size(client, list_collection):
    snapshot = list_collection[0]
    result = snapshot.archiveresult_set.get(plugin="singlefile")
    ArchiveResult.objects.filter(pk=result.pk).update(output_size=0)
    response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    row = _row(response.content.decode(), f"/{snapshot.archive_path_from_db}")
    assert _rendered_fragments(row)["singlefile"] == "#singlefile"


@pytest.mark.parametrize(
    ("output", "files", "visible"),
    [
        ("1 screencast frames (0 kept)", {"hook.sh": {"size": 199}}, False),
        ("1kb text indexed", {"hook.sh": {"size": 100}, "stdout.log": {"size": 80}, "hook.pid": {"size": 6}}, False),
        ("/old/archive/git", {"saved.mp3": {"size": 100}}, False),
        ("git", {"hook.sh": {"size": 100}, "repo/source.py": {"size": 100}}, True),
        ("git/legacy.html", {}, True),
    ],
)
def test_icon_availability_excludes_hook_artifacts_and_invalid_paths(client, admin_user, list_collection, output, files, visible):
    snapshot = list_collection[0]
    snapshot.archiveresult_set.filter(plugin="git").delete()
    result = _result(snapshot, "git", output_str=output, output_files=files)
    ArchiveResult.objects.filter(pk=result.pk).update(output_size=200)
    client.force_login(admin_user)
    url = reverse("admin:core_snapshot_changelist")
    assert client.get(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    row = _row(response.content.decode(), f'value="{snapshot.pk}"')
    assert ("git" in _rendered_fragments(row)) == visible
    assert _manifests_shipped(captured.captured_queries)[("git", "succeeded")] is None


@pytest.mark.django_db(transaction=True)
def test_plugin_icon_anchors_open_the_same_previews(snapshot, live_server, browser_runtime, admin_user):
    from urllib.parse import urlsplit

    from playwright.sync_api import expect, sync_playwright

    from archivebox.machine.models import Machine
    from archivebox.tests.test_snapshot_output_stacks import save_output

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    snapshot.permissions = "public"
    snapshot.status = "sealed"
    snapshot.save()
    results = [save_output(snapshot, plugin) for plugin in ("git", "headers", "singlefile", "wget")]
    results.append(save_output(snapshot, "readability", filename="replacement.html"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            listing = f"http://admin.archivebox.localhost:{port}/admin/core/snapshot/"
            page.goto(f"http://admin.archivebox.localhost:{port}/admin/login/?next=/admin/core/snapshot/")
            page.locator('[name="username"]').fill(admin_user.username)
            page.locator('[name="password"]').fill("testpassword")
            page.get_by_role("button", name="Log in", exact=True).click()
            checkbox = page.locator("#result_list input.action-select")
            checkbox.check()
            expect(checkbox).to_be_checked()
            checkbox.uncheck()
            page.locator("#action-toggle").check()
            expect(checkbox).to_be_checked()
            page.locator("#action-toggle").uncheck()
            expect(checkbox).not_to_be_checked()
            for result in results:
                page.goto(listing)
                pile = page.locator(".files-icon-pile").filter(has=page.locator(f".files-icon-plugin--{result.plugin}"))
                pile.locator(".files-icon-pile-top").hover()
                pile.locator(f".files-icon-pile-popup .files-icon-plugin--{result.plugin}").click()
                expect(page.locator(f'.selected-card[data-plugin-name="{result.plugin}"]')).to_have_count(1)
                frame = page.locator("#main-frame")
                expect(frame).to_have_attribute("src", re.compile(r".+"))
                card_src = frame.get_attribute("src")
                assert urlsplit(page.url).fragment == result.plugin
                page.goto(page.url.split("#")[0] + "#" + result.embed_path())
                expect(frame).to_have_attribute("src", card_src)
        finally:
            browser.close()


@pytest.mark.parametrize("plugin", ["archivedotorg", "opendataloader", "chrome"])
def test_branded_icon_namespace_does_not_duplicate_artwork_per_row(plugin):
    original = fromstring(str(get_plugin_icon(plugin))).find("svg")
    icon = fromstring(str(get_plugin_list_icon(plugin)))
    assert icon.xpath(f'.//use[@href="#abx-icon-{plugin}"]')
    symbol = fromstring(str(get_plugin_icon_sprite([plugin]))).find("symbol")
    assert symbol is not None
    # Keep the original paths, colors and embedded image data exactly intact.
    assert [tostring(child) for child in symbol] == [tostring(child) for child in original]
    assert symbol.get("viewbox") == original.get("viewbox")
    assert symbol.get("fill") == original.get("fill")


def _result(snapshot, plugin, status=ArchiveResult.StatusChoices.SUCCEEDED, *, hook="50", output_str="", output_files=None):
    output_files = output_files or {}
    return ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        hook_name=f"on_Snapshot__{hook}_{plugin}.py",
        status=status,
        output_str=output_str,
        output_files=output_files,
        output_size=sum(int(metadata.get("size") or 0) for metadata in output_files.values()),
    )


@pytest.fixture
def list_collection(admin_user, db):
    crawl = Crawl.objects.create(urls="https://list-results.example", created_by=admin_user, config={"PERMISSIONS": "public"})
    sealed = Snapshot.objects.create(
        url="https://list-results.example/article",
        title="Sealed list row",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
    )
    _result(
        sealed,
        "wget",
        output_str="wget/list-results.example/article.html",
        output_files={
            "list-results.example/article.html": {"size": 5000, "mimetype": "text/html"},
            **{
                f"list-results.example/assets/{index}.js": {"size": index, "mimetype": "text/javascript"}
                for index in range(BIG_MANIFEST_ENTRIES)
            },
        },
    )
    _result(
        sealed,
        "responses",
        hook="24",
        output_str="responses/list-results.example/article",
        output_files={
            **{
                f"all/20261012T000000__GET__{index}.png": {"size": 900 + index, "mimetype": "image/png"}
                for index in range(BIG_MANIFEST_ENTRIES)
            },
            "all/20261012T000001__GET__article.html": {"size": 7000, "mimetype": "text/html"},
            "all/20261012T000002__GET__tie.html": {"size": 7000, "mimetype": "text/html"},
        },
    )
    _result(sealed, "singlefile", output_str="singlefile.html", output_files={"singlefile.html": {"size": 3000, "root_relative": True}})
    _result(sealed, "chrome", hook="01", output_files={"browser.json": {"size": 40}})
    _result(sealed, "chrome", hook="02", output_str="navigated", output_files={"navigation.json": {"size": 60}})
    _result(sealed, "favicon", output_str="favicon/favicon.ico", output_files={"favicon.ico": {"size": 300}})
    # No usable file: the thumbnail must fall back to the next card candidate.
    _result(sealed, "screenshot", output_str="Chrome crashed")
    _result(sealed, "hashes", output_str="3 files hashed", output_files={"hashes.json": {"size": 80}})
    _result(
        sealed,
        "title",
        ArchiveResult.StatusChoices.FAILED,
        output_str="Timed out",
        output_files={f"partial/{index}.txt": {"size": index} for index in range(BIG_MANIFEST_ENTRIES)},
    )
    _result(sealed, "git", ArchiveResult.StatusChoices.QUEUED)

    started = Snapshot.objects.create(
        url="https://list-results.example/live",
        title="Started list row",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
    )
    _result(started, "screenshot", output_str="screenshot/screenshot.png", output_files={"screenshot.png": {"size": 2048}})
    _result(started, "dom", output_str="dom/output.html", output_files={"output.html": {"size": 512}})
    _result(started, "wget", ArchiveResult.StatusChoices.STARTED)
    return [sealed, started]


def _expected_links(snapshot):
    """Icon fragments, thumbnail card id and sizes, from full model instances."""
    results = list(snapshot.archiveresult_set.exclude(plugin="").order_by("plugin", "id"))
    first_succeeded = {}
    for result in results:
        if result.status == ArchiveResult.StatusChoices.SUCCEEDED:
            first_succeeded.setdefault(result.plugin, result)
    fragments = {}
    for plugin, result in first_succeeded.items():
        if plugin_icon_is_hidden(plugin) or not str(get_plugin_icon(plugin)).strip() or not result.output_size:
            continue
        fragments[plugin] = build_snapshot_detail_path("", output_path=get_plugin_name(plugin), prefix="")
    card = snapshot_thumbnail_result(results)
    return fragments, (str(card.id) if card else None), plugin_output_sizes(results)


def _rendered_fragments(row_html):
    """Every icon link in a row as {plugin: "#fragment"}; each plugin must agree on one link."""
    fragments = {}
    for href, plugin in re.findall(r'<a href="([^"]*)" class="[^"]*files-icon-plugin--([a-z0-9_]+)', row_html):
        fragment = "#" + unescape(href).split("#", 1)[1]
        assert fragments.setdefault(plugin, fragment) == fragment
    return fragments


def _row(html, marker):
    return next(row for row in re.findall(r"<tr\b.*?</tr>", html, re.S) if marker in row)


def _manifests_shipped(captured_queries):
    """Re-run the page's one ArchiveResult query: {(plugin, status): manifest JSON it returned}."""
    result_queries = [query["sql"] for query in captured_queries if 'FROM "core_archiveresult"' in query["sql"]]
    assert len(result_queries) == 1, "icons, sizes, favicons, thumbnails and progress must share one ArchiveResult query"
    with connection.cursor() as cursor:
        cursor.execute(result_queries[0])
        # values_list order: id, snapshot_id, plugin, status, output_size, output_str, output_files
        return {(row[2], row[3]): row[6] for row in cursor.fetchall()}


def _assert_only_linkable_manifests_shipped(captured_queries):
    shipped = _manifests_shipped(captured_queries)
    card_plugins = set(get_snapshot_thumbnail_card_order())
    for (plugin, status), manifest in shipped.items():
        linkable = (
            (status == ArchiveResult.StatusChoices.SUCCEEDED and plugin in get_snapshot_role_names("list_icon"))
            or plugin in card_plugins
            or plugin == "chrome"
        )
        assert (manifest is not None) == linkable, (plugin, status)
    # The failed hook's 3,000-entry manifest is never transferred or decoded.
    assert shipped[("title", ArchiveResult.StatusChoices.FAILED)] is None
    assert shipped[("git", ArchiveResult.StatusChoices.QUEUED)] is None


def _assert_icons_drawn_from_one_sprite(html):
    """Row icons <use> symbols that the page defines exactly once (see get_plugin_list_icon)."""
    used = set(re.findall(r'<use href="#(abx-icon-[a-z0-9_]+)">', html))
    defined = re.findall(r'<symbol id="(abx-icon-[a-z0-9_]+)"', html)
    assert used, "list rows should draw their icons from the page sprite"
    assert len(defined) == len(set(defined)), "the icon sprite must be emitted once per page"
    assert used <= set(defined)
    assert html.index("<symbol ") < html.index("<use href=")


@override_settings(PUBLIC_INDEX=True)
def test_public_index_links_match_model_instances_and_skip_unrendered_manifests(client, list_collection):
    sealed, started = list_collection
    with CaptureQueriesContext(connection) as captured:
        response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    html = response.content.decode()
    sealed_row = _row(html, f"/{sealed.archive_path_from_db}")
    started_row = _row(html, f"/{started.archive_path_from_db}")

    fragments, card_id, sizes = _expected_links(sealed)
    assert _rendered_fragments(sealed_row) == fragments
    # File icons open the plugin card; resolving its preview belongs on detail.
    assert fragments["wget"] == "#wget"
    assert fragments["responses"] == "#responses"
    assert fragments["singlefile"] == "#singlefile"
    assert fragments["chrome"] == "#chrome"
    assert "screenshot" not in fragments
    # The screenshot has no usable file, so the card falls back to responses.
    assert ArchiveResult.objects.get(pk=card_id).plugin == "responses"
    assert f"_card/{card_id}" in sealed_row
    assert 'favicon/favicon.ico" data-fallbacks=""' in sealed_row
    succeeded = sealed.archiveresult_set.filter(status=ArchiveResult.StatusChoices.SUCCEEDED).count()
    assert f'title="{succeeded} successful outputs"' in sealed_row
    # Sizes are each plugin's summed output_size, as stored.
    assert sizes["chrome"] == sum(sealed.archiveresult_set.filter(plugin="chrome").values_list("output_size", flat=True)) == 100

    _, started_card_id, _ = _expected_links(started)
    assert f"_card/{started_card_id}" in started_row
    assert "2/3 hooks" in started_row
    assert 'data-tooltip="screenshot"' in started_row and 'data-tooltip="dom"' in started_row

    _assert_only_linkable_manifests_shipped(captured.captured_queries)
    _assert_icons_drawn_from_one_sprite(html)


def test_admin_changelist_links_match_model_instances_and_skip_unrendered_manifests(client, admin_user, list_collection):
    sealed, _started = list_collection
    client.force_login(admin_user)
    url = reverse("admin:core_snapshot_changelist")
    # The first admin request provisions per-process rows (machine, API token).
    assert client.get(url, HTTP_HOST=ADMIN_TEST_HOST).status_code == 200
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    row = _row(response.content.decode(), f'value="{sealed.pk}"')

    fragments, card_id, _sizes = _expected_links(sealed)
    # The admin lists plugins whose first successful result saved bytes; here
    # that is every linked plugin, so both pages show the same links.
    assert _rendered_fragments(row) == fragments
    assert f"_card/{card_id}" in row
    assert re.search(r'class="snapshot-url-favicon" src="[^"]*favicon/favicon\.ico"', row)

    _assert_only_linkable_manifests_shipped(captured.captured_queries)
    _assert_icons_drawn_from_one_sprite(response.content.decode())
    html = response.content.decode()
    used = set(re.findall(r'<use href="#(abx-icon-[a-z0-9_]+)">', html))
    defined = set(re.findall(r'<symbol id="(abx-icon-[a-z0-9_]+)"', html))
    assert defined == used, "the list must not ship drawings for plugins absent from its rows"
    for symbol_id in used:
        assert html.index(f'<symbol id="{symbol_id}"') < html.index(f'<use href="#{symbol_id}"')


def test_admin_grid_keeps_running_and_sealed_cards_without_hidden_file_icons(client, admin_user, list_collection):
    sealed, started = list_collection
    # The compact grid shows both captures without the desktop table's file piles.
    Snapshot.objects.filter(pk=started.pk).update(bookmarked_at=sealed.bookmarked_at + timedelta(minutes=1))
    client.force_login(admin_user)
    response = client.get(reverse("admin:grid"), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    html = response.content.decode()
    cards = fromstring(html).find_class("cards")[0].xpath("./div")
    assert len(cards) == 2
    assert [card.find_class("title-text")[0].text_content() for card in cards] == ["Started list row", "Sealed list row"]
    assert [card.xpath('.//input[@name="_selected_action"]/@value')[0] for card in cards] == [str(started.pk), str(sealed.pk)]
    for card in cards:
        thumbnails = card.find_class("card-thumbnail")
        assert len(thumbnails) == 1 and thumbnails[0].tag == "a" and thumbnails[0].get("href")
        assert not card.find_class("files-icons")


def test_admin_icon_order_counts_all_hook_files_once(client, admin_user, list_collection):
    snapshot = list_collection[0]
    # chrome's two hooks save 100 bytes, larger than hashes' 80 bytes. Keeping
    # only its first successful hook incorrectly sorts chrome as 40 bytes.
    client.force_login(admin_user)
    response = client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    row = _row(response.content.decode(), f'value="{snapshot.pk}"')
    assert row.index('data-tooltip="chrome"') < row.index('data-tooltip="hashes"')


@pytest.mark.parametrize("title", [None, "Pending...", "https://list-results.example/article", "Saved title"])
def test_admin_untitled_url_opens_snapshot_details(client, admin_user, list_collection, title):
    snapshot = list_collection[0]
    Snapshot.objects.filter(pk=snapshot.pk).update(title=title)
    client.force_login(admin_user)
    response = client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    row = fromstring(_row(response.content.decode(), f'value="{snapshot.pk}"'))
    visible_url = row.find_class("snapshot-original-url")[0]
    detail_url = row.find_class("snapshot-title-detail-hitbox")[0].get("href")
    assert visible_url.get("href") == (snapshot.url if title == "Saved title" else detail_url)
    assert snapshot.url.removeprefix("https://") in visible_url.text_content()


def test_list_result_sizes_deduplicate_overlapping_failed_hooks_in_one_query(list_collection):
    from archivebox.core.list_results_util import load_snapshot_list_results

    snapshot = list_collection[0]
    plugin_dir = snapshot.output_dir / "dns"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    for name, content in {"shared.txt": b"12345", "first.txt": b"1234567", "second.txt": b"12345678901"}.items():
        (plugin_dir / name).write_bytes(content)
    _result(snapshot, "dns", hook="10", output_files={"shared.txt": {"size": 5}, "first.txt": {"size": 7}})
    _result(
        snapshot,
        "dns",
        ArchiveResult.StatusChoices.FAILED,
        hook="20",
        output_files={"shared.txt": {"size": 5}, "second.txt": {"size": 11}},
    )

    with CaptureQueriesContext(connection) as captured:
        summary = load_snapshot_list_results([snapshot])[snapshot.pk]
        sizes = summary.output_sizes
    assert len(captured) == 1
    assert sizes["dns"] == sum(path.stat().st_size for path in plugin_dir.iterdir()) == 23
    shipped = _manifests_shipped(captured.captured_queries)
    assert shipped[("dns", ArchiveResult.StatusChoices.FAILED)] is not None
    assert shipped[("title", ArchiveResult.StatusChoices.FAILED)] is None
    single = next(row for row in summary.results if row.plugin == "favicon")
    assert single.embed_path() is not None
    assert single._output_files is None
    assert single.embed_path() is not None
    siblings = [row for row in summary.results if row.plugin == "dns"]
    assert len(siblings) == 2
    assert all(row._output_files is not None for row in siblings)


def test_list_results_order_references_without_sorting_manifest_payloads(list_collection):
    from archivebox.core.list_results_util import load_snapshot_list_results

    snapshot = list_collection[0]
    first = _result(snapshot, "dns", hook="99", output_str="dns/first.json", output_files={"first.json": {"size": 5}})
    _result(snapshot, "dns", hook="00", output_str="dns/second.json", output_files={"second.json": {"size": 7}})
    with CaptureQueriesContext(connection) as captured:
        summaries = load_snapshot_list_results(list_collection)
    assert len(captured) == 1
    for snapshot in list_collection:
        expected = list(snapshot.archiveresult_set.exclude(plugin="").order_by("plugin", "id").values_list("pk", flat=True))
        assert [row.id for row in summaries[snapshot.pk].results] == [str(pk) for pk in expected]
    selected = summaries[first.snapshot_id].first_succeeded_by_plugin()["dns"]
    assert selected.id == str(first.pk)
    assert selected.embed_path() == "dns/first.json"
    assert "ORDER BY" not in captured[0]["sql"]
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("EXPLAIN QUERY PLAN " + captured[0]["sql"])
            plan = " ".join(str(row[-1]) for row in cursor.fetchall())
        assert "USE TEMP B-TREE" not in plan, plan


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"output.html": 500, "nested/INDEX.HTML": 1, "other/index.html": 1000}, "nested/INDEX.HTML"),
        ({"first/foo.html": 7, "second/bar.PDF": 8, "large.png": 1000}, "second/bar.PDF"),
        ({"first/foo.html": 7, "second/bar.html": 7}, "first/foo.html"),
        ({"image.png": 1000, "nested/.html": 9999, "article.json": 1}, "article.json"),
        ({"nested/.html": 9999, "image.png": 1}, "image.png"),
        ({"stdout.log": 1000, "hook.pid": 1000, "run.sh": 1000, "result.txt": 1}, "result.txt"),
        ({"unknown": 1000, "nested/.html": 9999}, None),
        ({"negative.html": -1, "valid.html": 1}, "valid.html"),
    ],
)
def test_list_fallback_preserves_name_extension_size_and_tie_priorities(snapshot, files, expected):
    from archivebox.core.list_results_util import load_snapshot_list_results

    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="responses",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_files={path: {"size": size} for path, size in files.items()},
    )
    expected_path = f"responses/{expected}" if expected is not None else None
    assert result.embed_path() == expected_path
    summary = load_snapshot_list_results([snapshot])[snapshot.pk]
    assert next(row for row in summary.results if row.id == str(result.pk)).embed_path() == expected_path


def test_list_fallback_ignores_malformed_sizes(snapshot):
    from archivebox.core.list_results_util import load_snapshot_list_results

    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="responses",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_files={"malformed.html": {"size": "invalid"}, "valid.html": {"size": 1}},
    )
    summary = load_snapshot_list_results([snapshot])[snapshot.pk]
    assert next(row for row in summary.results if row.id == str(result.pk)).embed_path() == "responses/valid.html"


@override_settings(PUBLIC_INDEX=True)
def test_warm_public_list_reflects_result_save_without_modified_at(client, list_collection):
    snapshot = list_collection[0]
    result = snapshot.archiveresult_set.get(plugin="favicon")
    assert client.get("/public/", HTTP_HOST=WEB_TEST_HOST).status_code == 200
    previous_modified_at = result.modified_at
    result.output_str = "favicon/replacement.ico"
    result.output_files = {"replacement.ico": {"size": 300}}
    result.save(update_fields=["output_str", "output_files"])
    result.refresh_from_db()
    assert result.modified_at == previous_modified_at

    response = client.get("/public/", HTTP_HOST=WEB_TEST_HOST)
    assert response.status_code == 200
    row = _row(response.content.decode(), f"/{snapshot.archive_path_from_db}")
    assert 'favicon/replacement.ico" data-fallbacks=""' in row
    assert 'favicon/favicon.ico"' not in row


def test_admin_detail_preserves_explicit_result_output_path(client, admin_user, list_collection):
    snapshot, _started = list_collection
    result = snapshot.archiveresult_set.get(plugin="favicon")
    result.output_str = "favicon/selected.ico"
    result.output_files = {"favicon.ico": {"size": 300}, "selected.ico": {"size": 100}}
    result.save(update_fields=["output_str", "output_files"])
    assert result.embed_path() == "favicon/selected.ico"

    client.force_login(admin_user)
    response = client.get(reverse("admin:core_snapshot_change", args=[snapshot.pk]), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    page = response.content.decode()
    favicon = re.search(r'<img src="([^"]+)" alt="Favicon"', page)
    assert favicon is not None
    assert favicon.group(1).endswith("/favicon/selected.ico")
