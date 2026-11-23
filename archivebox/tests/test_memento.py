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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("viewer", ["anonymous", "member", "staff"])
@pytest.mark.parametrize("current", [0, 2])
def test_capture_discovery_permissions(client, captures, django_user_model, viewer, current):
    hidden_owner = django_user_model.objects.create_user(username="hidden-capture-owner", password="testpassword")
    for snapshot in captures[2:]:
        snapshot.crawl.created_by = hidden_owner
        snapshot.crawl.save(update_fields=["created_by"])
    if viewer != "anonymous":
        user = django_user_model.objects.create_user(username="capture-viewer", password="testpassword", is_staff=viewer == "staff")
        assert client.login(username=user.username, password="testpassword")

    path = urlsplit(capture_url(captures[current])).path
    visible = captures if viewer == "staff" else captures[:2]
    for suffix in ("", "?format=link"):
        response = client.get(path + suffix, HTTP_HOST="admin.archivebox.localhost:5797")
        assert response.status_code == 200
        body = response.content.decode()
        if suffix:
            links = requests.utils.parse_header_links(body.replace("\n", ""))
            discovered = {link["url"] for link in links if link["rel"] == "memento"}
            assert discovered == {capture_url(snapshot) for snapshot in visible}
        for snapshot in captures:
            # Both formats link to the explicitly opened capture itself.
            expected = snapshot in visible or snapshot == captures[current]
            assert (str(snapshot.id) in body) == expected
        if viewer != "staff" and current == 0:
            assert hidden_owner.username not in body


@pytest.mark.django_db(transaction=True)
def test_static_capture_export_includes_all_permissions(captures, tmp_path):
    snapshot = captures[0]
    snapshot.write_html_details(out_dir=tmp_path)
    body = (tmp_path / "index.html").read_text()
    for capture in captures:
        assert str(capture.id) in body


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
            assert int(download["Content-Length"]) == len(archive_files[name])
            if method == "get":
                assert b"".join(download.streaming_content) == archive_files[name]
            else:
                assert not download.streaming
                assert download.content == b""
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
def test_replay_server_timing_preserves_saved_response(live_server, captures):
    snapshot = captures[0]
    path = "singlefile/singlefile.html"
    url = urlsplit(build_snapshot_url(str(snapshot.id), path))
    original = (snapshot.output_dir / path).read_bytes()
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(live_server.url + url.path + "?raw=1", headers={"Host": url.netloc}, timeout=10)
    assert response.status_code == 200
    assert response.content == original
    assert response.headers["Memento-Datetime"] == http_date(snapshot.downloaded_at.timestamp())
    assert 'rel="original"' in response.headers["Link"]
    timings = dict(part.strip().split(";dur=") for part in response.headers["Server-Timing"].split(","))
    assert {"replay", "replay_cpu", "replay_file"} <= timings.keys()
    assert 0 <= float(timings["replay_file"]) <= float(timings["replay"])
    assert float(timings["replay_cpu"]) >= 0
    assert (snapshot.output_dir / path).read_bytes() == original


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
@pytest.mark.parametrize("dated", [False, True])
@pytest.mark.parametrize("representation", ["detail", "raw", "viewer", "redirect", "card"])
def test_capture_representations_link_original_canonical(client, captures, dated, representation):
    snapshot = captures[0]
    if not dated:
        snapshot.downloaded_at = None
        snapshot.save(update_fields=["downloaded_at"])
    output = "singlefile/singlefile.html"
    urls = {
        "detail": capture_url(snapshot),
        "raw": build_snapshot_url(str(snapshot.id), output) + "?raw=1",
        "viewer": build_snapshot_url(str(snapshot.id), output) + "?preview=1",
        "redirect": capture_url(snapshot) + "/" + output,
        "card": build_snapshot_url(str(snapshot.id), f"_card/{snapshot.archiveresult_set.get(plugin='singlefile').pk}"),
    }
    response = fetch(client, urls[representation])
    assert response.status_code == (302 if representation == "redirect" else 200)
    links = {link["rel"]: link["url"] for link in requests.utils.parse_header_links(response.get("Link", ""))}
    assert links["canonical"] == links["original"] == snapshot.url
    assert links["timemap"] == capture_url(snapshot) + "?format=link"
    assert urlsplit(links["timegate"]).path == "/archive/" + quote(snapshot.url, safe=":/")
    if dated and representation != "redirect":
        assert response["Memento-Datetime"] == http_date(snapshot.downloaded_at.timestamp())
    else:
        assert "Memento-Datetime" not in response
    response.close()


