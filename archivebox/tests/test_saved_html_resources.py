"""Replay recorded HTML dependencies through the actual saved-response index."""

import json
import gzip
import re
import base64
import hashlib
import shutil
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from django.test import RequestFactory
from playwright.sync_api import expect, sync_playwright

from archivebox.misc.serve_static import serve_static_with_byterange_support

FIXTURE = Path(__file__).parent / "fixtures/crontab-resources"
NEWLINE_METADATA = gzip.decompress((Path(__file__).parent / "fixtures/saved-html-newlines/metadata.html.gz").read_bytes())
LAZY_FIXTURE = Path(__file__).parent / "fixtures/bablosoft-lazy-image"


class ResourceTags(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "link"):
            self.tags.append((tag, dict(attrs)))


@pytest.mark.parametrize("rel", ["preload", "modulepreload"])
def test_passive_thumbnail_omits_both_script_preload_forms(tmp_path, rel):
    source = (Path(__file__).parent / "fixtures/notion-script-resources.html").read_text().replace('rel="preload"', f'rel="{rel}"')
    output = tmp_path / "page.html"
    output.write_text(source)
    request = RequestFactory().get("/page.html?preview=thumbnail")
    request.archivebox_snapshot_url = "https://notion.notion.site/"
    response = serve_static_with_byterange_support(request, "page.html", document_root=tmp_path)
    links = [attrs for tag, attrs in ResourceTags(response.content.decode()).tags if tag == "link" and attrs.get("rel") == rel]
    assert len(links) == 2
    assert all("href" not in attrs for attrs in links)
    assert output.read_text() == source


@pytest.mark.parametrize("metadata", [b"", NEWLINE_METADATA], ids=["lf", "mixed-newlines"])
@pytest.mark.parametrize(
    "fixture",
    [FIXTURE / "page.html", Path(__file__).parent / "fixtures/notion-script-resources.html"],
    ids=["crontab", "notion"],
)
def test_passive_thumbnail_omits_script_fetches_without_changing_raw_or_full_replay(tmp_path, metadata, fixture):
    install_responses(tmp_path)
    path = "dom/output.html"
    output = tmp_path / path
    output.parent.mkdir()
    original = fixture.read_bytes().replace(b"<head>", b"<head>" + metadata, 1)
    output.write_bytes(original)
    digest = hashlib.sha256(original).hexdigest()
    (tmp_path / "hashes").mkdir()
    (tmp_path / "hashes/hashes.json").write_text(json.dumps({"files": [{"path": path, "hash": digest}]}))

    def get(query="", **headers):
        request = RequestFactory().get("/" + path + query, **headers)
        request.archivebox_snapshot_url = "https://crontab.guru/"
        response = serve_static_with_byterange_support(request, path, document_root=tmp_path, is_archive_replay=True)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        return response, body

    raw, body = get("?raw=1")
    assert body == original
    assert raw["ETag"] == f'"{digest}"'
    preview, thumbnail = get(
        "?preview=thumbnail",
        HTTP_IF_NONE_MATCH=raw["ETag"],
        HTTP_IF_MODIFIED_SINCE="Sat, 01 Jan 2050 00:00:00 GMT",
    )
    assert preview.status_code == 200
    assert not preview.has_header("ETag")
    assert "immutable" not in preview["Cache-Control"]
    assert preview.get("Content-Security-Policy") == raw.get("Content-Security-Policy")
    assert metadata in thumbnail
    tags = ResourceTags(thumbnail.decode()).tags
    assert any(tag == "script" for tag, _ in tags)
    assert not any(attrs.get("src") for tag, attrs in tags if tag == "script")
    assert not any(attrs.get("href") for tag, attrs in tags if tag == "link" and attrs.get("as") == "script")
    assert any(attrs.get("href") for tag, attrs in tags if tag == "link" and attrs.get("rel") == "stylesheet")
    _, full = get()
    assert len([attrs for tag, attrs in ResourceTags(full.decode()).tags if tag == "script" and attrs.get("src")]) == len(
        [attrs for tag, attrs in ResourceTags(original.decode()).tags if tag == "script" and attrs.get("src")],
    )
    assert get("?preview=thumbnail&raw=1")[1] == original
    ranged_preview, body = get("?preview=thumbnail", HTTP_RANGE="bytes=0-255")
    assert ranged_preview.status_code == 200
    assert body == thumbnail
    ranged, body = get("?preview=thumbnail&raw=1", HTTP_RANGE="bytes=0-255")
    assert ranged.status_code == 206
    assert body == original[:256]
    assert output.read_bytes() == original


