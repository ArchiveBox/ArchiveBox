"""Snapshot list pages render every result link from value rows, shipping only the manifests they link from.

The fixture collection mirrors production shapes: wget/responses manifests with
thousands of entries, a responses result whose output_str names a directory (so
its link comes from the manifest fallback), a legacy root-relative singlefile,
a plugin with two hooks, a screenshot without a usable file (so the thumbnail
falls back to the next candidate) and failed/queued rows with large manifests.
Expected links come from loading full ArchiveResult model instances, the path
these pages used before.
"""

import re
from datetime import timedelta
from html import unescape

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.routes_util import build_snapshot_detail_path, get_snapshot_output_anchor
from archivebox.crawls.models import Crawl
from archivebox.plugins.discovery import get_plugin_icon, get_snapshot_thumbnail_card_order
from archivebox.plugins.output_groups import plugin_icon_is_hidden, plugin_output_sizes, snapshot_thumbnail_result
from archivebox.tests.conftest import ADMIN_TEST_HOST, WEB_TEST_HOST

pytestmark = pytest.mark.django_db

BIG_MANIFEST_ENTRIES = 3000


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
        embed_path = result.embed_path()
        if plugin_icon_is_hidden(plugin) or not str(get_plugin_icon(plugin)).strip() or not embed_path:
            continue
        fragments[plugin] = build_snapshot_detail_path("", output_path=get_snapshot_output_anchor(plugin, embed_path), prefix="")
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
        return {(row[2], row[3]): row[-1] for row in cursor.fetchall()}


def _assert_only_linkable_manifests_shipped(captured_queries):
    shipped = _manifests_shipped(captured_queries)
    card_plugins = set(get_snapshot_thumbnail_card_order())
    for (plugin, status), manifest in shipped.items():
        linkable = status == ArchiveResult.StatusChoices.SUCCEEDED or plugin in card_plugins
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
    # Links resolved through each path the resolver has: output_str naming a
    # manifest key (wget), the extension/size fallback (responses: earliest of
    # the tied largest .html), a legacy root-relative file, and the first hook.
    assert fragments["wget"] == "#wget/list-results.example/article.html"
    assert fragments["responses"] == "#responses/all/20261012T000001__GET__article.html"
    assert fragments["singlefile"] == "#singlefile"
    assert fragments["chrome"] == "#chrome/browser.json"
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


def test_admin_grid_draws_icons_from_one_sprite_even_when_first_card_is_running(client, admin_user, list_collection):
    sealed, started = list_collection
    # The newest card is the running one, whose icons the grid hides.
    Snapshot.objects.filter(pk=started.pk).update(bookmarked_at=sealed.bookmarked_at + timedelta(minutes=1))
    client.force_login(admin_user)
    response = client.get(reverse("admin:grid"), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    html = response.content.decode()
    assert html.index("Started list row") < html.index("Sealed list row")
    _assert_icons_drawn_from_one_sprite(html)


def test_admin_icon_order_counts_all_hook_files_once(client, admin_user, list_collection):
    snapshot = list_collection[0]
    # chrome's two hooks save 100 bytes, larger than hashes' 80 bytes. Keeping
    # only its first successful hook incorrectly sorts chrome as 40 bytes.
    client.force_login(admin_user)
    response = client.get(reverse("admin:core_snapshot_changelist"), HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    row = _row(response.content.decode(), f'value="{snapshot.pk}"')
    assert row.index('data-tooltip="chrome"') < row.index('data-tooltip="hashes"')


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
