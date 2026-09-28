#!/usr/bin/env python3
"""
Comprehensive tests for archivebox add command.
Verify add creates snapshots in DB, crawls, source files, and archive directories.
"""

import os
import json
import pty
import select
import time
import termios

from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import (
    cli_env,
    run_archivebox_cmd,
    run_queued_crawls,
)

from archivebox.tests.test_orm_helpers import use_archivebox_db

from .test_cli_add_1 import (
    pytestmark as pytestmark,
    IMPORT_FORMAT_EXPECTATIONS as IMPORT_FORMAT_EXPECTATIONS,
    write_import_format_files as write_import_format_files,
    IMPORT_FORMAT_ENV as IMPORT_FORMAT_ENV,
    assert_expected_import_snapshots as assert_expected_import_snapshots,
    malicious_add_inputs as malicious_add_inputs,
    assert_no_file_or_shell_payload_snapshots as assert_no_file_or_shell_payload_snapshots,
)


@pytest.fixture
def progress_page(httpserver):
    # Exercise the real HTTP fetch and parser with fixed content. example.com's
    # outgoing IANA link has changed independently of ArchiveBox releases.
    httpserver.expect_request("/").respond_with_data(
        '<html><body><a href="https://iana.org/domains/example">Example domains</a></body></html>',
        content_type="text/html",
    )
    return httpserver.url_for("/")


