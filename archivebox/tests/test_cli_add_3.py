#!/usr/bin/env python3
"""
Comprehensive tests for archivebox add command.
Verify add creates snapshots in DB, crawls, source files, and archive directories.
"""

import os
import pty
import select
import time
import termios
import signal
import re
import subprocess

import psutil
from pathlib import Path

import pytest
from django.utils import timezone

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.crawls.models import Crawl
from archivebox.machine.models import Process
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


@pytest.mark.parametrize("choice", ["skip", "retry", "ctrl-c", "double", "noninteractive"])
def test_add_interrupts_background_only_capture(initialized_archive, choice):
    """Neither pause nor abort/reclaim semantics may depend on a foreground hook."""
    master, slave = pty.openpty()
    termios.tcsetwinsize(slave, (40, 200))
    output = bytearray()
    result = None

    def read_until(predicate, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.05)[0]:
                output.extend(os.read(master, 65536))
            if predicate():
                return
        raise AssertionError(output.decode(errors="replace"))

    def active_hook():
        with use_archivebox_db(initialized_archive):
            return Process.objects.filter(archiveresult__plugin="forumdl", status="running").order_by("-started_at").first()

    try:
        result = run_archivebox_cmd(
            ["add", "--depth=1", "--plugins=forumdl", "https://news.ycombinator.com"],
            cwd=initialized_archive,
            env=cli_env(),
            stdin=subprocess.DEVNULL if choice == "noninteractive" else slave,
            stdout=slave,
            stderr=slave,
            wait=False,
            start_new_session=True,
        )
        read_until(lambda: active_hook() is not None)
        hook = active_hook()
        children = psutil.Process(result.pid).children(recursive=True)
        result.send_signal(signal.SIGINT)
        if choice == "double":
            read_until(lambda: b"Forwarding Ctrl+C" in output)
            result.send_signal(signal.SIGINT)
        elif choice != "noninteractive":
            read_until(lambda: b"Choice [skip]:" in output, timeout=20)
            read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            assert not psutil.pid_exists(hook.pid)
            if choice == "retry":
                os.write(master, b"r")
                read_until(lambda: (next_hook := active_hook()) is not None and next_hook.pid != hook.pid)
                children.extend(psutil.Process(result.pid).children(recursive=True))
                offset = len(output)
                result.send_signal(signal.SIGINT)
                read_until(lambda: b"Choice [skip]:" in output[offset:], timeout=20)
                read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
            os.write(master, b"\r" if choice == "skip" else b"\x03")
        read_until(lambda: result.poll() is not None, timeout=30)
        assert result.returncode == (0 if choice == "skip" else 130), output.decode(errors="replace")
        assert not [child.pid for child in children if child.is_running() and child.status() != psutil.STATUS_ZOMBIE]
        assert not psutil.pid_exists(hook.pid)
        assert b"Traceback" not in output
        if choice == "noninteractive":
            assert b"Choice [skip]:" not in output
        # An explicit abort must not be mistaken for takeover and restart work.
        with use_archivebox_db(initialized_archive):
            assert Process.objects.filter(worker_type="worker_runner", process_type="orchestrator").count() == 1
        if choice != "skip":
            assert b"Aborting crawl" in output
    finally:
        if result is not None and result.poll() is None:
            result.terminate()
            result.wait(timeout=20)
        os.close(slave)
        os.close(master)


def test_background_completions_render_above_interrupt_prompt(initialized_archive):
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
            ["add", "--depth=1", "--plugins=wget,infiniscroll,parse_html_urls", "https://example.com"],
            cwd=initialized_archive,
            env=cli_env(WGET_ARGS_EXTRA='["--limit-rate=100"]', INFINISCROLL_SCROLL_DELAY="10000", CHROME_HEADLESS="True"),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            wait=False,
            start_new_session=True,
        )
        read_until(lambda: (scroll := result_for("infiniscroll")) is not None and scroll.status == "started")
        result.send_signal(signal.SIGINT)
        read_until(lambda: b"Choice [skip]:" in output)
        read_until(lambda: not termios.tcgetattr(slave)[3] & termios.ICANON)
        before_completion = len(output)
        read_until(lambda: (wget := result_for("wget")) is not None and wget.status == "succeeded")
        read_until(lambda: b"Choice [skip]:" in output[before_completion:])
        screen_updates = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output[before_completion:].decode(errors="replace"))
        completed_at = screen_updates.index("on_Snapshot__35_wget")
        prompt_at = screen_updates.rindex("Interrupted on_Snapshot__45_infiniscroll")
        assert "succeeded" in screen_updates[completed_at:prompt_at], screen_updates
        assert completed_at < prompt_at < screen_updates.rindex("Choice [skip]:"), screen_updates
        assert result_for("parse_html_urls") is None
        (initialized_archive / "interrupt-terminal.txt").write_bytes(output)
        os.write(master, b"a")
        read_until(lambda: result.poll() is not None)
        assert result.returncode == 130, output.decode(errors="replace")
        assert b"Traceback" not in output
    finally:
        if result is not None and result.poll() is None:
            result.terminate()
            result.wait(timeout=15)
        os.close(slave)
        os.close(master)


