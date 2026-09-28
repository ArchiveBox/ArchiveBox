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
import signal
import re

import psutil
from pathlib import Path

import pytest
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot, SnapshotTag
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.tests.conftest import (
    cli_env,
    find_snapshot_dir,
    run_archivebox_cmd,
    run_queued_crawls,
    resolve_abxpkg_chrome_env,
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


def test_abort_stops_long_running_background_hook(initialized_archive):
    env = cli_env(INFINISCROLL_SCROLL_DELAY="10000", CHROME_HEADLESS="True")
    # Keep first-use dependency installation outside the timed hook-start
    # observation. This test is about interrupting a running hook; a cold
    # browser or forumdl install must not consume its readiness window.
    installed = run_archivebox_cmd(
        ["install", "forumdl", "chrome"],
        cwd=initialized_archive,
        env=env,
        timeout=600,
    )
    assert installed.returncode == 0, installed.stderr or installed.stdout
    env.update(resolve_abxpkg_chrome_env(Path(env["ABXPKG_LIB_DIR"]), env))

    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, 200))
    output = bytearray()
    result = None

    def read_until(predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
            if predicate():
                return
        raise AssertionError(output.decode(errors="replace"))

    def result_for(plugin):
        with use_archivebox_db(initialized_archive):
            return ArchiveResult.objects.filter(plugin=plugin).first()

    try:
        result = run_archivebox_cmd(
            ["add", "--depth=1", "--plugins=forumdl,infiniscroll", "https://news.ycombinator.com"],
            cwd=initialized_archive,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            wait=False,
            start_new_session=True,
        )
        try:
            read_until(lambda: (scroll := result_for("infiniscroll")) is not None and scroll.status == "started")
        except AssertionError:
            # Capture state before teardown terminates the runner: otherwise a
            # missed readiness deadline loses the install/hook failure itself.
            with use_archivebox_db(initialized_archive):
                print("Hook readiness:", list(ArchiveResult.objects.values("plugin", "status", "output_str")))
                print("Process readiness:", list(Process.objects.values("process_type", "status", "exit_code", "stderr")))
            raise
        read_until(lambda: "running pid=" in re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output.decode(errors="replace")))
        result.send_signal(signal.SIGINT)
        read_until(lambda: b"Choice [skip]:" in output)
        read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
        forum = result_for("forumdl")
        assert forum is not None and forum.status == "started"
        children = psutil.Process(result.pid).children(recursive=True)
        abort_offset = len(output)
        os.write(master, b"\x03")
        read_until(lambda: b"Aborting crawl" in output[abort_offset:], timeout=3)
        read_until(lambda: result.poll() is not None, timeout=25)
        assert result.returncode == 130, output.decode(errors="replace")
        assert not [child.pid for child in children if child.is_running() and child.status() != psutil.STATUS_ZOMBIE]
        assert any("INFO:root:GET" in log.read_text() for log in initialized_archive.rglob("on_Snapshot__33_forumdl.*.stderr.log"))
        assert b"Stopped during crawl abort" in output
        assert b"INFO:root:GET" not in output[abort_offset:]
        assert b"Traceback" not in output
    finally:
        if result is not None and result.poll() is None:
            result.terminate()
            result.wait(timeout=15)
        os.close(slave)
        os.close(master)


def test_add_bg_persists_queue_without_starting_extraction_workers(initialized_archive):
    result = run_archivebox_cmd(
        ["add", "--bg", "--plugins=wget", "--crawl-max-concurrent-snapshots=4", "https://example.com", "https://example.org"],
        cwd=initialized_archive,
        env=cli_env(),
    )
    assert result.returncode == 0, result.stderr
    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        assert crawl.status == Crawl.StatusChoices.QUEUED
        assert crawl.retry_at is not None
        assert crawl.get_urls_list() == ["https://example.com", "https://example.org"]
        assert crawl.config["PLUGINS"] == "wget"
        assert crawl.config["CRAWL_MAX_CONCURRENT_SNAPSHOTS"] == 4
        assert not Snapshot.objects.exists()
        assert not ArchiveResult.objects.exists()
        assert not Process.objects.filter(process_type__in=[Process.TypeChoices.ORCHESTRATOR, Process.TypeChoices.HOOK]).exists()


