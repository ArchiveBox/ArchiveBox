"""Crawler hints cover generated replay views without disabling downloads."""

import io
import zipfile
from urllib.parse import urlsplit

import pytest
import requests

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import build_snapshot_detail_url, get_snapshot_host
from archivebox.machine.models import Machine


@pytest.mark.django_db(transaction=True)
def test_real_replay_crawler_hints_preserve_raw_outputs_and_zip_downloads(snapshot, live_server):
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": "http://archivebox.localhost",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    output = snapshot.output_dir / "wget"
    (output / "nested").mkdir(parents=True)
    documents = {
        "index.html": b"<!doctype html><title>Captured page</title><p>Archived bytes</p>",
        "image.svg": b'<svg xmlns="http://www.w3.org/2000/svg"></svg>',
        "nested/note.txt": b"Archived note\n",
    }
    for name, content in documents.items():
        (output / name).write_bytes(content)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        status="succeeded",
        output_str="index.html",
        output_files={name: {"size": len(content)} for name, content in documents.items()},
    )
    snapshot_host = get_snapshot_host(str(snapshot.id))
    with requests.Session() as client:
        client.trust_env = False
        for host in ("admin.archivebox.localhost", "web.archivebox.localhost", snapshot_host):
            robots = client.get(f"{live_server.url}/robots.txt", headers={"Host": host}, timeout=10)
            assert robots.status_code == 200
            assert robots.text.startswith("User-agent: *\nDisallow: /\n")
            assert "Allow: /dom/output.html$\n" in robots.text
            assert "Allow: /readability/content.html$\n" in robots.text
            assert "singlefile" not in robots.text

        client.headers["Host"] = snapshot_host
        raw = client.get(f"{live_server.url}/wget/index.html?raw=1", timeout=10)
        assert raw.status_code == 200
        assert "X-Robots-Tag" not in raw.headers
        assert b"Archived bytes" in raw.content

        listing = client.get(f"{live_server.url}/wget/?files=1", timeout=10)
        assert listing.status_code == 200
        assert listing.headers.get("X-Robots-Tag") == "noindex, nofollow"

        for suffix in ("index.html?preview=1", "index.html?preview=thumbnail", "index.html?thumbnail=1", "image.svg?preview=1&raw=1"):
            preview = client.get(f"{live_server.url}/wget/{suffix}", timeout=10)
            assert preview.status_code == 200, preview.text[:500]
            assert preview.headers.get("X-Robots-Tag") == "noindex, nofollow"

        download = client.get(f"{live_server.url}/wget/?files=1&download=zip", timeout=10)
        assert download.status_code == 200
        assert download.headers["Content-Type"] == "application/zip"
        assert download.headers.get("X-Robots-Tag") == "noindex, nofollow"
        with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
            assert {name: archive.read(name) for name in archive.namelist()} == {
                f"wget/{name}": content for name, content in documents.items()
            }
        refused = client.get(
            f"{live_server.url}/wget/?files=1&download=zip",
            headers={"User-Agent": "meta-externalagent/1.1"},
            timeout=10,
        )
        assert refused.status_code == 403
        assert not refused.content.startswith(b"PK")

        detail_url = urlsplit(build_snapshot_detail_url(snapshot.archive_path_from_db))
        detail = client.get(f"{live_server.url}{detail_url.path}", headers={"Host": detail_url.netloc}, timeout=10)
        assert detail.status_code == 200
        assert "X-Robots-Tag" not in detail.headers


