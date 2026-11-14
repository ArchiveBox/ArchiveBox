import hashlib
import os
import time
from pathlib import Path

import pytest

from archivebox.config.common import get_config
from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db(transaction=True)


def test_live_preview_route_is_declared_by_plugin(client, api_headers):
    from django.urls import resolve, reverse
    from archivebox.plugins.discovery import get_plugin_app, get_plugin_catalog

    plugin = get_plugin_catalog()["chrome_screencast"]
    assert plugin.manifest["snapshot_live_preview"] is True
    route = plugin.config.snapshot_live_preview_route
    assert reverse(route, kwargs={"snapshot_id": "0123456789abcdef0123456789abcdef"}) == (
        "/api/v1/core/snapshot/0123456789abcdef0123456789abcdef/screencast.jpg"
    )
    legacy = "/api/v1/crawls/crawl/0123456789abcdef0123456789abcdef/files/chrome_screencast/latest.jpg"
    assert resolve(legacy).url_name == "crawl_screencast"
    app = get_plugin_app(plugin.name)
    assert app is not None
    assert callable(app.get_api_routers)
    schema = client.get("/api/v1/openapi.json", **api_headers)
    assert schema.status_code == 200
    assert "/api/v1/core/snapshot/{snapshot_id}/screencast.jpg" in schema.json()["paths"]
    assert "/api/v1/crawls/crawl/{crawl_id}/files/chrome_screencast/latest.jpg" in schema.json()["paths"]


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
