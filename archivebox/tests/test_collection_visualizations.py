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
    telemetry = admin_client.get("/admin/bandwidth/data/", HTTP_HOST=ADMIN_TEST_HOST)
    assert telemetry.status_code == 200, telemetry.content
    # Unrelated host interfaces are absent when this collection has no captures running.
    assert telemetry.json()["interfaces"] == []
    assert all(interface["rx"] >= 0 and interface["tx"] >= 0 for interface in telemetry.json()["interfaces"])
