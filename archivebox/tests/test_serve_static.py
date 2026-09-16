from pathlib import Path

import pytest
from django.test import RequestFactory

from archivebox.misc.serve_static import serve_static_with_byterange_support


@pytest.mark.parametrize("filename", ["output.log", "hook.sh"])
@pytest.mark.parametrize("byte_range", [None, "bytes=2-5"])
def test_logs_and_shell_scripts_are_served_as_plain_text(tmp_path: Path, filename: str, byte_range: str | None):
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
