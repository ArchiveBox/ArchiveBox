"""Sidebar work stays bounded by navigation entries, not per-entry menus/queries."""

from time import perf_counter

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Snapshot, SnapshotTag, Tag
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import ADMIN_TEST_HOST


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["tags", "domains"])
def test_large_sidebar_shares_one_action_menu(admin_client, admin_user, mode):
    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    tags = Tag.objects.bulk_create([Tag(name=f"Research topic {i:04}") for i in range(1000)])
    snapshots = Snapshot.objects.bulk_create(
        [Snapshot(crawl=crawl, url=f"https://research{i:04}.com/", timestamp=str(1900500000 + i)) for i in range(1000)],
    )
    SnapshotTag.objects.bulk_create([SnapshotTag(snapshot=snapshot, tag=tag) for snapshot, tag in zip(snapshots, tags, strict=True)])
    start = perf_counter()
    with CaptureQueriesContext(connection) as queries:
        response = admin_client.get("/admin/core/snapshot/", {"sidebar": mode}, HTTP_HOST=ADMIN_TEST_HOST)
    elapsed = (perf_counter() - start) * 1000
    assert response.status_code == 200
    assert len(response.context["sidebar_entries"]) == 100
    html = response.content.decode()
    print(f"{mode}: {elapsed:.1f} ms, {len(queries)} queries, {len(html):,} bytes")
    assert html.count('id="library-entry-menu"') == 1
    assert len(queries) < 50


@pytest.mark.django_db
def test_sidebar_cursors_search_and_parent_order(admin_client, admin_user):
    from archivebox.core.models import Folder
    from archivebox.core.smart_folders import CHILDREN_RULES
    import re

    parent = Folder.objects.create(name="Parent", rules=CHILDREN_RULES)
    Folder.objects.bulk_create([Folder(name=f"Child {i:03}", parent=parent) for i in range(205)])
    Tag.objects.bulk_create([Tag(name=f"Topic {i:03}") for i in range(205)])
    path = "/admin/core/snapshot/sidebar/"

    def fetch(**params):
        response = admin_client.get(path, params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        return response.json()

    first = fetch(sidebar="tags")
    second = fetch(sidebar="tags", cursor=first["next"])
    third = fetch(sidebar="tags", cursor=second["next"])
    assert [len(page["choices"]) for page in (first, second, third)] == [100, 100, 5]
    assert len({tag["id"] for page in (first, second, third) for tag in page["choices"]}) == 205
    assert third["next"] == ""
    assert fetch(sidebar="tags", sidebar_q="204")["choices"][0]["name"] == "Topic 204"
    assert (
        admin_client.get(path, {"sidebar": "tags", "sidebar_q": "changed", "cursor": first["next"]}, HTTP_HOST=ADMIN_TEST_HOST).status_code
        == 400
    )
    roots = fetch(sidebar="folders")
    assert "Parent" in roots["html"] and "Child" not in roots["html"]
    children = fetch(sidebar="folders", parent=str(parent.pk))
    assert len(re.findall('class="folder-row ', children["html"])) == 100
    assert children["next"]
    result = fetch(sidebar="folders", sidebar_q="Child 204")["html"]
    assert result.index('data-folder-name="Parent"') < result.index('data-folder-name="Child 204"')


@pytest.mark.django_db
def test_domains_page_seeks_shared_index(admin_client, admin_user):
    from urllib.parse import urlsplit, parse_qs

    crawl = Crawl.objects.create(created_by=admin_user, urls="https://example.com/")
    Snapshot.objects.bulk_create([Snapshot(crawl=crawl, url=f"https://site{i:03}.com/", timestamp=str(1910000000 + i)) for i in range(105)])

    def fetch(params):
        response = admin_client.get("/admin/domains/", params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        return response

    with CaptureQueriesContext(connection) as queries:
        first = fetch({})
    captured = list(queries)
    assert len(first.context["domains"]) == 50
    assert [row["domain"] for row in first.context["domains"]] == [f"site{i:03}.com" for i in range(50)]
    second = fetch(parse_qs(urlsplit(first.context["domain_next_url"]).query))
    assert [row["domain"] for row in second.context["domains"]] == [f"site{i:03}.com" for i in range(50, 100)]
    previous = fetch(parse_qs(urlsplit(second.context["domain_previous_url"]).query))
    assert list(previous.context["domains"]) == list(first.context["domains"])
    assert "cursor" not in second.context["cl"]["params"]
    assert [row["domain"] for row in fetch({"q": "104"}).context["domains"]] == ["site104.com"]
    assert not any("OFFSET" in query["sql"].upper() for query in captured)
    grouped = next(query["sql"] for query in captured if '"crawl__persona_id"' in query["sql"] and "LIMIT 1001" in query["sql"])
    assert '"core_snapshot"."url"' in grouped