@pytest.mark.parametrize("extra_bytes", [0, 1])
def test_passive_thumbnail_enforces_existing_html_size_limit(tmp_path, extra_bytes):
    import sys

    limit = 10 * 1024 * 1024
    output = tmp_path / "page.html"
    source = (FIXTURE / "page.html").read_bytes()
    with output.open("wb") as stream:
        stream.write(source)
        stream.truncate(limit + extra_bytes)
    request = RequestFactory().get("/page.html?preview=thumbnail")
    request.archivebox_snapshot_url = "https://crontab.guru/"
    observed_opens = []
    phase = "thumbnail"

    # Observe real payload opens without replacing any filesystem operations.
    def observe_open(event, args):
        if phase and event == "open" and args[0] == str(output):
            observed_opens.append(phase)

    sys.addaudithook(observe_open)
    try:
        response = serve_static_with_byterange_support(request, "page.html", document_root=tmp_path)
        phase = "head"
        head = serve_static_with_byterange_support(
            RequestFactory().head("/page.html?preview=thumbnail"),
            "page.html",
            document_root=tmp_path,
        )
        assert head.status_code == response.status_code
        assert not head.has_header("ETag")
        assert not head.has_header("Content-Length")
        assert not head.has_header("Accept-Ranges")
        if not extra_bytes:
            assert head.streaming
            assert list(head.streaming_content) == []
            assert head["Cache-Control"] == response["Cache-Control"]
        phase = "full"
        full_request = RequestFactory().get("/page.html")
        full_request.archivebox_snapshot_url = "https://crontab.guru/"
        full = serve_static_with_byterange_support(full_request, "page.html", document_root=tmp_path)
        assert full.status_code == 200
        assert b"".join(full.streaming_content) == output.read_bytes()
        full.close()
    finally:
        phase = ""
    assert "full" in observed_opens
    assert "head" not in observed_opens
    assert ("thumbnail" in observed_opens) == (not extra_bytes)
    assert response.status_code == (413 if extra_bytes else 200)
    assert not response.streaming
    assert not response.has_header("ETag")
    if extra_bytes:
        assert response["Cache-Control"] == "no-store"
        assert b"Open the full capture" in response.content
        assert len(response.content) < 200
    else:
        assert not any(attrs.get("src") for tag, attrs in ResourceTags(response.content.decode()).tags if tag == "script")
    # Raw byte ranges still work, including beyond the thumbnail limit.
    raw = serve_static_with_byterange_support(
        RequestFactory().get("/page.html?raw=1", HTTP_RANGE="bytes=0-255"),
        "page.html",
        document_root=tmp_path,
    )
    assert raw.status_code == 206
    assert b"".join(raw.streaming_content) == source[:256]


