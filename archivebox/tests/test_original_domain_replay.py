"""Native original-domain replay using unchanged real Hacker News captures."""

import gzip
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.test import Client

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)
DOMAIN_HOST = "news.ycombinator.com.archivebox.localhost:5797"


@pytest.fixture
def saved_site(crawl):
    from archivebox.core.models import ArchiveResult, Snapshot
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": "http://archivebox.localhost:5797",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])

    fixture = Path(__file__).parent / "fixtures/original-domain-replay"
    snapshots = []
    for record in json.loads((fixture / "captures.json").read_text()):
        body = gzip.decompress((fixture / record["file"]).read_bytes())
        assert hashlib.sha256(body).hexdigest() == record["sha256"]
        snapshot = Snapshot.objects.create(url=record["url"], crawl=crawl, config={"PERMISSIONS": "public"}, output_size=len(body))
        output = snapshot.output_dir / "dom/output.html"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(body)
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="dom",
            hook_name="on_Snapshot__53_dom.js",
            status="succeeded",
            output_str="dom/output.html",
            output_files={"dom/output.html": {"size": len(body), "mimetype": "text/html"}},
            output_size=len(body),
        )
        snapshots.append((snapshot, output, body))
    return snapshots


def test_original_domain_links_select_saved_pages_and_preserve_capture_bytes(client, saved_site):
    response = client.get("/", HTTP_HOST=DOMAIN_HOST)
    assert response.status_code == 200
    assert f'href="http://{DOMAIN_HOST}/newest"'.encode() in response.content
    assert b'href="https://news.ycombinator.com/ask"' in response.content
    assert b"data-archivebox-original-replay" in response.content
    newest = client.get("/newest", HTTP_HOST=DOMAIN_HOST)
    assert newest.status_code == 200
    assert b"New Links" in newest.content
    query_page = client.get("/from?site=gatezh.com", HTTP_HOST=DOMAIN_HOST)
    assert query_page.status_code == 200

    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "a" and (href := dict(attrs).get("href")):
                links.append(urlsplit(href))

    links = []
    Links().feed(query_page.content.decode())
    assert any(link.hostname == "gatezh.com" and link.path == "/posts/macos-secure-enclave-ssh-keys/" for link in links)
    assert any(link.netloc == DOMAIN_HOST and link.path == "/from" and parse_qs(link.query) == {"site": ["gatezh.com"]} for link in links)
    assert client.get("/from?site=not-captured.example", HTTP_HOST=DOMAIN_HOST).status_code == 404
    assert client.get("/newest?different=1", HTTP_HOST=DOMAIN_HOST).status_code == 404
    for snapshot, output, body in saved_site:
        raw = client.get(f"/_archivebox/files/{snapshot.id}/dom/output.html?raw=1", HTTP_HOST=DOMAIN_HOST)
        served = b"".join(raw.streaming_content) if raw.streaming else raw.content
        assert raw.status_code == 200 and served == body
        assert output.read_bytes() == body


def test_private_domain_replay_grant_is_host_scoped_and_revoked_by_logout(admin_client, saved_site):
    for snapshot, _output, _body in saved_site:
        snapshot.config = {**snapshot.config, "PERMISSIONS": "private"}
        snapshot.save(update_fields=["config"])
    assert Client().get("/", HTTP_HOST=DOMAIN_HOST).status_code == 404
    first = saved_site[0][0]
    assert (
        admin_client.get(
            "/admin/core/snapshot/replay-auth/",
            {
                "snapshot": str(first.id),
                "original_domain": "unrelated.example",
                "next": "/",
            },
            HTTP_HOST=ADMIN_TEST_HOST,
        ).status_code
        == 404
    )
    auth = admin_client.get(
        "/admin/core/snapshot/replay-auth/",
        {
            "snapshot": str(first.id),
            "original_domain": "news.ycombinator.com",
            "next": "/newest",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert auth.status_code == 302
    grant = urlsplit(auth["Location"])
    assert grant.hostname == "news.ycombinator.com.archivebox.localhost"
    replay = Client()
    granted = replay.get(grant.path + "?" + grant.query, HTTP_HOST=DOMAIN_HOST)
    assert granted.status_code == 302 and granted["Location"] == "/newest"
    assert all(not cookie["domain"] and cookie["httponly"] for cookie in granted.cookies.values())
    assert replay.get("/newest", HTTP_HOST=DOMAIN_HOST).status_code == 200
    assert replay.get("/", HTTP_HOST="other.example.archivebox.localhost:5797").status_code == 404
    admin_client.logout()
    assert replay.get("/newest", HTTP_HOST=DOMAIN_HOST).status_code == 404


@pytest.mark.parametrize("rewrite_all", [False, True])
def test_original_domain_replay_browser_navigation(saved_site, live_server, browser_runtime, tmp_path, rewrite_all):
    from archivebox.machine.models import Machine
    from playwright.sync_api import sync_playwright

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}", "REWRITE_ARCHIVED_LINKS": rewrite_all}
    machine.save(update_fields=["config"])
    from archivebox.core.routes_util import build_snapshot_url

    origin = f"http://news.ycombinator.com.archivebox.localhost:{port}"
    start = build_snapshot_url(str(saved_site[0][0].id), "dom/output.html") if rewrite_all else origin + "/"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[
                *browser_runtime["chrome_args"],
                "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1",
            ],
        )
        page = browser.new_page()
        response = page.goto(start, wait_until="domcontentloaded")
        assert response.status == 200
        page.get_by_role("link", name="new", exact=True).click()
        page.wait_for_url(origin + "/newest")
        assert "New Links" in page.title()
        page.screenshot(path=str(tmp_path / "original-domain-hn-newest.png"), full_page=True)
        browser.close()
    assert all(output.read_bytes() == body for _snapshot, output, body in saved_site)


