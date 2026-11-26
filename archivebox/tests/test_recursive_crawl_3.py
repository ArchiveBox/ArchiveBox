#!/usr/bin/env python3
"""Integration tests for recursive crawling functionality."""

import json
import os
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Binary, Process
from archivebox.tests.conftest import run_archivebox_cmd, cli_env
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def run_add_until(args, env, condition, timeout=120):
    assert args[0] == "archivebox"
    result = run_archivebox_cmd(
        args[1:],
        cwd=Path.cwd(),
        env=env,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    with use_archivebox_db("."):
        assert condition(), f"Condition was false after command completed: {' '.join(args)}"
    return result.stdout, result.stderr


def test_background_hooks_dont_block_parser_extractors(tmp_path, initialized_archive, recursive_test_site):
    """Test that background hooks (.bg.) don't block other extractors from running."""

    # Verify the initialized_archive fixture prepared the expected data dir.
    assert initialized_archive == tmp_path
    assert (initialized_archive / "index.sqlite3").exists()

    # Enable only parser extractors and background hooks for this test
    env = os.environ.copy()
    env.update(
        {
            # Disable most extractors
            "SAVE_WGET": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_MERCURY": "false",
            "SAVE_HTMLTOTEXT": "false",
            "SAVE_PDF": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_DOM": "false",
            "SAVE_HEADERS": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_TITLE": "false",
            "SAVE_FAVICON": "true",
        },
    )

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--depth=1", "--plugins=favicon,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda: ArchiveResult.objects.filter(
            plugin__startswith="parse_",
            plugin__endswith="_urls",
            status__in=("started", "succeeded", "failed"),
        ).exists(),
    )

    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 2000 chars) ===\n{stdout[-2000:]}\n=== END STDOUT ===\n")

    with use_archivebox_db(tmp_path):
        snapshots = list(Snapshot.objects.values_list("url", "depth", "status"))
        bg_hooks = list(
            ArchiveResult.objects.filter(plugin__in=("favicon", "consolelog", "ssl", "responses", "redirects", "staticfile"))
            .order_by("plugin")
            .values_list("plugin", "status"),
        )
        parser_extractors = list(
            ArchiveResult.objects.filter(plugin__startswith="parse_", plugin__endswith="_urls")
            .order_by("plugin")
            .values_list("plugin", "status"),
        )
        all_extractors = list(ArchiveResult.objects.order_by("plugin").values_list("plugin", "status"))

    assert len(snapshots) > 0, (
        f"Should have created snapshot after Crawl hooks finished. "
        f"If this fails, Crawl hooks may be taking too long. "
        f"Snapshots: {snapshots}"
    )

    assert len(all_extractors) > 0, (
        f"Should have extractors created for snapshot. If this fails, Snapshot.run() may not have started. Got: {all_extractors}"
    )

    parser_statuses = [status for _, status in parser_extractors]
    assert "started" in parser_statuses or "succeeded" in parser_statuses or "failed" in parser_statuses, (
        f"Parser extractors should have run, got statuses: {parser_statuses}. Background hooks: {bg_hooks}"
    )