@pytest.mark.parametrize("attribute", ["data-echo", "data-src", "data-lazy-src"])
@pytest.mark.parametrize("source_kind", ["placeholder", "missing", "empty"])
def test_saved_lazy_image_uses_captured_body_without_script(tmp_path, attribute, source_kind):
    from archivebox.misc.serve_static import _rewrite_html_image_sources_for_request
    from html.parser import HTMLParser

    source = (LAZY_FIXTURE / "image.html").read_text().replace("data-echo", attribute)
    if source_kind != "placeholder":
        import re

        source = re.sub(r' src="[^"]*"', ' src=""' if source_kind == "empty" else "", source)
    responses = tmp_path / "responses"
    responses.mkdir()
    shutil.copyfile(LAZY_FIXTURE / "work-1.png", responses / "work-1.png")
    (responses / "index.jsonl").write_text(
        json.dumps({"method": "GET", "status": 200, "url": "https://bablosoft.com/landing2/work-1.png", "path": "work-1.png"}) + "\n",
    )
    request = RequestFactory().get("/wget/bablosoft.com/shop/BrowserAutomationStudio.html")
    request.archivebox_snapshot_url = "https://bablosoft.com/shop/BrowserAutomationStudio"
    body, _ = _rewrite_html_image_sources_for_request(request, source, tmp_path, "wget/bablosoft.com/shop/BrowserAutomationStudio.html")
    images = []

    class Images(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "img":
                images.append(dict(attrs))

    Images().feed(body)
    assert images[0]["src"] == "../../../responses/work-1.png"
    assert images[0][attribute] == images[0]["src"]
    assert images[0]["alt"] == "A problem"
    assert images[0]["style"] == "width:230px;height:230px"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("card", [False, True])
def test_captured_lazy_image_renders_without_javascript(snapshot, live_server, browser_runtime, card, tmp_path):
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Machine
    from django.utils import timezone

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.url = "https://bablosoft.com/shop/BrowserAutomationStudio"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["url", "permissions"])
    root = snapshot.output_dir
    (root / "responses").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LAZY_FIXTURE / "work-1.png", root / "responses/work-1.png")
    shutil.copyfile(LAZY_FIXTURE / "pic.jpg", root / "responses/pic.jpg")
    (root / "responses/index.jsonl").write_text(
        "\n".join(
            json.dumps({"method": "GET", "status": 200, "url": f"https://bablosoft.com/landing2/{name}", "path": name})
            for name in ("work-1.png", "pic.jpg")
        )
        + "\n",
    )
    path = "wget/page.html"
    output = root / path
    output.parent.mkdir(exist_ok=True)
    source = (LAZY_FIXTURE / "background.html").read_bytes() + (LAZY_FIXTURE / "image.html").read_bytes() + b"</section>"
    output.write_bytes(source)
    result = ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        start_ts=timezone.now(),
        output_str=path,
    )
    assert result.update_output_metadata_from_filesystem(full_scan=True)
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    origin = f"http://{host}:{port}"
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], f"--host-resolver-rules=MAP {host} 127.0.0.1"],
        )
        try:
            page = browser.new_page(java_script_enabled=False)
            response = page.goto(origin + (f"/_card/{result.id}" if card else "/" + path), wait_until="load")
            assert response.status == 200
            content = page.frame_locator("iframe") if card else page
            picture = content.locator('img[alt="A problem"]')
            expect(picture).to_be_visible()
            assert picture.evaluate("i => i.naturalWidth") == 230
            assert picture.evaluate("i => i.naturalHeight") == 230
            expect(content.locator("#header")).to_have_css("background-image", f'url("{origin}/responses/pic.jpg")')
            assert page.request.get(origin + "/responses/pic.jpg?raw=1").body() == (LAZY_FIXTURE / "pic.jpg").read_bytes()
            assert page.request.get(origin + "/" + path + "?raw=1").body() == source
            assert output.read_bytes() == source
            page.screenshot(path=str(tmp_path / ("lazy-card.png" if card else "lazy-full.png")))
            print(f"LAZY_IMAGE_SCREENSHOT={tmp_path}")
        finally:
            browser.close()


def install_responses(root):
    responses = root / "responses"
    (responses / "all").mkdir(parents=True)
    for name in (
        "page.html",
        "styles.css",
        "index.js",
        "JetBrainsMono-Regular.woff2",
        "JetBrainsMono-Bold.woff2",
        "JetBrainsMono-Italic.woff2",
    ):
        shutil.copyfile(FIXTURE / name, responses / "all" / name)
    shutil.copyfile(FIXTURE / "index.jsonl", responses / "index.jsonl")
    return responses