@pytest.mark.parametrize("terminal_stream", ["stdout", "stderr"])
def test_add_renders_live_progress_in_foreground_terminal(initialized_archive, terminal_stream, progress_page):
    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, 160))
    output = bytearray()
    result = None
    try:
        result = run_archivebox_cmd(
            ["add", "--plugins=parse_txt_urls", progress_page],
            cwd=initialized_archive,
            env=cli_env(USE_COLOR="True", SHOW_PROGRESS="True"),
            **{terminal_stream: slave},
            wait=False,
            start_new_session=True,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            elif result.poll() is not None:
                break
        assert result.poll() == 0, output.decode(errors="replace")
        assert b"\x1b[?25l" in output, output.decode(errors="replace")
        assert b"\x1b[?25h" in output, output.decode(errors="replace")
        assert b"on_Snapshot__71_parse_txt_urls" in output
        assert b"\x1b[2K" in output
        with use_archivebox_db(initialized_archive):
            assert Crawl.objects.get().status == Crawl.StatusChoices.SEALED
            snapshot = Snapshot.objects.get()
            assert snapshot.url == progress_page
            parsed_urls = Path(snapshot.output_dir) / "parse_txt_urls" / "urls.jsonl"
            assert json.loads(parsed_urls.read_text())["url"] == "https://iana.org/domains/example"
    finally:
        if result is not None and result.poll() is None:
            result.terminate()
            result.wait(timeout=10)
        os.close(slave)
        os.close(master)


def test_add_redirected_progress_remains_plain_text(initialized_archive, progress_page):
    result = run_archivebox_cmd(
        ["add", "--plugins=parse_txt_urls", progress_page],
        cwd=initialized_archive,
        env=cli_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "on_Snapshot__71_parse_txt_urls" in result.stderr
    assert "\x1b[?25l" not in result.stdout + result.stderr


@pytest.mark.timeout(360)
def test_add_stdin_import_formats_preserve_metadata_and_crawl_inner_urls(initialized_archive):
    """`archivebox add < import-file` should normalize rich import formats before crawling URLs."""
    import_files = write_import_format_files(initialized_archive)
    expected_urls = {case["url"] for case in IMPORT_FORMAT_EXPECTATIONS.values()}
    env = cli_env(**IMPORT_FORMAT_ENV)

    for import_path in import_files.values():
        source_text = import_path.read_text(encoding="utf-8")
        result = run_archivebox_cmd(
            ["add", "--bg", "--depth=0", "--tag=cli-stdin-import"],
            cwd=initialized_archive,
            env=env,
            stdin=source_text,
            timeout=360,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        with use_archivebox_db(initialized_archive):
            crawl = Crawl.objects.order_by("-created_at").first()
            assert crawl is not None
            assert crawl.snapshot_set.count() == 0
        assert crawl.urls == source_text

    run_queued_crawls(initialized_archive, env=env, timeout=240)
    with use_archivebox_db(initialized_archive):
        for crawl in Crawl.objects.all():
            assert not crawl.snapshot_set.filter(url__startswith="archivebox://").exists()
            root_input = (crawl.output_dir / "input" / "staticfile" / "stdin.txt").read_text(encoding="utf-8")
            assert root_input == crawl.urls
    assert_expected_import_snapshots(initialized_archive, expected_urls)

    list_result = run_archivebox_cmd(
        ["list", "--json"],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    assert list_result.returncode == 0, list_result.stderr or list_result.stdout
    for expected_url in expected_urls:
        assert expected_url in list_result.stdout

    with use_archivebox_db(initialized_archive):
        crawls = list(Crawl.objects.order_by("created_at"))
        snapshots_by_url = {snapshot.url: snapshot for snapshot in Snapshot.objects.prefetch_related("tags").filter(url__in=expected_urls)}
        tags_by_url = {snapshot.url: set(snapshot.tags.values_list("name", flat=True)) for snapshot in snapshots_by_url.values()}

    assert len(crawls) == len(import_files)
    assert [crawl.urls for crawl in crawls] == [path.read_text(encoding="utf-8") for path in import_files.values()]
    assert all(crawl.tags_str == "cli-stdin-import" for crawl in crawls)
    assert all(crawl.status in {Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED} for crawl in crawls)
    assert len(snapshots_by_url) == len(expected_urls)

    for import_name, expected in IMPORT_FORMAT_EXPECTATIONS.items():
        snapshot = snapshots_by_url.get(expected["url"])
        assert snapshot is not None, f"{import_name} did not create Snapshot for {expected['url']}"
        assert snapshot.status in {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
        if expected.get("title"):
            assert snapshot.title == expected["title"]
        if expected.get("date"):
            assert snapshot.bookmarked_at.date().isoformat() == expected["date"]
        if expected.get("tags"):
            assert expected["tags"] | {"cli-stdin-import"} <= tags_by_url[snapshot.url]


def test_add_bg_queues_direct_url_snapshot(initialized_archive):
    """Background add queues explicit URL arguments as real URL snapshots."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--bg", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshots = list(Snapshot.objects.all())

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is not None
    assert crawl.urls == "https://example.com"
    assert snapshots == []


@pytest.mark.timeout(180)
def test_add_title_hook_env_gets_canonical_runtime_config_without_archivebox_selectors_or_aliases(initialized_archive):
    env = os.environ.copy()
    env.update(
        {
            "USE_COLOR": "False",
            "SHOW_PROGRESS": "False",
            "PLUGINS": "title",
            "SAVE_TITLE": "True",
            "SECRET_KEY": "hook-env-secret-must-not-leak",
            "PUBLIC_ADD_VIEW": "True",
            "ADMIN_PASSWORD": "hook-env-admin-password-must-not-leak",
            "URL_BLACKLIST": "$^",
            "ARCHIVEBOX_TEST_ARBITRARY_ENV": "preserved-user-env",
            "LD_PRELOAD": "",
            "TIMEOUT": "60",
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": "1",
        },
    )
    result = run_archivebox_cmd(
        [
            "add",
            "--depth=0",
            "--plugins=title",
            "https://example.com/?archivebox-title-env=1",
        ],
        cwd=initialized_archive,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "Crawl.save() outside runner process" not in result.stdout + result.stderr

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot = Snapshot.objects.get()
        title_result = ArchiveResult.objects.select_related("process").get(snapshot=snapshot, plugin="title")
        process_env = title_result.process.env

    assert crawl.config["PLUGINS"] == "title"
    assert snapshot.url == "https://example.com/?archivebox-title-env=1"
    assert snapshot.status == Snapshot.StatusChoices.SEALED
    assert snapshot.title == "Example Domain"
    assert title_result.status == ArchiveResult.StatusChoices.SUCCEEDED
    assert title_result.output_str == "Example Domain"
    assert title_result.process.exit_code == 0
    assert process_env["TITLE_ENABLED"] == "True"
    assert process_env["CHROME_ENABLED"] == "True"
    assert process_env["WGET_ENABLED"] == "False"
    assert process_env["ARCHIVEBOX_TEST_ARBITRARY_ENV"] == "preserved-user-env"
    assert process_env["LD_PRELOAD"] == ""
    assert "PLUGINS" not in process_env
    assert "SAVE_TITLE" not in process_env
    assert "SEARCH_BACKEND_ENGINE" not in process_env
    assert "SECRET_KEY" not in process_env
    assert "ADMIN_PASSWORD" not in process_env
    assert "PUBLIC_ADD_VIEW" not in process_env
    assert "URL_BLACKLIST" not in process_env
    assert "hook-env-secret-must-not-leak" not in json.dumps(process_env)
    assert "hook-env-admin-password-must-not-leak" not in json.dumps(process_env)


def test_add_creates_crawl_record(initialized_archive):
    """Test that add command creates a Crawl record in the database."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    with use_archivebox_db(initialized_archive):
        crawl_count = Crawl.objects.count()

    assert crawl_count == 1


def test_add_rejects_file_path_argument(initialized_archive):
    """Local files must be piped through stdin, not passed as archiveable path arguments."""
    env = cli_env(disable_extractors=True)
    urls_file = initialized_archive / "urls.txt"
    urls_file.write_text("https://example.com\nhttps://example.org\n")

    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", str(urls_file)],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode != 0

    with use_archivebox_db(initialized_archive):
        assert Crawl.objects.count() == 0
        assert Snapshot.objects.count() == 0

    assert "No URLs provided" in (result.stderr or result.stdout)


def test_add_records_url_filter_overrides_on_crawl(initialized_archive):
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        [
            "add",
            "--index-only",
            "--depth=0",
            "--domain-allowlist=example.com,*.example.com",
            "--domain-denylist=static.example.com",
            "https://example.com",
        ],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()

    assert crawl.config["URL_ALLOWLIST"] == "example.com,*.example.com"
    assert crawl.config["URL_DENYLIST"] == "static.example.com"
    assert not (initialized_archive / "personas" / "Default" / "chrome_extensions").exists()


def test_add_help_shows_depth_and_tag_options(initialized_archive):
    """Test that add --help documents the main filter and crawl options."""

    result = run_archivebox_cmd(
        ["add", "--help"],
    )

    assert result.returncode == 0
    assert "--depth" in result.stdout
    assert "--max-urls" in result.stdout
    assert "--crawl-max-size" in result.stdout
    assert "--crawl-timeout" in result.stdout
    assert "--snapshot-max-size" in result.stdout
    assert "--tag" in result.stdout


def test_add_index_only_creates_direct_url_snapshot(initialized_archive):
    """Index-only add seeds explicit URL args for the runner to snapshot."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot = Snapshot.objects.get()

    assert crawl.urls == "https://example.com"
    assert snapshot.url == "https://example.com"
    assert snapshot.depth == 0


def test_snapshot_create_sets_snapshot_timestamp(initialized_archive):
    """Test the user-facing snapshot creation path sets a timestamp."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )

    with use_archivebox_db(initialized_archive):
        timestamp = Snapshot.objects.values_list("timestamp", flat=True).get()

    assert timestamp is not None
    assert len(str(timestamp)) > 0


@pytest.mark.timeout(180)
def test_cli_recursive_crawl_processes_discovered_html_urls(initialized_archive, recursive_test_site):

    env = os.environ.copy()
    env.update(
        {
            "USE_COLOR": "false",
            "SHOW_PROGRESS": "false",
            "TIMEOUT": "60",
            "SAVE_WGET": "true",
            "SAVE_HEADERS": "false",
            "SAVE_TITLE": "false",
            "SAVE_READABILITY": "false",
            "SAVE_SINGLEFILE": "false",
            "SAVE_MERCURY": "false",
            "SAVE_SCREENSHOT": "false",
            "SAVE_PDF": "false",
            "SAVE_DOM": "false",
            "SAVE_ARCHIVEDOTORG": "false",
            "SAVE_GIT": "false",
            "SAVE_YTDLP": "false",
            "SAVE_FAVICON": "false",
            "PARSE_HTML_URLS_ENABLED": "true",
            "PARSE_DOM_OUTLINKS_ENABLED": "false",
            "URL_ALLOWLIST": r"127\.0\.0\.1[:/].*",
        },
    )
    root_url = recursive_test_site["root_url"]
    child_url = recursive_test_site["child_urls"][0]

    result = run_archivebox_cmd(
        [
            "add",
            "--depth=2",
            "--max-urls=2",
            "--crawl-max-size=50mb",
            "--tag=recursive-flow",
            "--parser=url_list",
            "--plugins=wget,parse_html_urls",
            root_url,
        ],
        cwd=initialized_archive,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.order_by("-created_at").values_list("max_depth", "tags_str", "config").first()
        snapshots = list(Snapshot.objects.order_by("depth", "url").values_list("url", "depth", "status"))
        archive_results = list(
            ArchiveResult.objects.select_related("snapshot")
            .order_by("snapshot__depth", "snapshot__url", "plugin")
            .values_list("snapshot__url", "plugin", "status", "output_files"),
        )

    assert crawl[0] == 2
    assert crawl[1] == "recursive-flow"
    crawl_config = crawl[2] or {}
    assert crawl_config["CRAWL_MAX_URLS"] == 2
    assert crawl_config["CRAWL_MAX_SIZE"] == 50 * 1024 * 1024
    assert crawl_config.get("SNAPSHOT_MAX_SIZE", 0) == 0
    assert (root_url, 0, "sealed") in snapshots
    assert any(url == child_url and depth == 1 and status == "sealed" for url, depth, status in snapshots)

    by_url_plugin = {(url, plugin): status for url, plugin, status, _files in archive_results}
    assert by_url_plugin[(root_url, "wget")] == "succeeded"
    assert by_url_plugin[(root_url, "parse_html_urls")] == "succeeded"
    assert by_url_plugin[(child_url, "wget")] == "succeeded"

    urls_outputs = list((initialized_archive / "archive/users/system/snapshots").rglob("parse_html_urls/urls.jsonl"))
    assert urls_outputs
    assert any(child_url in path.read_text() for path in urls_outputs)
