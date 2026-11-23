from pathlib import Path

import pytest
from django.test import RequestFactory

from archivebox.misc.serve_static import serve_static_with_byterange_support


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
@pytest.mark.parametrize("byte_range", [None, "bytes=0-5"])
@pytest.mark.parametrize("target_kind", ["captured", "outside", "persona"])
def test_original_resource_alias_preserves_snapshot_containment(snapshot, tmp_path, mode, byte_range, target_kind):
    import os
    from urllib.parse import urlsplit

    from django.test import Client

    from archivebox.core.routes_util import build_snapshot_url
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": "http://archivebox.localhost:5797", "SERVER_SECURITY_MODE": mode}
    machine.save(update_fields=["config"])
    snapshot.url = "https://example.com/article"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["url", "permissions"])
    root = snapshot.output_dir
    content = b"window.capturedResource = true;\n"
    target = {"captured": root / "responses/all/chunk.js", "outside": tmp_path / "private.js", "persona": root / ".persona/private.js"}[
        target_kind
    ]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    alias = root / "responses/example.com/assets/chunk.js"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(os.path.relpath(target, alias.parent))
    # Dynamic loaders request the original URL, rather than a rewritten HTML
    # attribute. Exercise the real route's responses/<host> fallback.
    url = urlsplit(build_snapshot_url(str(snapshot.id), "assets/chunk.js"))
    response = Client().get(url.path, HTTP_HOST=url.netloc, **({"HTTP_RANGE": byte_range} if byte_range else {}))
    try:
        if target_kind == "captured":
            assert response.status_code == (206 if byte_range else 200)
            body = b"".join(response.streaming_content) if response.streaming else response.content
            assert body == (content[:6] if byte_range else content)
        else:
            assert response.status_code == 404
            assert content not in response.content
    finally:
        response.close()


@pytest.mark.django_db(transaction=True)
def test_dynamic_resource_alias_renders_in_full_replay(snapshot, live_server, browser_runtime, tmp_path):
    import json
    import os
    from urllib.parse import urlsplit

    from playwright.sync_api import sync_playwright

    from archivebox.core.models import ArchiveResult
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": f"http://archivebox.localhost:{port}",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.url = "https://example.com/article"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["url", "permissions"])
    root = snapshot.output_dir
    document = root / "wget/index.html"
    document.parent.mkdir(parents=True)
    document.write_text(
        "<!doctype html><html><head><title>Captured article</title></head><body>"
        '<h1>Captured article</h1><p id="content">Saved article preview</p>'
        '<script>import("/assets/chunk.js").then(({content}) => {'
        'document.querySelector("#content").textContent = content;});</script></body></html>',
    )
    captured = root / "responses/all/chunk.js"
    captured.parent.mkdir(parents=True)
    captured.write_text('export const content = "Captured chapter loaded from the archive";\n')
    alias = root / "responses/example.com/assets/chunk.js"
    alias.parent.mkdir(parents=True)
    alias.symlink_to(os.path.relpath(captured, alias.parent))
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        hook_name="on_Snapshot__50_wget.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="index.html",
        output_files={"index.html": {"size": document.stat().st_size, "mimetype": "text/html"}},
        output_size=document.stat().st_size,
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_runtime["chrome_binary"]),
            args=[*browser_runtime["chrome_args"], "--host-resolver-rules=MAP *.archivebox.localhost 127.0.0.1"],
        )
        try:
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(
                f"http://web.archivebox.localhost:{port}{snapshot.get_absolute_url()}/index.html#wget/index.html",
                wait_until="domcontentloaded",
            )
            full = page.frame_locator("#main-frame").frame_locator("#document")
            full.get_by_text("Captured chapter loaded from the archive", exact=True).wait_for()
            # Cards intentionally disable scripts; the saved static preview
            # remains readable without granting scripts access to the UI.
            card = page.locator('iframe[title="wget card"]').first.content_frame.frame_locator("iframe")
            card.get_by_text("Saved article preview", exact=True).wait_for()
            assert card.locator("#content").inner_text() == "Saved article preview"
            content_frame = next(
                frame
                for frame in page.frames
                if frame.locator("#content").count() and frame.locator("#content").inner_text().startswith("Captured chapter")
            )
            resource = page.request.get(f"{urlsplit(content_frame.url).scheme}://{urlsplit(content_frame.url).netloc}/assets/chunk.js")
            assert resource.status == 200
            assert resource.body() == captured.read_bytes()
            (tmp_path / "dynamic-resource-timing.json").write_text(
                json.dumps(
                    content_frame.evaluate("""() => {
                    const n = performance.getEntriesByType('navigation')[0];
                    return {ttfb_ms: n.responseStart - n.requestStart,
                        resources: performance.getEntriesByType('resource').map(r => ({name: r.name, duration_ms: r.duration}))};
                }"""),
                ),
            )
            page.screenshot(path=str(tmp_path / "dynamic-resource-replay.png"))
            page.locator("#main-frame").scroll_into_view_if_needed()
            page.screenshot(path=str(tmp_path / "dynamic-resource-full.png"))
        finally:
            browser.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
