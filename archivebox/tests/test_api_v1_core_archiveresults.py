from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import api_client_request


pytestmark = pytest.mark.django_db(transaction=True)


def test_archiveresult_upload_upserts_by_snapshot_plugin_and_hook(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/unified-result", crawl=crawl)

    def upload(hook_name, filename, contents):
        return client.post(
            "/api/v1/core/archiveresults",
            {
                "snapshot_id": str(snapshot.id),
                "plugin": "screenshot",
                "hook_name": hook_name,
                "files": SimpleUploadedFile(filename, contents, content_type="image/png"),
                "output_paths": filename,
            },
            **api_headers,
        )

    extension_response = upload("on_Snapshot__archivebox_browser_extension_upload", "browser.png", b"browser")
    server_response = upload("on_Snapshot__50_screenshot", "server.png", b"server")
    extension_update = upload("on_Snapshot__archivebox_browser_extension_upload", "browser-2.png", b"browser-2")

    assert extension_response.status_code == 200, extension_response.content
    assert server_response.status_code == 200, server_response.content
    assert extension_update.status_code == 200, extension_update.content
    assert extension_update.json()["id"] == extension_response.json()["id"]
    assert server_response.json()["id"] != extension_response.json()["id"]

    results = ArchiveResult.objects.filter(snapshot=snapshot, plugin="screenshot").order_by("hook_name")
    assert results.count() == 2
    extension_result = results.get(hook_name="on_Snapshot__archivebox_browser_extension_upload")
    server_result = results.get(hook_name="on_Snapshot__50_screenshot")
    assert set(extension_result.output_files) == {"browser.png", "browser-2.png"}
    assert set(server_result.output_files) == {"server.png"}
    snapshot.refresh_from_db()
    assert snapshot.output_size == len(b"browser") + len(b"browser-2") + len(b"server")


def test_archiveresult_create_does_not_open_a_database_transaction(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/autocommit-result", crawl=crawl)

    with CaptureQueriesContext(connection) as queries:
        response = client.post(
            "/api/v1/core/archiveresults",
            {
                "snapshot_id": str(snapshot.id),
                "plugin": "chrome_extension_screenshot",
                "files": SimpleUploadedFile("screenshot.png", b"screenshot", content_type="image/png"),
                "output_paths": "screenshot.png",
            },
            **api_headers,
        )

    assert response.status_code == 200, response.content
    if connection.vendor == "sqlite":
        transaction_queries = [query["sql"] for query in queries if query["sql"].strip().upper() in {"BEGIN", "COMMIT"}]
        assert transaction_queries == []


def test_intermediate_archiveresult_chunks_only_write_to_disk(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/chunked-result", crawl=crawl)
    create_response = client.post(
        "/api/v1/core/archiveresults",
        {
            "snapshot_id": str(snapshot.id),
            "plugin": "chrome_extension_mhtml",
            "status": ArchiveResult.StatusChoices.STARTED,
        },
        **api_headers,
    )
    assert create_response.status_code == 200, create_response.content
    result = ArchiveResult.objects.get(pk=create_response.json()["id"])
    original_modified_at = result.modified_at

    with CaptureQueriesContext(connection) as queries:
        chunk_response = client.patch(
            f"/api/v1/core/archiveresult/{result.id}",
            encode_multipart(
                BOUNDARY,
                {
                    "files": SimpleUploadedFile("snapshot.mhtml.part-000000", b"first", content_type="multipart/related"),
                    "chunk_output_path": "snapshot.mhtml",
                    "chunk_index": "0",
                    "chunk_count": "2",
                    "chunk_offset": "0",
                    "chunk_total_size": "11",
                    "mime_type": "multipart/related",
                    "status": ArchiveResult.StatusChoices.STARTED,
                },
            ),
            content_type=MULTIPART_CONTENT,
            **api_headers,
        )

    assert chunk_response.status_code == 200, chunk_response.content
    result.refresh_from_db()
    assert result.output_files == {}
    assert result.output_size == 0
    assert result.modified_at == original_modified_at
    writes = [query["sql"] for query in queries if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert writes == []

    final_response = client.patch(
        f"/api/v1/core/archiveresult/{result.id}",
        encode_multipart(
            BOUNDARY,
            {
                "files": SimpleUploadedFile("snapshot.mhtml.part-000001", b"-final", content_type="multipart/related"),
                "chunk_output_path": "snapshot.mhtml",
                "chunk_index": "1",
                "chunk_count": "2",
                "chunk_offset": "5",
                "chunk_total_size": "11",
                "mime_type": "multipart/related",
                "status": ArchiveResult.StatusChoices.SUCCEEDED,
            },
        ),
        content_type=MULTIPART_CONTENT,
        **api_headers,
    )
    assert final_response.status_code == 200, final_response.content
    result.refresh_from_db()
    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert result.output_size == 11
    assert result.output_files["snapshot.mhtml"]["upload"]["complete"] is True
    snapshot.refresh_from_db()
    assert snapshot.output_size == 11


def test_archiveresult_safe_update_rejects_stale_writers(api_admin_user):
    crawl = Crawl.objects.create(urls="https://example.com", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/cas-result", crawl=crawl)
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="chrome_extension_dom",
        hook_name=Snapshot.BROWSER_EXTENSION_UPLOAD_HOOK_NAME,
        status=ArchiveResult.StatusChoices.STARTED,
        output_size=1,
    )
    stale_result = ArchiveResult.objects.get(pk=result.pk)

    assert result.safe_update({"output_size": 2}) is True
    assert stale_result.safe_update({"output_size": 3}) is False

    stale_result.refresh_from_db()
    snapshot.refresh_from_db()
    assert stale_result.output_size == 2
    assert snapshot.output_size == 2


def test_archiveresult_upload_api_queues_snapshot_maintenance_without_finalizing(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by=api_admin_user,
        status=Crawl.StatusChoices.STARTED,
        retry_at=timezone.now(),
    )
    active_retry_at = timezone.now() + timedelta(minutes=5)
    active_snapshot = Snapshot.objects.create(
        url="https://example.com/active",
        crawl=crawl,
        status=Snapshot.StatusChoices.STARTED,
        retry_at=active_retry_at,
    )
    sealed_snapshot = Snapshot.objects.create(
        url="https://example.com/sealed",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
    )

    active_response = client.post(
        "/api/v1/core/archiveresults",
        {
            "snapshot_id": str(active_snapshot.id),
            "plugin": "chrome_extension_dom",
            "hook_name": "on_Snapshot__archivebox_browser_extension_upload",
            "status": ArchiveResult.StatusChoices.SUCCEEDED,
            "output_str": "uploaded active snapshot output",
        },
        **api_headers,
    )
    assert active_response.status_code == 200, active_response.content
    active_snapshot.refresh_from_db()
    assert active_snapshot.status == Snapshot.StatusChoices.STARTED
    assert active_snapshot.retry_at == active_retry_at
    assert active_snapshot.downloaded_at is not None

    sealed_response = client.post(
        "/api/v1/core/archiveresults",
        {
            "snapshot_id": str(sealed_snapshot.id),
            "plugin": "chrome_extension_mhtml",
            "hook_name": "on_Snapshot__archivebox_browser_extension_upload",
            "status": ArchiveResult.StatusChoices.SUCCEEDED,
            "output_str": "uploaded sealed snapshot output",
        },
        **api_headers,
    )
    assert sealed_response.status_code == 200, sealed_response.content
    sealed_snapshot.refresh_from_db()
    assert sealed_snapshot.status == Snapshot.StatusChoices.SEALED
    assert sealed_snapshot.retry_at is not None
    assert sealed_snapshot.downloaded_at is not None


def test_archiveresults_api_limit_uses_exact_count_without_full_row_distinct(client, api_headers):
    snapshot_response = api_client_request(
        client,
        "post",
        "/api/v1/core/snapshots",
        payload={
            "url": "https://example.com/archive-result-pagination",
            "title": "ArchiveResult pagination",
            "status": Snapshot.StatusChoices.QUEUED,
        },
        headers=api_headers,
    )
    assert snapshot_response.status_code == 200, snapshot_response.content
    snapshot_id = snapshot_response.json()["id"]

    for plugin_name in ("dom", "screenshot"):
        result_response = client.post(
            "/api/v1/core/archiveresults",
            {
                "snapshot_id": snapshot_id,
                "plugin": plugin_name,
                "hook_name": f"on_Snapshot__test_{plugin_name}",
                "status": ArchiveResult.StatusChoices.SUCCEEDED,
                "output_str": f"{plugin_name} output",
            },
            **api_headers,
        )
        assert result_response.status_code == 200, result_response.content

    total_archiveresults = ArchiveResult.objects.count()
    with CaptureQueriesContext(connection) as captured_queries:
        response = client.get(
            "/api/v1/core/archiveresults?limit=1",
            **api_headers,
        )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["count"] == total_archiveresults
    assert payload["total_items"] == total_archiveresults
    assert payload["limit"] == 1
    assert payload["num_items"] == 1

    count_queries = [
        query["sql"] for query in captured_queries if "COUNT" in query["sql"].upper() and '"core_archiveresult"' in query["sql"]
    ]
    assert count_queries
    assert not any("SELECT DISTINCT" in query.upper() for query in count_queries), count_queries


def test_archiveresults_api_join_filters_count_distinct_primary_keys(client, api_headers):
    snapshot_response = api_client_request(
        client,
        "post",
        "/api/v1/core/snapshots",
        payload={
            "url": "https://example.com/archive-result-tag-pagination",
            "title": "ArchiveResult tag pagination",
            "tags": ["api-tag-pagination-one", "api-tag-pagination-two"],
            "status": Snapshot.StatusChoices.QUEUED,
        },
        headers=api_headers,
    )
    assert snapshot_response.status_code == 200, snapshot_response.content
    snapshot_id = snapshot_response.json()["id"]

    result_response = client.post(
        "/api/v1/core/archiveresults",
        {
            "snapshot_id": snapshot_id,
            "plugin": "dom",
            "hook_name": "on_Snapshot__test_tag_pagination",
            "status": ArchiveResult.StatusChoices.SUCCEEDED,
            "output_str": "tag pagination output",
        },
        **api_headers,
    )
    assert result_response.status_code == 200, result_response.content

    with CaptureQueriesContext(connection) as captured_queries:
        response = client.get(
            "/api/v1/core/archiveresults?search=api-tag-pagination&limit=1",
            **api_headers,
        )

    assert response.status_code == 200, response.content
    payload = response.json()
    assert payload["count"] == 1
    assert payload["total_items"] == 1
    assert payload["num_items"] == 1
    assert [item["id"] for item in payload["items"]] == [result_response.json()["id"]]

    count_queries = [
        query["sql"] for query in captured_queries if "COUNT" in query["sql"].upper() and '"core_archiveresult"' in query["sql"]
    ]
    assert count_queries
    assert any("SELECT DISTINCT" in query.upper() for query in count_queries), count_queries
    assert not any('"core_archiveresult"."output_files" AS' in query for query in count_queries), count_queries
    assert not any('"core_archiveresult"."notes" AS' in query for query in count_queries), count_queries
