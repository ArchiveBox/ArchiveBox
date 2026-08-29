import threading
import time

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Snapshot
from archivebox.crawls.locks import crawl_lifecycle_lock
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_snapshots_api_filters_status_column(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by=api_admin_user,
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
    )
    Snapshot.objects.create(
        url="https://example.com/api-status-queued",
        crawl=crawl,
        status=Snapshot.StatusChoices.QUEUED,
    )
    sealed_snapshot = Snapshot.objects.create(
        url="https://example.com/api-status-sealed",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
    )

    response = client.get(
        "/api/v1/core/snapshots",
        {"status": "sealed"},
        **api_headers,
    )
    assert response.status_code == 200, response.content
    payload = response.json()
    items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    assert [item["id"] for item in items] == [str(sealed_snapshot.id)]
    assert [item["status"] for item in items] == ["sealed"]


def test_existing_snapshot_metadata_sync_does_not_wait_for_active_crawl(client, api_admin_user, api_headers):
    url = "https://example.com/browser-extension-upload"
    crawl = Crawl.objects.create(
        urls=url,
        created_by=api_admin_user,
        status=Crawl.StatusChoices.STARTED,
    )
    snapshot = Snapshot.objects.create(
        url=url,
        crawl=crawl,
        title="Original title",
        status=Snapshot.StatusChoices.STARTED,
    )
    lock_acquired = threading.Event()

    def hold_active_crawl_lock():
        with crawl_lifecycle_lock(str(crawl.id)):
            lock_acquired.set()
            time.sleep(2)

    holder = threading.Thread(target=hold_active_crawl_lock)
    holder.start()
    assert lock_acquired.wait(timeout=1)

    started_at = time.monotonic()
    response = client.post(
        "/api/v1/core/snapshots",
        data={
            "url": url,
            "crawl_id": str(crawl.id),
            "depth": 0,
            "title": "Browser title",
            "status": Snapshot.StatusChoices.STARTED,
        },
        content_type="application/json",
        **api_headers,
    )
    elapsed = time.monotonic() - started_at
    holder.join(timeout=3)

    assert response.status_code == 200, response.content
    assert response.json()["id"] == str(snapshot.id)
    assert elapsed < 1


def test_new_snapshot_creation_does_not_open_a_database_transaction(client, api_admin_user, api_headers):
    url = "https://example.com/browser-extension-new-snapshot"
    crawl = Crawl.objects.create(urls=url, created_by=api_admin_user)

    with CaptureQueriesContext(connection) as queries:
        response = client.post(
            "/api/v1/core/snapshots",
            data={
                "url": url,
                "crawl_id": str(crawl.id),
                "depth": 0,
                "status": Snapshot.StatusChoices.QUEUED,
                "tags": ["browser-extension-upload"],
            },
            content_type="application/json",
            **api_headers,
        )

    assert response.status_code == 200, response.content
    assert Snapshot.objects.filter(url=url, crawl=crawl).count() == 1
    assert Snapshot.objects.get(url=url, crawl=crawl).tags.filter(name="browser-extension-upload").exists()
    if connection.vendor == "sqlite":
        transaction_queries = [query["sql"] for query in queries if query["sql"].strip().upper() in {"BEGIN", "COMMIT"}]
        assert transaction_queries == []


def test_new_snapshot_creation_does_not_wait_for_active_crawl(client, api_admin_user, api_headers):
    url = "https://example.com/browser-extension-new-snapshot-active-crawl"
    crawl = Crawl.objects.create(urls=url, created_by=api_admin_user)
    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def hold_active_crawl_lock():
        with crawl_lifecycle_lock(str(crawl.id)):
            lock_acquired.set()
            release_lock.wait(timeout=3)

    holder = threading.Thread(target=hold_active_crawl_lock)
    holder.start()
    assert lock_acquired.wait(timeout=1)

    started_at = time.monotonic()
    response = client.post(
        "/api/v1/core/snapshots",
        data={
            "url": url,
            "crawl_id": str(crawl.id),
            "depth": 0,
            "status": Snapshot.StatusChoices.QUEUED,
            "tags": ["browser-extension-upload"],
        },
        content_type="application/json",
        **api_headers,
    )
    elapsed = time.monotonic() - started_at
    release_lock.set()
    holder.join(timeout=3)

    assert response.status_code == 200, response.content
    assert Snapshot.objects.filter(url=url, crawl=crawl).count() == 1
    assert elapsed < 1
