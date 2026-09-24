from pathlib import Path

import pytest
from django.test import RequestFactory

from archivebox.misc.serve_static import serve_static_with_byterange_support


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


@pytest.mark.django_db
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


def test_raw_html_preview_shows_escaped_source_in_text_viewer(tmp_path: Path):
    source = Path(__file__).parent / "fixtures" / "consolelog_preview.html"
    (tmp_path / source.name).write_bytes(source.read_bytes())
    request = RequestFactory().get(f"/{source.name}?preview=1&raw=1")

    response = serve_static_with_byterange_support(request, source.name, document_root=tmp_path)

    assert response.status_code == 200
    assert b"archivebox-text-preview" in response.content
    assert b"&lt;script&gt;" in response.content
    assert b"<script>" not in response.content


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


def test_image_rewrite_uses_optional_saved_artifacts(tmp_path: Path):
    import json
    from archivebox.misc.serve_static import _rewrite_html_image_sources_for_request

    source = '<img src="https://example.com/badge.svg">'
    request = RequestFactory().get("/git/README.md")

    def rewrite():
        return _rewrite_html_image_sources_for_request(request, source, tmp_path, "git/README.md")

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
