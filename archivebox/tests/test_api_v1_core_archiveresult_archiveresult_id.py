import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/archiveresult-detail", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url="https://example.com/archiveresult-detail", crawl=crawl)
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="api-basic",
        hook_name="on_Snapshot__api_basic",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="ok",
    )

    response = client.get(f"/api/v1/core/archiveresult/{result.id}", **api_headers)

    assert response.status_code == 200, response.content


def test_archiveresult_patch_upload_finalizes_queued_result(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(
        urls="https://example.com",
        created_by=api_admin_user,
        status=Crawl.StatusChoices.SEALED,
        retry_at=None,
    )
    snapshot = Snapshot.objects.create(
        url="https://example.com/upload-patch",
        crawl=crawl,
        status=Snapshot.StatusChoices.SEALED,
        retry_at=None,
    )
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="dom",
        hook_name="on_Snapshot__archivebox_browser_extension_upload",
        status=ArchiveResult.StatusChoices.QUEUED,
    )

    response = client.generic(
        "PATCH",
        f"/api/v1/core/archiveresult/{result.id}",
        encode_multipart(
            BOUNDARY,
            {
                "files": SimpleUploadedFile("output.html", b"<html>uploaded</html>", content_type="text/html"),
                "output_paths": "output.html",
                "output_str": "output.html",
            },
        ),
        content_type=MULTIPART_CONTENT,
        **api_headers,
    )
    assert response.status_code == 200, response.content

    result.refresh_from_db()
    snapshot.refresh_from_db()
    assert result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert result.output_str == "output.html"
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert snapshot.retry_at is not None


@pytest.mark.parametrize("chunked", [False, True])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
def test_live_archiveresult_multipart_upload(tmp_path, chunked, method):
    import requests

    from archivebox.tests.conftest import (
        api_auth_headers,
        cli_env,
        create_admin_and_token,
        get_free_port,
        init_archive,
        live_api_request,
        stop_archivebox_process,
    )
    from archivebox.tests.test_api_v1_cli_add import start_api_server_without_runner

    init_archive(tmp_path)
    token = create_admin_and_token(tmp_path)
    port = get_free_port()
    server = start_api_server_without_runner(tmp_path, cli_env(port=port, server=True), port)
    try:
        snapshot = live_api_request(
            port,
            "post",
            "/api/v1/core/snapshots",
            api_token=token,
            json={"url": "https://example.com/multipart", "status": "sealed"},
        )
        assert snapshot.status_code == 200, snapshot.text
        result = live_api_request(
            port,
            "post",
            "/api/v1/core/archiveresults",
            api_token=token,
            data={"snapshot_id": snapshot.json()["id"], "plugin": "dom", "status": "started"},
        )
        assert result.status_code == 200, result.text
        payload = b"<html>Real multipart upload</html>"
        body = encode_multipart(
            BOUNDARY,
            {
                "files": SimpleUploadedFile("output.html", payload, content_type="text/html"),
                "output_paths": "output.html",
                "status": "succeeded",
                "snapshot_id": snapshot.json()["id"],
                "plugin": "dom",
            },
        )
        path = "/api/v1/core/archiveresults" if method == "POST" else f"/api/v1/core/archiveresult/{result.json()['id']}"
        response = requests.request(
            method,
            f"http://127.0.0.1:{port}{path}",
            data=iter([body]) if chunked else body,
            headers={**api_auth_headers(token, port=port), "Content-Type": MULTIPART_CONTENT},
            timeout=30,
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "succeeded"
        files = list((tmp_path / "archive").glob("users/*/snapshots/*/*/*/dom/output.html"))
        assert len(files) == 1
        assert files[0].read_bytes() == payload
    finally:
        stop_archivebox_process(server)
