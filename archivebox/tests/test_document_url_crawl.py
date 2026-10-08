"""Real CLI recursion from a downloaded workbook, including labeled hyperlinks."""

import io
import zipfile
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("depth", [0, 1])
def test_workbook_links_are_archived_at_requested_depth(initialized_archive, httpserver, depth):
    root_url = httpserver.url_for("/links.xlsx")
    visible_url = httpserver.url_for("/visible")
    labeled_url = httpserver.url_for("/labeled")
    deeper_url = httpserver.url_for("/too-deep")
    workbook = io.BytesIO()
    with zipfile.ZipFile(workbook, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Links" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>{visible_url}</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>Labeled link</t></is></c></row></sheetData>'
            '<hyperlinks><hyperlink ref="A2" r:id="rId1"/></hyperlinks></worksheet>',
        )
        archive.writestr(
            "xl/worksheets/_rels/sheet1.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{labeled_url}" TargetMode="External"/>'
            "</Relationships>",
        )
    httpserver.expect_request("/links.xlsx").respond_with_data(
        workbook.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    for path in ("/visible", "/labeled"):
        httpserver.expect_request(path).respond_with_data(
            f'<html><body>Archived workbook target {path}<a href="{deeper_url}">Next level</a></body></html>',
            content_type="text/html",
        )
    result = run_archivebox_cmd(
        ["add", f"--depth={depth}", "--plugins=wget,parse_txt_urls", root_url],
        cwd=initialized_archive,
        env=cli_env(USE_CHROME="False", SAVE_WARC="False", URL_ALLOWLIST=r"localhost[:/].*"),
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with use_archivebox_db(initialized_archive):
        snapshots = list(Snapshot.objects.order_by("depth").values("id", "url", "depth", "parent_snapshot_id", "status", "downloaded_at"))
        results = list(ArchiveResult.objects.values("snapshot__url", "plugin", "status", "output_size"))
        directories = {snapshot.url: Path(snapshot.output_dir) for snapshot in Snapshot.objects.all()}
    expected = {root_url} if depth == 0 else {root_url, visible_url, labeled_url}
    assert {snapshot["url"] for snapshot in snapshots} == expected
    assert all(snapshot["status"] == "sealed" and snapshot["downloaded_at"] for snapshot in snapshots)
    root = next(snapshot for snapshot in snapshots if snapshot["url"] == root_url)
    assert root["depth"] == 0
    for child in (snapshot for snapshot in snapshots if snapshot["url"] != root_url):
        assert child["depth"] == 1
        assert child["parent_snapshot_id"] == root["id"]
        assert any(
            row["snapshot__url"] == child["url"] and row["plugin"] == "wget" and row["status"] == "succeeded" and row["output_size"] > 0
            for row in results
        )
        assert any(
            "Archived workbook target" in file.read_text(errors="replace") for file in (directories[child["url"]] / "wget").rglob("*.html")
        )
    assert any(file.read_bytes() == workbook.getvalue() for file in (directories[root_url] / "wget").rglob("*.xlsx"))


def test_live_google_sheet_depth_one(initialized_archive, browser_runtime):
    """Export a public Sheet, discover its link, and archive the linked page."""
    source = "https://docs.google.com/spreadsheets/d/13QQinPFhU9DwujctXS0A7un0up4N5BNyUDZwxK4I6hg/edit"
    target = "https://github.com/kmario23/deep-learning-drizzle"
    result = run_archivebox_cmd(
        ["add", "--depth=1", "--plugins=googledocs,wget,parse_txt_urls", source],
        cwd=initialized_archive,
        env=cli_env(
            ABXPKG_LIB_DIR=str(browser_runtime["lib_dir"]),
            CHROME_BINARY=str(browser_runtime["chrome_binary"]),
            CHROME_HEADLESS="True",
            GOOGLEDOCS_FORMATS='["xlsx"]',
            SAVE_WARC="False",
            URL_ALLOWLIST=r"docs\.google\.com/spreadsheets/d/13QQinPFhU9DwujctXS0A7un0up4N5BNyUDZwxK4I6hg/|github\.com/kmario23/deep-learning-drizzle$",
        ),
        timeout=240,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    with use_archivebox_db(initialized_archive):
        snapshots = {snapshot.url: snapshot for snapshot in Snapshot.objects.all()}
        directories = {url: Path(snapshot.output_dir) for url, snapshot in snapshots.items()}
        results = list(ArchiveResult.objects.values("snapshot__url", "plugin", "status", "output_size"))
    assert set(snapshots) == {source, target}
    assert snapshots[source].depth == 0
    assert snapshots[target].depth == 1
    assert snapshots[target].parent_snapshot_id == snapshots[source].id
    assert all(snapshot.status == "sealed" and snapshot.downloaded_at for snapshot in snapshots.values())
    for url, plugin in ((source, "googledocs"), (source, "parse_txt_urls"), (target, "wget")):
        assert any(
            row["snapshot__url"] == url and row["plugin"] == plugin and row["status"] == "succeeded" and row["output_size"] > 0
            for row in results
        ), results
    with zipfile.ZipFile(directories[source] / "googledocs/document.xlsx") as workbook:
        assert "xl/workbook.xml" in workbook.namelist()
    assert any("deep-learning-drizzle" in file.read_text(errors="replace") for file in (directories[target] / "wget").rglob("*.html"))
