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

from .test_recursive_crawl_1 import (
    pytestmark as pytestmark,
    run_add_until as run_add_until,
)


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


def test_parser_extractors_emit_snapshot_jsonl(tmp_path, initialized_archive, recursive_test_site):
    """Test that parser extractors emit Snapshot JSONL to stdout."""

    env = os.environ.copy()
    env.update(
        {
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
            "SAVE_FAVICON": "false",
            "USE_CHROME": "false",
        },
    )

    result = run_archivebox_cmd(
        ["add", "--depth=0", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    with use_archivebox_db(tmp_path):
        parse_html = (
            ArchiveResult.objects.filter(plugin__endswith="parse_html_urls")
            .order_by("id")
            .values_list("id", "status", "output_str")
            .first()
        )

    if parse_html:
        status = parse_html[1]
        output = parse_html[2] or ""

        assert status in ["started", "succeeded", "failed"], f"60_parse_html_urls should have run, got status: {status}"

        if status == "succeeded" and output:
            assert "parsed" in output.lower(), "Parser summary should report parsed URLs"

    urls_jsonl_files = list(Path("archive/users/system/snapshots").rglob("parse_html_urls/**/urls.jsonl"))
    assert urls_jsonl_files, "parse_html_urls should write urls.jsonl output"

    records = []
    for line in urls_jsonl_files[0].read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))

    assert records, "urls.jsonl should contain parsed Snapshot records"
    assert all(record.get("type") == "Snapshot" for record in records), f"Expected Snapshot JSONL records, got: {records}"


def test_recursive_crawl_creates_child_snapshots(tmp_path, initialized_archive, recursive_test_site):
    """Test that recursive crawling creates child snapshots with proper depth and parent_snapshot_id."""

    env = os.environ.copy()
    env.update(
        {
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
            "SAVE_READABILITY": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_MERCURY": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_PDF": "false",
            "SAVE_HEADERS": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_TITLE": "false",
        },
    )

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--depth=1", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda: (
            Snapshot.objects.filter(depth=0).count() >= 1
            and Snapshot.objects.filter(depth=1).count() >= len(recursive_test_site["child_urls"])
        ),
    )

    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 2000 chars) ===\n{stdout[-2000:]}\n=== END STDOUT ===\n")

    with use_archivebox_db(tmp_path):
        all_snapshots = list(Snapshot.objects.values_list("url", "depth"))
        root_snapshot = (
            Snapshot.objects.filter(depth=0).order_by("created_at").values_list("id", "url", "depth", "parent_snapshot_id").first()
        )
        child_snapshots = list(Snapshot.objects.filter(depth=1).values_list("id", "url", "depth", "parent_snapshot_id"))
        crawl = Crawl.objects.order_by("-created_at").values_list("id", "max_depth").first()
        parser_status = list(
            ArchiveResult.objects.filter(
                snapshot_id=root_snapshot[0] if root_snapshot else None,
                plugin__startswith="parse_",
                plugin__endswith="_urls",
            ).values_list("plugin", "status"),
        )
        started_extractors = list(
            ArchiveResult.objects.filter(
                snapshot_id=root_snapshot[0] if root_snapshot else None,
                status="started",
            ).values_list("plugin", "status"),
        )

    assert root_snapshot is not None, f"Root snapshot should exist at depth=0. All snapshots: {all_snapshots}"
    root_id = root_snapshot[0]

    assert crawl is not None, "Crawl should be created"
    assert crawl[1] == 1, f"Crawl max_depth should be 1, got {crawl[1]}"

    assert len(child_snapshots) > 0, (
        f"Child snapshots should be created from monadical.com links. Parser status: {parser_status}. Started extractors blocking: {started_extractors}"
    )

    for child_id, child_url, child_depth, parent_id in child_snapshots:
        assert child_depth == 1, f"Child snapshot should have depth=1, got {child_depth}"
        assert parent_id == root_id, f"Child snapshot {child_url} should have parent_snapshot_id={root_id}, got {parent_id}"


