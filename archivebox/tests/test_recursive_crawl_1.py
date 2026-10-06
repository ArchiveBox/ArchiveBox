#!/usr/bin/env python3
"""Integration tests for recursive crawling functionality."""

import json
import os
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.tests.conftest import run_archivebox_cmd
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


@pytest.mark.timeout(1200)
def test_recursive_crawl_depth_two_all_plugins_runs_snapshots_in_parallel(
    initialized_archive,
    cached_abxpkg_lib_dir,
    free_tcp_port_factory,
    recursive_test_site,
):
    """Run a bounded real depth=2 crawl with all plugins enabled and verify parallel snapshot execution."""

    from archivebox.plugins.discovery import get_plugin_catalog

    root_url = recursive_test_site["root_url"]
    plugin_selection = ",".join(sorted(plugin for plugin in get_plugin_catalog() if not plugin.startswith("claude")))
    env = os.environ.copy()
    for preinstalled_path_key in (
        "CHROME_BINARY",
        "LIB_DIR",
        "DATA_DIR",
        "NODE_MODULES_DIR",
        "NODE_PATH",
        "PNPM_BIN_DIR",
        "NPM_BIN_DIR",
        "CHROMEWEBSTORE_EXTENSIONS_DIR",
    ):
        env.pop(preinstalled_path_key, None)
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
            "ABXPKG_LIB_DIR": str(cached_abxpkg_lib_dir),
            "CHROMEWEBSTORE_EXTENSIONS_DIR": str(cached_abxpkg_lib_dir / "chromewebstore/extensions"),
            "TIMEOUT": "90",
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": "3",
            "SEARCH_BACKEND_SONIC_HOST_NAME": "127.0.0.1",
            "SEARCH_BACKEND_SONIC_PORT": str(free_tcp_port_factory()),
            "CHROME_HEADLESS": "true",
            "CHROME_SANDBOX": "false",
            "CHROME_ISOLATION": "snapshot",
            "LITEPARSE_OCR_ENABLED": "false",
            "LITEPARSE_MAX_SOURCES": "4",
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

    expected_urls = {
        root_url,
        *recursive_test_site["child_urls"],
        *recursive_test_site["deep_urls"],
    }
    snapshots_by_url = {url: (snapshot_id, depth, parent_id) for snapshot_id, url, depth, _status, parent_id, _downloaded_at in snapshots}
    assert set(snapshots_by_url) == expected_urls
    root_id, root_depth, root_parent_id = snapshots_by_url[root_url]
    assert root_depth == 0
    assert root_parent_id is None
    child_ids_by_url = {}
    for child_url in recursive_test_site["child_urls"]:
        child_id, child_depth, child_parent_id = snapshots_by_url[child_url]
        assert child_depth == 1
        assert child_parent_id == root_id
        child_ids_by_url[child_url] = child_id
    for child_url, deep_url in zip(recursive_test_site["child_urls"], recursive_test_site["deep_urls"], strict=True):
        _deep_id, deep_depth, deep_parent_id = snapshots_by_url[deep_url]
        assert deep_depth == 2
        assert deep_parent_id == child_ids_by_url[child_url]
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
    # This fixture serves HTTP. TLSNotary must reject every plaintext document;
    # a setup, timeout, or verifier error must not count as that expected refusal.
    tlsnotary_results = [row for row in archive_results if row[3] == "tlsnotary"]
    assert {row[1] for row in tlsnotary_results} == expected_urls
    assert len(tlsnotary_results) == len(expected_urls)
    with use_archivebox_db(initialized_archive):
        for snapshot_id, _url, _depth, _plugin, hook_name, status, files, size, _output in tlsnotary_results:
            assert status == ArchiveResult.StatusChoices.FAILED
            assert not files
            assert size == 0
            process = ArchiveResult.objects.get(snapshot_id=snapshot_id, plugin="tlsnotary", hook_name=hook_name).process
            assert process is not None
            assert process.status == Process.StatusChoices.EXITED
            assert process.exit_code == 1
            assert process.stderr.strip() == "[tlsnotary] TLSNotary requires an HTTPS document"
    assert not [result for result in unexpected_results if result["plugin"] != "tlsnotary"]
    ytdlp_results = [
        (url, status, output_str)
        for _snapshot_id, url, _depth, plugin, _hook_name, status, _files, _size, output_str in archive_results
        if plugin == "ytdlp"
    ]
    assert ytdlp_results
    assert all(status != ArchiveResult.StatusChoices.FAILED for _url, status, _output_str in ytdlp_results), ytdlp_results

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
    parsed_urls = {
        json.loads(line)["url"] for path in urls_jsonl_files for line in path.read_text(errors="ignore").splitlines() if line.strip()
    }
    assert set(recursive_test_site["child_urls"]).issubset(parsed_urls)
    assert set(recursive_test_site["deep_urls"]).issubset(parsed_urls)

    assert processes
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
