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
    assert response.status_code == 302
    assert not Process.objects.filter(worker_type="site-export").exists()
    result = admin_client.get(response["Location"], HTTP_HOST=ADMIN_TEST_HOST)
    assert b"absolute server directory" in result.content


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
    assert response.status_code == 302
    from archivebox.machine.models import Process

    assert not Process.objects.filter(worker_type="site-export").exists()
    page = admin_client.get(response["Location"], HTTP_HOST=ADMIN_TEST_HOST)
    assert b"absolute server directory" in page.content
    assert b"Export to disk" in page.content
    assert b"Server directory" in page.content
    assert response["Location"] == detail + "export/"


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