def test_recursive_crawl_respects_depth_limit(tmp_path, initialized_archive, recursive_test_site):
    """Test that recursive crawling stops at max_depth."""
    env = cli_env(disable_extractors=True)

    env = env.copy()
    env["URL_ALLOWLIST"] = r"127\.0\.0\.1[:/].*"

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--depth=1", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda: (
            Snapshot.objects.filter(depth=0).count() >= 1
            and Snapshot.objects.filter(depth=1).count() >= len(recursive_test_site["child_urls"])
            and ArchiveResult.objects.filter(
                snapshot__depth=1,
                plugin__startswith="parse_",
                plugin__endswith="_urls",
                status__in=("started", "succeeded", "failed"),
            )
            .values("snapshot_id")
            .distinct()
            .count()
            >= len(recursive_test_site["child_urls"])
        ),
    )

    with use_archivebox_db(tmp_path):
        depths = list(Snapshot.objects.values_list("depth", flat=True))
        max_depth_found = max(depths) if depths else None
        depth_counts = [(depth, Snapshot.objects.filter(depth=depth).count()) for depth in sorted(set(depths))]

    assert max_depth_found is not None, "Should have at least one snapshot"
    assert max_depth_found <= 1, f"Max depth should not exceed 1, got {max_depth_found}. Depth distribution: {depth_counts}"


def test_recursive_crawl_depth_two_writes_real_outputs_and_process_records(tmp_path, initialized_archive, recursive_test_site):
    """Run a real depth=2 crawl and verify DB, output files, and process side effects."""

    env = os.environ.copy()
    env.update(
        {
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
            "SAVE_WGET": "true",
            "SAVE_READABILITY": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_MERCURY": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_PDF": "false",
            "SAVE_HEADERS": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_TITLE": "false",
            "SAVE_FAVICON": "false",
            "USE_CHROME": "false",
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
        },
    )

    result = run_archivebox_cmd(
        ["add", "--depth=2", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        cwd=initialized_archive,
        env=env,
        timeout=240,
    )
    stdout, stderr = result.stdout, result.stderr

    if stderr:
        print(f"\n=== STDERR ===\n{stderr}\n=== END STDERR ===\n")
    if stdout:
        print(f"\n=== STDOUT (last 2000 chars) ===\n{stdout[-2000:]}\n=== END STDOUT ===\n")
    assert result.returncode == 0, stderr or stdout

    with use_archivebox_db(tmp_path):
        depths = list(Snapshot.objects.values_list("depth", flat=True))
        depth_counts = {depth: Snapshot.objects.filter(depth=depth).count() for depth in sorted(set(depths))}
        crawl = Crawl.objects.order_by("-created_at").values_list("id", "max_depth").first()
        root_snapshot = (
            Snapshot.objects.filter(depth=0).order_by("created_at").values_list("id", "url", "depth", "parent_snapshot_id").first()
        )
        child_rows = list(Snapshot.objects.filter(depth=1).values_list("id", "url", "parent_snapshot_id"))
        deep_rows = list(Snapshot.objects.filter(depth=2).values_list("id", "url", "parent_snapshot_id"))
        parser_results = list(
            ArchiveResult.objects.filter(plugin__startswith="parse_", plugin__endswith="_urls")
            .order_by("snapshot__depth", "snapshot__url")
            .values_list("snapshot__url", "snapshot__depth", "plugin", "status", "output_files", "output_size"),
        )
        wget_results = list(
            ArchiveResult.objects.filter(plugin="wget")
            .order_by("snapshot__depth", "snapshot__url")
            .values_list("snapshot__url", "snapshot__depth", "status", "output_files", "output_size"),
        )
        process_rows = list(
            Process.objects.filter(process_type="hook")
            .order_by("created_at")
            .values_list("process_type", "worker_type", "status", "exit_code", "pwd", "cmd"),
        )

    assert crawl is not None
    assert crawl[1] == 2
    assert root_snapshot is not None
    assert root_snapshot[2] == 0
    assert root_snapshot[3] is None
    assert depth_counts.get(0, 0) >= 1
    assert depth_counts.get(1, 0) >= len(recursive_test_site["child_urls"])
    assert depth_counts.get(2, 0) >= len(recursive_test_site["deep_urls"])
    assert max(depth_counts) <= 2

    child_urls = {row[1] for row in child_rows}
    deep_urls = {row[1] for row in deep_rows}
    child_ids = {row[0] for row in child_rows}
    assert set(recursive_test_site["child_urls"]).issubset(child_urls)
    assert set(recursive_test_site["deep_urls"]).issubset(deep_urls)
    assert all(parent_id == root_snapshot[0] for _id, _url, parent_id in child_rows)
    assert all(parent_id in child_ids for _id, _url, parent_id in deep_rows)

    parser_statuses = {status for _url, _depth, _plugin, status, _files, _size in parser_results}
    wget_statuses = {status for _url, _depth, status, _files, _size in wget_results}
    assert parser_results
    assert wget_results
    assert "succeeded" in parser_statuses
    assert "succeeded" in wget_statuses
    assert len([row for row in parser_results if row[3] == "failed"]) <= 2
    assert len([row for row in wget_results if row[2] == "failed"]) <= 2

    urls_jsonl_files = list(Path("archive/users/system/snapshots").rglob("parse_html_urls/**/urls.jsonl"))
    assert urls_jsonl_files, "parse_html_urls should write urls.jsonl files"
    parsed_urls = set()
    for path in urls_jsonl_files:
        for line in path.read_text().splitlines():
            if line.strip():
                parsed_urls.add(json.loads(line)["url"])
    assert set(recursive_test_site["child_urls"]).issubset(parsed_urls)
    assert set(recursive_test_site["deep_urls"]).issubset(parsed_urls)

    snapshot_dirs = [path.parent for path in Path("archive/users/system/snapshots").rglob("index.jsonl")]
    assert snapshot_dirs
    for snapshot_dir in snapshot_dirs:
        assert (snapshot_dir / "index.jsonl").exists()

    assert process_rows
    assert any("parse_html_urls" in (pwd or "") or "parse_html_urls" in (cmd or "") for *_rest, pwd, cmd in process_rows)
    assert any("wget" in (pwd or "") or "wget" in (cmd or "") for *_rest, pwd, cmd in process_rows)


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


def test_snapshot_depth_field_exists(tmp_path, initialized_archive):
    """Test that Snapshot model has depth field."""

    column_names = {field.column for field in Snapshot._meta.local_fields}

    assert "depth" in column_names, f"Snapshot table should have depth column. Columns: {column_names}"


def test_root_snapshot_has_depth_zero(tmp_path, initialized_archive, recursive_test_site):
    """Test that root snapshots are created with depth=0."""
    env = cli_env(disable_extractors=True)

    env = env.copy()
    env["URL_ALLOWLIST"] = r"127\.0\.0\.1[:/].*"

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--depth=1", "--plugins=wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda: Snapshot.objects.filter(url=recursive_test_site["root_url"]).count() >= 1,
    )

    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.filter(url=recursive_test_site["root_url"]).order_by("created_at").values_list("id", "depth").first()

    assert snapshot is not None, "Root snapshot should be created"
    assert snapshot[1] == 0, f"Root snapshot should have depth=0, got {snapshot[1]}"


