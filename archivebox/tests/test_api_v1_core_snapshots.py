import threading
import time

import pytest

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
