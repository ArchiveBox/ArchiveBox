"""Real plugin routes, domain grouping, cursor pages and OS telemetry."""

import pytest

from archivebox.core.models import Snapshot
from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db


def test_graph_domain_pages_and_directed_discovery(admin_client, crawl):
    parent = Snapshot.objects.create(crawl=crawl, url="https://news.google.co.uk/one")
    Snapshot.objects.create(crawl=crawl, url="https://www.google.co.uk/two")
    Snapshot.objects.create(crawl=crawl, url="https://amazon.com/item", parent_snapshot=parent)
    response = admin_client.get("/admin/graph/data/", HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    nodes = {node["id"]: node for node in response.json()["nodes"]}
    assert nodes["google.co.uk"]["count"] == 2
    assert nodes["amazon.com"]["count"] == 1
    response = admin_client.get("/admin/graph/data/", {"domain": "*.google.co.uk"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    assert {"source": "google.co.uk", "target": "amazon.com", "value": 1} in response.json()["links"]
    response = admin_client.get("/admin/graph/data/", {"domain": "*.amazon.com"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert {"source": "google.co.uk", "target": "amazon.com", "value": 1} in response.json()["links"]
    assert admin_client.get("/admin/graph/data/?cursor=bad", HTTP_HOST=ADMIN_TEST_HOST).status_code == 400
    assert admin_client.get("/admin/graph/data/?domain=*.amazon.com&after=bad", HTTP_HOST=ADMIN_TEST_HOST).status_code == 400


def test_visualizations_are_registered_private_and_self_contained(admin_client):
    from django.urls import resolve
    from django.test import Client

    client = Client()

    for name, route, script in (("networkgraph", "graph", "graph.mjs"), ("bandwidth", "bandwidth", "bandwidth.mjs")):
        assert resolve(f"/admin/{route}/").func.func.__module__ == f"abx_plugins.plugins.{name}.app"
        assert client.get(f"/admin/{route}/data/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 302
        page = admin_client.get(f"/admin/{route}/", HTTP_HOST=ADMIN_TEST_HOST)
        assert page.status_code == 200, page.content
        assert b'id="header"' in page.content
        assert b'class="breadcrumbs"' in page.content
        assert b"{% extends" not in page.content
        asset = admin_client.get(f"/admin/{route}/assets/{script}", HTTP_HOST=ADMIN_TEST_HOST)
        assert asset.status_code == 200
        assert len(b"".join(asset.streaming_content)) > 1000
        assert admin_client.post(f"/admin/{route}/data/", HTTP_HOST=ADMIN_TEST_HOST).status_code == 405
    dashboard = admin_client.get("/admin/", HTTP_HOST=ADMIN_TEST_HOST)
    assert dashboard.status_code == 200
    html = dashboard.content
    navbar = html.split(b'id="user-tools"', 1)[1].split(b"</nav>", 1)[0]
    assert b'href="/admin/graph/"' not in navbar
    assert b'href="/admin/bandwidth/"' not in navbar
    results_row = html.split(b'class="abx-admin-flow__row abx-admin-flow__row--grandchild"', 1)[1].split(b"</article>", 2)
    assert b"Archive Results" in results_row[0]
    assert b'href="/admin/graph/"' in results_row[1] and b"Graph Explorer" in results_row[1]
    environment = html.split(b'id="abx-admin-environment-title"', 1)[1].split(b"</article>", 1)[0]
    assert b'href="/admin/bandwidth/"' in environment and b"Bandwidth" in environment

    telemetry = admin_client.get("/admin/bandwidth/data/", HTTP_HOST=ADMIN_TEST_HOST)
    assert telemetry.status_code == 200, telemetry.content
    # Unrelated host interfaces are absent when this collection has no captures running.
    assert telemetry.json()["interfaces"] == []
    assert all(interface["rx"] >= 0 and interface["tx"] >= 0 for interface in telemetry.json()["interfaces"])


def test_graph_stream_counts_every_capture_once(admin_client, crawl):
    parent = Snapshot.objects.create(crawl=crawl, url="https://news.google.co.uk/stream")
    Snapshot.objects.create(crawl=crawl, url="https://amazon.com/stream", parent_snapshot=parent)
    response = admin_client.get("/admin/graph/data/", {"scan": "1"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    data = response.json()
    assert data["sampled"] == 2
    assert sum(node["count"] for node in data["nodes"]) == 2
    assert data["cursor"] is None
    assert {"source": "google.co.uk", "target": "amazon.com", "value": 1} in data["links"]
    assert admin_client.get("/admin/graph/data/?scan=1&after=bad", HTTP_HOST=ADMIN_TEST_HOST).status_code == 400


def test_graph_uses_saved_links_between_archived_urls(admin_client, crawl):
    import json

    source = Snapshot.objects.create(crawl=crawl, url="https://news.google.co.uk/article")
    Snapshot.objects.create(crawl=crawl, url="https://amazon.com/linked")
    directory = source.get_storage_path_for_version(source.fs_version) / "parse_dom_outlinks"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "urls.jsonl").write_text(json.dumps({"url": "https://amazon.com/linked"}) + "\n")
    response = admin_client.get("/admin/graph/data/", {"scan": "links"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    assert response.json()["sampled"] == 2
    assert response.json()["links"] == [{"source": "google.co.uk", "target": "amazon.com", "value": 1}]
    assert admin_client.get("/admin/graph/data/?scan=links&after=bad", HTTP_HOST=ADMIN_TEST_HOST).status_code == 400


def test_graph_excludes_schema_references_from_all_edges(admin_client, crawl):
    import json

    source = Snapshot.objects.create(crawl=crawl, url="https://example.com/article")
    references = {
        "w3.org": "https://www.w3.org/2000/svg",
        "schema.org": "https://schema.org/Article",
        "ogp.me": "https://ogp.me/ns",
        "w.org": "https://api.w.org/",
    }
    urls = [*references.values(), "https://amazon.com/item"]
    for url in urls:
        Snapshot.objects.create(crawl=crawl, url=url, parent_snapshot=source)
    directory = source.get_storage_path_for_version(source.fs_version) / "parse_dom_outlinks"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "urls.jsonl").write_text("\n".join(json.dumps({"url": url}) for url in urls))
    for params in ({"scan": "1"}, {"scan": "links"}, {"domain": "*.example.com"}):
        response = admin_client.get("/admin/graph/data/", params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200
        data = response.json()
        assert {"source": "example.com", "target": "amazon.com", "value": 1} in data["links"]
        assert all(edge["source"] not in references and edge["target"] not in references for edge in data["links"])
        assert all(node["id"] not in references for node in data.get("nodes", []))


def test_graph_keeps_creative_commons_pages_and_excludes_boilerplate(admin_client, crawl):
    import json

    source = Snapshot.objects.create(crawl=crawl, url="https://example.com/article")
    profile = Snapshot.objects.create(crawl=crawl, url="http://gmpg.org/xfn/11", parent_snapshot=source)
    license = Snapshot.objects.create(crawl=crawl, url="https://creativecommons.org/licenses/by/4.0/", parent_snapshot=source)
    cc0 = Snapshot.objects.create(crawl=crawl, url="https://creativecommons.org/publicdomain/zero/1.0/", parent_snapshot=source)
    article = Snapshot.objects.create(crawl=crawl, url="https://creativecommons.org/who-we-are/", parent_snapshot=source)
    destination = Snapshot.objects.create(crawl=crawl, url="https://example.net/next", parent_snapshot=license)
    for snapshot, targets in ((source, [profile, license, cc0, article]), (license, [destination])):
        directory = snapshot.get_storage_path_for_version(snapshot.fs_version) / "parse_dom_outlinks"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "urls.jsonl").write_text("\n".join(json.dumps({"url": target.url}) for target in targets))

    expected = [{"source": "example.com", "target": "creativecommons.org", "value": 1}]
    for params in ({"scan": "1"}, {"scan": "links"}, {"domain": "*.example.com"}, {"domain": "*.creativecommons.org"}):
        response = admin_client.get("/admin/graph/data/", params, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 200, response.content
        data = response.json()
        assert data["links"] == expected
        if params.get("scan") == "1":
            assert {node["id"]: node["count"] for node in data["nodes"]} == {"example.com": 1, "example.net": 1, "creativecommons.org": 1}
        if params.get("domain") == "*.creativecommons.org":
            assert [capture["url"] for capture in data["captures"]] == [article.url]