@pytest.mark.parametrize("metadata", [b"", NEWLINE_METADATA], ids=["lf", "mixed-newlines"])
@pytest.mark.parametrize("path", ["dom/output.html", "responses/all/page.html"])
def test_saved_html_stylesheets_and_scripts_resolve_locally_and_raw_stays_exact(tmp_path, path, metadata):
    install_responses(tmp_path)
    output = tmp_path / path
    output.parent.mkdir(exist_ok=True)
    original = (FIXTURE / "page.html").read_bytes().replace(b"<head>", b"<head>" + metadata, 1)
    output.write_bytes(original)
    request = RequestFactory().get("/" + path)
    # A responses document must use its own recorded URL, not the crawl URL.
    request.archivebox_snapshot_url = "https://crontab.guru/" if path.startswith("dom/") else "https://archivebox.io/tests/"
    response = serve_static_with_byterange_support(request, path, document_root=tmp_path)
    body = b"".join(response.streaming_content) if response.streaming else response.content
    prefix = "../responses/all/" if path.startswith("dom/") else ""
    assert f"href='{prefix}styles.css'".encode() in body
    assert f'src="{prefix}index.js"'.encode() in body
    assert metadata in body
    assert re.findall(rb"<script\b[^>]*>(.*?)</script\s*>", body, re.I | re.S) == re.findall(
        rb"<script\b[^>]*>(.*?)</script\s*>",
        original,
        re.I | re.S,
    )
    assert b"archivebox-static-html-preview-style" not in body
    raw = serve_static_with_byterange_support(RequestFactory().get("/" + path + "?raw=1"), path, document_root=tmp_path)
    assert b"".join(raw.streaming_content) == original
    assert output.read_bytes() == original


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("metadata", [b"", NEWLINE_METADATA], ids=["lf", "mixed-newlines"])
@pytest.mark.parametrize("card,attribute_gap", [(False, " "), (True, " "), (True, "")], ids=["full", "card", "adjacent-attributes-card"])
def test_recorded_crontab_styles_and_script_render_on_snapshot_origin(
    snapshot,
    live_server,
    browser_runtime,
    card,
    tmp_path,
    metadata,
    attribute_gap,
):
    from archivebox.core.routes_util import get_snapshot_host
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.url = "https://crontab.guru/" if card else "https://archivebox.io/tests/"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["url", "permissions"])
    install_responses(snapshot.output_dir)
    captured = snapshot.output_dir / "responses/all/page.html"
    css_integrity = "sha384-" + base64.b64encode(hashlib.sha384((FIXTURE / "styles.css").read_bytes()).digest()).decode()
    script_integrity = "sha384-" + base64.b64encode(hashlib.sha384((FIXTURE / "index.js").read_bytes()).digest()).decode()
    captured.write_text(
        captured.read_text()
        .replace("<link href='./css/styles.css?cb=1'", f"<link integrity='{css_integrity}' href='./css/styles.css?cb=1'")
        .replace('<script src="/index.js">', f'<script integrity="{script_integrity}" src="/index.js">'),
    )
    captured.write_bytes(captured.read_bytes().replace(b"<head>", b"<head>" + metadata, 1))
    path = "/responses/all/page.html#@daily"
    if card:
        from archivebox.core.models import ArchiveResult
        from django.utils import timezone

        output = snapshot.output_dir / "dom/output.html"
        output.parent.mkdir()
        output.write_bytes(
            (FIXTURE / "page.html")
            .read_bytes()
            .replace(b"<head>", b"<head>" + metadata, 1)
            .replace(b'<script src="/index.js">', f'<script defer=""{attribute_gap}src="/index.js">'.encode())
            .replace(
                b"</body>",
                b'<svg width="40" height="40"><script src="/index.js"/>'
                b'<rect id="thumbnail-svg-marker" width="40" height="40" fill="green"/></svg></body>',
            ),
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="dom",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
            start_ts=timezone.now(),
            output_str="dom/output.html",
        )
        assert result.update_output_metadata_from_filesystem(full_scan=True)
        path = f"/_card/{result.id}"
    host = get_snapshot_host(str(snapshot.id)).split(":")[0]
    origin = f"http://{host}:{port}"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], f"--host-resolver-rules=MAP {host} 127.0.0.1"],
        )
        try:
            page = browser.new_page()
            responses = []
            stylesheets = []
            requests = []
            page.on("request", lambda request: requests.append((request.resource_type, request.url)))

            def observed(response):
                responses.append((response.url, response.status))
                if response.url == origin + "/responses/all/styles.css":
                    stylesheets.append(response)

            page.on("response", observed)
            page.goto(origin + path, wait_until="load")
            if card:
                assert page.locator("iframe").get_attribute("sandbox") == "allow-same-origin"
                content = page.frame_locator("iframe")
                expect(content.locator("html")).to_have_css("background-color", "rgb(23, 23, 23)")
                expect(content.locator("body")).to_contain_text("loading...")
                assert (origin + "/responses/all/styles.css", 200) in responses
                assert not [url for kind, url in requests if kind == "script"]
                # A self-closing script in foreign content must not consume
                # the following SVG markup when its unusable src is omitted.
                expect(content.locator("svg > #thumbnail-svg-marker")).to_be_visible()
                assert page.request.get(origin + "/dom/output.html?raw=1").body() == output.read_bytes()
                head = page.request.head(page.locator("iframe").get_attribute("src"))
                assert head.status == 200
                assert "content-length" not in head.headers
                assert "accept-ranges" not in head.headers
                assert "etag" not in head.headers
                page.screenshot(path=str(tmp_path / "card.png"))
                print(f"REPLAY_SCREENSHOT={tmp_path / 'card.png'}")
                return
            expect(page.locator("html")).to_have_css("background-color", "rgb(23, 23, 23)")
            expect(page.locator(".loading")).to_have_count(0)
            assert (origin + "/responses/all/styles.css", 200) in responses
            assert (origin + "/responses/all/index.js", 200) in responses
            assert page.locator("body").inner_text().find("At 00:00.") >= 0
            assert page.locator("script[integrity]").get_attribute("integrity") == script_integrity
            actual_css = stylesheets[-1].body()
            replay_integrity = "sha384-" + base64.b64encode(hashlib.sha384(actual_css).digest()).decode()
            assert page.locator('link[rel="stylesheet"]').get_attribute("integrity") == replay_integrity
            assert replay_integrity != css_integrity
            page.evaluate("document.fonts.ready")
            assert page.evaluate("document.fonts.check('16px \"JetBrains Mono\"')")
            head = page.evaluate(
                "async url => {const r = await fetch(url, {method:'HEAD'}); return {status:r.status, length:r.headers.get('Content-Length')};}",
                origin + "/responses/all/styles.css",
            )
            assert head == {"status": 200, "length": None}
            page.screenshot(path=str(tmp_path / "full.png"))
            print(f"REPLAY_SCREENSHOT={tmp_path / 'full.png'}")
        finally:
            browser.close()


