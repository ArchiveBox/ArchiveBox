"""Replay recorded HTML dependencies through the actual saved-response index."""

import json
import gzip
import re
import base64
import hashlib
import shutil
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from django.test import RequestFactory
from playwright.sync_api import expect, sync_playwright

from archivebox.misc.serve_static import serve_static_with_byterange_support

FIXTURE = Path(__file__).parent / "fixtures/crontab-resources"
NEWLINE_METADATA = gzip.decompress((Path(__file__).parent / "fixtures/saved-html-newlines/metadata.html.gz").read_bytes())
LAZY_FIXTURE = Path(__file__).parent / "fixtures/bablosoft-lazy-image"


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
@pytest.mark.parametrize("card", [False, True])
def test_recorded_crontab_styles_and_script_render_on_snapshot_origin(snapshot, live_server, browser_runtime, card, tmp_path, metadata):
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
        output.write_bytes((FIXTURE / "page.html").read_bytes().replace(b"<head>", b"<head>" + metadata, 1))
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