@pytest.mark.parametrize(
    "user_agent",
    [
        "meta-externalagent/1.1",
        "meta-webindexer/1.1",
        "Mediapartners-Google",
        "APIs-Google",
        "Google-Safety",
        "meta-externalfetcher/1.1",
        "facebookexternalhit/1.1",
        "GPTBot/1.3",
        "OAI-SearchBot/1.3",
        "OAI-AdsBot/1.0",
        "ChatGPT-User/1.0",
        "ClaudeBot/1.0",
        "Claude-User/1.0",
        "Claude-Agent/1.0",
        "KimiBot/1.0",
        "Kimi-SearchBot/1.0",
        "Kimi-User/1.0",
        "Googlebot/2.1",
        "GoogleOther",
        "Google-Agent",
        "Google-GeminiNotebook",
        "FeedFetcher-Google",
        "bingbot/2.0",
        "BingPreview/1.0",
        "MicrosoftPreview/2.0",
        "Baiduspider",
        "YisouSpider",
        "Bytespider",
        "Amazonbot/0.1",
        "Amzn-User/1.0",
        "Perplexity-User/1.0",
        "MistralAI-Training/1.0",
        "Applebot/0.1",
        "CCBot/2.0",
        "DuckDuckBot/1.1",
        "YandexBot/3.0",
        "PetalBot",
        "Sogou web spider",
    ],
)
@pytest.mark.django_db
def test_crawlers_are_refused_before_database_or_replay_work(client, user_agent):
    import cProfile
    import pstats
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    # Initialize the real handler first; policy/catalog construction is startup work.
    client.get("/health/")
    profile = cProfile.Profile()
    with CaptureQueriesContext(connection) as queries, profile:
        response = client.get("/wget/?files=1&download=zip", HTTP_HOST="snap-123456789abc.archivebox.localhost", HTTP_USER_AGENT=user_agent)
    assert response.status_code == 403
    assert response["Cache-Control"] == "private, no-store"
    assert "User-Agent" in response["Vary"]
    assert len(queries) == 0, [query["sql"] for query in queries]
    calls = {name for (_filename, _line, name) in pstats.Stats(profile).stats}
    assert calls.isdisjoint({"_build_snapshot_replay_response", "_resolve_archive_path", "resolve", "_iter_visible_files"}), calls


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/singlefile/output.html",
        "/archivewebpage/archive.wacz",
        "/screenshot/screenshot.png",
        "/staticfile/movie.mp4",
        "/dom/output.html?preview=1",
        "/dom/output.html?preview=thumbnail",
        "/dom/output.html?files=1",
        "/dom/output.html?download=zip",
        "/dom/output.html?raw=1&raw=0",
        "/prefix/dom/output.html",
        "/snapshot/not-an-id/dom/output.html",
        "/original/example.com/dom/output.html",
        "/dom/../singlefile/output.html",
        "/dom/%2e%2e/singlefile/output.html",
        "/dom%2f..%2fsinglefile%2foutput.html",
        "/dom/output.html?arbitrary=1",
        "/static/typography.css?preview=1",
        "/static/typography.css?download=zip",
        "/static/typography.css?thumbnail=1",
    ],
)
def test_crawler_allowlist_does_not_admit_derived_or_lookalike_paths(client, path):
    response = client.get(path, HTTP_HOST="snap-123456789abc.archivebox.localhost", HTTP_USER_AGENT="Googlebot")
    assert response.status_code == 403


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("plugin,filename", [("readability", "content.html"), ("dom", "output.html")])
def test_crawler_html_is_exact_saved_bytes_without_manifest_or_rewrite_work(snapshot, client, live_server, plugin, filename):
    import cProfile
    import pstats
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": "http://archivebox.localhost", "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay"}
    machine.save(update_fields=["config"])
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    output = snapshot.output_dir / plugin / filename
    output.parent.mkdir(parents=True)
    content = b'<!doctype html><title>Saved HTML</title><a href="https://example.com/">Original</a>&lt;unchanged&gt;'
    output.write_bytes(content)
    host = get_snapshot_host(str(snapshot.id))
    profile = cProfile.Profile()
    with CaptureQueriesContext(connection) as queries, profile:
        response = client.get(f"/{plugin}/{filename}", HTTP_HOST=host, HTTP_USER_AGENT="meta-externalagent/1.1")
        body = b"".join(response.streaming_content) if response.streaming else response.content
        response.close()
    assert response.status_code == 200
    assert body == content
    assert "User-Agent" in response["Vary"]
    assert "X-Robots-Tag" not in response
    assert not any('"core_archiveresult"' in query["sql"] for query in queries), [query["sql"] for query in queries]
    calls = {name for (_filename, _line, name) in pstats.Stats(profile).stats}
    assert calls.isdisjoint(
        {
            "_resolve_archiveresult_relpath",
            "get_plugin_replay_roots",
            "_load_file_inventory",
            "_render_directory_index",
            "_normalize_output_files",
            "render_plugin_full_document",
            "_rewrite_replay_document_for_request",
        },
    ), calls

    versioned = client.get(f"/{plugin}/{filename}?raw=1&_abx_rev=123.456789", HTTP_HOST=host, HTTP_USER_AGENT="Googlebot")
    assert versioned.status_code == 200
    assert b"".join(versioned.streaming_content) == content
    versioned.close()

    with requests.Session() as network:
        network.trust_env = False
        network.headers.update({"Host": host, "User-Agent": "Googlebot"})
        public = network.get(f"{live_server.url}/{plugin}/{filename}", timeout=10)
        assert public.status_code == 200
        assert public.content == content
        head = network.head(f"{live_server.url}/{plugin}/{filename}", timeout=10)
        assert head.status_code == 200
        assert head.content == b""
        assert int(head.headers["Content-Length"]) == len(content)

    for route in (f"/snapshot/{snapshot.id}/{plugin}/{filename}", f"/{snapshot.archive_path_from_db}/{plugin}/{filename}"):
        routed = client.get(route, HTTP_HOST="web.archivebox.localhost", HTTP_USER_AGENT="Googlebot")
        assert routed.status_code in {200, 302}, routed.content
        routed.close()

    output.unlink()
    missing_profile = cProfile.Profile()
    with missing_profile:
        missing = client.get(f"/{plugin}/{filename}", HTTP_HOST=host, HTTP_USER_AGENT="Googlebot")
    assert missing.status_code == 404
    missing_calls = {name for (_filename, _line, name) in pstats.Stats(missing_profile).stats}
    assert "iterdir" not in missing_calls, missing_calls
    output.write_bytes(content)

    snapshot.config = {**snapshot.config, "PERMISSIONS": "private"}
    snapshot.save(update_fields=["config"])
    private = client.get(f"/{plugin}/{filename}", HTTP_HOST=host, HTTP_USER_AGENT="Googlebot")
    assert private.status_code in {302, 403, 404}
    assert content not in private.content


@pytest.mark.django_db
@pytest.mark.parametrize(
    "user_agent",
    ["curl/8.0", "Wget/1.21", "python-requests/2.32", "python-httpx/0.28", "Mozilla/5.0 Chrome/130.0 Safari/537.36"],
)
def test_manual_clients_keep_existing_derived_routes(client, user_agent):
    response = client.get("/missing/?download=zip", HTTP_HOST="snap-123456789abc.archivebox.localhost", HTTP_USER_AGENT=user_agent)
    # Normal replay lookup still runs (missing snapshot); the crawler gate did not refuse it.
    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_crawler_refusal_uses_async_django_handler(async_client):
    import asyncio

    response = asyncio.run(
        async_client.get(
            "/singlefile/?download=zip",
            headers={"user-agent": "Claude-User/1.0"},
        ),
    )
    assert response.status_code == 403
    assert response["X-Robots-Tag"] == "noindex, nofollow"