def test_resource_mapping_respects_base_and_ignores_markup_in_data(tmp_path):
    from archivebox.misc.serve_static import _rewrite_html_image_sources_for_request

    install_responses(tmp_path)
    source = """<!doctype html><html><head><base href="https://crontab.guru/">
<link rel="stylesheet" href="css/styles.css?cb=1">
<script>const example = '<script src="/index.js">';</script>
<!-- <script src="/index.js"></script> -->
<script src="/index.js"></script></head></html>"""
    request = RequestFactory().get("/web/snapshot/dom/output.html")
    request.archivebox_snapshot_url = "https://archivebox.io/tests/"
    body, count = _rewrite_html_image_sources_for_request(request, source, tmp_path, "dom/output.html")
    assert count == 2
    assert 'href="http://testserver/web/snapshot/responses/all/styles.css"' in body
    assert 'src="http://testserver/web/snapshot/responses/all/index.js"' in body
    assert "const example = '<script src=\"/index.js\">';" in body
    assert '<!-- <script src="/index.js"></script> -->' in body


@pytest.mark.parametrize("bad_path", ["../../secret.js", "./all/escape.js"])
def test_resource_mapping_never_uses_escape_or_failed_response(tmp_path, bad_path):
    from archivebox.misc.serve_static import _rewrite_html_image_sources_for_request

    root = tmp_path / "snapshot"
    install_responses(root)
    secret = tmp_path / "secret.js"
    secret.write_text("private")
    (root / "responses/all/escape.js").symlink_to(secret)
    records = [
        {"method": "GET", "status": 200, "url": "https://crontab.guru/index.js", "path": bad_path},
        {"method": "GET", "status": 403, "url": "https://crontab.guru/css/styles.css?cb=1", "path": "./all/styles.css"},
    ]
    (root / "responses/index.jsonl").write_text("\n".join(json.dumps(x) for x in records))
    request = RequestFactory().get("/dom/output.html")
    request.archivebox_snapshot_url = "https://crontab.guru/"
    source = '<link rel="stylesheet" href="/css/styles.css?cb=1"><script src="/index.js"></script>'
    assert _rewrite_html_image_sources_for_request(request, source, root, "dom/output.html") == (source, 0)


