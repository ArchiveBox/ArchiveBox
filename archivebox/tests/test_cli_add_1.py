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
import subprocess

import psutil
from pathlib import Path

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
from archivebox.tests.conftest import (
    cli_env,
    run_archivebox_cmd,
)

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


IMPORT_FORMAT_EXPECTATIONS = {
    "rss": {
        "url": "https://example.com/",
        "title": "RSS Example Import",
        "date": "2024-01-01",
        "tags": {"rss-tag", "metadata"},
    },
    "netscape": {
        "url": "https://www.iana.org/domains/reserved",
        "title": "IANA Reserved Domains",
        "date": "2024-01-02",
        "tags": {"netscape-tag", "metadata"},
    },
    "dom": {
        "url": "https://www.iana.org/help/example-domains",
    },
    "json": {
        "url": "https://example.com/?archivebox-json-import=1",
        "title": "JSON Import Example",
        "date": "2024-01-03",
        "tags": {"json-tag", "metadata"},
    },
    "jsonl": {
        "url": "https://example.com/?archivebox-jsonl-import=1",
        "title": "JSONL Import Example",
        "date": "2024-01-04",
        "tags": {"jsonl-tag", "metadata"},
    },
    "txt": {
        "url": "https://example.org/",
    },
}


def write_import_format_files(base_dir: Path) -> dict[str, Path]:
    files = {
        "rss": base_dir / "test_rss.xml",
        "netscape": base_dir / "test_netscape.html",
        "dom": base_dir / "test_dom.html",
        "json": base_dir / "test_bookmarks.json",
        "jsonl": base_dir / "test_bookmarks.jsonl",
        "txt": base_dir / "test_urls.txt",
    }
    files["rss"].write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ArchiveBox RSS import fixture</title>
    <link>https://example.com/</link>
    <description>ArchiveBox RSS import fixture</description>
    <item>
      <title>RSS Example Import</title>
      <link>https://example.com/</link>
      <guid>https://example.com/</guid>
      <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
      <category>rss-tag</category>
      <category>metadata</category>
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )
    files["netscape"].write_text(
        """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
  <DT><A HREF="https://www.iana.org/domains/reserved" ADD_DATE="1704153600" TAGS="netscape-tag,metadata">IANA Reserved Domains</A>
</DL><p>
""",
        encoding="utf-8",
    )
    files["dom"].write_text(
        """<!doctype html>
<html>
  <head><title>DOM import fixture</title></head>
  <body>
    <a href="https://www.iana.org/help/example-domains">IANA Example Domains</a>
  </body>
</html>
""",
        encoding="utf-8",
    )
    files["json"].write_text(
        json.dumps(
            {
                "url": "https://example.com/?archivebox-json-import=1",
                "title": "JSON Import Example",
                "tags": ["json-tag", "metadata"],
                "bookmarked_at": "2024-01-03T00:00:00+00:00",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    files["jsonl"].write_text(
        json.dumps(
            {
                "url": "https://example.com/?archivebox-jsonl-import=1",
                "title": "JSONL Import Example",
                "tags": "jsonl-tag,metadata",
                "bookmarked_at": "2024-01-04T00:00:00+00:00",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    files["txt"].write_text(
        "Plain text import fixture containing https://example.org/ as a real live URL.\n",
        encoding="utf-8",
    )
    return files


IMPORT_FORMAT_ENV = {
    "USE_COLOR": "False",
    "SHOW_PROGRESS": "False",
    "PLUGINS": "parse_html_urls,parse_jsonl_urls,parse_netscape_urls,parse_rss_urls,parse_txt_urls",
    "SAVE_WGET": "False",
    "SAVE_HEADERS": "False",
    "USE_CHROME": "False",
    "URL_ALLOWLIST": r"example\.com|example\.org|iana\.org|www\.iana\.org",
}


def assert_expected_import_snapshots(cwd: Path, expected_urls: set[str]) -> None:
    allowed_statuses = {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
    with use_archivebox_db(cwd):
        rows = list(Snapshot.objects.filter(url__in=expected_urls).values_list("url", "status"))
    counts = {url: 0 for url in expected_urls}
    bad_statuses = []
    for url, status in rows:
        counts[url] += 1
        if status not in allowed_statuses:
            bad_statuses.append((url, status))
    assert all(count == 1 for count in counts.values()), counts
    assert not bad_statuses, bad_statuses


def malicious_add_inputs(tmp_path: Path, *, safe_url: str) -> tuple[list[str], Path]:
    other_crawl_source = tmp_path / "sources" / "other_crawl_source.txt"
    other_crawl_source.parent.mkdir(parents=True, exist_ok=True)
    other_crawl_source.write_text("https://example.com/not-owned-by-this-crawl\n", encoding="utf-8")
    canary = tmp_path / "archivebox_shell_injection_canary"
    return (
        [
            safe_url,
            "file:///etc/hosts",
            "/etc/hosts",
            "../../../../etc/passwd",
            f"file://{other_crawl_source}",
            str(other_crawl_source),
            f"'; touch {canary}; #",
            f'" && touch {canary} && echo "',
            f"$(touch {canary})",
            f"`touch {canary}`",
            """<?xml version="1.0"?>
<!DOCTYPE rss [
  <!ENTITY localfile SYSTEM "file:///etc/hosts">
]>
<rss version="2.0" xmlns:xi="http://www.w3.org/2001/XInclude">
  <channel>
    <item><title>&localfile;</title><link>file:///etc/passwd</link></item>
    <xi:include href="file:///etc/hosts" parse="text"/>
  </channel>
</rss>""",
        ],
        canary,
    )


def assert_no_file_or_shell_payload_snapshots(cwd: Path, *, canary: Path) -> None:
    with use_archivebox_db(cwd):
        snapshots = list(Snapshot.objects.all())
    assert not canary.exists()
    assert not [snapshot.url for snapshot in snapshots if str(snapshot.url).startswith("file:")]
    for forbidden in ("/etc/hosts", "/etc/passwd", "other_crawl_source", "archivebox_shell_injection_canary"):
        assert not [snapshot.url for snapshot in snapshots if forbidden in str(snapshot.url)]


@pytest.mark.parametrize(
    "choice,plugins",
    [(choice, "chrome") for choice in ["skip", "retry", "abort", "ctrl-c", "noninteractive"]] + [("noninteractive", "archivewebpage")],
)
def test_add_interrupts_active_hook(initialized_archive, choice, plugins):
    env = cli_env(CHROME_DELAY_AFTER_LOAD="60", CHROME_TIMEOUT="120", CHROME_HEADLESS="True")
    # The timed observation below is for a running navigate hook. Resolve the
    # selected plugin's real binaries before starting it, so a cold install is
    # not counted as a hook-start failure.
    installed = run_archivebox_cmd(["install", plugins], cwd=initialized_archive, env=env, timeout=600)
    assert installed.returncode == 0, installed.stderr or installed.stdout

    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, 160))
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

    def active_hook():
        with use_archivebox_db(initialized_archive):
            navigating = (
                ArchiveResult.objects.select_related("process")
                .filter(
                    hook_name="on_Snapshot__30_chrome_navigate",
                    status=ArchiveResult.StatusChoices.STARTED,
                    process__status=Process.StatusChoices.RUNNING,
                )
                .first()
            )
            return navigating.process if navigating else None

    def navigation_result():
        with use_archivebox_db(initialized_archive):
            return ArchiveResult.objects.filter(hook_name="on_Snapshot__30_chrome_navigate").values().get()

    try:
        result = run_archivebox_cmd(
            ["add", f"--plugins={plugins}", "https://example.com"],
            cwd=initialized_archive,
            env=env,
            stdin=subprocess.DEVNULL if choice == "noninteractive" else slave,
            stdout=slave,
            stderr=slave,
            wait=False,
            start_new_session=True,
        )
        read_until(lambda: active_hook() is not None)
        hook = active_hook()
        assert hook is not None
        before_interrupt = navigation_result()
        result.send_signal(signal.SIGINT)
        if choice != "noninteractive":
            read_until(lambda: b"Choice [skip]:" in output)
            read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            assert not psutil.pid_exists(hook.pid)
            assert navigation_result() == before_interrupt
            if choice == "retry":
                os.write(master, b"r")
                read_until(lambda: (new_hook := active_hook()) is not None and new_hook.pid != hook.pid)
                retry_result = navigation_result()
                assert retry_result["id"] == before_interrupt["id"]
                assert retry_result["process_id"] != before_interrupt["process_id"]
                for field in ("output_str", "output_json", "output_files", "output_size", "output_mimetypes", "notes"):
                    assert retry_result[field] == before_interrupt[field]
                before_interrupt = retry_result
                prompt_offset = len(output)
                result.send_signal(signal.SIGINT)
                read_until(lambda: b"Choice [skip]:" in output[prompt_offset:])
                read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            if choice == "ctrl-c":
                result.send_signal(signal.SIGINT)
            else:
                os.write(master, b"a" if choice == "abort" else b"\r")
        read_until(lambda: result.poll() is not None)
        assert result.returncode == (130 if choice in {"abort", "ctrl-c", "noninteractive"} else 0), output.decode(errors="replace")
        if choice == "noninteractive":
            assert b"Choice [skip]:" not in output
        assert not psutil.pid_exists(hook.pid)
        assert b"Traceback" not in output
        # Cancellation has no new capture outcome: preserve the entire same row,
        # including its output metadata, instead of deleting or reconstructing it.
        assert navigation_result() == before_interrupt
        with use_archivebox_db(initialized_archive):
            if plugins == "archivewebpage":
                start = ArchiveResult.objects.get(hook_name="on_Snapshot__16_archivewebpage_start")
                assert start.status == ArchiveResult.StatusChoices.NORESULTS
                assert not ArchiveResult.objects.filter(hook_name="on_Snapshot__65_archivewebpage_stop").exists()
                assert not ArchiveResult.objects.filter(plugin="archivewebpage", status="succeeded").exists()
                assert not any(output["name"] == "archivewebpage" for output in start.snapshot.get_html_details_context()["archiveresults"])
        for log in (initialized_archive / "logs").glob("worker_runner_add_*.log"):
            assert "Choice [skip]:" not in log.read_text()

        rerun = run_archivebox_cmd(
            ["extract", f"--plugins={plugins}", str(before_interrupt["snapshot_id"])],
            cwd=initialized_archive,
            env=env,
            timeout=90,
        )
        assert rerun.returncode == 0, rerun.stdout + rerun.stderr
        after_rerun = navigation_result()
        assert after_rerun["id"] == before_interrupt["id"]
        assert after_rerun["process_id"] != before_interrupt["process_id"]
        assert after_rerun["status"] == ArchiveResult.StatusChoices.SUCCEEDED
        assert after_rerun["notes"] == ""
        with use_archivebox_db(initialized_archive):
            snapshot_dir = Snapshot.objects.get(pk=before_interrupt["snapshot_id"]).output_dir
        navigation = json.loads((snapshot_dir / "chrome" / "navigation.json").read_text())
        assert navigation["url"] == "https://example.com"
        assert navigation["status"] == 200
    finally:
        if result is not None and result.poll() is None:
            result.terminate()
            result.wait(timeout=15)
        os.close(slave)
        os.close(master)


def test_add_single_url_records_url_in_crawl(initialized_archive):
    """Test that adding a single URL queues a crawl with the submitted URL."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0
    assert "Crawl.save() outside runner process" not in result.stderr

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshots = list(Snapshot.objects.all())

    assert crawl.urls == "https://example.com"
    assert crawl.get_urls_list() == ["https://example.com"]
    assert snapshots == []


def test_add_with_depth_0_flag(initialized_archive):
    """Test that --depth=0 flag is accepted and works."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --depth" not in result.stderr


def test_add_records_max_url_and_size_limits_on_crawl(initialized_archive):
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        [
            "add",
            "--index-only",
            "--depth=1",
            "--max-urls=3",
            "--crawl-max-size=45mb",
            "--crawl-timeout=120",
            "--snapshot-max-size=5mb",
            "https://example.com",
        ],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    columns = {field.name for field in Crawl._meta.local_fields}
    with use_archivebox_db(initialized_archive):
        config = Crawl.objects.values_list("config", flat=True).get() or {}

    assert {"max_urls", "crawl_max_size", "crawl_timeout", "snapshot_max_size"}.isdisjoint(columns)
    assert config["CRAWL_MAX_URLS"] == 3
    assert config["CRAWL_MAX_SIZE"] == 45 * 1024 * 1024
    assert config["CRAWL_TIMEOUT"] == 120
    assert config["SNAPSHOT_MAX_SIZE"] == 5 * 1024 * 1024


def test_add_without_args_shows_usage(initialized_archive):
    """Test that add without URLs fails with a usage hint instead of crashing."""

    result = run_archivebox_cmd(
        ["add"],
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "usage" in combined.lower() or "url" in combined.lower()
