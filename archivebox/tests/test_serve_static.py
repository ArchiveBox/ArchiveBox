from pathlib import Path

import pytest
from django.test import RequestFactory

from archivebox.misc.serve_static import serve_static_with_byterange_support


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