def test_enriched_stylesheet_integrity_and_raw_css(tmp_path):
    from archivebox.misc.serve_static import _rewrite_html_image_sources_for_request, _rewrite_css_sources_to_responses

    install_responses(tmp_path)
    request = RequestFactory().get("/dom/output.html")
    request.archivebox_snapshot_url = "https://crontab.guru/"
    source = '<link integrity="sha256-captured" rel="stylesheet" href="/css/styles.css?cb=1"><script integrity="sha256-script" src="/index.js"></script>'
    body, count = _rewrite_html_image_sources_for_request(request, source, tmp_path, "dom/output.html")
    assert count == 2
    css_response = serve_static_with_byterange_support(
        RequestFactory().get("/responses/all/styles.css"),
        "responses/all/styles.css",
        document_root=tmp_path,
    )
    digest = base64.b64encode(hashlib.sha384(css_response.content).digest()).decode("ascii")
    assert f'integrity="sha384-{digest}"' in body
    assert 'integrity="sha256-script"' in body
    stylesheet = tmp_path / "responses/all/styles.css"
    original_css = stylesheet.read_bytes()
    stylesheet.write_text("html { color: red; }")
    unchanged, _ = _rewrite_html_image_sources_for_request(request, source, tmp_path, "dom/output.html")
    assert 'integrity="sha256-captured"' in unchanged
    stylesheet.write_bytes(original_css)
    css = (FIXTURE / "styles.css").read_text()
    rewritten, count = _rewrite_css_sources_to_responses(css, tmp_path, "responses/all/styles.css")
    assert count == 3
    assert 'url("JetBrainsMono-Regular.woff2")' in rewritten
    assert "url(/fonts/inter/InterVariable.woff2)" in rewritten  # absent captured resources are not fabricated
    source = '/* url(/fonts/jetbrains-mono/JetBrainsMono-Regular.woff2) */\na::after{content:"url(/fonts/jetbrains-mono/JetBrainsMono-Regular.woff2)"}'
    assert _rewrite_css_sources_to_responses(source, tmp_path, "responses/all/styles.css") == (source, 0)
    raw = serve_static_with_byterange_support(
        RequestFactory().get("/responses/all/styles.css?raw=1"),
        "responses/all/styles.css",
        document_root=tmp_path,
    )
    assert b"".join(raw.streaming_content) == (FIXTURE / "styles.css").read_bytes()


def test_response_css_head_and_range_preserve_payload_boundary(tmp_path):
    import sys

    install_responses(tmp_path)
    output = tmp_path / "responses/all/styles.css"
    opened = []
    observing = False

    def observe(event, args):
        if observing and event == "open" and str(args[0]) == str(output):
            opened.append(args[0])

    sys.addaudithook(observe)
    observing = True
    try:
        response = serve_static_with_byterange_support(
            RequestFactory().head("/responses/all/styles.css"),
            "responses/all/styles.css",
            document_root=tmp_path,
        )
    finally:
        observing = False
    assert response.status_code == 200
    assert not opened
    assert not response.streaming
    assert response.content == b""
    assert "Content-Length" not in response
    response = serve_static_with_byterange_support(
        RequestFactory().get("/responses/all/styles.css", HTTP_RANGE="bytes=0-3"),
        "responses/all/styles.css",
        document_root=tmp_path,
    )
    assert response.status_code == 206
    assert response["Content-Range"] == f"bytes 0-3/{output.stat().st_size}"
    assert b"".join(response.streaming_content) == output.read_bytes()[:4]


@pytest.mark.parametrize("validator", ["HTTP_IF_MODIFIED_SINCE", "HTTP_IF_NONE_MATCH"])
def test_response_css_revalidates_new_captured_assets_without_source_change(tmp_path, validator):
    from django.utils.http import http_date

    install_responses(tmp_path)
    output = tmp_path / "responses/all/styles.css"
    original = output.read_bytes()
    font = tmp_path / "responses/all/JetBrainsMono-Regular.woff2"
    font_bytes = font.read_bytes()
    for candidate in (tmp_path / "responses/all").glob("*.woff2"):
        candidate.unlink()
    digest = hashlib.sha256(original).hexdigest()
    (tmp_path / "hashes").mkdir()
    (tmp_path / "hashes/hashes.json").write_text(json.dumps({"files": [{"path": "responses/all/styles.css", "hash": digest}]}))
    first = serve_static_with_byterange_support(
        RequestFactory().get("/responses/all/styles.css"),
        "responses/all/styles.css",
        document_root=tmp_path,
    )
    first_body = b"".join(first.streaming_content) if first.streaming else first.content
    assert first_body == original
    modified = output.stat().st_mtime_ns
    font.write_bytes(font_bytes)
    header = http_date(output.stat().st_mtime) if validator == "HTTP_IF_MODIFIED_SINCE" else f'"{digest}"'
    response = serve_static_with_byterange_support(
        RequestFactory().get("/responses/all/styles.css", **{validator: header}),
        "responses/all/styles.css",
        document_root=tmp_path,
    )
    assert response.status_code == 200
    assert b'url("JetBrainsMono-Regular.woff2")' in response.content
    assert output.stat().st_mtime_ns == modified
    raw = serve_static_with_byterange_support(
        RequestFactory().get("/responses/all/styles.css?raw=1", **{validator: header}),
        "responses/all/styles.css",
        document_root=tmp_path,
    )
    assert raw.status_code == 304