@pytest.mark.django_db(transaction=True)
def test_crawler_raw_memento_links_do_not_load_manifests(client, captures):
    snapshot = captures[0]
    path = "dom/output.html"
    output = snapshot.output_dir / path
    output.parent.mkdir()
    content = b"<!doctype html><title>Saved DOM</title><p>Original saved bytes</p>"
    output.write_bytes(content)
    with CaptureQueriesContext(connection) as queries:
        response = fetch(client, build_snapshot_url(str(snapshot.id), path), HTTP_USER_AGENT="ChatGPT-User/1.0")
    assert response.status_code == 200
    assert response["Memento-Datetime"] == http_date(snapshot.downloaded_at.timestamp())
    links = {link["rel"]: link["url"] for link in requests.utils.parse_header_links(response["Link"])}
    assert links["original"] == links["canonical"] == snapshot.url
    assert links["timemap"] == capture_url(snapshot) + "?format=link"
    assert "enclosure" not in links
    assert not any('"core_archiveresult"' in query["sql"] for query in queries)
    assert b"".join(response.streaming_content) == content
    response.close()


@pytest.mark.django_db(transaction=True)
def test_wacz_viewer_has_capture_headers_but_bundle_has_no_capture_date(client, captures, archive_files):
    snapshot = captures[0]
    url = build_snapshot_url(str(snapshot.id), "webrecorder/capture.wacz")
    viewer = fetch(client, url + "?preview=1")
    assert viewer.status_code == 200
    assert viewer["Content-Type"].startswith("text/html")
    assert viewer["Memento-Datetime"] == http_date(snapshot.downloaded_at.timestamp())
    links = {link["rel"]: link["url"] for link in requests.utils.parse_header_links(viewer["Link"])}
    assert links["canonical"] == links["original"] == snapshot.url
    assert links["timemap"] == capture_url(snapshot) + "?format=link"
    download = fetch(client, url + "?raw=1")
    assert download.status_code == 200
    assert "Memento-Datetime" not in download
    links = {link["rel"]: link["url"] for link in requests.utils.parse_header_links(download["Link"])}
    assert links["canonical"] == links["original"] == snapshot.url
    assert b"".join(download.streaming_content) == archive_files["capture.wacz"]
    download.close()


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
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url.path + "?format=link", HTTP_HOST="admin.archivebox.localhost:5797")
    assert response.status_code == 200
    assert response.content.decode().count('rel="memento"') == 4
    assert response.content.decode().count('rel="enclosure"') == 12
    assert response["Cache-Control"] == "private, no-store"
    assert "Cookie" in response["Vary"]
    manifest_queries = [query["sql"] for query in queries if '"core_archiveresult"."output_files"' in query["sql"]]
    assert len(manifest_queries) == 1, manifest_queries


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
    for capture in captures:
        assert (str(capture.id) in response.text) == (capture in captures[:2])
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
        links = {link["rel"]: link["url"] for link in requests.utils.parse_header_links(response["Link"])}
        assert links["canonical"] == links["original"] == snapshot.url
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
    seal = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="hashes",
        status="succeeded",
        output_files={"hashes.json": {"size": hashes.stat().st_size}},
    )
    revision = f"{seal.id.hex}-{seal.modified_at.isoformat()}"
    validator = sha256(f"{revision}:{path}".encode()).hexdigest()
    url = build_snapshot_url(str(snapshot.id), path) + "?raw=1"
    response = fetch(client, url, HTTP_RANGE="bytes=0-9")
    assert response.status_code == 206
    assert b"".join(response.streaming_content) == content[:10]
    assert response["ETag"] == f'"{validator}"'
    assert response["Memento-Datetime"] == http_date(snapshot.downloaded_at.timestamp())
    response = fetch(client, url, HTTP_IF_NONE_MATCH=f'"{validator}"')
    assert response.status_code == 304
    assert response.content == b""
    assert response["ETag"] == f'"{validator}"'
    assert response["Memento-Datetime"] == http_date(snapshot.downloaded_at.timestamp())
    assert 'rel="original"' in response["Link"]


