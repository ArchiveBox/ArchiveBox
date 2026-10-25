"""Liveness probes must not depend on collection queries or authentication."""

import socket
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
def test_health_through_real_uvicorn(archivebox_daemon_server):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite")
    server.wait_for_workers(("worker_uvicorn",))
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
    print(f"Real Uvicorn health request times (ms): {elapsed}")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("header_value", [b"before\rafter", b"before\nafter"])
def test_real_uvicorn_rejects_bare_cr_lf_in_header_values(archivebox_daemon_server, header_value):
    server = archivebox_daemon_server(SEARCH_BACKEND_ENGINE="sqlite")
    server.wait_for_workers(("worker_uvicorn",))
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as client:
        client.sendall(
            b"GET /health/ HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nX-Test: " + header_value + b"\r\n\r\n",
        )
        response = bytearray()
        while chunk := client.recv(4096):
            response.extend(chunk)
    assert response.startswith(b"HTTP/1.1 400 "), bytes(response)
    assert b"X-ArchiveBox-Health: OK" not in response
