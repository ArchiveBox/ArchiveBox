import asyncio
import threading
from urllib.parse import urlencode
import pytest
from asgiref.sync import async_to_sync
from django.core.cache import caches
from django.db.backends.signals import connection_created
from archivebox.core.models import Snapshot, Folder
from archivebox.search.views import get_admin_search_cache_key, search_state
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def isolate_search_result_cache(settings, tmp_path):
    # xdist gives each test its own collection, but Django configures this
    # file cache at import time. Keep generations from different DBs apart.
    settings.CACHES = {
        **settings.CACHES,
        "search_results": {**settings.CACHES["search_results"], "LOCATION": tmp_path / "search-results"},
    }


def complete_search(client, params):
    path = "/admin/core/snapshot/"
    response = client.get(path + "search-stream/", {**params, "search_url": path + "?" + urlencode(params)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200

    async def consume():
        return b"".join([chunk async for chunk in response.streaming_content])

    async_to_sync(consume)()
    return path


def test_next_page_uses_confirmed_rows_while_search_is_running(admin_client, crawl):
    Snapshot.objects.bulk_create(
        Snapshot(crawl=crawl, url=f"https://en.wikipedia.org/wiki/Topic_{i}", timestamp=str(1900000000 + i)) for i in range(650)
    )
    path = "/admin/core/snapshot/"
    params = {"q": "meta:wikipedia", "search_mode": "query"}
    search_url = path + "?" + urlencode(params)
    response = admin_client.get(path + "search-stream/", {**params, "search_url": search_url}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    key = get_admin_search_cache_key(response.wsgi_request, search_url)

    async def visit_next_page():
        stream = response._iterator
        try:
            while int(await anext(stream)) < 101:
                # A reader may consume updates more slowly than the 50ms
                # progress cadence. The bounded producer keeps working.
                await asyncio.sleep(0.06)
            state = await asyncio.to_thread(search_state, response.wsgi_request, key)
            assert not state["done"]
            second = await asyncio.to_thread(admin_client.get, path, {**params, "p": "2"}, HTTP_HOST=ADMIN_TEST_HOST)
            assert second.status_code == 200
            cl = second.context["cl"]
            assert cl.page_num == 2 and not cl.search_stream_complete
            assert [row.pk.hex for row in cl.result_list] == state["ids"][50:100]
            assert [int(update) async for update in stream][-1] == 650
        finally:
            await stream.aclose()

    async_to_sync(visit_next_page)()


@pytest.mark.parametrize("aborted", [True, False], ids=["stale-final", "stale-progress"])
def test_superseded_meta_search_cannot_overwrite_replacement(admin_client, crawl, aborted):
    query = "example.org"
    snapshots = [
        Snapshot.objects.create(crawl=crawl, url=url, timestamp=str(1900000000 + i))
        for i, url in enumerate((f"https://{query}/capture", f"https://www.{query}/capture", f"http://{query}/capture"))
    ]
    path = "/admin/core/snapshot/"
    params = {"q": query, "search_mode": "meta"}
    search_url = path + "?" + urlencode(params)
    requests = {**params, "search_url": search_url}
    old = admin_client.get(path + "search-stream/", requests, HTTP_HOST=ADMIN_TEST_HOST)
    replacement = admin_client.get(path + "search-stream/", requests, HTTP_HOST=ADMIN_TEST_HOST)
    assert old.status_code == replacement.status_code == 200
    key = get_admin_search_cache_key(old.wsgi_request, search_url)
    stalled_worker = None
    stalled = threading.Event()
    release = threading.Event()
    stalled_after_progress = threading.Event()
    release_after_progress = threading.Event()

    def hold_next_real_prefix(execute, sql, params, many, context):
        nonlocal stalled_worker
        if params and params[0] == f"https://www.{query}/" and not stalled.is_set():
            stalled_worker = threading.current_thread()
            stalled.set()
            assert release.wait(10), "Old search producer not released"
        if not aborted and threading.current_thread() is stalled_worker and params and params[0] == f"http://{query}/":
            stalled_after_progress.set()
            assert release_after_progress.wait(10), "Old search producer not released after progress"
        return execute(sql, params, many, context)

    def observe_connection(sender, connection, **kwargs):
        if threading.current_thread().name == "admin-snapshot-search-stream":
            connection.execute_wrappers.append(hold_next_real_prefix)

    async def overlap():
        iterator = old._iterator
        try:
            assert int(await asyncio.wait_for(anext(iterator), 5)) == 0
            assert int(await asyncio.wait_for(anext(iterator), 5)) == 1
            assert await asyncio.to_thread(stalled.wait, 5)
            assert search_state(old.wsgi_request, key) == {"ids": [snapshots[0].pk.hex], "done": False, "partial": False}

            async def consume_replacement():
                return [int(chunk) async for chunk in replacement.streaming_content]

            assert (await asyncio.wait_for(consume_replacement(), 5))[-1] == len(snapshots)
            expected = {"ids": [item.pk.hex for item in snapshots], "done": True, "partial": False}
            assert search_state(old.wsgi_request, key) == expected
            if aborted:
                await iterator.aclose()
            else:
                await asyncio.sleep(0.06)  # Permit a real progress publish after the 50 ms batching window.
            release.set()
            if not aborted:
                assert int(await asyncio.wait_for(anext(iterator), 5)) == 2
                assert await asyncio.to_thread(stalled_after_progress.wait, 5)
                assert search_state(old.wsgi_request, key) == expected
                await iterator.aclose()
                release_after_progress.set()
            await asyncio.to_thread(stalled_worker.join, 5)
            assert not stalled_worker.is_alive()
            assert search_state(old.wsgi_request, key) == expected
        finally:
            release.set()
            release_after_progress.set()
            await iterator.aclose()
            if stalled_worker is not None:
                await asyncio.to_thread(stalled_worker.join, 5)

    connection_created.connect(observe_connection)
    try:
        async_to_sync(overlap)()
    finally:
        connection_created.disconnect(observe_connection)


@pytest.mark.parametrize("size", [60, 1200])
def test_completed_meta_search_sort_and_page_reuse(admin_client, crawl, size):
    snapshots = Snapshot.objects.bulk_create(
        [
            Snapshot(url=f"https://www.amazon.com/{i:03}", title=f"Title {size - 1 - i:05}", timestamp=str(1900000000 + i), crawl=crawl)
            for i in range(size)
        ],
    )
    params = {"q": "amazon.com", "search_mode": "meta"}
    path = complete_search(admin_client, params)
    first = admin_client.get(path, params, HTTP_HOST=ADMIN_TEST_HOST)
    assert first.context["cl"].search_stream_complete
    assert len(first.context["cl"].result_list) == 50
    assert b"var initialForm =" not in first.content
    assert b'document.addEventListener("submit", streamSnapshotSearch)' in first.content
    second = admin_client.get(path, {**params, "p": "2"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert second.context["cl"].search_stream_complete
    assert len(second.context["cl"].result_list) == min(size - 50, 50)
    assert {s.pk for s in first.context["cl"].result_list}.isdisjoint(s.pk for s in second.context["cl"].result_list)
    assert set(first.context["cl"].queryset.values_list("pk", flat=True)) == {s.pk for s in snapshots}
    sorted_page = admin_client.get(path, {**params, "o": "4"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert sorted_page.context["cl"].search_stream_complete
    rows = list(sorted_page.context["cl"].queryset)
    assert [s.title for s in rows] == sorted(s.title for s in snapshots)
    assert rows[0].pk != first.context["cl"].result_list[0].pk
    for sidebar in ("tags", "domains"):
        switched = admin_client.get(path, {**params, "o": "4", "sidebar": sidebar}, HTTP_HOST=ADMIN_TEST_HOST)
        assert switched.status_code == 200
        assert switched.context["sidebar_mode"] == sidebar
        assert switched.context["cl"].search_stream_complete
        assert [row.pk for row in switched.context["cl"].result_list] == [row.pk for row in rows[:50]]
        assert b"var initialForm =" not in switched.content
    multi = admin_client.get(path, {**params, "o": "-4.5"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert multi.context["cl"].search_stream_complete
    assert [s.title for s in multi.context["cl"].result_list] == sorted((s.title for s in snapshots), reverse=True)[:50]
    back = admin_client.get(path, params, HTTP_HOST=ADMIN_TEST_HOST)
    assert [s.pk for s in back.context["cl"].result_list] == [s.pk for s in first.context["cl"].result_list]
    folder = Folder.objects.create(name="Different scope")
    scoped = admin_client.get(path, {**params, "folder": str(folder.pk)}, HTTP_HOST=ADMIN_TEST_HOST)
    assert not scoped.context["cl"].search_stream_complete
    assert b"var initialForm =" in scoped.content
    key = get_admin_search_cache_key(first.wsgi_request)
    search_cache = caches["search_results"]
    generation = search_cache.get(key)
    assert search_cache.delete(f"{key}:{generation}")
    expired = admin_client.get(path, {**params, "p": "2"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert expired.status_code == 200
    assert not expired.context["cl"].search_stream_complete
    assert b"var initialForm =" in expired.content
    complete_search(admin_client, {**params, "p": "2"})
    resumed = admin_client.get(path, {**params, "p": "2"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert resumed.context["cl"].search_stream_complete
    assert len(resumed.context["cl"].result_list) == min(size - 50, 50)


def test_search_key_preserves_user_mode_and_multivalue_filters(admin_client, admin_user, django_user_model):
    live = admin_client.get("/admin/core/snapshot/", HTTP_HOST=ADMIN_TEST_HOST)
    request = live.wsgi_request

    def key(query):
        return get_admin_search_cache_key(request, "/admin/core/snapshot/?" + query)

    expected = key("q=amazon.com&search_mode=meta&tag=a&tag=b")
    assert expected == key("tag=a&tag=b&search_mode=meta&q=amazon.com&o=4&p=2&sidebar=domains")
    assert expected != key("q=amazon.com&search_mode=meta&tag=a&tag=b&domain=amazon.com")
    assert expected != key("q=amazon.com&search_mode=meta&tag=b&tag=a")
    assert expected != key("q=amazon.com&search_mode=contents&tag=a&tag=b")
    assert expected != key("q=amazon.com&search_mode=meta&tag=a")
    other = django_user_model.objects.create_user(username="cache-other")
    request.user = other
    assert expected != key("q=amazon.com&search_mode=meta&tag=a&tag=b")


@pytest.mark.parametrize("sort", [None, "4"])
def test_cached_search_does_not_display_results_moved_out_of_folder(admin_client, crawl, sort):
    folder = Folder.objects.create(name="Search scope")
    other = Folder.objects.create(name="Outside search scope")
    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://www.amazon.com/{i:03}",
                title=f"Title {59 - i:05}",
                timestamp=str(1900000000 + i),
                crawl=crawl,
                folder=folder,
            )
            for i in range(60)
        ],
    )
    params = {"q": "amazon.com", "search_mode": "meta", "folder": str(folder.pk)}
    path = complete_search(admin_client, params)
    expected = admin_client.get(path, params, HTTP_HOST=ADMIN_TEST_HOST)
    assert expected.context["cl"].search_stream_complete
    moved = expected.context["cl"].result_list[0]
    Snapshot.objects.filter(pk=moved.pk).update(folder=other)
    if sort is not None:
        params["o"] = sort
    response = admin_client.get(path, params, HTTP_HOST=ADMIN_TEST_HOST)
    changelist = response.context["cl"]
    assert changelist.search_stream_complete
    assert len(changelist.result_list) == 50
    assert moved.pk not in {row.pk for row in changelist.result_list}
    assert set(changelist.queryset.values_list("pk", flat=True)) == {row.pk for row in rows} - {moved.pk}
    if sort is not None:
        assert [row.title for row in changelist.result_list] == sorted(row.title for row in rows if row.pk != moved.pk)[:50]
