import pytest
import os
import time
import hashlib
import uuid

from archivebox.config.common import get_config
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
    crawl = Crawl.objects.create(urls="https://example.com/screencast", created_by=api_admin_user, permissions="private")
    # The hook keys live frames by the lexical absolute CRAWL_DIR path.
    crawl_key = hashlib.sha256(os.path.abspath(crawl.output_dir).encode()).hexdigest()
    frame = get_config(crawl=crawl).TMP_DIR / "chrome_screencast" / crawl_key / "latest.jpg"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes(b"stored frame")
    archived_frame = crawl.output_dir / "chrome_screencast" / "latest.jpg"
    archived_frame.parent.mkdir(parents=True, exist_ok=True)
    archived_frame.write_bytes(b"historical frame")
    started_at = time.time()
    os.utime(frame, (started_at - 10, started_at - 10))
    url = f"/api/v1/crawls/crawl/{crawl.id}/files/chrome_screencast/latest.jpg?after={started_at}"
    assert client.get(url).status_code == 404
    assert client.get(url, **api_headers).status_code == 404
    os.utime(frame, (started_at + 1, started_at + 1))
    response = client.get(url, **api_headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"stored frame"
    assert response["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate"
    assert client.get(url.replace(str(started_at), "invalid"), **api_headers).status_code == 400
    frame.unlink()
    response = client.get(url.split("?")[0], **api_headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"historical frame"
    assert archived_frame.read_bytes() == b"historical frame"


def test_screencast_frame_uses_legacy_live_dir_and_archived_fallback_freshness(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/screencast-legacy", created_by=api_admin_user, permissions="private")
    current_dir, legacy_dir = crawl.output_dir_candidates
    assert crawl.output_dir == current_dir
    assert legacy_dir == current_dir.with_name(str(uuid.UUID(hex=crawl.id.hex)))
    assert legacy_dir != current_dir
    live_root = get_config(crawl=crawl).TMP_DIR / "chrome_screencast"
    current_frame = live_root / hashlib.sha256(os.path.abspath(current_dir).encode()).hexdigest() / "latest.jpg"
    legacy_frame = live_root / hashlib.sha256(os.path.abspath(legacy_dir).encode()).hexdigest() / "latest.jpg"
    url = f"/api/v1/crawls/crawl/{crawl.id}/files/chrome_screencast/latest.jpg"

    # No live or archived frame yet.
    assert client.get(url, **api_headers).status_code == 404

    # A capture keyed by the legacy hyphenated crawl dir is still served.
    legacy_frame.parent.mkdir(parents=True, exist_ok=True)
    legacy_frame.write_bytes(b"legacy live frame")
    response = client.get(url, **api_headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"legacy live frame"

    # The current crawl dir's live frame wins over the legacy one.
    current_frame.parent.mkdir(parents=True, exist_ok=True)
    current_frame.write_bytes(b"current live frame")
    response = client.get(url, **api_headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"current live frame"

    # Without live frames, the archived frame is served and ?after= applies to it.
    current_frame.unlink()
    legacy_frame.unlink()
    archived_frame = crawl.output_dir / "chrome_screencast" / "latest.jpg"
    archived_frame.parent.mkdir(parents=True, exist_ok=True)
    archived_frame.write_bytes(b"archived frame")
    started_at = time.time()
    os.utime(archived_frame, (started_at - 10, started_at - 10))
    assert client.get(f"{url}?after={started_at}", **api_headers).status_code == 404
    os.utime(archived_frame, (started_at + 1, started_at + 1))
    response = client.get(f"{url}?after={started_at}", **api_headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"archived frame"
    assert response["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate"


def test_crawl_file_rejects_paths_outside_crawl_dir(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/crawl-file-traversal", created_by=api_admin_user)
    (crawl.output_dir / "folder").mkdir(parents=True, exist_ok=True)
    (crawl.output_dir / "inside.txt").write_text("inside")
    outside = crawl.output_dir.parent / "outside-secret.txt"
    outside.write_text("outside secret")
    (crawl.output_dir / "folder" / "escape.txt").symlink_to(outside)

    # ".." segments reach the view and stay usable inside the crawl dir.
    inside = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/folder/../inside.txt", **api_headers)
    assert inside.status_code == 200
    assert b"".join(inside.streaming_content) == b"inside"
    for path in ("../outside-secret.txt", "%2e%2e/outside-secret.txt", "folder/escape.txt"):
        response = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/{path}", **api_headers)
        assert response.status_code == 404, path
        assert response.json() == {"detail": "Crawl file not found"}, path
    # Directories and missing files are 404s, not server errors.
    for path in ("folder", "folder/missing.txt", "inside.txt/child"):
        response = client.get(f"/api/v1/crawls/crawl/{crawl.id}/files/{path}", **api_headers)
        assert response.status_code == 404, path
        assert response.json() == {"detail": "Crawl file not found"}, path
    assert outside.read_text() == "outside secret"
