from urllib.parse import urlencode

import pytest
from asgiref.sync import async_to_sync
from django.core.cache import cache

from archivebox.core.models import Folder, Snapshot
from archivebox.machine.models import Machine
from archivebox.search.views import get_public_search_cache_key

pytestmark = pytest.mark.django_db(transaction=True)
HOST = "archivebox.localhost:5797"


def complete(client, params):
    response = client.get("/public/search-stream/", {**params, "search_url": "/public/?" + urlencode(params)}, HTTP_HOST=HOST)
    assert response.status_code == 200

    async def consume():
        return b"".join([chunk async for chunk in response.streaming_content])

    async_to_sync(consume)()


def test_public_completed_search_pages_expiry_and_scope(client, crawl):
    Machine.from_json({"config": {"PUBLIC_INDEX": True, "SNAPSHOTS_PER_PAGE": 50}})
    cache.clear()
    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://paging.example/{i}",
                title=f"Paging {i}",
                timestamp=str(1900100000 + i),
                crawl=crawl,
                config={"PERMISSIONS": "public"},
            )
            for i in range(65)
        ],
    )
    private = Snapshot.objects.create(url="https://paging.example/private", crawl=crawl, config={"PERMISSIONS": "private"})
    params = {"q": "paging.example", "search_mode": "meta"}
    complete(client, params)
    first = client.get("/public/", params, HTTP_HOST=HOST)
    assert first.status_code == 200
    assert len(first.context["object_list"]) == 50
    assert not first.context["public_search_stream_pending"]
    assert b"const initialForm =" not in first.content
    assert b"document.addEventListener('submit', streamPublicSnapshotSearch)" in first.content
    second = client.get("/public/", {**params, "page": "2"}, HTTP_HOST=HOST)
    assert second.status_code == 200
    assert second.context["page_obj"].number == 2
    assert len(second.context["object_list"]) == 15
    found = [row.pk for row in first.context["object_list"]] + [row.pk for row in second.context["object_list"]]
    assert len(set(found)) == 65
    assert set(found) == {row.pk for row in rows}
    assert private.pk not in found
    for sidebar in ("tags", "domains"):
        switched = client.get("/public/", {**params, "sidebar": sidebar, "page": "2"}, HTTP_HOST=HOST)
        assert switched.status_code == 200
        assert switched.context["sidebar_mode"] == sidebar
        assert not switched.context["public_search_stream_pending"]
        assert [row.pk for row in switched.context["object_list"]] == [row.pk for row in second.context["object_list"]]
        assert b"const initialForm =" not in switched.content
    folder = Folder.objects.create(name="Other public scope")
    Snapshot.objects.create(url="https://unrelated.example/", crawl=crawl, folder=folder, config={"PERMISSIONS": "public"})
    scoped = client.get("/public/", {**params, "folder": str(folder.pk)}, HTTP_HOST=HOST)
    assert scoped.status_code == 200
    assert scoped.context["public_search_stream_pending"]
    complete(client, {**params, "folder": str(folder.pk)})
    scoped = client.get("/public/", {**params, "folder": str(folder.pk)}, HTTP_HOST=HOST)
    assert not scoped.context["object_list"]
    cache.delete(get_public_search_cache_key(first.wsgi_request))
    expired = client.get("/public/", {**params, "page": "2"}, HTTP_HOST=HOST)
    assert expired.status_code == 200
    assert expired.context["public_search_stream_pending"]
    assert b"const initialForm =" in expired.content
    complete(client, {**params, "page": "2"})
    resumed = client.get("/public/", {**params, "page": "2"}, HTTP_HOST=HOST)
    assert resumed.status_code == 200
    assert resumed.context["page_obj"].number == 2
    assert len(resumed.context["object_list"]) == 15
    invalid = client.get("/public/", {**params, "page": "3"}, HTTP_HOST=HOST)
    assert invalid.status_code == 404
    url_page = client.get("/public/", {**params, "search_mode": "url", "page": "2"}, HTTP_HOST=HOST)
    assert url_page.status_code == 200
    assert url_page.context["page_obj"].number == 2
    assert len(url_page.context["object_list"]) == 15
    assert not url_page.context["public_search_stream_pending"]
    assert b"const initialForm =" not in url_page.content