@pytest.mark.parametrize("escaped", [False, True])
@pytest.mark.parametrize("path", ["dom/output.html", "readability/content.html"])
def test_dom_aliases_use_original_source_before_display_transform(tmp_path, escaped, path):
    import html

    responses = tmp_path / "responses"
    responses.mkdir()
    shutil.copyfile(LAZY_FIXTURE / "work-1.png", responses / "image.png")
    (responses / "index.jsonl").write_text(
        json.dumps({"method": "GET", "status": 200, "url": "https://proxy.example/image", "path": "image.png"}) + "\n",
    )
    source = (
        '<!doctype html><html><body><img src="https://original.example/image">'
        '<img src="https://proxy.example/image" data-canonical-src="https://original.example/image">'
        "</body></html>"
    )
    original = html.escape(source) if escaped else source
    dom = tmp_path / "dom/output.html"
    dom.parent.mkdir()
    dom.write_text(original)
    output = tmp_path / path
    output.parent.mkdir(exist_ok=True)
    output.write_text(original)
    response = serve_static_with_byterange_support(RequestFactory().get("/" + path), path, document_root=tmp_path)
    body = response.content.decode()
    expected = source.replace('src="https://proxy.example/image"', 'src="../responses/image.png"')
    if not escaped:
        expected = expected.replace('src="https://original.example/image"', 'src="../responses/image.png"', 1)
    # Escaped markup is displayable HTML, but cannot invent aliases absent from
    # the original DOM. Raw serving and both saved files remain byte-identical.
    assert body == expected
    raw = serve_static_with_byterange_support(RequestFactory().get("/" + path + "?raw=1"), path, document_root=tmp_path)
    assert b"".join(raw.streaming_content) == original.encode()
    assert dom.read_bytes() == output.read_bytes() == original.encode()


def test_concurrent_html_resource_parsers_keep_document_state_isolated(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    inputs = []
    for number in range(16):
        root = tmp_path / str(number)
        responses = root / "responses"
        responses.mkdir(parents=True)
        shutil.copyfile(LAZY_FIXTURE / "work-1.png", responses / f"image-{number}.png")
        url = f"https://example.com/{number}/image.png"
        (responses / "index.jsonl").write_text(
            json.dumps({"method": "GET", "status": 200, "url": url, "path": f"image-{number}.png"}) + "\n",
        )
        source = (
            "<!doctype html><html><body>"
            + ("🌍\r\n\r\u2028é\n" * (number + 1))
            + f'''<!-- <img src="{url}"> --><script>const data = '<img src="{url}">';</script>'''
            + f'<img data-src="{url}" src="data:image/png;base64,AA==" srcset="{url} 2x"/>'
            + "</body></html>"
        )
        output = root / "dom/output.html"
        output.parent.mkdir()
        output.write_text(source)
        inputs.append((root, source, url, number))
    barrier = Barrier(len(inputs))

    def read(item):
        root, source, url, number = item
        barrier.wait(timeout=10)
        response = serve_static_with_byterange_support(RequestFactory().get("/dom/output.html"), "dom/output.html", document_root=root)
        expected = source.replace(f'data-src="{url}"', f'data-src="../responses/image-{number}.png"').replace(
            'src="data:image/png;base64,AA=="',
            f'src="../responses/image-{number}.png"',
        )
        assert response.content.decode() == expected
        assert (root / "dom/output.html").read_bytes() == source.encode()

    with ThreadPoolExecutor(max_workers=len(inputs)) as executor:
        list(executor.map(read, inputs))