@pytest.mark.parametrize("query,headers", [("", {}), ("?raw=1", {"HTTP_RANGE": "bytes=0-5"}), ("?preview=1", {})])
@pytest.mark.parametrize("link_kind", ["absolute", "relative", "directory", "casefold"])
def test_public_replay_rejects_escaping_symlinks(snapshot, tmp_path, mode, query, headers, link_kind):
    import os
    from urllib.parse import urlsplit

    from django.test import Client

    from archivebox.core.routes_util import build_snapshot_url
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": "http://archivebox.localhost:5797", "SERVER_SECURITY_MODE": mode}
    machine.save(update_fields=["config"])
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"synthetic private contents")
    output = snapshot.output_dir / "git"
    output.mkdir(parents=True, exist_ok=True)
    path = "git/leak.txt"
    if link_kind == "directory":
        (output / "leak").symlink_to(tmp_path, target_is_directory=True)
        path = "git/leak/secret.txt"
    else:
        target = os.path.relpath(secret, output) if link_kind == "relative" else secret
        (output / "leak.txt").symlink_to(target)
        if link_kind == "casefold":
            path = "GIT/LEAK.TXT"
    url = urlsplit(build_snapshot_url(str(snapshot.id), path))

    response = Client().get(f"{url.path}{query}", HTTP_HOST=url.netloc, **headers)

    assert response.status_code == 404
    assert secret.read_bytes() not in response.content


@pytest.mark.parametrize("query", ["?files=1", "?download=zip"])
def test_directory_replay_rejects_escaping_symlink(tmp_path, query):
    from django.http import Http404

    root = tmp_path / "snapshot"
    root.mkdir()
    outside = tmp_path / "snapshot-other"
    outside.mkdir()
    (outside / "secret.txt").write_text("synthetic private contents")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(Http404):
        serve_static_with_byterange_support(RequestFactory().get(f"/linked/{query}"), "linked", document_root=root, show_indexes=True)


@pytest.mark.parametrize("target", ["missing", "loop", ".persona/private.txt"])
def test_replay_rejects_broken_or_private_symlink(tmp_path, target):
    from django.http import Http404

    (tmp_path / ".persona").mkdir()
    (tmp_path / ".persona" / "private.txt").write_text("synthetic browser state")
    (tmp_path / "loop").symlink_to("loop")
    (tmp_path / "alias.txt").symlink_to(target)
    with pytest.raises(Http404):
        serve_static_with_byterange_support(RequestFactory().get("/alias.txt"), "alias.txt", document_root=tmp_path)


def test_directory_index_omits_escaping_and_broken_symlinks(tmp_path):
    root = tmp_path / "snapshot"
    root.mkdir()
    (root / "note.txt").write_text("inside")
    (root / "alias.txt").symlink_to("note.txt")
    (root / "outside").symlink_to(tmp_path, target_is_directory=True)
    (root / "broken").symlink_to("missing")
    (root / "loop").symlink_to("loop")
    response = serve_static_with_byterange_support(RequestFactory().get("/?files=1"), "", document_root=root, show_indexes=True)
    assert response.status_code == 200
    assert b'href="note.txt"' in response.content
    assert b'href="alias.txt"' in response.content
    for name in (b"outside", b"broken", b"loop"):
        assert b'href="' + name not in response.content


@pytest.mark.parametrize("byte_range", [None, "bytes=2-5"])
@pytest.mark.parametrize("path", ["alias.txt", "linked/note.txt", "LINKED/NOTE.TXT"])
def test_replay_preserves_in_snapshot_symlinks(tmp_path, path, byte_range):
    root = tmp_path / "snapshot"
    (root / "nested").mkdir(parents=True)
    content = b"0123456789"
    (root / "nested" / "note.txt").write_bytes(content)
    (root / "alias.txt").symlink_to("nested/note.txt")
    (root / "linked").symlink_to("nested", target_is_directory=True)
    # Collections themselves may live behind a trusted storage symlink.
    document_root = tmp_path / "storage"
    document_root.symlink_to(root, target_is_directory=True)
    response = serve_static_with_byterange_support(
        RequestFactory().get(f"/{path}?raw=1", **({"HTTP_RANGE": byte_range} if byte_range else {})),
        path,
        document_root=document_root,
    )
    assert response.status_code == (206 if byte_range else 200)
    assert b"".join(response.streaming_content) == (content[2:6] if byte_range else content)
    response.close()


@pytest.mark.parametrize("validator", ["etag", "modified"])
@pytest.mark.parametrize("extension", ["wacz", "zip"])
def test_generated_archive_preview_is_not_validated_by_source_file(tmp_path, validator, extension):
    import hashlib
    import json
    import zipfile

    from django.utils.http import http_date

    output = tmp_path / f"capture.{extension}"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("pages/pages.jsonl", json.dumps({"url": "https://example.com/"}) + "\n")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (tmp_path / "hashes").mkdir()
    (tmp_path / "hashes" / "hashes.json").write_text(json.dumps({"files": [{"path": output.name, "hash": digest}]}))
    headers = {
        "etag": {"HTTP_IF_NONE_MATCH": f'"{digest}"'},
        "modified": {"HTTP_IF_MODIFIED_SINCE": http_date(output.stat().st_mtime)},
    }[validator]
    request = RequestFactory().get(f"/{output.name}?preview=1", **headers)
    request.archivebox_snapshot_url = "https://example.com/"
    response = serve_static_with_byterange_support(request, output.name, document_root=tmp_path)
    # A deployment can change the generated viewer without touching its archive.
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert (b"replay-web-page" if extension == "wacz" else b"indexZip") in response.content
    assert "ETag" not in response

    raw = serve_static_with_byterange_support(
        RequestFactory().get(f"/{output.name}?raw=1", **headers),
        output.name,
        document_root=tmp_path,
    )
    assert raw.status_code == 304