def test_public_cache_key_preserves_membership_scope(client):
    Machine.from_json({"config": {"PUBLIC_INDEX": True}})
    response = client.get("/public/", HTTP_HOST=HOST)
    request = response.wsgi_request

    def key(query):
        return get_public_search_cache_key(request, "/public/?" + query)

    expected = key("q=site&search_mode=meta&folder=7&tag=a&tag=b")
    assert expected == key("tag=a&tag=b&folder=7&search_mode=meta&q=site&page=2&sidebar=domains")
    assert expected != key("q=site&search_mode=meta&folder=7&tag=a&tag=b&domain=example.com")
    assert expected != key("q=site&search_mode=meta&folder=8&tag=a&tag=b")
    assert expected != key("q=site&search_mode=contents&folder=7&tag=a&tag=b")
    assert expected != key("q=site&search_mode=meta&folder=7&tag=b&tag=a")
    assert expected != get_public_search_cache_key(request, "/other/?q=site&search_mode=meta&folder=7&tag=a&tag=b")


def test_public_search_actual_http_next_and_expired_page(live_server, crawl):
    import html
    import re
    from urllib.parse import urljoin, urlsplit
    import requests

    Machine.from_json({"config": {"PUBLIC_INDEX": True, "SNAPSHOTS_PER_PAGE": 50}})
    cache.clear()
    rows = Snapshot.objects.bulk_create(
        [
            Snapshot(
                url=f"https://http-pages.example/item/{i:03}/",
                timestamp=str(1900500000 + i),
                crawl=crawl,
                config={"PERMISSIONS": "public"},
            )
            for i in range(65)
        ],
    )
    session = requests.Session()
    session.headers["Host"] = f"archivebox.localhost:{urlsplit(live_server.url).port}"
    params = {"q": "http-pages.example", "search_mode": "meta"}
    path = "/public/?" + urlencode(params)
    initial = session.get(live_server.url + path, timeout=20)
    assert initial.status_code == 200
    assert "const initialForm =" in initial.text
    stream = session.get(live_server.url + "/public/search-stream/", params={**params, "search_url": path}, timeout=20)
    assert stream.status_code == 200
    first = session.get(live_server.url + path, timeout=20)
    assert first.status_code == 200
    assert "const initialForm =" not in first.text
    next_href = re.search(r'<a href="([^"]+)">next</a>', first.text)
    assert next_href is not None
    next_url = urljoin(first.url, html.unescape(next_href[1]))
    second = session.get(next_url, timeout=20)
    assert second.status_code == 200
    first_ids = {r.pk for r in rows if r.url in first.text}
    second_ids = {r.pk for r in rows if r.url in second.text}
    assert len(first_ids) == 50
    assert len(second_ids) == 15
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == {r.pk for r in rows}
    assert "const initialForm =" not in second.text
    cache.clear()
    expired = session.get(next_url, timeout=20)
    assert expired.status_code == 200
    assert "const initialForm =" in expired.text
    rebuilt = session.get(
        live_server.url + "/public/search-stream/",
        params={**params, "search_url": urlsplit(next_url).path + "?" + urlsplit(next_url).query},
        timeout=20,
    )
    assert rebuilt.status_code == 200
    resumed = session.get(next_url, timeout=20)
    assert resumed.status_code == 200
    assert {r.pk for r in rows if r.url in resumed.text} == second_ids
    url_page = session.get(live_server.url + "/public/", params={**params, "search_mode": "url", "page": "2"}, timeout=20)
    assert url_page.status_code == 200
    assert len({r.pk for r in rows if r.url in url_page.text}) == 15
    assert "const initialForm =" not in url_page.text
    session.close()