def test_snapshot_replay_link_setting_hides_nondiscoverable_targets(client, saved_site):
    from archivebox.core.routes_util import build_snapshot_url
    from archivebox.machine.models import Machine

    snapshot, output, body = saved_site[0]
    replay = urlsplit(build_snapshot_url(str(snapshot.id), "dom/output.html"))
    before = client.get(replay.path, HTTP_HOST=replay.netloc)
    assert before.status_code == 200
    before_body = b"".join(before.streaming_content) if before.streaming else before.content
    assert b"data-archivebox-original-replay" not in before_body
    machine = Machine.current()
    machine.config = {**machine.config, "REWRITE_ARCHIVED_LINKS": True}
    machine.save(update_fields=["config"])
    enabled = client.get(replay.path, HTTP_HOST=replay.netloc)
    assert enabled.status_code == 200
    assert f'href="http://{DOMAIN_HOST}/newest"'.encode() in enabled.content
    assert b'href="https://news.ycombinator.com/ask"' in enabled.content
    for permission in ("private", "unlisted"):
        other = saved_site[1][0]
        other.config = {**other.config, "PERMISSIONS": permission}
        other.save(update_fields=["config"])
        restricted = client.get(replay.path, HTTP_HOST=replay.netloc)
        assert restricted.status_code == 200
        assert f"http://{DOMAIN_HOST}/newest".encode() not in restricted.content
        assert b'href="https://news.ycombinator.com/newest"' in restricted.content
    assert output.read_bytes() == body


def test_navigation_preserves_doctype_without_explicit_head():
    from archivebox.misc.serve_static import rewrite_navigation_links

    body = (Path(__file__).parent / "fixtures/crontab-resources/page.html").read_text()
    body = body.replace("<head>", "").replace("</head>", "")
    rewritten, _ = rewrite_navigation_links(body, "https://crontab.guru/", {}, asset_base="https://archive.example/files/")
    assert rewritten.lstrip().lower().startswith("<!doctype html>")
    assert '<base href="https://archive.example/files/">' in rewritten


def test_navigation_leaves_saved_lazy_background_markup_unchanged():
    from archivebox.misc.serve_static import rewrite_navigation_links

    body = (Path(__file__).parent / "fixtures/bablosoft-lazy-image/background.html").read_text()
    rewritten, _ = rewrite_navigation_links(body, "https://bablosoft.com/", {})
    assert rewritten.endswith(body)


def test_original_domain_resources_preserve_query_and_fragment(client, saved_site):
    import shutil

    snapshot, output, body = saved_site[0]
    asset = output.parent / "captured-image.png"
    shutil.copyfile(Path(__file__).parent / "fixtures/redirected-image/image.png", asset)
    source = body.replace(b"</body>", b'<img src="captured-image.png?revision=2#preview"></body>')
    output.write_bytes(source)
    response = client.get("/", HTTP_HOST=DOMAIN_HOST)
    assert response.status_code == 200
    target = f"/_archivebox/files/{snapshot.id}/dom/captured-image.png?revision=2#preview"
    assert target.encode() in response.content
    assert output.read_bytes() == source


def test_public_navigation_map_only_queries_page_destinations(client, saved_site):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from archivebox.core.models import Snapshot
    from archivebox.core.routes_util import build_snapshot_url
    from archivebox.machine.models import Machine

    snapshot = saved_site[0][0]
    for number in range(25):
        Snapshot.objects.create(
            url=f"https://unrelated.example/{number}", crawl=snapshot.crawl, config={"PERMISSIONS": "public"}, output_size=100
        )
    machine = Machine.current()
    machine.config = {**machine.config, "REWRITE_ARCHIVED_LINKS": True}
    machine.save(update_fields=["config"])
    url = urlsplit(build_snapshot_url(str(snapshot.id), "dom/output.html"))
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url.path, HTTP_HOST=url.netloc)
    assert response.status_code == 200
    assert f'href="http://{DOMAIN_HOST}/newest"'.encode() in response.content
    assert b"unrelated.example" not in response.content
    map_queries = [entry["sql"] for entry in queries if 'SELECT DISTINCT "core_snapshot"."url"' in entry["sql"]]
    assert len(map_queries) == 1
    assert '"core_snapshot"."url" IN (' in map_queries[0]


def test_query_replay_without_html_never_uses_another_queries_response(client, saved_site):
    from archivebox.core.models import Snapshot

    exact, output, body = saved_site[2]
    output.unlink()
    other = Snapshot.objects.create(
        url="https://news.ycombinator.com/from?site=other.example",
        crawl=exact.crawl,
        permissions="public",
        output_size=len(body),
    )
    response_file = other.output_dir / "responses/news.ycombinator.com/from"
    response_file.parent.mkdir(parents=True)
    response_file.write_bytes(body)
    response = client.get("/from?site=gatezh.com", HTTP_HOST=DOMAIN_HOST)
    assert response.status_code == 404


def test_original_asset_query_cannot_enable_raw_replay(client, saved_site):
    snapshot, output, original = saved_site[0]
    stylesheet = output.parent / "style.css"
    stylesheet.write_text("body { color: red; }")
    output.write_bytes(original + b'<link rel="stylesheet" href="style.css?raw=1&amp;v=2#theme">')
    response = client.get("/", HTTP_HOST=DOMAIN_HOST)
    assert response.status_code == 200
    assert f"/_archivebox/files/{snapshot.pk}/dom/style.css?v=2#theme".encode() in response.content
    assert b"style.css?raw=" not in response.content
    assert b"style.css?raw=1" in output.read_bytes()