def test_archiveresult_worker_queue_filters_by_foreground_extractors(tmp_path, initialized_archive, recursive_test_site):
    """Test that background hooks don't block foreground extractors from running."""

    env = os.environ.copy()
    env.update(
        {
            "SAVE_WGET": "true",
            "SAVE_SINGLEFILE": "false",
            "SAVE_PDF": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_FAVICON": "true",
        },
    )

    stdout, stderr = run_add_until(
        ["archivebox", "add", "--plugins=favicon,wget,parse_html_urls", recursive_test_site["root_url"]],
        env=env,
        timeout=120,
        condition=lambda: ArchiveResult.objects.filter(
            plugin__startswith="parse_",
            plugin__endswith="_urls",
            status__in=("started", "succeeded", "failed"),
        ).exists(),
    )

    with use_archivebox_db(tmp_path):
        bg_results = list(
            ArchiveResult.objects.filter(
                plugin__in=("favicon", "consolelog", "ssl", "responses", "redirects", "staticfile"),
                status__in=("started", "succeeded", "failed"),
            ).values_list("plugin", "status"),
        )
        parser_status = list(
            ArchiveResult.objects.filter(plugin__startswith="parse_", plugin__endswith="_urls").values_list("plugin", "status"),
        )

    if len(bg_results) > 0:
        parser_statuses = [status for _, status in parser_status]
        non_queued = [s for s in parser_statuses if s != "queued"]
        assert len(non_queued) > 0 or len(parser_status) == 0, (
            f"With {len(bg_results)} background hooks started, parser extractors should still run. Got statuses: {parser_statuses}"
        )
