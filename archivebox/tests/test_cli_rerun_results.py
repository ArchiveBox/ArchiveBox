"""Real hook reruns replace their own results without clearing saved captures first."""

import os
import signal
import time
from contextlib import closing
from threading import Event, Timer

from watchfiles import watch

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import (
    cleanup_process_group,
    cli_env,
    parse_jsonl_output,
    run_archivebox_cmd,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def wait_for_projected_process(archive, parser_id, previous_process_id, *, deadline):
    """A hook's HTTP request can precede its asynchronous DB projection."""
    remaining = deadline - time.monotonic()
    assert remaining > 0, "Timed out before waiting for hook projection"
    stopped = Event()
    timer = Timer(remaining, stopped.set)
    timer.start()
    try:
        # Watch the directory, not a WAL inode that SQLite may replace. Timeout
        # yields also cover a commit between the first read and watcher startup.
        with closing(
            watch(archive, recursive=False, watch_filter=None, yield_on_timeout=True, rust_timeout=1000, stop_event=stopped),
        ) as changes:
            while True:
                with use_archivebox_db(archive):
                    parser = ArchiveResult.objects.select_related("process").get(pk=parser_id)
                if parser.process_id != previous_process_id:
                    return parser
                assert not stopped.is_set(), "Hook did not project its new Process before the phase deadline"
                if next(changes, None) is None:
                    raise AssertionError("Hook did not project its new Process before the phase deadline")
    finally:
        timer.cancel()
        timer.join()


def test_extract_rerun_overwrites_failed_result_only_as_hook_executes(initialized_archive, blocking_http_server):
    """Interrupt a real parser, then rerun the same row to a real noresults outcome."""
    env = cli_env(PLUGINS="parse_txt_urls,hashes", HASHES_ENABLED="True")
    created = run_archivebox_cmd(
        ["snapshot", "create", blocking_http_server.url],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    snapshot_id = next(record["id"] for record in parse_jsonl_output(created.stdout) if record.get("type") == "Snapshot")
    with use_archivebox_db(initialized_archive):
        snapshot_dir = Snapshot.objects.get(pk=snapshot_id).output_dir

    source = snapshot_dir / "staticfile" / "links.txt"
    source.parent.mkdir(parents=True)
    source.write_text("https://example.com/previous-capture\n", encoding="utf-8")
    captured = run_archivebox_cmd(
        ["extract", "--plugins=parse_txt_urls,hashes", snapshot_id],
        cwd=initialized_archive,
        env=env,
        timeout=90,
    )
    assert captured.returncode == 0, captured.stderr or captured.stdout
    with use_archivebox_db(initialized_archive):
        parser = ArchiveResult.objects.get(snapshot_id=snapshot_id, plugin="parse_txt_urls")
        assert parser.status == ArchiveResult.StatusChoices.SUCCEEDED
        assert parser.output_str == "1 URLs parsed"
        parser_id = parser.pk
        initial_process_id = parser.process_id
        unrelated_result = ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin="hashes").values().get()
        assert unrelated_result["status"] == ArchiveResult.StatusChoices.SUCCEEDED

    urls_path = snapshot_dir / "parse_txt_urls" / "urls.jsonl"
    previous_output = urls_path.read_bytes()
    hashes_path = snapshot_dir / "hashes" / "hashes.json"
    previous_hashes = hashes_path.read_bytes()
    assert previous_output and previous_hashes

    # Without a saved text input, the shipped parser fetches the snapshot URL.
    # The existing HTTP fixture lets us inspect a genuinely running hook before
    # its response completes, without modifying the hook or its dependencies.
    source.unlink()
    interrupted = run_archivebox_cmd(
        ["extract", "--plugins=parse_txt_urls", snapshot_id],
        cwd=initialized_archive,
        env=env,
        wait=False,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        assert blocking_http_server.request_started.wait(max(0, deadline - time.monotonic())), "Parser did not request the snapshot URL"
        parser = wait_for_projected_process(initialized_archive, parser_id, initial_process_id, deadline=deadline)
        assert parser.status == ArchiveResult.StatusChoices.STARTED
        # A waiter arriving after the commit must not need another WAL event.
        assert (
            wait_for_projected_process(initialized_archive, parser_id, initial_process_id, deadline=deadline).process_id
            == parser.process_id
        )
        hook_pid = parser.process.pid
        assert urls_path.read_bytes() == previous_output
        os.kill(hook_pid, signal.SIGKILL)
        stdout, stderr = interrupted.communicate(timeout=30)
        assert interrupted.returncode == 0, stderr or stdout
    except BaseException:
        blocking_http_server.release_response.set()
        raise
    finally:
        cleanup_process_group(interrupted.pid)

    with use_archivebox_db(initialized_archive):
        parser = ArchiveResult.objects.get(pk=parser_id)
        assert parser.status == ArchiveResult.StatusChoices.FAILED
        failed_process_id = parser.process_id
        failed_result = ArchiveResult.objects.filter(pk=parser_id).values().get()
    assert urls_path.read_bytes() == previous_output

    queued = run_archivebox_cmd(
        ["extract", "--no-wait", "--plugins=parse_txt_urls", snapshot_id],
        cwd=initialized_archive,
        env=env,
    )
    assert queued.returncode == 0, queued.stderr or queued.stdout
    with use_archivebox_db(initialized_archive):
        assert ArchiveResult.objects.filter(pk=parser_id).values().get() == failed_result
        assert ArchiveResult.objects.filter(pk=unrelated_result["id"]).values().get() == unrelated_result
    assert urls_path.read_bytes() == previous_output
    assert hashes_path.read_bytes() == previous_hashes

    blocking_http_server.request_started.clear()
    rerun = run_archivebox_cmd(
        ["extract", "--plugins=parse_txt_urls", snapshot_id],
        cwd=initialized_archive,
        env=env,
        wait=False,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 30
        assert blocking_http_server.request_started.wait(max(0, deadline - time.monotonic())), "Rerun did not request the snapshot URL"
        parser = wait_for_projected_process(initialized_archive, parser_id, failed_process_id, deadline=deadline)
        assert parser.status == ArchiveResult.StatusChoices.STARTED
        assert parser.process_id != failed_process_id
        with use_archivebox_db(initialized_archive):
            assert ArchiveResult.objects.filter(pk=unrelated_result["id"]).values().get() == unrelated_result
        assert urls_path.read_bytes() == previous_output
        assert hashes_path.read_bytes() == previous_hashes
        blocking_http_server.release_response.set()
        stdout, stderr = rerun.communicate(timeout=30)
        assert rerun.returncode == 0, stderr or stdout
    finally:
        blocking_http_server.release_response.set()
        cleanup_process_group(rerun.pid)

    result = next(
        record
        for record in parse_jsonl_output(stdout)
        if record.get("type") == "ArchiveResult" and record.get("plugin") == "parse_txt_urls"
    )
    assert result["id"] == str(parser_id)
    assert result["status"] == ArchiveResult.StatusChoices.NORESULTS
    assert result["output_str"] == "0 URLs parsed"
    with use_archivebox_db(initialized_archive):
        parser = ArchiveResult.objects.get(pk=parser_id)
        assert parser.status == ArchiveResult.StatusChoices.NORESULTS
        assert parser.output_str == "0 URLs parsed"
        assert parser.output_files == {}
        assert parser.output_size == 0
        assert parser.notes == ""
        assert ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin="parse_txt_urls").count() == 1
        assert ArchiveResult.objects.filter(pk=unrelated_result["id"]).values().get() == unrelated_result
    assert not urls_path.exists()
    assert hashes_path.read_bytes() == previous_hashes


def test_projection_wait_expires_when_process_identity_does_not_change(initialized_archive):
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.create(urls="https://example.com/projection-deadline")
        snapshot = Snapshot.objects.create(url="https://example.com/projection-deadline", crawl=crawl)
        parser = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin="parse_txt_urls",
            hook_name="on_Snapshot__parse",
            status=ArchiveResult.StatusChoices.SUCCEEDED,
        )
        parser_id = parser.pk
    with pytest.raises(AssertionError, match="phase deadline"):
        wait_for_projected_process(initialized_archive, parser_id, None, deadline=time.monotonic() + 0.1)
