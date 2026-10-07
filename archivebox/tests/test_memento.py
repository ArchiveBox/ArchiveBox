from datetime import UTC, datetime, timedelta
from hashlib import sha256
import gzip
import json
from pathlib import Path
from urllib.parse import quote, urlsplit
from zipfile import ZipFile

import pytest
import requests
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.http import http_date

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.core.routes_util import build_snapshot_detail_url, build_snapshot_url
from archivebox.crawls.models import Crawl


@pytest.fixture
def captures(admin_user, db):
    snapshots = []
    for day, permission in ((1, "public"), (3, "public"), (4, "unlisted"), (5, "private")):
        crawl = Crawl.objects.create(urls="https://example.com/page?a=1&b=%2F", created_by=admin_user)
        snapshot = Snapshot.objects.create(
            url=crawl.urls,
            crawl=crawl,
            bookmarked_at=datetime(2020, 1, day, tzinfo=UTC),
            downloaded_at=datetime(2026, 9, day, tzinfo=UTC),
            status=Snapshot.StatusChoices.SEALED,
            config={"PERMISSIONS": permission},
        )
        output = snapshot.output_dir / "singlefile" / "singlefile.html"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"<!doctype html><title>Capture {day}</title><p>Saved on day {day}</p>")
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="singlefile",
            hook_name="on_Snapshot__50_singlefile",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            start_ts=snapshot.downloaded_at - timedelta(seconds=10),
            end_ts=snapshot.downloaded_at,
            output_size=output.stat().st_size,
            output_files={"singlefile.html": {"size": output.stat().st_size}},
        )
        snapshot.refresh_from_db()
        snapshots.append(snapshot)
    return snapshots


def fetch(client, url, method="get", **headers):
    parts = urlsplit(url)
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    return getattr(client, method)(path, HTTP_HOST=parts.netloc or "web.archivebox.localhost:5797", **headers)


def capture_url(snapshot):
    return build_snapshot_detail_url(snapshot.archive_path_from_db)


@pytest.fixture
def archive_files(captures):
    # Real Webrecorder capture: exercise ZIP and gzip bytes, not placeholder bundles.
    fixture = Path(__file__).parent / "fixtures/memento/iframetest.wacz"
    with ZipFile(fixture) as bundle:
        assert bundle.testzip() is None
        compressed = bundle.read("archive/data.warc.gz")
    files = {"capture.wacz": fixture.read_bytes(), "capture.warc.gz": compressed, "capture.warc": gzip.decompress(compressed)}
    for snapshot in captures:
        output_dir = snapshot.output_dir / "webrecorder"
        output_dir.mkdir()
        for name, content in files.items():
            (output_dir / name).write_bytes(content)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="webrecorder",
            hook_name="on_Snapshot__90_webrecorder",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            start_ts=snapshot.downloaded_at - timedelta(seconds=10),
            end_ts=snapshot.downloaded_at,
            output_size=sum(map(len, files.values())),
            output_files={name: {"size": len(content)} for name, content in files.items()},
        )
    return files


@pytest.mark.django_db(transaction=True)
def test_memento_archive_enclosures(client, captures, archive_files):
    snapshot = captures[0]
    response = fetch(client, capture_url(snapshot))
    links = requests.utils.parse_header_links(response["Link"])
    enclosures = [link for link in links if link["rel"] == "enclosure"]
    assert len(enclosures) == 3
    types = {"capture.wacz": "application/wacz", "capture.warc": "application/warc", "capture.warc.gz": "application/gzip"}
    for link in enclosures:
        name = urlsplit(link["url"]).path.rsplit("/", 1)[-1]
        assert link["type"] == types[name]
        assert link["anchor"] == capture_url(snapshot)
        assert urlsplit(link["url"]).query == "raw=1"
        for method in ("get", "head"):
            download = fetch(client, link["url"], method)
            assert download.status_code == 200
            assert download["Content-Type"] == types[name]
            assert "Content-Encoding" not in download
            assert "Memento-Datetime" not in download
            assert b"".join(download.streaming_content) == (archive_files[name] if method == "get" else b"")
        partial = fetch(client, link["url"], HTTP_RANGE="bytes=0-9")
        assert partial.status_code == 206
        assert b"".join(partial.streaming_content) == archive_files[name][:10]
        assert "Content-Encoding" not in partial
        assert "Memento-Datetime" not in partial

    timemap = fetch(client, capture_url(snapshot) + "?format=link").content.decode()
    assert timemap.count('rel="enclosure"') == 6
    for capture in captures[:2]:
        assert f'anchor="{capture_url(capture)}"' in timemap
    for hidden in captures[2:]:
        assert str(hidden.id) not in timemap
    private_download = build_snapshot_url(str(captures[-1].id), "webrecorder/capture.wacz") + "?raw=1"
    assert fetch(client, private_download).status_code in (302, 403)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("name,mime", [("capture.wacz", "application/wacz"), ("capture.warc.gz", "application/gzip")])