def test_recursive_crawl_respects_depth_limit(initialized_archive, recursive_test_site):
    root_url = recursive_test_site["root_url"]
    children = recursive_test_site["child_urls"]
    result = run_archivebox_cmd(
        ["add", "--depth=1", "--plugins=wget,parse_html_urls", root_url],
        cwd=initialized_archive,
        env=cli_env(live=True, URL_ALLOWLIST=r"127\.0\.0\.1[:/].*"),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        snapshots = {snapshot.url: snapshot for snapshot in Snapshot.objects.all()}
        assert snapshots.keys() == {root_url, *children}
        root = snapshots[root_url]
        assert root.depth == 0
        for url in children:
            child = snapshots[url]
            assert child.depth == 1
            assert child.parent_snapshot_id == root.id
            assert child.status == Snapshot.StatusChoices.SEALED
            assert child.archiveresult_set.get(plugin="parse_html_urls").status == ArchiveResult.StatusChoices.SUCCEEDED


def test_recursive_crawl_depth_two_writes_real_outputs_and_process_records(initialized_archive, recursive_test_site):
    """Follow the site's links and verify the saved pages and concurrent hooks."""
    root_url = recursive_test_site["root_url"]
    children = recursive_test_site["child_urls"]
    grandchildren = recursive_test_site["deep_urls"]
    expected_parents = {
        root_url: None,
        **dict.fromkeys(children, root_url),
        **dict(zip(grandchildren, children, strict=True)),
    }
    max_urls = len(expected_parents) + 1
    # The fetch and link parser exercise the actual crawl graph. Each extractor's
    # output and provider-specific behavior already has its own integration tests.
    result = run_archivebox_cmd(
        [
            "add",
            "--depth=2",
            f"--max-urls={max_urls}",
            "--crawl-max-size=100mb",
            "--tag=recursive-crawl",
            "--plugins=wget,parse_html_urls",
            root_url,
        ],
        cwd=initialized_archive,
        env=cli_env(live=True, URL_ALLOWLIST=r"127\.0\.0\.1[:/].*", CRAWL_MAX_CONCURRENT_SNAPSHOTS="3"),
        timeout=240,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get(tags_str="recursive-crawl")
        assert crawl.max_depth == 2
        assert crawl.status == Crawl.StatusChoices.SEALED
        assert crawl.retry_at is None
        assert crawl.config["CRAWL_MAX_URLS"] == max_urls
        assert crawl.config["CRAWL_MAX_SIZE"] == 100 * 1024 * 1024
        assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 3
        snapshots = {snapshot.url: snapshot for snapshot in Snapshot.objects.filter(crawl=crawl)}
        assert snapshots.keys() == expected_parents.keys()
        for url, parent_url in expected_parents.items():
            snapshot = snapshots[url]
            assert snapshot.depth == (0 if parent_url is None else snapshots[parent_url].depth + 1)
            assert snapshot.parent_snapshot_id == (snapshots[parent_url].id if parent_url else None)
            assert snapshot.status == Snapshot.StatusChoices.SEALED
            assert snapshot.downloaded_at is not None
            wget = snapshot.archiveresult_set.get(plugin="wget")
            assert wget.status == ArchiveResult.StatusChoices.SUCCEEDED
            assert wget.output_size > 0
            assert (snapshot.output_dir / "index.jsonl").is_file()
            pages = list((snapshot.output_dir / "wget").rglob("*.html"))
            assert any(b"<html" in page.read_bytes() for page in pages), url
            if url == root_url:
                assert any(b"<title>Root</title>" in page.read_bytes() for page in pages)

        for parent_url in [root_url, *children]:
            snapshot = snapshots[parent_url]
            parser = snapshot.archiveresult_set.get(plugin="parse_html_urls")
            assert parser.status == ArchiveResult.StatusChoices.SUCCEEDED
            assert "parsed" in parser.output_str.lower()
            lines = (snapshot.output_dir / "parse_html_urls" / "urls.jsonl").read_text().splitlines()
            records = [json.loads(line) for line in lines if line.strip()]
            assert records and all(record["type"] == "Snapshot" for record in records)
            assert {url for url, parent in expected_parents.items() if parent == parent_url} <= {record["url"] for record in records}

        processes = Process.objects.filter(process_type=Process.TypeChoices.HOOK, archiveresult__snapshot__crawl=crawl)
        assert processes.exists()
        assert all(process.status == Process.StatusChoices.EXITED for process in processes)
        intervals = list(processes.values_list("archiveresult__snapshot_id", "started_at", "ended_at").distinct())

    assert any(
        left_id != right_id and left_start < right_end and right_start < left_end
        for index, (left_id, left_start, left_end) in enumerate(intervals)
        for right_id, right_start, right_end in intervals[index + 1 :]
        if left_start and left_end and right_start and right_end
    ), intervals


@pytest.mark.timeout(1200)
def test_add_archivewebpage_installs_required_chrome_dependency(initialized_archive):
    """archivebox add should resolve selected plugins' required plugins and persist binary projections."""

    env = os.environ.copy()
    env.pop("CHROME_BINARY", None)
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "TIMEOUT": "120",
            "ABXPKG_LIB_DIR": str(initialized_archive / "lib"),
            "CHROME_HEADLESS": "true",
            "CHROME_SANDBOX": "false",
            "CHROME_ISOLATION": "snapshot",
            "CHROMEWEBSTORE_EXTENSIONS_DIR": str(initialized_archive / "lib/chromewebstore/extensions"),
        },
    )

    result = run_archivebox_cmd(
        [
            "add",
            "--depth=0",
            "--max-urls=1",
            "--tag=archivewebpage-required-plugin-preflight",
            "--parser=url_list",
            "--plugins=archivewebpage",
            "https://example.com/",
        ],
        cwd=initialized_archive,
        env=env,
        timeout=1200,
    )
    stdout, stderr = result.stdout, result.stderr

    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 4000 chars) ===\n{stdout[-4000:]}\n=== END STDOUT ===\n")
    assert result.returncode == 0, stderr or stdout

    with use_archivebox_db(initialized_archive):
        binaries = {
            row["name"]: row for row in Binary.objects.order_by("name").values("name", "status", "binprovider", "abspath", "version")
        }
        archive_results = list(
            ArchiveResult.objects.order_by("plugin", "hook_name").values_list(
                "plugin",
                "hook_name",
                "status",
                "output_str",
                "output_files",
            ),
        )
        process_rows = list(
            Process.objects.order_by("process_type", "created_at").values_list("process_type", "status", "exit_code", "cmd", "env"),
        )
        snapshot_output_dirs = [snapshot.output_dir for snapshot in Snapshot.objects.order_by("created_at")]

    assert "chromium" in binaries
    assert binaries["chromium"]["status"] == Binary.StatusChoices.INSTALLED
    assert Path(binaries["chromium"]["abspath"]).exists()
    chromium_version_parts = [int(part) for part in binaries["chromium"]["version"].split(".")[:3]]
    assert chromium_version_parts >= [149, 0, 0]

    assert "archivewebpage" in binaries
    assert binaries["archivewebpage"]["status"] == Binary.StatusChoices.INSTALLED
    assert binaries["archivewebpage"]["binprovider"] == "chromewebstore"
    archivewebpage_metadata = Path(binaries["archivewebpage"]["abspath"])
    assert archivewebpage_metadata.exists()
    assert archivewebpage_metadata.name == "archivewebpage.extension.json"
    archivewebpage_extension = json.loads(archivewebpage_metadata.read_text(encoding="utf-8"))
    archivewebpage_manifest = Path(archivewebpage_extension["unpacked_path"]) / "manifest.json"
    assert archivewebpage_manifest.exists()
    assert json.loads(archivewebpage_manifest.read_text(encoding="utf-8"))["version"] == binaries["archivewebpage"]["version"]

    plugins_seen = {plugin for plugin, _hook_name, _status, _output_str, _output_files in archive_results}
    assert {"chrome", "archivewebpage"}.issubset(plugins_seen)
    archivewebpage_statuses = {
        hook_name: status for plugin, hook_name, status, _output_str, _output_files in archive_results if plugin == "archivewebpage"
    }
    assert archivewebpage_statuses == {
        "on_Snapshot__16_archivewebpage_start": ArchiveResult.StatusChoices.NORESULTS,
        "on_Snapshot__65_archivewebpage_stop": ArchiveResult.StatusChoices.SUCCEEDED,
    }, archive_results
    assert all(
        status == ArchiveResult.StatusChoices.SUCCEEDED
        for plugin, _hook_name, status, _output_str, _output_files in archive_results
        if plugin == "chrome"
    ), archive_results
    assert snapshot_output_dirs
    archivewebpage_wacz = Path(snapshot_output_dirs[0]) / "archivewebpage" / "archivewebpage.wacz"
    assert archivewebpage_wacz.exists()
    assert archivewebpage_wacz.stat().st_size > 0
    chrome_hook_envs = [
        env
        for process_type, _status, _exit_code, cmd, env in process_rows
        if process_type == Process.TypeChoices.HOOK and "chrome_launch" in str(cmd)
    ]
    assert chrome_hook_envs
    assert all("{ABXPKG_LIB_DIR}" not in str(env) for env in chrome_hook_envs)
    assert any(process_type == Process.TypeChoices.BINARY for process_type, _status, _exit_code, _cmd, _env in process_rows)
    assert all(
        status == Process.StatusChoices.EXITED and exit_code == 0
        for process_type, status, exit_code, _cmd, _env in process_rows
        if process_type == Process.TypeChoices.BINARY
    )
