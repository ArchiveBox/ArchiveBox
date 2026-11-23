"""All served replay documents identify the source without changing saved files."""

import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest
from lxml.html import fromstring

from archivebox.core.models import ArchiveResult
from archivebox.core.routes_util import get_snapshot_host
from archivebox.machine.models import Machine
from archivebox.tests.conftest import WEB_TEST_HOST


@pytest.mark.django_db(transaction=True)
def test_replay_documents_share_original_and_search_metadata(snapshot, client):
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": "http://archivebox.localhost", "SERVER_SECURITY_MODE": "safe-subdomains-fullreplay"}
    machine.save(update_fields=["config"])
    snapshot.url = "https://example.com/article?a=1&b=%22yes%22"
    snapshot.permissions = "public"
    snapshot.save(update_fields=["url", "permissions"])
    root = snapshot.output_dir
    documents = {
        "singlefile/output.html": b'<html><head><link rel="canonical" href="https://wrong.example/"><meta name="robots" content="index, nofollow"></head><body>Saved article</body></html>',
        "dom/output.html": b"<!doctype html><html><head><title>DOM</title></head><body>Saved DOM</body></html>",
        "readability/content.html": b"<article>Readable article</article>",
        "wget/index.html": b"<html><head><title>Wget</title></head><body>Saved page</body></html>",
        "wget/note.txt": b"Saved notes\n",
        "wget/data.json": b'{"title": "Saved metadata"}',
        "git/README.md": b"# Archived repository\n\nOriginal documentation.\n",
    }
    for name, content in documents.items():
        output = root / name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
    fixtures = Path(__file__).parent / "fixtures"
    shutil.copyfile(fixtures / "redirected-image/image.png", root / "wget/image.png")
    shutil.copyfile(fixtures / "model-preview/Box.glb", root / "wget/model.glb")
    with zipfile.ZipFile(root / "wget/bundle.zip", "w") as bundle:
        bundle.writestr("note.txt", documents["wget/note.txt"])
    for plugin in ("singlefile", "dom", "readability", "wget", "git"):
        files = sorted((root / plugin).iterdir())
        ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin=plugin,
            status="succeeded",
            output_str=files[0].name,
            output_files={path.name: {"size": path.stat().st_size} for path in files},
        )
    saved = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.glob("*/*") if path.is_file()}
    host = get_snapshot_host(str(snapshot.id))
    routes = [
        (WEB_TEST_HOST, snapshot.get_absolute_url()),
        *[(host, f"/{path}") for path in documents if path.endswith((".html", ".md"))],
        *[(host, f"/{path}?preview=1") for path in documents],
        (host, "/wget/image.png?preview=1"),
        (host, "/wget/model.glb?preview=1"),
        (host, "/wget/bundle.zip?preview=1"),
        (host, "/wget/?files=1"),
        (host, "/replay/replay.html"),
    ]
    for request_host, path in routes:
        response = client.get(path, HTTP_HOST=request_host)
        assert response.status_code == 200, (path, response.status_code)
        body = b"".join(response.streaming_content) if response.streaming else response.content
        doc = fromstring(body)
        assert doc.xpath('//head/link[@rel="canonical"]/@href') == [snapshot.url], path
        assert doc.xpath('//head/link[@rel="original"]/@href') == [snapshot.url], path
        assert doc.xpath('//head/meta[@name="robots"]/@content') == ["noindex, follow"], path
        assert response["X-Robots-Tag"] == "noindex, follow", path
        response.close()
    assert {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in saved} == saved
