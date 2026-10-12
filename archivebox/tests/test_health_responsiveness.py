"""Liveness probes must not depend on collection queries or authentication."""

import time

import pytest
import requests


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "head"])
def test_health_does_not_query_collection(client, django_assert_num_queries, method):
    with django_assert_num_queries(0):
        response = getattr(client, method)("/health/")
    assert response.status_code == 200
    assert response.content == (b"OK" if method == "get" else b"")
    assert response["Content-Type"] == "text/plain"
    assert response["X-ArchiveBox-Health"] == "OK"
    assert response["Access-Control-Allow-Origin"] == "*"
    assert response["Access-Control-Expose-Headers"] == "X-ArchiveBox-Health"
    assert "no-store" in response["Cache-Control"]
    assert not response.cookies


@pytest.mark.django_db(transaction=True)
def test_health_through_real_daphne(archivebox_daemon_server):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite")
    server.wait_for_workers(("worker_daphne",))
    elapsed = []
    with requests.Session() as client:
        for method in ("GET", "HEAD") * 5:
            started = time.perf_counter()
            response = client.request(method, f"http://127.0.0.1:{server.port}/health/", timeout=5)
            elapsed.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200
            assert response.content == (b"OK" if method == "GET" else b"")
            assert response.headers["X-ArchiveBox-Health"] == "OK"
            assert "no-store" in response.headers["Cache-Control"]
    print(f"Real Daphne health request times (ms): {elapsed}")