def test_add_summary_points_to_snapshot_outputs(initialized_archive):
    result = run_archivebox_cmd(
        ["add", "--plugins=parse_txt_urls", "https://example.com"],
        cwd=initialized_archive,
        env=cli_env(),
    )
    assert result.returncode == 0, result.stderr
    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.get()
        assert Path(snapshot.output_dir).is_dir()
        assert str(snapshot.output_dir) in result.stdout
        assert "snapshot output saved to:" in result.stdout
        assert "crawl logs and setup:" in result.stdout
        assert "crawl output saved to:" not in result.stdout


def test_initial_crawl_creation_does_not_warn_as_an_outside_runner_update(initialized_archive, caplog):
    from archivebox.core.takeover_util import current_command

    with use_archivebox_db(initialized_archive):
        command = current_command(Process.TypeChoices.ADD, data_dir=initialized_archive)
        caplog.clear()
        with caplog.at_level("WARNING", logger="archivebox.workers.models"):
            crawl = Crawl.objects.create(urls="https://example.com", status=Crawl.StatusChoices.QUEUED)
        assert "Crawl.save() outside runner process" not in caplog.text

        caplog.clear()
        with caplog.at_level("WARNING", logger="archivebox.workers.models"):
            crawl.save(update_fields=["modified_at"])
        command.mark_exited(exit_code=0)

    assert "Crawl.save() outside runner process" in caplog.text