@pytest.mark.parametrize("validator", [None, "range", "etag", "modified"])
@pytest.mark.parametrize("filename", ["favicon.ico", "favicon.svg", "favicon.png"])
def test_favicons_allow_long_lived_shared_caching(tmp_path, validator, filename):
    import hashlib
    import json

    from django.utils.http import http_date

    content = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
    output = tmp_path / "favicon" / filename
    output.parent.mkdir()
    output.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    (tmp_path / "hashes").mkdir()
    (tmp_path / "hashes" / "hashes.json").write_text(json.dumps({"files": [{"path": f"favicon/{filename}", "hash": digest}]}))
    headers = {
        "range": {"HTTP_RANGE": "bytes=0-3"},
        "etag": {"HTTP_IF_NONE_MATCH": f'"{digest}"'},
        "modified": {"HTTP_IF_MODIFIED_SINCE": http_date(output.stat().st_mtime)},
    }.get(validator, {})
    request = RequestFactory().get(f"/favicon/{filename}", **headers)
    request.archivebox_cache_policy = "private"
    response = serve_static_with_byterange_support(request, f"favicon/{filename}", document_root=tmp_path, is_archive_replay=True)
    assert response.status_code == (304 if validator in ("etag", "modified") else 206 if validator == "range" else 200)
    assert response["Cache-Control"] == "public, max-age=31536000, s-maxage=31536000, immutable"
    if response.streaming:
        assert b"".join(response.streaming_content) == (content[:4] if validator == "range" else content)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("mode", ["safe-subdomains-fullreplay", "safe-onedomain-nojsreplay"])
@pytest.mark.parametrize("permissions", ["public", "unlisted", "private"])
def test_favicon_cache_policy_survives_replay_and_middleware(snapshot, admin_user, mode, permissions):
    import hashlib
    import json
    from urllib.parse import urlsplit

    from django.test import Client

    from archivebox.core.routes_util import build_snapshot_url, get_admin_host
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": "http://archivebox.localhost:5797", "SERVER_SECURITY_MODE": mode}
    machine.save(update_fields=["config"])
    snapshot.config = {**snapshot.config, "PERMISSIONS": permissions}
    snapshot.save(update_fields=["config"])
    output = snapshot.output_dir / "favicon" / "favicon.ico"
    output.parent.mkdir(parents=True, exist_ok=True)
    content = b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>'
    output.write_bytes(content)
    (output.parent / "other.svg").write_bytes(content)
    hashes = snapshot.output_dir / "hashes"
    hashes.mkdir(exist_ok=True)
    (hashes / "hashes.json").write_text(
        json.dumps({"files": [{"path": "favicon/favicon.ico", "hash": hashlib.sha256(content).hexdigest()}]}),
    )
    from archivebox.core.models import ArchiveResult

    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="hashes",
        status="succeeded",
        output_str="Completed hashes",
        output_files={"hashes.json": {"size": (hashes / "hashes.json").stat().st_size}},
    )
    url = urlsplit(build_snapshot_url(str(snapshot.id), "favicon/favicon.ico"))
    client = Client()
    if permissions == "private":
        denied = client.get(url.path, HTTP_HOST=url.netloc)
        assert denied.status_code in (302, 403, 404)
        assert "public" not in denied["Cache-Control"]
        admin = Client()
        admin.force_login(admin_user)
        grant = admin.get(
            f"/admin/core/snapshot/replay-auth/?snapshot={snapshot.id}&next={url.path}",
            HTTP_HOST=get_admin_host(),
        )
        assert grant.status_code == 302
        target = urlsplit(grant["Location"])
        response = client.get(f"{target.path}?{target.query}", HTTP_HOST=target.netloc)
        assert response.status_code == 302

    response = client.get(url.path, HTTP_HOST=url.netloc)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == content
    expected = "public, max-age=31536000, s-maxage=31536000, immutable"
    assert response["Cache-Control"] == expected
    assert not {"cookie", "authorization"} & {v.strip().lower() for v in response.get("Vary", "").split(",")}
    for headers, status in [
        ({"HTTP_RANGE": "bytes=0-3"}, 206),
        ({"HTTP_IF_MODIFIED_SINCE": response["Last-Modified"]}, 304),
        ({"HTTP_IF_NONE_MATCH": response["ETag"]}, 304),
    ]:
        cached = client.get(url.path, HTTP_HOST=url.netloc, **headers)
        assert cached.status_code == status
        assert cached["Cache-Control"] == expected
        cached.close()
    other = client.get(url.path.replace("favicon.ico", "other.svg"), HTTP_HOST=url.netloc)
    assert other.status_code == 200
    assert other["Cache-Control"] == f"{'public' if permissions == 'public' else 'private'}, max-age=604800, immutable"
    other.close()


