import threading
import time

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from archivebox.core.models import Snapshot
from archivebox.crawls.locks import crawl_lifecycle_lock
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_browser_metadata_respects_only_new_and_reports_capture_owner(client, api_headers):
    url = "https://example.com/browser-deduplication"
    for name in ("Original", "Replacement"):
        persona = client.post(
            "/api/v1/personas/sync",
            data={"extension_persona_id": f"dedupe-{name}", "name": name},
            content_type="application/json",
            **api_headers,
        )
        assert persona.status_code == 200, persona.content

    def submit(only_new, persona):
        queued = client.post(
            "/api/v1/cli/add",
            data={"urls": [url], "only_new": only_new, "persona": persona},
            content_type="application/json",
            **api_headers,
        )
        assert queued.status_code == 200, queued.content
        crawl_id = queued.json()["result"]["crawl_id"]
        metadata = client.post(
            "/api/v1/core/snapshots",
            data={"url": url, "crawl_id": crawl_id},
            content_type="application/json",
            **api_headers,
        )
        assert metadata.status_code == 200, metadata.content
        return crawl_id, metadata.json()

    first_crawl, first = submit(True, "Original")
    second_crawl, reused = submit(True, "Replacement")
    assert second_crawl != first_crawl
    assert reused["id"] == first["id"]
    assert reused["crawl_id"] == first_crawl
    assert reused["persona"] == "Original"
    assert Snapshot.objects.filter(url=url).count() == 1
    forced_crawl, forced = submit(False, "Replacement")
    assert forced["id"] != first["id"]
    assert forced["crawl_id"] == forced_crawl
    assert forced["persona"] == "Replacement"
    assert Snapshot.objects.filter(url=url).count() == 2


def test_snapshot_delete_only_queues_cleanup(client, api_headers):
    created = client.post(
        "/api/v1/core/snapshots",
        data={"url": "https://example.com/queued-delete"},
        content_type="application/json",
        **api_headers,
    )
    assert created.status_code == 200, created.content
    snapshot_id = created.json()["id"]
    response = client.delete(f"/api/v1/core/snapshot/{snapshot_id}", **api_headers)
    assert response.status_code == 200, response.content
    assert response.json()["queued_count"] == 1
    assert response.json()["deleted_count"] == 0
    assert Snapshot.objects.get(pk=snapshot_id).status == Snapshot.DELETING_STATE


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


def test_snapshot_metadata_requests_do_not_touch_archive_storage(client, api_admin_user, api_headers):
    """Metadata writes and serialization must work without replay storage access."""
    import sys
    import threading
    from pathlib import Path
    from archivebox.config import CONSTANTS

    url = "https://example.com/metadata-without-storage"
    crawl = Crawl.objects.create(urls=url, created_by=api_admin_user)
    storage_calls = []

    def observe(frame, event, arg):
        if event == "call" and frame.f_code.co_name in {
            "stat",
            "lstat",
            "exists",
            "is_dir",
            "is_file",
            "is_symlink",
            "open",
            "mkdir",
            "iterdir",
            "glob",
            "rglob",
            "readlink",
            "symlink_to",
            "unlink",
        }:
            path = frame.f_locals.get("self", frame.f_locals.get("path"))
            if isinstance(path, (str, Path)) and Path(path).is_relative_to(CONSTANTS.ARCHIVE_DIR):
                storage_calls.append((frame.f_code.co_name, str(path)))

    previous = sys.getprofile()
    thread_profile = threading.getprofile()
    threading.setprofile_all_threads(observe)
    try:
        response = client.post(
            "/api/v1/core/snapshots",
            data={"url": url, "crawl_id": str(crawl.id), "title": "Browser title", "tags": ["browser"]},
            content_type="application/json",
            **api_headers,
        )
        assert response.status_code == 200, response.content
        snapshot_id = response.json()["id"]
        updated = client.post(
            "/api/v1/core/snapshots",
            data={"url": url, "crawl_id": str(crawl.id), "title": "Updated title", "tags": ["browser"]},
            content_type="application/json",
            **api_headers,
        )
        assert updated.status_code == 200, updated.content
        result = client.post(
            "/api/v1/core/archiveresults",
            data={"snapshot_id": snapshot_id, "plugin": "chrome_extension_viewport", "status": "started"},
            **api_headers,
        )
        assert result.status_code == 200, result.content
        result_id = result.json()["id"]
        result_get = client.get(f"/api/v1/core/archiveresult/{result_id}", **api_headers)
        assert result_get.status_code == 200, result_get.content
        assert result_get.json()["output_files"] == {}
        fetched = client.get(f"/api/v1/core/snapshot/{snapshot_id}", **api_headers)
        assert fetched.status_code == 200, fetched.content
        assert fetched.json()["archiveresults"][0]["id"] == result_id
        deleted = client.delete(f"/api/v1/core/snapshot/{snapshot_id}", **api_headers)
        assert deleted.status_code == 200, deleted.content
        assert deleted.json()["queued_count"] == 1
    finally:
        threading.setprofile_all_threads(thread_profile)
        sys.setprofile(previous)
    snapshot = Snapshot.objects.get(pk=snapshot_id)
    assert snapshot.title == "Updated title"
    assert snapshot.status == Snapshot.DELETING_STATE
    assert list(snapshot.tags.values_list("name", flat=True)) == ["browser"]
    assert fetched.json()["title"] == "Updated title"
    assert storage_calls == []
