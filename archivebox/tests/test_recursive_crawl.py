#!/usr/bin/env python3
"""Integration tests for recursive crawling functionality."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Binary, Process
from archivebox.tests.conftest import run_archivebox_cmd, cli_env
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def wait_for_db_condition(timeout, condition, interval=0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists("index.sqlite3"):
            with use_archivebox_db("."):
                if condition():
                    return True
        time.sleep(interval)
    return False


def stop_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            return proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return proc.communicate()


def run_add_until(args, env, condition, timeout=120):
    assert args[0] == "archivebox"
    proc = run_archivebox_cmd(
        args[1:],
        cwd=Path.cwd(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        wait=False,
    )

    assert wait_for_db_condition(timeout=timeout, condition=condition), f"Timed out waiting for condition while running: {' '.join(args)}"
    return stop_process(proc)


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

    proc = run_archivebox_cmd(
        ["add", "--depth=1", "--plugins=favicon,parse_html_urls", recursive_test_site["root_url"]],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        wait=False,
    )

    assert wait_for_db_condition(
        timeout=120,
        condition=lambda: ArchiveResult.objects.filter(
            plugin__startswith="parse_",
            plugin__endswith="_urls",
            status__in=("started", "succeeded", "failed"),
        ).exists(),
    ), "Parser extractors never progressed beyond queued status"
    stdout, stderr = stop_process(proc)

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
    """archivebox add should install selected plugins' required_plugins and binaries before hooks run."""

    env = os.environ.copy()
    env.pop("CHROME_BINARY", None)
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "TIMEOUT": "120",
            "ABXPKG_INSTALL_TIMEOUT": "900",
            "LIB_DIR": str(initialized_archive / "lib"),
            "ABXPKG_LIB_DIR": str(initialized_archive / "lib"),
            "CHROME_HEADLESS": "true",
            "CHROME_SANDBOX": "false",
            "CHROME_ISOLATION": "snapshot",
            "CHROME_EXTENSIONS_DIR": str(initialized_archive / "lib/chromewebstore/extensions"),
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
    assert binaries["chromium"]["binprovider"] == "puppeteer"
    assert Path(binaries["chromium"]["abspath"]).exists()
    chromium_version_parts = [int(part) for part in binaries["chromium"]["version"].split(".")[:3]]
    assert chromium_version_parts >= [149, 0, 0]

    assert "archivewebpage" in binaries
    assert binaries["archivewebpage"]["status"] == Binary.StatusChoices.INSTALLED
    assert binaries["archivewebpage"]["binprovider"] == "chromewebstore"
    archivewebpage_manifest = Path(binaries["archivewebpage"]["abspath"])
    assert archivewebpage_manifest.exists()
    assert archivewebpage_manifest.name == "manifest.json"

    plugins_seen = {plugin for plugin, _hook_name, _status, _output_str, _output_files in archive_results}
    assert {"chrome", "archivewebpage"}.issubset(plugins_seen)
    assert all(
        status == ArchiveResult.StatusChoices.SUCCEEDED
        for plugin, _hook_name, status, _output_str, _output_files in archive_results
        if plugin in {"chrome", "archivewebpage"}
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
    assert all("{LIB_DIR}" not in str(env) for env in chrome_hook_envs)
    assert any(process_type == Process.TypeChoices.BINARY for process_type, _status, _exit_code, _cmd, _env in process_rows)
    assert all(
        status == Process.StatusChoices.EXITED and exit_code == 0
        for process_type, status, exit_code, _cmd, _env in process_rows
        if process_type == Process.TypeChoices.BINARY
    )


@pytest.mark.timeout(1200)
def test_recursive_crawl_depth_two_all_plugins_runs_snapshots_in_parallel(initialized_archive, free_tcp_port_factory):
    """Run a bounded real depth=2 crawl with all plugins enabled and verify parallel snapshot execution."""

    from abx_dl.models import discover_plugins

    root_url = "https://example.com/"
    plugin_selection = ",".join(
        sorted(plugin for plugin in discover_plugins().keys() if not plugin.startswith("claude")),
    )
    env = os.environ.copy()
    env.pop("CHROME_BINARY", None)
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "LIB_DIR": str(initialized_archive / "lib"),
            "ABXPKG_LIB_DIR": str(initialized_archive / "lib"),
            "TIMEOUT": "90",
            "ABXPKG_INSTALL_TIMEOUT": "900",
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": "3",
            "SEARCH_BACKEND_SONIC_HOST_NAME": "127.0.0.1",
            "SEARCH_BACKEND_SONIC_PORT": str(free_tcp_port_factory()),
            "CHROME_HEADLESS": "true",
            "CHROME_SANDBOX": "false",
            "CHROME_ISOLATION": "snapshot",
        },
    )

    result = run_archivebox_cmd(
        [
            "add",
            "--depth=2",
            "--max-urls=8",
            "--crawl-max-size=100mb",
            "--tag=recursive-all-plugins",
            "--parser=url_list",
            f"--plugins={plugin_selection}",
            root_url,
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
        crawl = Crawl.objects.get(tags_str="recursive-all-plugins")
        snapshots = list(
            Snapshot.objects.filter(crawl=crawl)
            .order_by("depth", "url")
            .values_list("id", "url", "depth", "status", "parent_snapshot_id", "downloaded_at"),
        )
        archive_results = list(
            ArchiveResult.objects.filter(snapshot__crawl=crawl)
            .select_related("snapshot")
            .order_by("snapshot__depth", "snapshot__url", "plugin", "hook_name")
            .values_list(
                "snapshot_id",
                "snapshot__url",
                "snapshot__depth",
                "plugin",
                "hook_name",
                "status",
                "output_files",
                "output_size",
                "output_str",
            ),
        )
        process_snapshot_ids = {
            process_id: str(snapshot_id)
            for snapshot_id, process_id in ArchiveResult.objects.filter(
                snapshot__crawl=crawl,
                process_id__isnull=False,
            ).values_list("snapshot_id", "process_id")
        }
        processes = list(
            Process.objects.filter(process_type=Process.TypeChoices.HOOK, id__in=process_snapshot_ids)
            .order_by("started_at")
            .values_list("id", "pwd", "cmd", "status", "exit_code", "started_at", "ended_at"),
        )

    assert crawl.max_depth == 2
    assert crawl.config["CRAWL_MAX_URLS"] == 8
    assert crawl.config["CRAWL_MAX_SIZE"] == 100 * 1024 * 1024
    assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 3
    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None

    assert len(snapshots) == 8
    assert any(url == root_url and depth == 0 for _id, url, depth, _status, _parent, _downloaded_at in snapshots)
    assert any("iana.org" in url and depth == 1 for _id, url, depth, _status, _parent, _downloaded_at in snapshots)
    assert any(depth == 2 for _id, _url, depth, _status, _parent, _downloaded_at in snapshots)
    assert all(status == Snapshot.StatusChoices.SEALED for _id, _url, _depth, status, _parent, _downloaded_at in snapshots)
    assert all(downloaded_at is not None for _id, _url, _depth, _status, _parent, downloaded_at in snapshots)

    assert archive_results
    allowed_statuses = {
        ArchiveResult.StatusChoices.SUCCEEDED,
        ArchiveResult.StatusChoices.NORESULTS,
        ArchiveResult.StatusChoices.SKIPPED,
    }
    unexpected_results = [
        {
            "url": url,
            "depth": depth,
            "plugin": plugin,
            "hook_name": hook_name,
            "status": status,
            "output_str": output_str,
        }
        for _snapshot_id, url, depth, plugin, hook_name, status, _files, _size, output_str in archive_results
        if not (status in allowed_statuses or (plugin == "archivedotorg" and status == ArchiveResult.StatusChoices.FAILED))
    ]
    assert not unexpected_results

    plugins_seen = {plugin for _snapshot_id, _url, _depth, plugin, _hook_name, _status, _files, _size, _output in archive_results}
    assert {
        "wget",
        "headers",
        "title",
        "pdf",
        "screenshot",
        "dom",
        "singlefile",
        "readability",
        "mercury",
        "htmltotext",
        "favicon",
        "parse_html_urls",
        "archivedotorg",
    }.issubset(plugins_seen)

    snapshot_root = initialized_archive / "archive/users/system/snapshots"
    assert list(snapshot_root.rglob("wget/**/*.html"))
    assert list(snapshot_root.rglob("headers/**/headers.json"))
    assert list(snapshot_root.rglob("title/title.txt"))
    assert list(snapshot_root.rglob("pdf/**/*.pdf"))
    assert list(snapshot_root.rglob("screenshot/**/*.png"))
    assert list(snapshot_root.rglob("dom/**/*.html"))
    assert list(snapshot_root.rglob("singlefile/**/*.html"))
    assert list(snapshot_root.rglob("readability/**/*.html"))
    assert list(snapshot_root.rglob("mercury/**/*.html"))
    assert list(snapshot_root.rglob("htmltotext/**/*.txt"))
    assert list(snapshot_root.rglob("favicon/**/*"))
    urls_jsonl_files = list(snapshot_root.rglob("parse_html_urls/urls.jsonl"))
    assert urls_jsonl_files
    assert any("iana.org" in path.read_text(errors="ignore") for path in urls_jsonl_files)

    assert processes
    failed_hook_results = [
        {
            "url": url,
            "depth": depth,
            "plugin": plugin,
            "hook_name": hook_name,
            "status": status,
            "output_str": output_str,
        }
        for _snapshot_id, url, depth, plugin, hook_name, status, _files, _size, output_str in archive_results
        if status == ArchiveResult.StatusChoices.FAILED and plugin != "archivedotorg"
    ]
    assert not failed_hook_results
    assert all(status == Process.StatusChoices.EXITED for _id, _pwd, _cmd, status, _exit_code, _started_at, _ended_at in processes)

    intervals = []
    for process_id, pwd, cmd, _status, _exit_code, started_at, ended_at in processes:
        if not started_at or not ended_at:
            continue
        process_snapshot_id = process_snapshot_ids.get(process_id)
        if process_snapshot_id is None:
            continue
        intervals.append((process_snapshot_id, started_at, ended_at, pwd, cmd))

    overlapping = [
        (left, right)
        for index, left in enumerate(intervals)
        for right in intervals[index + 1 :]
        if left[0] != right[0] and left[1] < right[2] and right[1] < left[2]
    ]
    assert overlapping, f"Expected hook processes from different snapshots to overlap, got intervals: {intervals}"


def test_crawl_snapshot_has_parent_snapshot_field(tmp_path, initialized_archive):
    """Test that Snapshot model has parent_snapshot field."""

    column_names = {field.column for field in Snapshot._meta.local_fields}

    assert "parent_snapshot_id" in column_names, f"Snapshot table should have parent_snapshot_id column. Columns: {column_names}"


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
