# ci-runner: hosted
"""Capture-to-Readability integration with a real ArchiveWeb.page WACZ."""

import zipfile
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import cli_env, run_archivebox_cmd
from archivebox.tests.test_orm_helpers import use_archivebox_db


@pytest.mark.django_db(transaction=True)
@pytest.mark.timeout(600, func_only=True)
def test_archivewebpage_capture_supplies_readability_without_other_html_producers(
    initialized_archive: Path,
    browser_runtime,
    httpserver_ipv4,
) -> None:
    """The real runner must make the stopped WACZ available to Readability."""

    from warcio.archiveiterator import ArchiveIterator

    marker = "The tide gauges recorded a sustained rise across the southern harbor."
    passage = f"{marker} Researchers compared twelve years of observations with the local weather station to separate seasonal effects from the long-term trend."
    html = (
        '<!doctype html><html lang="en"><head><title>Harbor field report</title></head><body>'
        "<nav>Home | About | Contact</nav><main><article><h1>Harbor field report</h1>"
        + "".join(f"<p>{passage}</p>" for _ in range(6))
        + "</article></main></body></html>"
    )
    httpserver_ipv4.expect_request("/article").respond_with_data(html, content_type="text/html; charset=utf-8")
    httpserver_ipv4.expect_request("/favicon.ico").respond_with_data("", status=204)
    url = httpserver_ipv4.url_for("/article")
    lib_dir = browser_runtime["lib_dir"]
    selection = "archivewebpage,readability"
    env = cli_env(
        PLUGINS=selection,
        URL_ALLOWLIST=r"127\.0\.0\.1[:/].*",
        ARCHIVEDOTORG_ENABLED="False",
        ABXPKG_LIB_DIR=str(lib_dir),
        NODE_PATH=str(browser_runtime["node_path"]),
        NODE_MODULES_DIR=str(browser_runtime["node_modules_dir"]),
        CHROMEWEBSTORE_EXTENSIONS_DIR=str(lib_dir / "chromewebstore" / "extensions"),
        CHROME_BINARY=str(browser_runtime["chrome_binary"]),
        CHROME_HEADLESS="True",
        CHROME_ISOLATION="snapshot",
        ARCHIVEWEBPAGE_ENABLED="True",
        READABILITY_ENABLED="True",
        # Explicitly disable DOM so the catalog selects Readability's declared
        # ArchiveWeb.page fallback instead of pulling DOM in as a dependency.
        DOM_ENABLED="False",
    )
    result = run_archivebox_cmd(
        ["install", "archivewebpage", "readability"],
        cwd=initialized_archive,
        env=env,
        timeout=300,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    result = run_archivebox_cmd(
        ["add", "--depth=0", "--max-urls=1", f"--plugins={selection}", url],
        cwd=initialized_archive,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    assert "total urls snapshotted: 1" in result.stdout, f"{result.stdout}\n{result.stderr}"

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get(url=url)
        assert snapshot.status == Snapshot.StatusChoices.SEALED
        results = snapshot.archiveresult_set
        assert not results.filter(plugin="dom").exists()
        recording = results.get(hook_name="on_Snapshot__65_archivewebpage_stop")
        assert recording.status == ArchiveResult.StatusChoices.SUCCEEDED, recording.output_str
        readability = results.get(hook_name="on_Snapshot__66_readability")
        assert readability.status == ArchiveResult.StatusChoices.SUCCEEDED, readability.output_str
        output_dir = Path(snapshot.output_dir)

    with zipfile.ZipFile(output_dir / "archivewebpage/archivewebpage.wacz") as archive:
        assert archive.testzip() is None
        archived_pages = []
        for name in archive.namelist():
            if not name.startswith("archive/") or not name.endswith(".warc.gz"):
                continue
            with archive.open(name) as stream:
                for record in ArchiveIterator(stream):
                    if record.rec_type == "response" and record.rec_headers.get_header("WARC-Target-URI") == url:
                        archived_pages.append(record.content_stream().read())
    assert any(marker.encode() in page for page in archived_pages)
    wacz_input = "readability/.wacz-article-input.html"
    assert (output_dir / wacz_input).read_text() in [page.decode("utf-8", errors="replace") for page in archived_pages]
    assert marker in (output_dir / "readability/content.txt").read_text()
    # The consumer materializes a private copy of the verified WARC input.
    # Allow that and the app index, not a different producer's HTML.
    assert {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*.html")} <= {
        "index.html",
        "readability/content.html",
        wacz_input,
    }
    assert not list(output_dir.rglob("*.mhtml"))