@pytest.mark.timeout(240)
def test_add_rejects_file_path_and_shell_injection_payloads(initialized_archive):
    """CLI add must not turn user-supplied local paths or shell payloads into snapshots."""
    safe_url = "https://example.com/?archivebox-cli-security=1"
    inputs, canary = malicious_add_inputs(initialized_archive, safe_url=safe_url)
    env = cli_env(**IMPORT_FORMAT_ENV)

    result = run_archivebox_cmd(
        ["add", "--bg", "--depth=0", "--tag=cli-security"],
        cwd=initialized_archive,
        env=env,
        stdin="\n".join(inputs),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    run_queued_crawls(initialized_archive, env=env, timeout=120)
    assert_expected_import_snapshots(initialized_archive, {safe_url})

    assert_no_file_or_shell_payload_snapshots(initialized_archive, canary=canary)
    with use_archivebox_db(initialized_archive):
        snapshots = list(Snapshot.objects.filter(url=safe_url).values_list("url", "status", "tags__name"))
        crawl = Crawl.objects.get()
    assert crawl.status in {Crawl.StatusChoices.STARTED, Crawl.StatusChoices.SEALED}
    assert len({url for url, _status, _tag in snapshots}) == 1
    assert all(
        status in {Snapshot.StatusChoices.QUEUED, Snapshot.StatusChoices.STARTED, Snapshot.StatusChoices.SEALED}
        for _url, status, _tag in snapshots
    )
    assert "cli-security" in {tag for _url, _status, tag in snapshots}


@pytest.mark.timeout(180)
def test_run_rejects_depth_two_file_url_snapshot_injected_directly_with_db_update(initialized_archive):
    """A queued Snapshot row with a file:// URL must not be allowed to run hooks or recurse."""
    secret_url = "https://example.com/?archivebox-sql-depth2-file-secret=1"
    local_source = initialized_archive / "not_owned_by_depth_two_snapshot.txt"
    local_source.write_text(f"{secret_url}\n", encoding="utf-8")
    file_url = local_source.resolve().as_uri()
    env = cli_env(**{**IMPORT_FORMAT_ENV, "PLUGINS": "parse_txt_urls", "SAVE_HEADERS": "False", "SAVE_WGET": "False"})

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(
            urls="https://example.com/?archivebox-sql-depth2-root=1",
            max_depth=2,
            tags_str="sql-depth2-file-url",
            status=Crawl.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        root_snapshot = Snapshot.objects.create(
            url="https://example.com/?archivebox-sql-depth2-root=1",
            crawl=crawl,
            depth=0,
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
        )
        injected_snapshot = Snapshot.objects.create(
            url="https://example.com/?archivebox-sql-depth2-placeholder=1",
            crawl=crawl,
            parent_snapshot=root_snapshot,
            depth=2,
            status=Snapshot.StatusChoices.QUEUED,
            retry_at=timezone.now(),
        )
        Snapshot.objects.filter(pk=injected_snapshot.pk).update(url=file_url)

    result = run_archivebox_cmd(
        ["run", f"--snapshot-id={injected_snapshot.id}"],
        cwd=initialized_archive,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        injected_snapshot.refresh_from_db()
        snapshot_urls = set(Snapshot.objects.values_list("url", flat=True))
        file_results = list(
            ArchiveResult.objects.filter(
                snapshot=injected_snapshot,
            ).values_list("plugin", "status"),
        )

    assert injected_snapshot.url == file_url
    assert secret_url not in snapshot_urls
    assert file_results == []


def test_add_index_only_rejected_urls_leave_empty_crawl_for_runner_to_seal(initialized_archive):
    """Index-only add only creates the crawl; rejected URLs are sealed by the runner."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        [
            "add",
            "--index-only",
            "--depth=0",
            "--url-denylist=example.com",
            "https://example.com",
        ],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_urls = set(Snapshot.objects.values_list("url", flat=True))

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert crawl.urls == "https://example.com"
    assert snapshot_urls == set()

    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_urls = set(Snapshot.objects.values_list("url", flat=True))

    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None
    assert crawl.urls == "https://example.com"
    assert snapshot_urls == set()


def test_add_index_only_rejects_archivebox_internal_urls(initialized_archive):
    """Index-only add must apply the same internal URL guard as snapshot creation."""
    env = cli_env(disable_extractors=True)
    internal_urls = [
        "http://archivebox.localhost:9292/admin/",
        "http://web.archivebox.localhost:9292/",
        "http://api.archivebox.localhost:9292/api/v1/docs",
        "http://snap-2fb8e923c58c.archivebox.localhost:9292/index.html",
    ]
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", *internal_urls],
        cwd=initialized_archive,
        env={**env, "BASE_URL": "http://archivebox.localhost:9292"},
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshot_urls = set(Snapshot.objects.values_list("url", flat=True))

    assert crawl.urls.splitlines() == internal_urls
    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert snapshot_urls == set()


def test_add_multiple_urls_single_command(initialized_archive):
    """Test adding multiple URLs in a single command records one crawl."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com", "https://example.org"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshots = list(Snapshot.objects.order_by("url").values_list("url", "depth"))

    assert crawl.urls.splitlines() == ["https://example.com", "https://example.org"]
    assert snapshots == []


def test_add_with_tags(initialized_archive):
    """Test adding URL with tags stores tags_str in crawl.

    With --index-only, Tag objects are not created until archiving happens.
    Tags are stored as a string in the Crawl.tags_str field.
    """
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "--tag=test,example", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    with use_archivebox_db(initialized_archive):
        tags_str = Crawl.objects.values_list("tags_str", flat=True).get()

    # Tags are stored as a comma-separated string in crawl
    assert "test" in tags_str or "example" in tags_str


def test_add_with_overwrite_flag(initialized_archive):
    """Test that --overwrite flag forces re-archiving."""
    env = cli_env(disable_extractors=True)

    # Add URL first time
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    # Add with overwrite
    result = run_archivebox_cmd(
        ["add", "--index-only", "--overwrite", "https://example.com"],
        cwd=initialized_archive,
        env=env,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --overwrite" not in result.stderr


def test_add_index_only_queues_crawl_without_starting_runner(initialized_archive):
    """Test that --index-only creates only a queued crawl and returns fast."""
    env = cli_env(disable_extractors=True)
    result = run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        timeout=30,  # Should be fast
    )

    assert result.returncode == 0

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.get()
        snapshots = list(Snapshot.objects.all())

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert crawl.urls == "https://example.com"
    assert snapshots == []
