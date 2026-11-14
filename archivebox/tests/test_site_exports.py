# ruff: noqa: F811 - pytest injects the imported shared capture fixture by name.
"""Portable site exports from real captured pages through the native command."""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from archivebox.tests.conftest import ADMIN_TEST_HOST
from archivebox.tests.test_original_domain_replay import saved_site  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("format", ["html", "html_zip", "wacz", "replay"])
def test_main_domain_export_options_validate_server_directory(admin_client, saved_site, format):
    from archivebox.machine.models import Process

    page = admin_client.get("/admin/domains/", HTTP_HOST=ADMIN_TEST_HOST)
    # Each format is offered in both the bulk and per-domain export dropdowns.
    assert page.content.count(f'<option value="{format}">'.encode()) == 2
    response = admin_client.post(
        "/admin/domains/actions/",
        {"action": "export", "domain": "*.ycombinator.com", "export_format": format, "directory": "relative/path"},
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 400
    assert not Process.objects.filter(worker_type="site-export").exists()
    assert b"absolute server directory" in response.content


def test_static_site_command_preserves_sources_and_exports_links(saved_site, tmp_path):
    destination = tmp_path / "export"
    call_command("site_export", scope="news.ycombinator.com", format="html", destination=str(destination))
    manifest = json.loads((destination / "pages.json").read_text())
    assert len(manifest) == len(saved_site)
    paths = {entry["url"]: entry["path"] for entry in manifest}
    assert (destination / "index.html").is_file()
    homepage = destination / paths["https://news.ycombinator.com/"]
    body = homepage.read_text()
    assert "archivebox-links.js" in body
    assert "newest" in (destination / "archivebox-links.js").read_text()
    assert "../" in body
    assert "https://news.ycombinator.com/ask" in body
    assert not list(destination.rglob("*.sqlite3"))
    assert not list(destination.rglob("cookies*"))
    for _, source, original in saved_site:
        assert source.read_bytes() == original
    # Repeating a command never overwrites an existing export or original bytes.
    original_export = homepage.read_bytes()
    with pytest.raises(CommandError, match="File exists"):
        call_command("site_export", scope="news.ycombinator.com", format="html", destination=str(destination))
    assert homepage.read_bytes() == original_export


def test_site_export_ui_requires_absolute_server_path(admin_client, saved_site):
    crawl = saved_site[0][0].crawl
    crawl.tags_str = "site-clone"
    crawl.save(update_fields=["tags_str"])
    detail = f"/admin/domains/{crawl.pk}/"
    response = admin_client.post(detail + "export/", {"format": "html", "directory": "relative/path"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 400
    assert b"absolute server directory" in response.content
    from archivebox.machine.models import Process

    assert not Process.objects.filter(worker_type="site-export").exists()
    page = admin_client.get(detail + "export/", HTTP_HOST=ADMIN_TEST_HOST)
    assert page.status_code == 200
    assert page["Content-Type"] == "application/json"
    assert page.json() == {"format": "html_zip", "query": "domain=example.com", "count": 0, "jobs": []}


def test_replay_setting_uses_machine_config(admin_client, saved_site):
    from archivebox.config.collection import _load_file_config_dict
    from archivebox.config.common import get_config
    from archivebox.machine.models import Machine

    crawl = saved_site[0][0].crawl
    crawl.tags_str = "site-clone"
    crawl.save(update_fields=["tags_str"])
    endpoint = f"/admin/domains/{crawl.pk}/replay-settings/"
    before = dict(Machine.current().config)
    for enabled in (True, False):
        response = admin_client.post(endpoint, {"rewrite_archived_links": "on"} if enabled else {}, HTTP_HOST=ADMIN_TEST_HOST)
        assert response.status_code == 302
        assert response.url == "/admin/domains/"
        assert get_config().REWRITE_ARCHIVED_LINKS is enabled
        assert Machine.current().config == {**before, "REWRITE_ARCHIVED_LINKS": enabled}
        file_config, _mtime = _load_file_config_dict()
        assert file_config["REWRITE_ARCHIVED_LINKS"].lower() == str(enabled).lower()


def test_static_zip_export_and_size_limit_use_saved_pages(saved_site, tmp_path):
    import zipfile

    destination = tmp_path / "zip-export"
    call_command("site_export", scope="news.ycombinator.com", format="html_zip", destination=str(destination), max_bytes=4 * 1024**3)
    assert [item.name for item in destination.iterdir()] == ["site.zip"]
    with zipfile.ZipFile(destination / "site.zip") as archive:
        assert "index.html" in archive.namelist()
        manifest = json.loads(archive.read("pages.json"))
        assert len(manifest) == len(saved_site)
        assert b"archivebox-links.js" in archive.read(manifest[0]["path"])
        assert b"newest" in archive.read("archivebox-links.js")
    with pytest.raises(CommandError, match="exceeds"):
        call_command("site_export", scope="news.ycombinator.com", format="html_zip", destination=str(tmp_path / "limited"), max_bytes=100)
    assert not (tmp_path / "limited/site.zip").exists()
    for _, source, original in saved_site:
        assert source.read_bytes() == original


def test_static_export_preserves_non_utf8_capture_bytes(saved_site, tmp_path):
    snapshot, source, _original = saved_site[0]
    # A saved page's declared charset and bytes must survive URL rewriting.
    body = (
        b'<!doctype html><html><head><meta charset="windows-1252"></head><body>Encoded: \xe9 \x97 <a href="/newest">new</a></body></html>'
    )
    source.write_bytes(body)
    destination = tmp_path / "encoded-export"
    call_command("site_export", scope="news.ycombinator.com", format="html", destination=str(destination))
    output = destination / "pages" / str(snapshot.pk) / "dom/output.html"
    assert b'charset="windows-1252"' in output.read_bytes()
    assert b"Encoded: \xe9 \x97" in output.read_bytes()
    assert b"archivebox-links.js" in output.read_bytes()
    assert source.read_bytes() == body


@pytest.mark.parametrize("format", ["html_zip", "wacz"])
def test_final_archive_size_limit_removes_oversized_output(crawl, tmp_path, format):
    from pathlib import Path

    from archivebox.core.models import ArchiveResult, Snapshot

    snapshot = Snapshot.objects.create(url="https://example.com/", crawl=crawl)
    if format == "wacz":
        body = (Path(__file__).parent / "fixtures/memento/iframetest.wacz").read_bytes()
        plugin, relative = "archivewebpage", "archivewebpage/archive.wacz"
    else:
        body = b"<!doctype html><title>Saved page</title>" + b"".join(
            f'<link rel="stylesheet" href="style-{index}.css">'.encode() for index in range(10)
        )
        plugin, relative = "dom", "dom/output.html"
    source = snapshot.output_dir / relative
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(body)
    if format == "html_zip":
        for index in range(10):
            (source.parent / f"style-{index}.css").write_bytes(b".a{}")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin=plugin,
        status="succeeded",
        output_str=relative,
        output_files={relative: {"size": len(body)}},
        output_size=len(body),
    )
    # First measure genuine rewritten pages/recordings, then exercise packaging
    # overhead that takes the finished archive beyond that payload budget.
    directory = tmp_path / "baseline"
    call_command("site_export", scope="example.com", format="html" if format == "html_zip" else "wacz", destination=str(directory))
    limit = sum(path.stat().st_size for path in (directory / "pages").rglob("*") if path.is_file()) if format == "html_zip" else len(body)
    limited = tmp_path / "limited"
    with pytest.raises(CommandError, match=rf"{limit} bytes"):
        call_command("site_export", scope="example.com", format=format, destination=str(limited), max_bytes=limit)
    assert not (limited / ("site.zip" if format == "html_zip" else "site.wacz")).exists()
    assert source.read_bytes() == body


def test_domain_delete_uses_native_confirmation_then_queues(admin_client, saved_site):
    from archivebox.core.models import Snapshot

    ids = [str(snapshot.pk) for snapshot, _, _ in saved_site]
    endpoint = "/admin/core/snapshot/?domain=*.news.ycombinator.com"
    selection = {"action": "delete_selected", "select_across": "1", "_selected_action": ["*.news.ycombinator.com"]}
    preview = admin_client.post(endpoint, selection, HTTP_HOST=ADMIN_TEST_HOST)
    assert preview.status_code == 200
    assert any(template.name == "admin/delete_selected_confirmation.html" for template in preview.templates)
    assert Snapshot.objects.filter(pk__in=ids, status="deleting").count() == 0
    assert all(source.read_bytes() == original for _, source, original in saved_site)
    confirmed = admin_client.post(endpoint, {**selection, "post": "yes"}, HTTP_HOST=ADMIN_TEST_HOST)
    assert confirmed.status_code == 302
    assert Snapshot.objects.filter(pk__in=ids, status="deleting").count() == len(ids)
    assert all(source.read_bytes() == original for _, source, original in saved_site)


@pytest.mark.parametrize("format", ["html_zip", "wacz"])
def test_query_export_uses_folder_subtree_and_preserves_sources(saved_site, tmp_path, format):
    from pathlib import Path
    from urllib.parse import urlencode
    import zipfile

    from archivebox.core.models import ArchiveResult, Folder

    folder = Folder.objects.create(name="Reading")
    child = Folder.objects.create(name="Articles", parent=folder)
    unrelated = Folder.objects.create(name="Elsewhere")
    selected = saved_site[:2]
    for index, (snapshot, _source, _body) in enumerate(saved_site):
        snapshot.folder = [folder, child][index] if index < 2 else unrelated
        snapshot.config = {**snapshot.config, "PERMISSIONS": ("private", "unlisted", "public")[index]}
        snapshot.save(update_fields=["folder", "config"])
    recordings = []
    if format == "wacz":
        fixtures = Path(__file__).parent / "fixtures"
        for index, (snapshot, _source, _body) in enumerate(saved_site):
            recording = (fixtures / ("memento/iframetest.wacz" if index != 1 else "responsive-images/google-drive.wacz")).read_bytes()
            relative = "archivewebpage/archive.wacz"
            output = snapshot.output_dir / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(recording)
            ArchiveResult.objects.create(
                snapshot=snapshot,
                plugin="archivewebpage",
                status="succeeded",
                output_str=relative,
                output_files={relative: {"size": len(recording)}},
                output_size=len(recording),
            )
            if index < 2:
                recordings.append(recording)
    destination = tmp_path / "folder-export"
    call_command("site_export", query=urlencode({"folder": str(folder.pk)}), format=format, destination=str(destination))
    with zipfile.ZipFile(destination / ("site.zip" if format == "html_zip" else "site.wacz")) as archive:
        if format == "html_zip":
            manifest = json.loads(archive.read("pages.json"))
            assert {page["url"] for page in manifest} == {snapshot.url for snapshot, _, _ in selected}
        else:
            package = json.loads(archive.read("datapackage.json"))
            assert len(package["resources"]) == 2
            assert {archive.read(resource["path"]) for resource in package["resources"]} == set(recordings)
    for _snapshot, source, original in saved_site:
        assert source.read_bytes() == original
    limited = tmp_path / "limited-folder-export"
    with pytest.raises(CommandError, match="exceeds"):
        call_command("site_export", query=urlencode({"folder": str(folder.pk)}), format=format, destination=str(limited), max_bytes=100)
    assert not (limited / ("site.zip" if format == "html_zip" else "site.wacz")).exists()


def test_query_export_combines_native_filters_and_public_visibility(saved_site, tmp_path):
    from urllib.parse import urlencode
    import zipfile
    from archivebox.core.models import Folder

    folder = Folder.objects.create(name="Reading")
    child = Folder.objects.create(name="Articles", parent=folder)
    for snapshot, _source, _body in saved_site:
        snapshot.folder = child
        snapshot.save(update_fields=["folder"])
    query = urlencode({"folder": str(folder.pk), "domain": "news.ycombinator.com", "q": "newest", "search_mode": "meta"})
    destination = tmp_path / "filtered"
    call_command("site_export", query=query, public_only=True, format="html_zip", destination=str(destination))
    with zipfile.ZipFile(destination / "site.zip") as archive:
        assert [page["url"] for page in json.loads(archive.read("pages.json"))] == ["https://news.ycombinator.com/newest"]
    snapshot = next(snapshot for snapshot, _, _ in saved_site if snapshot.url.endswith("/newest"))
    snapshot.config = {**snapshot.config, "PERMISSIONS": "private"}
    snapshot.save(update_fields=["config"])
    with pytest.raises(CommandError, match="No snapshots match these filters"):
        call_command("site_export", query=query, public_only=True, format="html_zip", destination=str(tmp_path / "private"))
    assert not (tmp_path / "private/site.zip").exists()


def test_archive_job_api_exports_selected_files_and_revokes_public_download(initialized_archive):
    from pathlib import Path
    from archivebox.tests.conftest import run_python_cwd

    fixture = Path(__file__).parent / "fixtures/original-domain-replay"
    script = """
import os
from pathlib import Path
os.environ["DATA_DIR"] = str(Path.cwd())
import django
django.setup()
import gzip, hashlib, io, json, zipfile
from urllib.parse import urlencode
from django.contrib.auth import get_user_model
from django.test import Client
from archivebox.api.models import APIToken
from archivebox.core.models import ArchiveResult, Folder, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process

user = get_user_model().objects.create_superuser(username="export-api", password="export-api")
token = APIToken.objects.create(created_by=user)
crawl = Crawl.objects.create(urls="https://news.ycombinator.com/", created_by=user)
root = Folder.objects.create(name="Hacker News", created_by=user)
child = Folder.objects.create(name="Recent", parent=root, created_by=user)
fixture = Path(FIXTURE_PATH)
saved = []
for index, record in enumerate(json.loads((fixture / "captures.json").read_text())):
    body = gzip.decompress((fixture / record["file"]).read_bytes())
    assert hashlib.sha256(body).hexdigest() == record["sha256"]
    snapshot = Snapshot.objects.create(url=record["url"], crawl=crawl, folder=child, config={"PERMISSIONS": ("public", "unlisted", "private")[index]})
    output = snapshot.output_dir / "dom/output.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(body)
    ArchiveResult.objects.create(snapshot=snapshot, plugin="dom", hook_name="on_Snapshot__53_dom.js", status="succeeded", output_str="dom/output.html", output_files={"dom/output.html": {"size": len(body), "mimetype": "text/html"}}, output_size=len(body))
    saved.append((snapshot, output, body))
client = Client(HTTP_HOST="api.archivebox.localhost:5797")
headers = {"HTTP_X_ARCHIVEBOX_API_KEY": token.token}
query = urlencode({"folder": str(root.pk)})
response = client.post("/api/v1/core/snapshots/export/html_zip", json.dumps({"query": query, "directory": str(Path.cwd() / "exports")}), content_type="application/json", **headers)
assert response.status_code == 202, response.content
job = response.json()
process = Process.objects.get(pk=job["id"])
assert token.token not in " ".join(process.cmd)
assert "--query" in process.cmd and "--user" in process.cmd
assert process.cmd[process.cmd.index("--max-bytes") + 1] == str(4 * 1024**3)
assert process.wait(timeout=30) == 0, process.stderr_file.read_text()
status = client.get(job["status_url"], **headers)
assert status.status_code == 200, status.content
assert status.json()["result"]["complete"] is True
assert Path(status.json()["result"]["destination"]).is_absolute()
assert client.get(job["download_url"]).status_code == 403
response = client.get(job["download_url"], **headers)
assert response.status_code == 200
with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as bundle:
    pages = json.loads(bundle.read("pages.json"))
    assert {page["url"] for page in pages} == {snapshot.url for snapshot, _, _ in saved}
    assert b"archivebox-links.js" in bundle.read(pages[0]["path"])
response.close()
# Public jobs use the same worker and become unavailable after visibility changes.
response = client.post("/api/v1/core/snapshots/export/html_zip", json.dumps({"query": query}), content_type="application/json")
assert response.status_code == 202, response.content
public = response.json()
process = Process.objects.get(pk=public["id"])
assert "--public-only" in process.cmd and "--user" not in process.cmd
assert process.wait(timeout=30) == 0, process.stderr_file.read_text()
response = client.get(public["download_url"])
assert response.status_code == 200
with zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content))) as bundle:
    assert [page["url"] for page in json.loads(bundle.read("pages.json"))] == [saved[0][0].url]
response.close()
Snapshot.objects.filter(pk=saved[0][0].pk).update(config={"PERMISSIONS": "private"})
response = client.get(public["download_url"])
assert response.status_code == 409, response.content
for snapshot, output, body in saved:
    assert output.read_bytes() == body
print("archive-job-api-ok")
""".replace("FIXTURE_PATH", repr(str(fixture)))
    stdout, stderr, returncode = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert returncode == 0, stderr + stdout
    assert "archive-job-api-ok" in stdout


@pytest.mark.parametrize("format", ["rss", "csv", "jsonl"])
def test_domain_metadata_export_uses_shared_native_selection(admin_client, saved_site, format):
    import csv
    import io
    from xml.etree import ElementTree
    from archivebox.machine.models import Process

    payload = {"action": "export", "domain": "news.ycombinator.com/newest", "export_format": format}
    response = admin_client.post("/admin/domains/actions/", payload, HTTP_HOST=ADMIN_TEST_HOST)
    assert response.status_code == 200, response.content
    if format == "rss":
        urls = [
            item.findtext("description").splitlines()[0].removeprefix("Original URL: ")
            for item in ElementTree.fromstring(response.content).findall("channel/item")
        ]
    elif format == "csv":
        urls = [row["url"] for row in csv.DictReader(io.StringIO(response.content.decode()))]
    else:
        urls = [json.loads(line)["url"] for line in response.content.decode().splitlines()]
    assert urls == ["https://news.ycombinator.com/newest"]
    assert not Process.objects.filter(worker_type="site-export").exists()


def test_archive_digest_tracks_consumed_selection_when_folder_membership_changes(saved_site, tmp_path):
    from archivebox.core.exports import selection_digest
    from archivebox.core.models import Folder, Snapshot
    from archivebox.domains.exports import export_snapshots_to_directory

    first, second = (snapshot for snapshot, _, _ in saved_site[:2])
    folder = Folder.objects.create(name="Export selection", created_by=first.crawl.created_by)
    Snapshot.objects.filter(pk=first.pk).update(folder=folder)
    entered = False
    left = False

    def progress(state):
        nonlocal entered, left
        if not entered:
            Snapshot.objects.filter(pk=second.pk).update(folder=folder)
            entered = True
        elif state.get("pages") == 1 and not left:
            Snapshot.objects.filter(pk=second.pk).update(folder=None, config={"PERMISSIONS": "private"})
            left = True

    destination = tmp_path / "changing-selection"
    report = export_snapshots_to_directory(
        Snapshot.objects.filter(folder=folder),
        destination=destination,
        format="html",
        progress=progress,
    )
    assert entered and left
    assert {page["url"] for page in json.loads((destination / "pages.json").read_text())} == {first.url, second.url}
    assert report["selection_digest"] == selection_digest(Snapshot.objects.filter(pk__in=[first.pk, second.pk]))
    assert report["selection_digest"] != selection_digest(Snapshot.objects.filter(folder=folder))


def test_native_static_zip_keeps_all_snapshots_outputs_and_portable_details(saved_site, tmp_path):
    import shutil
    import subprocess
    import zipfile
    from pathlib import Path

    from archivebox.core.models import ArchiveResult, Snapshot

    first = saved_site[0][0]
    image = Path(__file__).parent / "fixtures/redirected-image/image.png"
    from archivebox.crawls.models import Crawl

    other_crawl = Crawl.objects.create(urls=first.url, created_by=first.crawl.created_by)
    second = Snapshot.objects.create(url=first.url, crawl=other_crawl, config={"PERMISSIONS": "public"})
    saved_image = second.output_dir / "staticfile/image.png"
    saved_image.parent.mkdir(parents=True)
    shutil.copyfile(image, saved_image)
    ArchiveResult.objects.create(
        snapshot=second,
        plugin="staticfile",
        status="succeeded",
        output_str="image.png",
        output_files={"image.png": {"size": image.stat().st_size, "mimetype": "image/png"}},
    )
    # Preserve real repository metadata, including hidden paths in saved Git output.
    repo = tmp_path / "repository"
    subprocess.run(["git", "init", str(repo)], cwd=tmp_path, check=True, capture_output=True)
    git_head = repo / ".git/HEAD"
    saved_head = first.output_dir / "git/.git/HEAD"
    saved_head.parent.mkdir(parents=True)
    shutil.copyfile(git_head, saved_head)
    (first.output_dir / "outside.png").symlink_to(image.resolve())
    first.config = {**first.config, "PRIVATE_SETTING": "private-config-value"}
    first.notes = "private-note-value"
    first.save(update_fields=["config", "notes"])
    first.write_index_jsonl()
    operational_manifest = (first.output_dir / "index.jsonl").read_bytes()
    assert b"private-config-value" in operational_manifest
    destination = tmp_path / "portable"
    call_command("site_export", query=f"id__in={first.pk},{second.pk}", format="html_zip", destination=str(destination))
    with zipfile.ZipFile(destination / "site.zip") as archive:
        records = [json.loads(line) for line in archive.read("index.jsonl").splitlines()]
        assert {record["id"] for record in records} == {str(first.pk), str(second.pk)}
        for snapshot in (first, second):
            relative = snapshot.static_archive_path
            assert f"./{relative}/index.html".encode() in archive.read("index.html")
            details = archive.read(f"{relative}/index.html").decode()
            assert 'class="thumb-card' in details
            assert str(snapshot.output_dir) not in details
            assert "/admin/" not in details
            assert f"{relative}/index.jsonl" in archive.namelist()
            metadata = json.loads(archive.read(f"{relative}/index.jsonl"))
            assert "config" not in metadata and "notes" not in metadata
            assert b"private-config-value" not in archive.read(f"{relative}/index.jsonl")
            assert "private-note-value" not in details
            assert f"{relative}/index.json" not in archive.namelist()
        assert archive.read(f"{second.static_archive_path}/staticfile/image.png") == image.read_bytes()
        assert archive.read(f"{first.static_archive_path}/git/.git/HEAD") == git_head.read_bytes()
        assert f"{first.static_archive_path}/outside.png" not in archive.namelist()
        assert archive.read(f"{first.static_archive_path}/dom/output.html") == saved_site[0][2]
        for snapshot, _, _ in saved_site[1:]:
            assert f"{snapshot.static_archive_path}/index.html" not in archive.namelist()
    assert saved_image.read_bytes() == image.read_bytes()
    assert saved_head.read_bytes() == git_head.read_bytes()
    assert (first.output_dir / "index.jsonl").read_bytes() == operational_manifest


def test_native_static_export_accepts_snapshot_without_html(snapshot, tmp_path):
    import shutil
    from pathlib import Path

    from archivebox.core.models import ArchiveResult

    image = Path(__file__).parent / "fixtures/redirected-image/image.png"
    output = snapshot.output_dir / "screenshot/screenshot.png"
    output.parent.mkdir(parents=True)
    shutil.copyfile(image, output)
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="screenshot",
        status="succeeded",
        output_str="screenshot.png",
        output_files={"screenshot.png": {"size": image.stat().st_size, "mimetype": "image/png"}},
    )
    destination = tmp_path / "images"
    call_command("site_export", query=f"id={snapshot.pk}", format="html", destination=str(destination))
    assert (destination / snapshot.static_archive_path / "screenshot/screenshot.png").read_bytes() == image.read_bytes()
    assert 'class="thumb-card' in (destination / snapshot.static_archive_path / "index.html").read_text()
    assert json.loads((destination / "pages.json").read_text()) == []
