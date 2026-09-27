import pytest
import os
import time

from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_basic_success_case_request(client, tmp_path, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/crawl-file-nested", created_by=api_admin_user)
    nested_dir = crawl.output_dir / "folder"
    nested_dir.mkdir(parents=True, exist_ok=True)
    (nested_dir / "basic.txt").write_text("ok")

    response = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/folder/basic.txt", **api_headers)

    assert response.status_code == 200, response.content


def test_screencast_frame_is_checked_by_image_request(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/screencast", created_by=api_admin_user)
    frame = crawl.output_dir / "chrome_screencast" / "latest.jpg"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"stored frame")
    started_at = time.time()
    os.utime(frame, (started_at - 10, started_at - 10))
    url = f"/api/v1/crawls/crawl/{crawl.id}/files/chrome_screencast/latest.jpg?after={started_at}"
    assert client.get(url, **api_headers).status_code == 404
    os.utime(frame, (started_at + 1, started_at + 1))
    response = client.get(url, **api_headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"stored frame"
    assert client.get(url.replace(str(started_at), "invalid"), **api_headers).status_code == 400