@pytest.mark.timeout(180)
def test_run_rejects_file_url_injected_directly_into_crawl_urls_with_db_update(initialized_archive):
    """Runner must validate Crawl.urls again when DB writes bypass normal add/create paths."""
    secret_url = "https://example.com/?archivebox-sql-crawl-file-secret=1"
    local_source = initialized_archive / "not_owned_by_crawl_urls.txt"
    local_source.write_text(f"{secret_url}\n", encoding="utf-8")
    file_url = local_source.resolve().as_uri()
    env = cli_env(**{**IMPORT_FORMAT_ENV, "PLUGINS": "parse_txt_urls", "SAVE_HEADERS": "False", "SAVE_WGET": "False"})

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(
            urls="https://example.com/?archivebox-sql-crawl-control=1",
            max_depth=2,
            tags_str="sql-file-url",
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        bad_jsonl = json.dumps({"type": "Snapshot", "url": file_url, "depth": 0, "tags": "sql-file-url"})
        Crawl.objects.filter(pk=crawl.pk).update(urls=bad_jsonl)

    result = run_archivebox_cmd(
        ["run", f"--crawl-id={crawl.id}"],
        cwd=initialized_archive,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        crawl.refresh_from_db()
        snapshot_urls = set(Snapshot.objects.values_list("url", flat=True))

    assert crawl.status in {Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED}
    assert file_url not in snapshot_urls
    assert secret_url not in snapshot_urls


@pytest.mark.timeout(180)
def test_add_tagged_single_url_seals_without_duplicate_snapshot_tags(initialized_archive):
    env = os.environ.copy()
    env.update(
        {
            "USE_COLOR": "False",
            "SHOW_PROGRESS": "False",
            "PLUGINS": "parse_txt_urls,title",
            "TIMEOUT": "60",
            "CRAWL_MAX_CONCURRENT_SNAPSHOTS": "1",
        },
    )
    result = run_archivebox_cmd(
        [
            "add",
            "--bg",
            "--depth=0",
            "--tag=tagged-single-url",
            "https://example.com/?archivebox-tagged-single-url=1",
        ],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    run_queued_crawls(initialized_archive, env, timeout=180)

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshots = list(Snapshot.objects.order_by("depth", "url"))
        tag_counts = {
            snapshot.url: SnapshotTag.objects.filter(snapshot=snapshot, tag__name="tagged-single-url").count() for snapshot in snapshots
        }
        results = list(
            ArchiveResult.objects.select_related("snapshot")
            .order_by("snapshot__depth", "snapshot__url", "plugin")
            .values_list("snapshot__url", "plugin", "status", "output_str"),
        )

    assert crawl.status == Crawl.StatusChoices.SEALED
    assert [(snapshot.url, snapshot.depth, snapshot.status) for snapshot in snapshots] == [
        ("https://example.com/?archivebox-tagged-single-url=1", 0, Snapshot.StatusChoices.SEALED),
    ]
    assert tag_counts == {
        "https://example.com/?archivebox-tagged-single-url=1": 1,
    }
    by_url_plugin = {(url, plugin): status for url, plugin, status, _output in results}
    assert by_url_plugin[("https://example.com/?archivebox-tagged-single-url=1", "title")] == "succeeded"
    unexpected_failures = [(url, plugin, status, output) for url, plugin, status, output in results if status == "failed"]
    assert not unexpected_failures


def test_add_direct_url_creates_snapshot_without_internal_input_file(initialized_archive):
    """Explicit URL args materialize real snapshots when the runner claims the crawl."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get()
        assert snapshot.url == "https://example.com"
        assert snapshot.depth == 0
        assert not (snapshot.output_dir / "staticfile" / "stdin.txt").exists()


def test_add_with_depth_1_flag(initialized_archive):
    """Test that --depth=1 flag is accepted."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=1", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --depth" not in result.stderr


def test_add_rejects_invalid_depth_values(initialized_archive):
    """Test that add rejects depth values outside the supported range."""
    env = cli_env(disable_extractors=True)

    for depth in ("5", "-1"):
        result = run_archivebox_cmd(
            ["add", "--index-only", f"--depth={depth}", "https://example.com"],
            cwd=initialized_archive,
            env=env,
        )
        stderr = result.stderr.lower()
        assert result.returncode != 0
        assert "invalid" in stderr or "not one of" in stderr


def test_add_records_selected_persona_on_crawl(initialized_archive):
    """Test add persists the selected persona so browser config derives from it later."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "--persona=Default", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()

    assert crawl.persona_id
    assert "ACTIVE_PERSONA" not in crawl.config
    assert (initialized_archive / "personas" / "Default" / "chrome_profile").is_dir()


def test_add_duplicate_url_creates_separate_crawls(initialized_archive):
    """Test that adding the same URL twice creates separate crawls.

    Each 'add' command creates a new Crawl. Multiple crawls can archive the same URL.
    This allows re-archiving URLs at different times.
    """

    env = cli_env(disable_extractors=True)
    # Add URL first time
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    # Add same URL second time with --update to opt out of ONLY_NEW.
    run_archivebox_cmd(
        ["add", "--index-only", "--update", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        crawl_count = Crawl.objects.count()
        snapshots = list(Snapshot.objects.order_by("created_at").values_list("url", "depth"))

    # Each add creates a new crawl with its own queued work.
    assert crawl_count == 2
    assert snapshots == [("https://example.com", 0), ("https://example.com", 0)]


def test_snapshot_create_creates_current_output_directory(initialized_archive):
    """Test the user-facing snapshot creation path creates an output directory."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )

    with use_archivebox_db(initialized_archive):
        snapshot_id = str(Snapshot.objects.values_list("id", flat=True).get())

    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot_id)
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"
    assert snapshot_dir.is_dir()


def test_add_preserves_apostrophe_in_snapshot_url(initialized_archive):
    url = "https://aaib.gov.in/What's%20New%20Assets/Preliminary%20Report%20VT-EXO.pdf"
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", url],
        cwd=initialized_archive,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        assert Crawl.objects.get().urls == url
        assert Snapshot.objects.get().url == url


@pytest.mark.timeout(180)
def test_cli_add_real_urls_with_options_writes_inspectable_outputs(initialized_archive):

    wget_urls = [
        "https://example.com",
        "https://pirate.github.io/stress-tests/challenge.html",
    ]
    chrome_url = "https://example.com/?archivebox-chrome-flow=1"
    env = os.environ.copy()
    env.pop("CHROME_BINARY", None)
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
        },
    )
    _cmd_result = run_archivebox_cmd(
        [
            "add",
            "--depth=0",
            "--max-urls=2",
            "--crawl-max-size=10mb",
            "--tag=real-flow,challenge",
            "--parser=url_list",
            "--plugins=wget",
            *wget_urls,
        ],
        cwd=initialized_archive,
        env=env,
        timeout=180,
    )
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout

    chrome_env = env | {
        "SAVE_WGET": "false",
        "SAVE_HEADERS": "true",
        "SAVE_TITLE": "true",
        "CHROME_HEADLESS": "true",
        "CHROME_SANDBOX": "false",
        "CHROME_ISOLATION": "snapshot",
    }
    _cmd_result = run_archivebox_cmd(
        ["install", "chrome"],
        cwd=initialized_archive,
        env=chrome_env,
        timeout=600,
    )
    install_stdout, install_stderr, install_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert install_returncode == 0, install_stderr or install_stdout
    chrome_env.update(resolve_abxpkg_chrome_env(Path(chrome_env["ABXPKG_LIB_DIR"]), chrome_env))
    _cmd_result = run_archivebox_cmd(
        [
            "add",
            "--depth=0",
            "--max-urls=1",
            "--crawl-max-size=10mb",
            "--tag=chrome-flow",
            "--parser=url_list",
            "--plugins=chrome,wget,headers,title",
            chrome_url,
        ],
        cwd=initialized_archive,
        env=chrome_env,
        timeout=180,
    )
    chrome_stdout, chrome_stderr, chrome_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert chrome_returncode == 0, chrome_stderr or chrome_stdout

    _cmd_result = run_archivebox_cmd(
        ["list", "--tag=real-flow"],
        cwd=initialized_archive,
        env=env,
        timeout=60,
    )
    list_stdout, list_stderr, list_returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert list_returncode == 0, list_stderr or list_stdout
    listed = [json.loads(line) for line in list_stdout.splitlines() if line.strip()]
    assert {item["url"] for item in listed} >= set(wget_urls)

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.order_by("-created_at").values_list("max_depth", "tags_str", "config").first()
        real_flow_crawl = Crawl.objects.filter(tags_str="real-flow,challenge").values_list("max_depth", "tags_str", "config").first()
        snapshots = list(Snapshot.objects.order_by("url").values_list("id", "url", "depth", "status", "title"))
        archive_results = list(
            ArchiveResult.objects.select_related("snapshot")
            .order_by("snapshot__url", "plugin")
            .values_list("snapshot__url", "plugin", "status", "output_files", "output_size", "output_str"),
        )
        processes = list(Process.objects.filter(process_type="hook").values_list("process_type", "status", "exit_code", "pwd", "cmd"))

    assert real_flow_crawl is not None
    assert real_flow_crawl[0] == 0
    assert real_flow_crawl[1] == "real-flow,challenge"
    real_flow_config = real_flow_crawl[2] or {}
    assert real_flow_config["CRAWL_MAX_URLS"] == 2
    assert real_flow_config["CRAWL_MAX_SIZE"] == 10 * 1024 * 1024
    assert real_flow_config.get("SNAPSHOT_MAX_SIZE", 0) == 0
    assert "wget" in real_flow_config["PLUGINS"]
    assert crawl is not None
    assert crawl[1] == "chrome-flow"
    assert "wget,headers,title" in json.dumps(crawl[2] or {})

    snapshot_urls = {url for _id, url, _depth, _status, _title in snapshots}
    assert snapshot_urls >= {*wget_urls, chrome_url}
    assert all(depth == 0 for _id, url, depth, _status, _title in snapshots)

    by_url_plugin = {(url, plugin): status for url, plugin, status, _files, _size, _output in archive_results}
    assert by_url_plugin[("https://example.com", "wget")] == "succeeded"
    assert by_url_plugin[("https://pirate.github.io/stress-tests/challenge.html", "wget")] == "succeeded"
    assert by_url_plugin[(chrome_url, "headers")] == "succeeded"
    assert by_url_plugin[(chrome_url, "title")] == "succeeded"
    unexpected_results = [
        (url, plugin, status, output) for url, plugin, status, _files, _size, output in archive_results if status != "succeeded"
    ]
    assert not unexpected_results

    snapshot_root = initialized_archive / "archive/users/system/snapshots"
    html_outputs = [path for path in snapshot_root.rglob("wget/**/*.html") if path.is_file()]
    header_outputs = [path for path in snapshot_root.rglob("headers/**/headers.json") if path.is_file() and path.stat().st_size > 0]
    title_outputs = [path for path in snapshot_root.rglob("title/title.txt") if path.is_file() and path.stat().st_size > 0]
    index_outputs = [path for path in snapshot_root.rglob("index.jsonl") if path.is_file()]
    assert html_outputs
    assert header_outputs
    assert any("example.com" in path.read_text(errors="ignore").lower() for path in header_outputs)
    assert title_outputs
    assert any("Example Domain" in path.read_text(errors="ignore") for path in title_outputs)
    assert len(index_outputs) >= len(wget_urls) + 1

    combined_html = "\n".join(path.read_text(errors="ignore") for path in html_outputs)
    assert "Example Domain" in combined_html
    assert "Browser Agent Challenge for AI Browser Drivers" in combined_html

    assert processes
    assert any("wget" in (pwd or "") or "wget" in (cmd or "") for _type, _status, _exit, pwd, cmd in processes)
    assert any("headers" in (pwd or "") or "headers" in (cmd or "") for _type, _status, _exit, pwd, cmd in processes)