@pytest.mark.django_db(transaction=True)
def test_raw_output_enclosures_only_resolve_archive_paths(client, captures, archive_files):
    import sys

    from archivebox.memento.views import _enclosures

    snapshot = captures[0]
    directory = snapshot.output_dir / "responses"
    directory.mkdir()
    files = {}
    for index in range(64):
        name = f"asset-{index}.txt"
        path = directory / name
        path.write_text(f"Captured asset {index}")
        files[name] = {"size": path.stat().st_size, "mimetype": "text/plain"}
    ArchiveResult.objects.create(snapshot=snapshot, plugin="responses", status="succeeded", output_files=files)
    resolved_paths = []

    def observe(frame, event, _arg):
        if event == "call" and frame.f_code is ArchiveResult.output_file_path.__code__:
            if frame.f_back is not None and frame.f_back.f_code is _enclosures.__code__:
                resolved_paths.append(frame.f_locals["path"])

    # Observe real call frames on this request thread, not cProfile's aggregate
    # caller attribution (which can misattribute calls across other threads).
    previous_profile = sys.getprofile()
    try:
        sys.setprofile(observe)
        with CaptureQueriesContext(connection) as queries:
            response = fetch(client, build_snapshot_url(str(snapshot.id), "singlefile/singlefile.html") + "?raw=1")
    finally:
        sys.setprofile(previous_profile)
    assert response.status_code == 200
    assert b"Saved on day 1" in b"".join(response.streaming_content)
    assert len([link for link in requests.utils.parse_header_links(response["Link"]) if link["rel"] == "enclosure"]) == 3
    assert len(resolved_paths) == 3, resolved_paths
    assert set(resolved_paths) == set(archive_files), resolved_paths
    manifest_queries = [query["sql"] for query in queries if '"core_archiveresult"."output_files"' in query["sql"]]
    enclosure_query = manifest_queries[-1]
    assert '"output_str"' not in enclosure_query.split(" FROM ")[0]
    assert "\"status\" = 'succeeded'" in enclosure_query


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("viewer", ["anonymous", "member", "staff", "inactive_staff"])
def test_timegate_bounded_projection_preserves_ties_and_permissions(admin_user, django_user_model, viewer):
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory
    from archivebox.core.routes_util import build_snapshot_detail_url
    from archivebox.memento.views import _links, timegate_response
    from django.http import Http404

    url = "https://memento.example.invalid/ties"
    dt = datetime(2026, 1, 1, tzinfo=UTC)
    crawls = [Crawl(created_by=admin_user, urls=url, config={"HEAVY": "x" * 10000}) for _ in range(8)]
    Crawl.objects.bulk_create(crawls)
    rows = [
        Snapshot(
            timestamp=str(1710000000 + i),
            url=url,
            crawl=crawls[i],
            bookmarked_at=dt,
            downloaded_at=dt + timedelta(seconds=(i // 2) * 10),
            fs_version="0.9.5" if i % 2 else "0.7.0",
            output_size=1,
            config={"PERMISSIONS": "public" if i < 4 else ("unlisted" if i < 6 else "private")},
        )
        for i in range(8)
    ]
    Snapshot.objects.bulk_create(rows)
    request = RequestFactory().get("/archive/" + url)
    request.user = (
        AnonymousUser()
        if viewer == "anonymous"
        else django_user_model.objects.create_user(username=viewer, is_staff=viewer.endswith("staff"), is_active=viewer != "inactive_staff")
    )
    visible = sorted(rows if viewer == "staff" else rows[:4], key=lambda x: (x.downloaded_at, x.id))
    for seconds in [None, -10, 0, 5, 10, 15, 25, 35]:
        user = request.user
        headers = {} if seconds is None else {"HTTP_ACCEPT_DATETIME": http_date((dt + timedelta(seconds=seconds)).timestamp())}
        request = RequestFactory().get("/archive/" + url, **headers)
        request.user = user
        expected = visible[-1] if seconds is None else min(visible, key=lambda x: abs((x.downloaded_at - dt).total_seconds() - seconds))
        with CaptureQueriesContext(connection) as queries:
            response = timegate_response(request, url)
        assert response.status_code == 302
        assert response["Location"] == build_snapshot_detail_url(expected.archive_path_from_db, request=request)
        assert response["Link"] == ", ".join(_links(request, expected))
        assert response["Vary"] == "Accept-Datetime"
        assert response["Cache-Control"] == "private, no-store"
        assert "Memento-Datetime" not in response
        capture_queries = [q["sql"] for q in queries if 'FROM "core_snapshot"' in q["sql"]]
        assert len(capture_queries) == (1 if seconds is None else 2)
        assert all(
            "LIMIT 1" in sql and '"crawls_crawl"."urls"' not in sql and '"auth_user"."password"' not in sql for sql in capture_queries
        )
    with pytest.raises(Http404):
        timegate_response(request, url + "/missing")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("viewer", ["anonymous", "staff"])
@pytest.mark.parametrize("manifest_kind", ["mapping", "paths", "records", "json", "single", "empty"])
def test_timemap_projects_paths_and_preserves_legacy_manifests(captures, archive_files, admin_user, viewer, manifest_kind):
    from django.contrib.auth.models import AnonymousUser
    from django.test import RequestFactory
    from archivebox.memento.views import _captures, _enclosures, _links, timemap_response

    manifests = {
        "mapping": {"capture.warc": {"size": 12}, "capture.wacz": {"root_relative": True}, "../escape.warc": {}},
        "paths": ["capture.warc", "capture.wacz"],
        "records": [{"path": "capture.warc", "size": 12}, {"path": "capture.wacz", "root_relative": True}],
        "json": json.dumps({"capture.warc": {"size": 12}}),
        "single": "capture.warc",
        "empty": {},
    }
    ArchiveResult.objects.filter(plugin="webrecorder").update(
        output_files=manifests[manifest_kind],
        output_str="capture log\n" * 1000,
        output_json={"detail": "x" * 10000},
    )
    Snapshot.objects.filter(pk=captures[0].pk).update(fs_version="0.7.0")
    snapshot = Snapshot.objects.select_related("crawl__created_by").get(pk=captures[0].pk)
    request = RequestFactory().get("/ignored")
    request.user = admin_user if viewer == "staff" else AnonymousUser()
    # Build the same complete link document from full rows; the projected view
    # must preserve legacy manifests, permission membership and enclosure order.
    links = _links(request, snapshot, relation="self")
    for capture in _captures(request, snapshot.url).prefetch_related("archiveresult_set"):
        url = build_snapshot_detail_url(capture.archive_path_from_db, request=request)
        links.append(f'<{url}>; rel="memento"; datetime="{http_date(capture.downloaded_at.timestamp())}"')
        links.extend(_enclosures(request, capture))
    with CaptureQueriesContext(connection) as queries:
        response = timemap_response(request, snapshot)
    assert response.status_code == 200
    assert response.content.decode() == ",\n".join(links) + "\n"
    assert response["Link"] == ", ".join(links[:4])
    assert response["Cache-Control"] == "private, no-store"
    assert response["Content-Type"].startswith("application/link-format")
    assert len(queries) == 2
    selected = " ".join(query["sql"].split(" FROM ")[0] for query in queries)
    for unwanted in ['"output_str"', '"output_json"', '"password"', '"urls"', '"config"']:
        assert unwanted not in selected
