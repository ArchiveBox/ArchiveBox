"""Metadata download bodies use bounded file streams and release ownership on disconnect."""

import asyncio
import os
import stat
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import pytest

from archivebox.core.models import Snapshot
from archivebox.misc.serve_static import RangedFileReader
from archivebox.tests.conftest import ADMIN_TEST_HOST, API_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def large_export(crawl):
    # Keep every export larger than a response chunk when the reader batch size
    # changes, so disconnect tests still stop before consuming the whole body.
    title = "Export, café\n" * 45
    Snapshot.objects.bulk_create(
        [
            Snapshot(
                crawl=crawl,
                url=f"https://example.com/export-stream/{index}",
                timestamp=str(1900000000 + index),
                title=title,
                permissions="public",
            )
            for index in range(RangedFileReader.block_size // len(title.encode()) + 1)
        ],
    )
    return {"crawl_id": str(crawl.pk)}


@pytest.mark.parametrize("format", ["csv", "jsonl", "rss"])
def test_metadata_export_wsgi_file_and_head(admin_client, large_export, format):
    path = f"/admin/core/snapshot/export.{format}"
    before = regular_files()
    response = admin_client.get(path, large_export, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200
    assert response.streaming and not response.is_async
    body_length = int(response["Content-Length"])
    spools = {item for item in regular_files() - before if item[2] == body_length}
    assert len(spools) == 1
    body = response.getvalue()
    assert len(body) == body_length > RangedFileReader.block_size
    assert not spools.intersection(regular_files())
    head = admin_client.head(path, large_export, HTTP_HOST=ADMIN_TEST_HOST)
    assert head.status_code == 200 and head.getvalue() == b""
    for key in ("Content-Type", "Content-Length", "Content-Disposition", "Cache-Control", "Referrer-Policy"):
        assert head.get(key) == response.get(key), key
    if format == "rss":
        assert "Content-Disposition" not in response


def regular_files():
    files = set()
    for name in os.listdir("/dev/fd"):
        try:
            info = os.fstat(int(name))
        except OSError:  # The descriptor used to list /dev/fd is already closed.
            continue
        if stat.S_ISREG(info.st_mode):
            files.add((info.st_dev, info.st_ino, info.st_size))
    return files


@pytest.mark.parametrize("ending", ["complete", "before-body", "during-body"])
@pytest.mark.parametrize("format", ["jsonl", "rss"])
def test_metadata_export_actual_asgi_stream_closes_spool(initialized_archive, large_export, client, ending, format):
    from archivebox.core.asgi import application

    path = f"/api/v1/core/snapshots/export/{format}"
    expected = client.get(path, large_export, HTTP_HOST=API_TEST_HOST, secure=True).getvalue() if ending == "complete" else b""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": f"crawl_id={large_export['crawl_id']}".encode(),
        "headers": [(b"host", API_TEST_HOST.encode())],
        "server": ("127.0.0.1", 443),
        "client": ("127.0.0.1", 12345),
    }

    async def exchange():
        inbound = asyncio.Queue()
        await inbound.put({"type": "http.request"})
        before = regular_files()
        spools = set()
        received = bytearray()

        async def disconnect():
            await inbound.put({"type": "http.disconnect"})
            # A slow consumer: Django must cancel the actual send and close the spool.
            await asyncio.Future()

        async def send(message):
            if message["type"] == "http.response.start":
                assert message["status"] == 200
                body_length = int({key.lower(): value for key, value in message["headers"]}[b"content-length"])
                spools.update(item for item in regular_files() - before if item[2] == body_length)
                assert len(spools) == 1
                if ending == "before-body":
                    await disconnect()
            else:
                assert message["type"] == "http.response.body"
                chunk = message.get("body", b"")
                assert len(chunk) <= RangedFileReader.block_size
                if ending == "during-body":
                    assert message["more_body"] and len(chunk) == RangedFileReader.block_size
                    await disconnect()
                received.extend(chunk)

        await asyncio.wait_for(application(scope, inbound.get, send), timeout=5)
        assert len(spools) == 1 and not spools.intersection(regular_files())
        assert received == expected

    asyncio.run(exchange())


@pytest.mark.parametrize("date_source", ["updated", "published", "empty"])
@pytest.mark.parametrize("security_mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
def test_public_rss_spool_matches_django_bytes_and_channel_date(client, crawl, date_source, security_mode):
    from archivebox.api.v1_core import _snapshots_rss_response
    from archivebox.core.routes_util import build_snapshot_detail_url, build_web_url
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "SERVER_SECURITY_MODE": security_mode}
    machine.save(update_fields=["config"])

    earliest = datetime(2026, 1, 1, tzinfo=UTC)
    latest = earliest + timedelta(days=4)
    empty = date_source == "empty"
    first = Snapshot.objects.create(
        crawl=crawl,
        url="https://example.com/archive?q=red&color=blå",
        title='Café "paper" &lt;p&gt; & berries',
        config={"PERMISSIONS": "public"},
        bookmarked_at=latest if date_source == "published" else earliest,
    )
    first.save_tags(['éclair "quoted" & <tag>'])
    Snapshot.objects.filter(pk=first.pk).update(
        created_at=earliest,
        modified_at=earliest if date_source == "published" else latest,
        title='Café "paper" &lt;p&gt; & berries',
        fs_version="0.8.0",
    )
    first.refresh_from_db()
    second = Snapshot.objects.create(
        crawl=crawl,
        url="https://example.com/second",
        title="Strawberries",
        config={"PERMISSIONS": "public"},
        bookmarked_at=earliest + timedelta(days=1),
    )
    Snapshot.objects.filter(pk=second.pk).update(
        created_at=earliest + timedelta(days=1),
        modified_at=earliest + timedelta(days=2),
        fs_version="1.0.0",
    )
    second.refresh_from_db()
    Snapshot.objects.create(
        crawl=crawl,
        url="https://example.com/private",
        title="Not in a public export",
        config={"PERMISSIONS": "private"},
    )
    filters = {"crawl_id": str(crawl.pk)}
    if empty:
        filters["crawl_id"] = "00000000-0000-0000-0000-000000000001"
    started = datetime.now(UTC).replace(microsecond=0)
    response = client.get("/api/v1/core/snapshots/export/rss", filters, HTTP_HOST=API_TEST_HOST)
    assert response.status_code == 200
    assert response.streaming
    assert response["Content-Type"] == "application/rss+xml; charset=utf-8"
    assert "Content-Disposition" not in response
    body = response.getvalue()
    channel = ElementTree.fromstring(body).find("./channel")
    build_date = parsedate_to_datetime(channel.findtext("lastBuildDate"))
    rows = [] if empty else [second, first]
    reference = _snapshots_rss_response(response.wsgi_request, snapshots=rows).content
    assert [item.findtext("guid") for item in channel.findall("item")] == [str(row.pk) for row in rows]
    assert channel.findtext("link") == build_web_url("/public/", request=response.wsgi_request)
    # Legacy timestamp paths and current owner/date paths keep the same escaping
    # and request-specific origin when RSS resolves that origin just once.
    assert [item.findtext("link") for item in channel.findall("item")] == [
        build_snapshot_detail_url(row.archive_path_from_db, request=response.wsgi_request) for row in rows
    ]
    if empty:
        assert started <= build_date <= datetime.now(UTC)
        # Match the exact dynamic RFC 2822 date if the two real renders cross a second boundary.
        date = ElementTree.fromstring(reference).findtext("./channel/lastBuildDate").encode()
        reference = reference.replace(b"<lastBuildDate>" + date, b"<lastBuildDate>" + channel.findtext("lastBuildDate").encode(), 1)
    else:
        assert build_date == latest
        assert b"&lt;p&gt; &amp; berries" in body
        assert 'éclair "quoted" &amp;<'.encode() in body
    assert body == reference
