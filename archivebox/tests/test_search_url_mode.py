import re
from urllib.parse import urlencode

import pytest
from asgiref.sync import async_to_sync

from archivebox.core.models import Snapshot, Tag
from archivebox.machine.models import Machine
from archivebox.search.query import apply_snapshot_search, query_search_index

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def url_rows(crawl):
    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://www.example.com/Needle/{i:03}",
                title=f"Title {64 - i:03}",
                timestamp=str(1900000000 + i),
                crawl=crawl,
                status=Snapshot.StatusChoices.SEALED,
                config={"PERMISSIONS": "public"},
            )
            for i in range(65)
        ],
    )
    for i, field in enumerate(("title", "tag", "content")):
        decoy = Snapshot.objects.create(
            url=f"https://elsewhere.example/{i}",
            title="needle" if field == "title" else "Unrelated",
            timestamp=str(1900000100 + i),
            crawl=crawl,
            status=Snapshot.StatusChoices.SEALED,
            config={"PERMISSIONS": "public"},
        )
        if field == "tag":
            decoy.tags.add(Tag.objects.create(name="needle"))
        if field == "content":
            output = decoy.output_dir / "article" / "output.txt"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("needle", encoding="utf-8")
    private = Snapshot.objects.create(
        url="https://example.com/needle/private",
        title="Private",
        crawl=crawl,
        config={"PERMISSIONS": "private"},
    )
    return rows, private


def consume(response):
    assert response.status_code == 200

    async def chunks():
        return b"".join([chunk async for chunk in response.streaming_content])

    return async_to_sync(chunks)()


@pytest.mark.parametrize("surface", ["admin", "public"])
def test_url_only_search_stream_and_pages(admin_client, client, url_rows, surface):
    Machine.from_json({"config": {"PUBLIC_INDEX": True, "SNAPSHOTS_PER_PAGE": 50}})
    rows, private = url_rows
    if surface == "admin":
        browser, path, host = admin_client, "/admin/core/snapshot/", "admin.archivebox.localhost:5797"
        expected = {row.pk for row in rows} | {private.pk}
    else:
        client.logout()
        browser, path, host = client, "/public/", "web.archivebox.localhost:5797"
        expected = {row.pk for row in rows}
    params = {"q": "nEeDlE", "search_mode": "url"}
    initial = browser.get(path, params, HTTP_HOST=host)
    assert initial.status_code == 200
    selector = re.search(r'<select[^>]*name="search_mode"[^>]*>(.*?)</select>', initial.content.decode(), re.S).group(1)
    options = re.findall(r'<option value="([^"]+)"[^>]*>(.*?)</option>', selector, re.S)
    assert [(value, label.strip()) for value, label in options][:2] == [("meta", "meta"), ("url", "URL")]
    if surface == "admin":
        assert initial.context["cl"].search_stream_complete
        assert len(initial.context["cl"].result_list) == 50
    else:
        assert not initial.context["public_search_stream_pending"]
        assert len(initial.context["object_list"]) == 50
    consume(browser.get(path + "search-stream/", {**params, "search_url": path + "?" + urlencode(params)}, HTTP_HOST=host))
    first = browser.get(path, params, HTTP_HOST=host)
    assert first.status_code == 200
    if surface == "admin":
        cl = first.context["cl"]
        assert set(cl.queryset.values_list("pk", flat=True)) == expected
        first_rows = list(cl.result_list)
        second = browser.get(path, {**params, "p": "2"}, HTTP_HOST=host)
        second_rows = list(second.context["cl"].result_list)
        for order, reverse in (("4", False), ("-4", True)):
            sorted_page = browser.get(path, {**params, "o": order}, HTTP_HOST=host)
            titles = list(sorted_page.context["cl"].queryset.values_list("title", flat=True))
            assert titles == sorted(titles, reverse=reverse)
    else:
        first_rows = list(first.context["object_list"])
        second = browser.get(path, {**params, "page": "2"}, HTTP_HOST=host)
        second_rows = list(second.context["object_list"])
    assert len(first_rows) == 50
    assert len(second_rows) == len(expected) - 50
    assert {row.pk for row in first_rows + second_rows} == expected
    assert not ({row.pk for row in first_rows} & {row.pk for row in second_rows})
    empty = browser.get(path, {"q": "missing-url-query", "search_mode": "url"}, HTTP_HOST=host)
    assert empty.status_code == 200
    if surface == "admin":
        assert not empty.context["cl"].result_list
    else:
        assert not empty.context["object_list"]
        assert not empty.context["public_search_stream_pending"]


def test_url_only_shared_query_preserves_scope(url_rows):
    rows, private = url_rows
    scoped = Snapshot.objects.filter(pk__in=[rows[0].pk, private.pk])
    assert set(apply_snapshot_search(scoped, "needle", search_mode="url").values_list("pk", flat=True)) == {rows[0].pk, private.pk}
    assert not apply_snapshot_search(Snapshot.objects.all(), "Title", search_mode="url").exists()
    assert not apply_snapshot_search(Snapshot.objects.all(), "needle%", search_mode="url").exists()
    assert set(query_search_index("needle", search_mode="url").values_list("pk", flat=True)) == {row.pk for row in rows} | {private.pk}
    assert query_search_index("needle", search_mode="url", max_results=2).count() == 2


@pytest.mark.parametrize("query", ["über", "%C3%BCber"])
@pytest.mark.parametrize("surface", ["admin", "public"])
def test_url_only_equivalent_uri_iri_spellings(admin_client, client, crawl, query, surface):
    Machine.from_json({"config": {"PUBLIC_INDEX": True}})
    matches = [
        Snapshot.objects.create(url=f"https://example.com/{path}", crawl=crawl, config={"PERMISSIONS": "public"})
        for path in ("über", "%C3%BCber")
    ]
    Snapshot.objects.create(url="https://elsewhere.example/", title="über %C3%BCber", crawl=crawl, config={"PERMISSIONS": "public"})
    if surface == "admin":
        browser, path, host = admin_client, "/admin/core/snapshot/", "admin.archivebox.localhost:5797"
    else:
        client.logout()
        browser, path, host = client, "/public/", "web.archivebox.localhost:5797"
    params = {"q": query, "search_mode": "url"}
    response = browser.get(path, params, HTTP_HOST=host)
    assert response.status_code == 200
    results = response.context["cl"].result_list if surface == "admin" else response.context["object_list"]
    expected = {row.pk for row in matches}
    assert {row.pk for row in results} == expected
    streamed = consume(browser.get(path + "search-stream/", {**params, "search_url": path + "?" + urlencode(params)}, HTTP_HOST=host))
    assert streamed.splitlines()[-1].strip() == b"2"
    assert set(apply_snapshot_search(Snapshot.objects.all(), query, search_mode="url").values_list("pk", flat=True)) == expected
    assert set(query_search_index(query, search_mode="url").values_list("pk", flat=True)) == expected