def test_memento_archive_live_range(live_server, captures, archive_files, name, mime):
    url = urlsplit(build_snapshot_url(str(captures[0].id), "webrecorder/" + name))
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(
            live_server.url + url.path + "?raw=1",
            headers={"Host": url.netloc, "Range": "bytes=0-31"},
            timeout=10,
        )
    assert response.status_code == 206
    assert response.content == archive_files[name][:32]
    assert response.headers["Content-Type"] == mime
    assert "Content-Encoding" not in response.headers


@pytest.mark.django_db(transaction=True)
def test_memento_existing_routes(client, captures):
    first, latest, unlisted, private = captures
    gate = "/archive/" + quote(first.url, safe=":/")
    response = fetch(client, gate, HTTP_ACCEPT_DATETIME=http_date(first.downloaded_at.timestamp()))
    assert response.status_code == 302
    assert response["Location"] == capture_url(first)
    assert "accept-datetime" in response["Vary"].lower()
    assert "Memento-Datetime" not in response
    assert 'rel="original"' in response["Link"]

    for method in ("get", "head"):
        response = fetch(client, capture_url(first), method)
        assert response.status_code == 200
        assert response["Memento-Datetime"] == http_date(first.downloaded_at.timestamp())
        assert f'<{first.url}>; rel="original"' in response["Link"]
        assert 'rel="timegate"' in response["Link"]
        response = fetch(client, capture_url(first) + "?format=link", method)
        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/link-format")
        assert "Memento-Datetime" not in response
        if method == "get":
            body = response.content.decode()
            assert capture_url(first) in body and capture_url(latest) in body
            assert capture_url(unlisted) not in body and capture_url(private) not in body
            assert body.count('rel="memento"') == 2
            assert http_date(first.downloaded_at.timestamp()) in body
        else:
            assert response.content == b""

    output_url = build_snapshot_url(str(first.id), "singlefile/singlefile.html")
    response = fetch(client, output_url)
    assert response.status_code == 200
    assert response["Memento-Datetime"] == http_date(first.downloaded_at.timestamp())


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("day,selected", [(None, 1), (1, 0), (2, 0), (3, 1), (9, 1)])
def test_timegate_selection(client, captures, day, selected):
    headers = {} if day is None else {"HTTP_ACCEPT_DATETIME": http_date(datetime(2026, 9, day, tzinfo=UTC).timestamp())}
    response = fetch(client, "/archive/" + quote(captures[0].url, safe=":/"), **headers)
    assert response.status_code == 302
    assert response["Location"] == capture_url(captures[selected])


@pytest.mark.django_db(transaction=True)
def test_timegate_errors_and_no_fuzzy_matches(client, captures):
    gate = "/archive/" + quote(captures[0].url, safe=":/")
    for date in ("garbage", "", "Sun, 06 Nov 1994 08:49:37 +0000"):
        assert fetch(client, gate, HTTP_ACCEPT_DATETIME=date).status_code == 400
    for url in ("https://example.com/page", "http://example.com/page?a=1&b=%2F", "https://example.com/missing"):
        assert fetch(client, "/archive/" + quote(url, safe=":/")).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_memento_private_access_and_incomplete_capture(client, captures):
    first, _, unlisted, private = captures
    assert fetch(client, capture_url(unlisted)).status_code == 200
    response = fetch(client, capture_url(private))
    assert response.status_code in (302, 403)
    assert "Memento-Datetime" not in response and "Link" not in response
    first.downloaded_at = None
    first.save(update_fields=["downloaded_at"])
    response = fetch(client, capture_url(first))
    assert response.status_code == 200
    assert "Memento-Datetime" not in response
    response = fetch(client, capture_url(unlisted) + "?format=link")
    assert capture_url(first) not in response.content.decode()


@pytest.mark.django_db(transaction=True)
def test_memento_authenticated_discovery(client, captures, admin_user, archive_files):
    assert client.login(username=admin_user.username, password="testpassword")
    url = urlsplit(capture_url(captures[0]))
    response = client.get(url.path + "?format=link", HTTP_HOST="admin.archivebox.localhost:5797")
    assert response.status_code == 200
    assert response.content.decode().count('rel="memento"') == 4
    assert response.content.decode().count('rel="enclosure"') == 12
    assert response["Cache-Control"] == "private, no-store"
    assert "Cookie" in response["Vary"]


