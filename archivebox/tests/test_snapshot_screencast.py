import hashlib
import os
import time
from pathlib import Path

import pytest

from archivebox.config.common import get_config
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_snapshot_screencasts_are_isolated_and_private(client, api_admin_user, api_headers):
    crawl = Crawl.objects.create(urls="https://example.com/a\nhttps://example.com/b", created_by=api_admin_user, permissions="public")
    snapshots = [
        Snapshot.objects.create(url=f"https://example.com/{name}", crawl=crawl, config={"PERMISSIONS": "private"}) for name in ("a", "b")
    ]
    jpeg = (Path(__file__).parent / "fixtures/bablosoft-lazy-image/pic.jpg").read_bytes()
    frames = []
    urls = []
    for index, snapshot in enumerate(snapshots):
        key = hashlib.sha256(os.path.abspath(snapshot.output_dir).encode()).hexdigest()
        frame = get_config(snapshot=snapshot).TMP_DIR / "chrome_screencast" / key / "latest.jpg"
        frame.parent.mkdir(parents=True, exist_ok=True)
        # A distinct valid JPEG comment keeps these real image bytes identifiable.
        frame.write_bytes(jpeg[:2] + b"\xff\xfe\x00\x03" + bytes([65 + index]) + jpeg[2:])
        frames.append(frame)
        urls.append(f"/api/v1/core/snapshot/{snapshot.pk}/screencast.jpg")

    for url, frame in zip(urls, frames):
        assert client.get(url).status_code == 404
        response = client.get(url, **api_headers)
        assert response.status_code == 200
        assert b"".join(response.streaming_content) == frame.read_bytes()
        assert response["Cache-Control"] == "no-store, no-cache, max-age=0, must-revalidate"

    # A sibling's live frame and the old shared crawl frame must never fill a
    # missing snapshot frame, even when the crawl itself is public.
    shared_key = hashlib.sha256(os.path.abspath(crawl.output_dir).encode()).hexdigest()
    shared = get_config(crawl=crawl).TMP_DIR / "chrome_screencast" / shared_key / "latest.jpg"
    shared.parent.mkdir(parents=True, exist_ok=True)
    shared.write_bytes(jpeg)
    frames[0].unlink()
    assert client.get(urls[0], **api_headers).status_code == 404
    response = client.get(urls[1], **api_headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == frames[1].read_bytes()


def test_snapshot_screencast_requires_fresh_frame_and_full_unlisted_id(client, api_admin_user):
    crawl = Crawl.objects.create(urls="https://example.com/unlisted", created_by=api_admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl, config={"PERMISSIONS": "unlisted"})
    key = hashlib.sha256(os.path.abspath(snapshot.output_dir).encode()).hexdigest()
    frame = get_config(snapshot=snapshot).TMP_DIR / "chrome_screencast" / key / "latest.jpg"
    frame.parent.mkdir(parents=True, exist_ok=True)
    frame.write_bytes((Path(__file__).parent / "fixtures/bablosoft-lazy-image/pic.jpg").read_bytes())
    now = time.time()
    os.utime(frame, (now - 10, now - 10))
    url = f"/api/v1/core/snapshot/{snapshot.pk}/screencast.jpg"
    assert client.get(f"{url}?after={now}").status_code == 404
    assert client.get(f"{url}?after=invalid").status_code == 400
    assert client.get(url.replace(str(snapshot.pk), str(snapshot.pk)[:8])).status_code == 404
    os.utime(frame, (now + 1, now + 1))
    response = client.get(f"{url}?after={now}")
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == frame.read_bytes()
