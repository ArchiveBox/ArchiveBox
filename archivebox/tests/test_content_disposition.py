"""Saved filenames remain data, never HTTP header syntax."""

import io
import zipfile
from collections.abc import Iterable
from email.message import Message
from urllib.parse import quote, urlsplit

import pytest
from django.test import Client, RequestFactory
from django.http import StreamingHttpResponse

from archivebox.misc.serve_static import serve_static_with_byterange_support


FILENAMES = [
    "ordinary file",
    "ascii\nnewline",
    "carriage\r\nX-Injected: yes",
    "galápagos\n  Scientific Paper 中文",
    'quoted";filename=other\\name',
    "control\x01\x7fname",
    "tab\tname",
]


def assert_disposition(response, disposition, filename):
    header = response["Content-Disposition"]
    assert "\r" not in header and "\n" not in header
    assert all(char == "\t" or 32 <= ord(char) <= 126 for char in header)
    parsed = Message()
    parsed["Content-Disposition"] = header
    assert parsed.get_content_disposition() == disposition
    assert parsed.get_filename() == filename
    assert "X-Injected" not in response


@pytest.mark.parametrize("stem", FILENAMES)
@pytest.mark.parametrize("method,byte_range", [("get", None), ("head", None), ("get", "bytes=2-5")])
def test_static_file_disposition_encodes_filename(tmp_path, stem, method, byte_range):
    filename = stem + ".txt"
    content = b"0123456789\n"
    (tmp_path / filename).write_bytes(content)
    request = getattr(RequestFactory(), method)(
        "/" + quote(filename, safe=""),
        **({"HTTP_RANGE": byte_range} if byte_range else {}),
    )
    response = serve_static_with_byterange_support(request, filename, document_root=tmp_path)
    try:
        assert response.status_code == (206 if byte_range else 200)
        assert_disposition(response, "inline", filename)
        if isinstance(response, StreamingHttpResponse):
            assert not response.is_async
            stream = response.streaming_content
            assert isinstance(stream, Iterable)
            body = b"".join(stream)
        else:
            body = response.content
        assert body == (b"" if method == "head" else content[2:6] if byte_range else content)
    finally:
        response.close()


@pytest.mark.parametrize("stem", FILENAMES)
def test_transformed_file_disposition_encodes_filename(tmp_path, stem):
    filename = stem + ".md"
    (tmp_path / filename).write_text("# Archived document\n")
    request = RequestFactory().get("/" + quote(filename, safe=""))
    response = serve_static_with_byterange_support(request, filename, document_root=tmp_path)
    try:
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/html")
        assert b"Archived document" in response.content
        assert_disposition(response, "inline", filename)
    finally:
        response.close()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("stem", FILENAMES)
def test_plugin_full_preview_encodes_filename(snapshot, stem):
    from archivebox.core.models import ArchiveResult
    from archivebox.core.routes_util import build_snapshot_url
    from archivebox.machine.models import Machine

    machine = Machine.current()
    machine.config = {
        **machine.config,
        "BASE_URL": "http://archivebox.localhost:5797",
        "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay",
    }
    machine.save(update_fields=["config"])
    snapshot.config = {**snapshot.config, "PERMISSIONS": "public"}
    snapshot.save(update_fields=["config"])
    filename = stem + ".pdf"
    output = snapshot.output_dir / "papersdl" / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"%PDF-1.4\n%%EOF\n")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="papersdl",
        hook_name="on_Snapshot__50_papersdl.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str=filename,
        output_files={filename: {"size": output.stat().st_size, "mimetype": "application/pdf"}},
    )
    url = urlsplit(build_snapshot_url(str(snapshot.id), f"papersdl/{filename}"))
    response = Client().get(f"{url.path}?preview=1", HTTP_HOST=url.netloc)
    try:
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/html")
        assert b"Archived scientific paper" in response.content
        assert_disposition(response, "inline", stem + ".html")
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Referrer-Policy"] == "no-referrer"
        assert response["Content-Security-Policy"]
    finally:
        response.close()


def test_zip_keeps_attachment_disposition_and_safe_export_name(tmp_path):
    directory = tmp_path / 'galápagos\r\n"export'
    directory.mkdir()
    (directory / "document.txt").write_bytes(b"archived")
    request = RequestFactory().get("/" + quote(directory.name, safe="") + "/?download=zip")
    response = serve_static_with_byterange_support(request, directory.name, document_root=tmp_path, show_indexes=True)
    try:
        assert response.status_code == 200
        assert_disposition(response, "attachment", "gal-pagos-export.zip")
        assert isinstance(response, StreamingHttpResponse) and not response.is_async
        stream = response.streaming_content
        assert isinstance(stream, Iterable)
        with zipfile.ZipFile(io.BytesIO(b"".join(stream))) as archive:
            assert archive.read("gal-pagos-export/document.txt") == b"archived"
    finally:
        response.close()