def test_generated_favicon_preview_retains_private_cache_policy(tmp_path):
    (tmp_path / "favicon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    request = RequestFactory().get("/favicon.png?preview=1")
    request.archivebox_cache_policy = "private"
    response = serve_static_with_byterange_support(request, "favicon.png", document_root=tmp_path)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert response["Cache-Control"] == "private, max-age=60, stale-while-revalidate=300"


def test_svg_favicon_saved_with_ico_extension_uses_svg_content_type(tmp_path):
    content = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16" fill="#f60"/></svg>'
    (tmp_path / "favicon.ico").write_bytes(content)
    request = RequestFactory().get("/favicon.ico")
    response = serve_static_with_byterange_support(request, "favicon.ico", document_root=tmp_path, is_archive_replay=True)
    assert response.status_code == 200
    assert response["Content-Type"] == "image/svg+xml; charset=utf-8"
    assert b"".join(response.streaming_content) == content


@pytest.mark.parametrize("filename", ["output.log", "hook.sh", "index.jsonl", "index.JSONL"])
@pytest.mark.parametrize("byte_range", [None, "bytes=2-5"])
def test_logs_shell_scripts_and_jsonl_are_served_as_plain_text(tmp_path: Path, filename: str, byte_range: str | None):
    content = b"# Heading\n\n- item\n- another item\n\n&lt;literal&gt;\n"
    (tmp_path / filename).write_bytes(content)
    request = RequestFactory().get(f"/{filename}", **({"HTTP_RANGE": byte_range} if byte_range else {}))

    response = serve_static_with_byterange_support(request, filename, document_root=tmp_path)

    assert response.status_code == (206 if byte_range else 200)
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    assert response["Content-Disposition"] == f'inline; filename="{filename}"'
    assert b"".join(response.streaming_content) == (content[2:6] if byte_range else content)


@pytest.mark.parametrize("filename", ["output.description", "output.DESCRIPTION"])
@pytest.mark.parametrize("byte_range", [None, "bytes=2-5"])
def test_description_file_is_served_as_plain_text(tmp_path: Path, filename: str, byte_range: str | None):
    content = b"Title: Test Page\nAuthor: ArchiveBox\n"
    (tmp_path / filename).write_bytes(content)
    request = RequestFactory().get(f"/{filename}", **({"HTTP_RANGE": byte_range} if byte_range else {}))

    response = serve_static_with_byterange_support(request, filename, document_root=tmp_path)

    assert response.status_code == (206 if byte_range else 200)
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    assert b"".join(response.streaming_content) == (content[2:6] if byte_range else content)


@pytest.mark.parametrize("filename,query", [("document.html", "?raw=1"), ("payload.bin", "")])
@pytest.mark.parametrize("byte_range", [None, "bytes=2-5"])
def test_head_file_headers_do_not_open_payload(tmp_path: Path, filename: str, query: str, byte_range: str | None):
    import sys

    content = b"<!doctype html><html><body>" + b"saved archive content\n" * 100_000 + b"</body></html>"
    output = tmp_path / filename
    output.write_bytes(content)
    headers = {"HTTP_RANGE": byte_range} if byte_range else {}
    observed_opens: list[str] = []
    phase = ""

    # Observe native CPython file opens without replacing or interrupting any
    # filesystem operation. On a full-cache FUSE mount even open() can start
    # remote payload reads, so merely suppressing HEAD's wire body is too late.
    def observe_open(event, args):
        if phase and event == "open" and args[0] == str(output):
            observed_opens.append(phase)

    sys.addaudithook(observe_open)
    try:
        phase = "head"
        request = RequestFactory().head(f"/{filename}{query}", **headers)
        request.scope = {"type": "http"}
        head = serve_static_with_byterange_support(request, filename, document_root=tmp_path)
        head.close()
        phase = "get"
        get = serve_static_with_byterange_support(RequestFactory().get(f"/{filename}{query}", **headers), filename, document_root=tmp_path)
        assert b"".join(get.streaming_content) == (content[2:6] if byte_range else content)
        get.close()
    finally:
        phase = ""

    assert "get" in observed_opens, "the observer must see the real GET payload open"
    assert "head" not in observed_opens, "HEAD opened the payload before returning headers"
    assert head.status_code == get.status_code == (206 if byte_range else 200)
    assert not head.streaming and head.content == b""
    for name in (
        "Content-Type",
        "Content-Length",
        "Content-Range",
        "Accept-Ranges",
        "Last-Modified",
        "Cache-Control",
        "Content-Disposition",
    ):
        assert head.get(name) == get.get(name), name


def test_archive_file_response_uses_async_iterator_under_asgi(tmp_path: Path):
    output = tmp_path / "screenshot" / "output.png"
    output.parent.mkdir()
    output.write_bytes(b"0123456789")

    request = RequestFactory().get("/screenshot/output.png", HTTP_RANGE="bytes=2-5")
    request.scope = {"type": "http"}

    response = serve_static_with_byterange_support(
        request,
        "screenshot/output.png",
        document_root=tmp_path,
    )

    assert response.is_async is True
    assert response.status_code == 206
    assert response["Content-Range"] == "bytes 2-5/10"
    assert response["Content-Length"] == "4"


def test_path_routed_directory_index_keeps_file_browsing_context(tmp_path: Path):
    plugin_dir = tmp_path / "archivewebpage"
    plugin_dir.mkdir()
    (plugin_dir / "archivewebpage.wacz").write_bytes(b"wacz")

    request = RequestFactory().get("/snapshot/snapshot-id/?files=1")
    response = serve_static_with_byterange_support(
        request,
        "",
        document_root=tmp_path,
        show_indexes=True,
        is_archive_replay=True,
    )

    html = response.content.decode()
    assert 'href="archivewebpage/?files=1"' in html
    assert 'href="/snapshot/snapshot-id/"' in html

    nested_request = RequestFactory().get("/snapshot/snapshot-id/archivewebpage/?files=1")
    nested_response = serve_static_with_byterange_support(
        nested_request,
        "archivewebpage",
        document_root=tmp_path,
        show_indexes=True,
        is_archive_replay=True,
    )

    nested_html = nested_response.content.decode()
    assert 'href="../?files=1"' in nested_html
    assert 'href="/snapshot/snapshot-id/"' in nested_html
    assert 'href="archivewebpage.wacz"' in nested_html


def test_directory_preview_requests_content_fit_without_changing_saved_html(tmp_path: Path):
    from archivebox.config.common import get_config

    factory = RequestFactory()
    source = Path(__file__).parent / "fixtures" / "consolelog_preview.html"
    (tmp_path / "singlefile.html").write_bytes(source.read_bytes())

    directory = serve_static_with_byterange_support(
        factory.get("/snapshot/snapshot-id/?files=1"),
        "",
        document_root=tmp_path,
        show_indexes=True,
    )
    assert directory.status_code == 200
    assert b"archivebox-preview-height" in directory.content
    assert b"fitContent: true" in directory.content

    request = factory.get("/singlefile.html?preview=1")
    request.archivebox_snapshot_url = "https://example.com/"
    request.archivebox_config = get_config(
        overrides={"SERVER_SECURITY_MODE": "safe-subdomains-fullreplay"},
        include_machine=False,
        resolve_plugins=False,
    )
    saved_html = serve_static_with_byterange_support(request, "singlefile.html", document_root=tmp_path)
    assert saved_html.status_code == 200
    assert b'title="Saved page"' in saved_html.content
    assert b"archivebox-preview-height" in saved_html.content
    assert b"fitContent" not in saved_html.content


def test_raw_html_preview_shows_escaped_source_in_text_viewer(tmp_path: Path):
    source = Path(__file__).parent / "fixtures" / "consolelog_preview.html"
    (tmp_path / source.name).write_bytes(source.read_bytes())
    request = RequestFactory().get(f"/{source.name}?preview=1&raw=1")

    response = serve_static_with_byterange_support(request, source.name, document_root=tmp_path)

    assert response.status_code == 200
    assert b"archivebox-text-preview" in response.content
    assert b"&lt;script&gt;" in response.content
    assert b"<script>" not in response.content
    import html
    from html.parser import HTMLParser

    class ScriptInventory(HTMLParser):
        def __init__(self):
            super().__init__()
            self.scripts = []

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                self.scripts.append(dict(attrs))

    inventory = ScriptInventory()
    inventory.feed(response.content.decode())
    assert inventory.scripts == [{"id": "archivebox-preview-height"}]
    assert html.escape(source.read_text()) in response.content.decode()


@pytest.mark.parametrize("byte_range", [None, "bytes=2-25"])
def test_raw_text_file_preserves_markdown_bytes(tmp_path: Path, byte_range: str | None):
    source = Path(__file__).resolve().parents[2] / "README.md"
    content = source.read_bytes()
    (tmp_path / "article.txt").write_bytes(content)
    request = RequestFactory().get("/article.txt?raw=1", **({"HTTP_RANGE": byte_range} if byte_range else {}))

    response = serve_static_with_byterange_support(request, "article.txt", document_root=tmp_path)

    assert response.status_code == (206 if byte_range else 200)
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    assert b"".join(response.streaming_content) == (content[2:26] if byte_range else content)


def test_markdown_file_renders_short_document_and_keeps_raw_source(tmp_path: Path):
    source = "# Repository\n\nA **small** README with `code`.\n"
    (tmp_path / "README.md").write_text(source)
    response = serve_static_with_byterange_support(
        RequestFactory().get("/README.md"),
        "README.md",
        document_root=tmp_path,
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert b"<h1" in response.content
    assert b"<strong>small</strong>" in response.content
    raw = serve_static_with_byterange_support(
        RequestFactory().get("/README.md?raw=1"),
        "README.md",
        document_root=tmp_path,
    )
    assert b"".join(raw.streaming_content).decode() == source


def test_markdown_repository_tables_and_code_render(tmp_path: Path):
    # Git captures serve real README files, including tables like ulid/spec's
    # implementation list. A handwritten fallback silently lost that structure.
    source = "# Implementations\n\n| Language | Binary |\n| --- | --- |\n| Python | `ulid()` |\n"
    (tmp_path / "README.md").write_text(source)
    response = serve_static_with_byterange_support(
        RequestFactory().get("/README.md"),
        "README.md",
        document_root=tmp_path,
    )
    assert response.status_code == 200
    assert b"<table>" in response.content
    assert b"<th>Language</th>" in response.content
    assert b"<td>Python</td>" in response.content
    assert b"<code>ulid()</code>" in response.content


@pytest.mark.parametrize("closing_tags", ["</body></html>", ""])
def test_complete_html_is_not_reinterpreted_as_markdown(tmp_path: Path, closing_tags: str):
    # Markdown syntax in page data/comments must not replace an HTML document.
    markers = "\n".join(f"# Saved heading {number}" for number in range(6))
    source = f"<!doctype html><html><head><title>Saved page</title></head><body><p>Article</p><!--\n{markers}\n-->{closing_tags}"
    output = tmp_path / "page.html"
    output.write_text(source)
    response = serve_static_with_byterange_support(RequestFactory().get("/page.html"), "page.html", document_root=tmp_path)
    assert response.status_code == 200
    body = b"".join(response.streaming_content) if response.streaming else response.content
    assert body == source.encode()
    assert output.read_text() == source


def test_markdown_in_html_fragment_still_renders(tmp_path: Path):
    source = "<p>" + "\n".join(f"# Saved heading {number}" for number in range(6)) + "</p>"
    (tmp_path / "article.html").write_text(source)
    response = serve_static_with_byterange_support(RequestFactory().get("/article.html"), "article.html", document_root=tmp_path)
    assert response.status_code == 200
    assert response.content.count(b"<h1") == 6
    assert (tmp_path / "article.html").read_text() == source


def test_image_rewrite_uses_optional_saved_artifacts(tmp_path: Path):
    import json
    from archivebox.misc.serve_static import _rewrite_replay_document_for_request

    source = '<img src="https://example.com/badge.svg">'
    request = RequestFactory().get("/git/README.md")

    def rewrite():
        return _rewrite_replay_document_for_request(request, source, tmp_path, "git/README.md")

    assert rewrite() == (source, 0)
    responses = tmp_path / "responses"
    responses.mkdir()
    (responses / "short.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (responses / "index.jsonl").write_text(
        "broken json\n"
        + json.dumps(
            {
                "url": "https://proxy.example.com/image",
                "method": "GET",
                "status": 200,
                "path": "./short.svg",
            },
        )
        + "\n",
    )
    dom = tmp_path / "dom"
    dom.mkdir()
    (dom / "output.html").write_text('<img src="https://proxy.example.com/image" data-canonical-src="https://example.com/badge.svg">')
    assert rewrite() == ('<img src="../responses/short.svg">', 1)
    (responses / "index.jsonl").unlink()
    (responses / "index.jsonl").mkdir()
    assert rewrite() == (source, 0)


def test_zip_preview_is_generic_and_raw_range_stays_seekable(tmp_path):
    import zipfile

    output = tmp_path / "arbitrary-plugin" / "nested" / "bundle.ZIP"
    output.parent.mkdir(parents=True)
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("inside/note.txt", "generic archive browsing")
    path = output.relative_to(tmp_path).as_posix()
    factory = RequestFactory()
    preview = serve_static_with_byterange_support(factory.get(f"/{path}?preview=1"), path, document_root=tmp_path)
    assert preview.status_code == 200
    assert preview["Content-Type"].startswith("text/html")
    assert b"indexZip" in preview.content
    assert b"bundle.ZIP" in preview.content
    assert b"raw=1" in preview.content
    assert b"downloads.json" not in preview.content
    raw = serve_static_with_byterange_support(factory.get(f"/{path}?raw=1", HTTP_RANGE="bytes=0-3"), path, document_root=tmp_path)
    assert raw.status_code == 206
    assert b"".join(raw.streaming_content) == b"PK\x03\x04"
    listing = serve_static_with_byterange_support(
        factory.get("/arbitrary-plugin/nested/?files=1"),
        "arbitrary-plugin/nested/",
        document_root=tmp_path,
        show_indexes=True,
    )
    assert b"bundle.ZIP?preview=1" in listing.content


def test_directory_index_has_filter_and_per_entry_downloads(tmp_path: Path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "note.txt").write_text("searchable text")
    response = serve_static_with_byterange_support(
        RequestFactory().get("/snapshot/demo/?files=1"),
        "",
        document_root=tmp_path,
        show_indexes=True,
        is_archive_replay=True,
    )
    html = response.content.decode()
    assert 'aria-label="Filter files"' in html
    assert 'data-zip-path="nested/"' in html
    assert "download=zip" not in html
    assert 'href="note.txt?raw=1" download' in html


def test_directory_zip_excludes_symlinks_outside_export_root(tmp_path: Path):
    import io
    import zipfile

    root = tmp_path / "export"
    root.mkdir()
    (root / "note.txt").write_bytes(b"inside")
    (root / "alias.txt").symlink_to(root / "note.txt")
    (root / ".persona").mkdir()
    (root / ".persona" / "private.txt").write_bytes(b"private browser state")
    (root / "private.txt").symlink_to(".persona/private.txt")
    (root / "broken.txt").symlink_to("missing")
    (root / "loop.txt").symlink_to("loop.txt")
    outside = tmp_path / "export-other"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"outside")
    (root / "leak.txt").symlink_to(outside / "secret.txt")
    response = serve_static_with_byterange_support(
        RequestFactory().get("/?download=zip"),
        "",
        document_root=root,
        show_indexes=True,
        is_archive_replay=True,
    )
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as archive:
        assert set(archive.namelist()) == {"export/note.txt", "export/alias.txt"}
        assert archive.read("export/note.txt") == b"inside"
        assert archive.read("export/alias.txt") == b"inside"


def test_directory_zip_resolves_ancestors_per_directory_not_per_file(tmp_path):
    import io
    import os
    import sys
    import zipfile

    root = tmp_path.resolve()
    (root / "nested").mkdir()
    expected = {}
    for folder in (root, root / "nested"):
        for number in range(10):
            path = folder / f"file-{number}.txt"
            path.write_text(path.name)
            expected[f"{root.name}/{path.relative_to(root)}"] = path.name.encode()
    response = serve_static_with_byterange_support(
        RequestFactory().get("/?download=zip"),
        "",
        document_root=root,
        show_indexes=True,
    )
    root_lookups = []

    def observe(code, offset, callee, arg0):
        if callee is os.lstat and Path(arg0) == root:
            root_lookups.append(str(arg0))

    tool_id = next(tool for tool in range(6) if sys.monitoring.get_tool(tool) is None)
    sys.monitoring.use_tool_id(tool_id, "zip-ancestor-lookups")
    sys.monitoring.register_callback(tool_id, sys.monitoring.events.CALL, observe)
    sys.monitoring.set_events(tool_id, sys.monitoring.events.CALL)
    try:
        body = b"".join(response.streaming_content)
    finally:
        response.close()
        sys.monitoring.set_events(tool_id, 0)
        sys.monitoring.register_callback(tool_id, sys.monitoring.events.CALL, None)
        sys.monitoring.free_tool_id(tool_id)
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == expected
    assert len(root_lookups) == 2, root_lookups


def test_casefold_paths_remain_inside_archive_root(tmp_path: Path):
    from django.core.exceptions import SuspiciousFileOperation
    from archivebox.misc.serve_static import _resolve_archive_path

    (tmp_path / "Documents").mkdir()
    saved = tmp_path / "Documents" / "Note.txt"
    saved.write_text("inside root")
    resolved, relative, root = _resolve_archive_path(tmp_path, "documents/note.TXT")
    assert resolved.read_text() == "inside root"
    assert resolved.is_relative_to(tmp_path)
    assert relative.casefold() == "documents/note.txt"
    assert root == tmp_path.resolve()
    with pytest.raises(SuspiciousFileOperation):
        _resolve_archive_path(tmp_path, "../DOCUMENTS/note.TXT")


def test_directory_previews_only_small_supported_files(tmp_path: Path):
    import sqlite3

    with sqlite3.connect(tmp_path / "database.sqlite3") as database:
        database.execute("CREATE TABLE example (value TEXT)")
    (tmp_path / "small.txt").write_text("small preview")
    (tmp_path / "exact-limit.txt").write_bytes(b"x" * (100 * 1024))
    (tmp_path / "unknown.bin").write_bytes(b"\x00\x01")
    (tmp_path / "picture.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    response = serve_static_with_byterange_support(
        RequestFactory().get("/snapshot/demo/?files=1"),
        "",
        document_root=tmp_path,
        show_indexes=True,
        is_archive_replay=True,
    )
    html = response.content.decode()
    assert 'data-url="small.txt?raw=1"' in html
    assert 'src="picture.svg?raw=1"' in html
    assert 'data-url="exact-limit.txt?raw=1"' not in html
    assert 'data-url="unknown.bin?raw=1"' not in html
    assert 'data-url="database.sqlite3?raw=1"' not in html


def test_directory_index_reads_each_entry_metadata_once(tmp_path):
    import os
    import sys
    from collections import Counter

    paths = [tmp_path / f"file-{index}.txt" for index in range(10)]
    for path in paths:
        path.write_text(path.name)
    folder = tmp_path / "nested"
    folder.mkdir()
    paths.append(folder)
    metadata_reads = Counter()

    def observe_stat(code, offset, callee, arg0):
        if callee in (os.stat, os.lstat):
            path = Path(arg0) if isinstance(arg0, (str, bytes, os.PathLike)) else None
        elif callee is os.DirEntry.stat:
            path = Path(arg0.path)
        else:
            return
        if path in paths:
            metadata_reads[path] += 1

    # Observe native metadata work, including realpath's lstat calls and
    # scandir metadata. Counting only Path.stat misses repeated FUSE lookups.
    tool_id = next(tool for tool in range(6) if sys.monitoring.get_tool(tool) is None)
    sys.monitoring.use_tool_id(tool_id, "directory-metadata-reads")
    sys.monitoring.register_callback(tool_id, sys.monitoring.events.CALL, observe_stat)
    sys.monitoring.set_events(tool_id, sys.monitoring.events.CALL)
    try:
        response = serve_static_with_byterange_support(
            RequestFactory().get("/?files=1"),
            "",
            document_root=tmp_path,
            show_indexes=True,
        )
    finally:
        sys.monitoring.set_events(tool_id, 0)
        sys.monitoring.register_callback(tool_id, sys.monitoring.events.CALL, None)
        sys.monitoring.free_tool_id(tool_id)
    assert response.status_code == 200
    for path in paths:
        target = f"{path.name}/?files=1" if path == folder else path.name
        assert f'href="{target}"'.encode() in response.content
    assert metadata_reads == dict.fromkeys(paths, 1), metadata_reads


@pytest.mark.parametrize("linked_root", [False, True])
def test_directory_index_resolves_document_root_once(tmp_path, linked_root):
    import os
    import sys

    root = tmp_path / "outputs"
    root.mkdir()
    root = root.resolve()
    (root / "note.txt").write_text("captured")
    document_root = root
    if linked_root:
        document_root = tmp_path / "storage-link"
        document_root.symlink_to(root, target_is_directory=True)
    root_lookups = []

    def observe(code, offset, callee, arg0):
        if callee is os.lstat and Path(arg0) == root:
            root_lookups.append(str(arg0))

    tool_id = next(tool for tool in range(6) if sys.monitoring.get_tool(tool) is None)
    sys.monitoring.use_tool_id(tool_id, "replay-root-lookups")
    sys.monitoring.register_callback(tool_id, sys.monitoring.events.CALL, observe)
    sys.monitoring.set_events(tool_id, sys.monitoring.events.CALL)
    try:
        response = serve_static_with_byterange_support(
            RequestFactory().get("/?files=1"),
            "",
            document_root=document_root,
            show_indexes=True,
        )
    finally:
        sys.monitoring.set_events(tool_id, 0)
        sys.monitoring.register_callback(tool_id, sys.monitoring.events.CALL, None)
        sys.monitoring.free_tool_id(tool_id)
    assert response.status_code == 200
    assert b'href="note.txt"' in response.content
    assert len(root_lookups) == 1, root_lookups


def test_missing_plugin_replay_roots_do_not_resolve_ancestors(tmp_path):
    import os
    import sys
    from archivebox.plugins.discovery import get_plugin_replay_roots

    root = tmp_path.resolve()
    calls = []

    def observe(code, offset, callee, arg0):
        if callee in (os.stat, os.lstat) and isinstance(arg0, (str, os.PathLike)):
            path = Path(arg0)
            if path.is_relative_to(root):
                calls.append((callee.__name__, path.relative_to(root).as_posix()))

    tool_id = next(tool for tool in range(6) if sys.monitoring.get_tool(tool) is None)
    sys.monitoring.use_tool_id(tool_id, "replay-provider-lookups")
    sys.monitoring.register_callback(tool_id, sys.monitoring.events.CALL, observe)
    sys.monitoring.set_events(tool_id, sys.monitoring.events.CALL)
    try:
        roots = list(get_plugin_replay_roots(root, "https://example.com/"))
    finally:
        sys.monitoring.set_events(tool_id, 0)
        sys.monitoring.register_callback(tool_id, sys.monitoring.events.CALL, None)
        sys.monitoring.free_tool_id(tool_id)
    assert roots == []
    assert sorted(calls) == [("stat", "responses/example.com"), ("stat", "wget/example.com")], calls


@pytest.mark.parametrize("target_kind", ["inside", "outside", "missing"])
def test_plugin_replay_root_symlinks_remain_contained(tmp_path, target_kind):
    from archivebox.plugins.discovery import get_plugin_replay_roots

    root = tmp_path / "snapshot"
    (root / "responses").mkdir(parents=True)
    inside = root / "captured"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = {"inside": inside, "outside": outside, "missing": root / "missing"}[target_kind]
    alias = root / "responses/example.com"
    alias.symlink_to(target, target_is_directory=True)
    assert list(get_plugin_replay_roots(root, "https://example.com/")) == ([alias] if target_kind == "inside" else [])


@pytest.mark.parametrize("use_asgi", [False, True])
def test_directory_zip_head_keeps_headers_without_generating_zip(tmp_path, use_asgi):
    import asyncio
    import io
    import zipfile

    from django.test import AsyncRequestFactory

    root = tmp_path / "download"
    root.mkdir()
    payload = b"captured payload\n"
    (root / "capture.txt").write_bytes(payload)
    request_factory = AsyncRequestFactory() if use_asgi else RequestFactory()

    def serve(request):
        return serve_static_with_byterange_support(
            request,
            "",
            document_root=root,
            show_indexes=True,
            is_archive_replay=True,
        )

    async def collect_async(response):
        return b"".join([chunk async for chunk in response.streaming_content])

    def collect(response):
        try:
            return asyncio.run(collect_async(response)) if use_asgi else b"".join(response.streaming_content)
        finally:
            response.close()

    head = serve(request_factory.head("/?download=zip"))
    get = serve(request_factory.get("/?download=zip"))
    assert head.status_code == get.status_code == 200
    assert head.is_async == get.is_async == use_asgi
    assert dict(head.headers) == dict(get.headers)
    assert head.headers["Content-Disposition"] == 'attachment; filename="download.zip"'
    assert "Content-Length" not in head.headers
    # Uvicorn discards every HEAD body byte, but Django still consumes its
    # iterator. Keeping that iterator empty avoids opening and compressing files.
    assert collect(head) == b""
    with zipfile.ZipFile(io.BytesIO(collect(get))) as archive:
        assert archive.namelist() == ["download/capture.txt"]
        assert archive.read("download/capture.txt") == payload