@pytest.mark.django_db(transaction=True)
def test_memento_discovery_is_read_only(client, captures, archive_files):
    with CaptureQueriesContext(connection) as queries:
        assert fetch(client, capture_url(captures[0]) + "?format=link").status_code == 200
        assert fetch(client, "/archive/" + quote(captures[0].url, safe=":/")).status_code == 302
    assert queries.captured_queries
    assert all(query["sql"].lstrip().split()[0].upper() == "SELECT" for query in queries.captured_queries)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("host", ["web.archivebox.localhost", "archive.example.test"])
def test_memento_live_http(live_server, captures, host):
    first = captures[0]
    session = requests.Session()
    session.trust_env = False

    def get(url, method="GET", **headers):
        parts = urlsplit(url)
        return session.request(
            method,
            live_server.url + parts.path + (f"?{parts.query}" if parts.query else ""),
            headers={"Host": parts.netloc or host, **headers},
            allow_redirects=False,
            timeout=10,
        )

    gate = "/archive/" + first.url
    # Exercise an unencoded source query as well as the encoded advertised URI.
    response = get(gate, **{"Accept-Datetime": http_date(first.downloaded_at.timestamp() - 86400)})
    assert response.status_code == 302
    assert "accept-datetime" in response.headers["Vary"].lower()
    target = response.headers["Location"]
    assert str(first.id) in target
    response = get(target)
    assert response.status_code == 200
    assert response.headers["Memento-Datetime"] == http_date(first.downloaded_at.timestamp())
    assert response.content
    links = {link["rel"]: link["url"] for link in requests.utils.parse_header_links(response.headers["Link"])}
    advertised = get(links["timegate"], **{"Accept-Datetime": http_date(first.downloaded_at.timestamp())})
    assert advertised.status_code == 302 and advertised.headers["Location"] == target
    response = get(target, method="HEAD", **{"Accept-Datetime": http_date(captures[1].downloaded_at.timestamp())})
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["Memento-Datetime"] == http_date(first.downloaded_at.timestamp())
    response = get(target + "?format=link")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/link-format")
    assert response.text.count('rel="memento"') == 2
    assert "Memento-Datetime" not in response.headers
    output = target + "/singlefile/singlefile.html"
    response = get(output)
    assert response.status_code == 302
    response = get(response.headers["Location"])
    assert response.status_code == 200
    assert "Saved on day 1" in response.text
    assert response.headers["Memento-Datetime"] == http_date(first.downloaded_at.timestamp())
    session.close()


@pytest.mark.django_db(transaction=True)
def test_memento_excludes_application_and_auxiliary_files(client, captures):
    snapshot = captures[0]
    (snapshot.output_dir / "singlefile" / "stdout.log").write_text("A capture log")
    for path in ("singlefile/stdout.log", "singlefile/"):
        response = fetch(client, build_snapshot_url(str(snapshot.id), path) + "?files=1")
        assert response.status_code == 200
        assert "Memento-Datetime" not in response
    response = fetch(client, build_snapshot_url(str(snapshot.id), "singlefile/missing.html"))
    assert response.status_code == 404
    assert "Memento-Datetime" not in response


@pytest.mark.django_db(transaction=True)
def test_memento_range_and_conditional_responses(client, captures):
    snapshot = captures[0]
    path = "singlefile/singlefile.html"
    content = (snapshot.output_dir / path).read_bytes()
    digest = sha256(content).hexdigest()
    hashes = snapshot.output_dir / "hashes" / "hashes.json"
    hashes.parent.mkdir()
    hashes.write_text(json.dumps({"files": [{"path": path, "hash": digest}]}))
    url = build_snapshot_url(str(snapshot.id), path) + "?raw=1"
    response = fetch(client, url, HTTP_RANGE="bytes=0-9")
    assert response.status_code == 206
    assert b"".join(response.streaming_content) == content[:10]
    assert response["Memento-Datetime"] == http_date(snapshot.downloaded_at.timestamp())
    response = fetch(client, url, HTTP_IF_NONE_MATCH=f'"{digest}"')
    assert response.status_code == 304
    assert response.content == b""
    assert response["ETag"] == f'"{digest}"'
    assert response["Memento-Datetime"] == http_date(snapshot.downloaded_at.timestamp())
    assert 'rel="original"' in response["Link"]
