"""Real hook reruns replace their own results without clearing saved captures first."""

import os
import signal

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
        assert blocking_http_server.request_started.wait(30), "Parser did not request the snapshot URL"
        with use_archivebox_db(initialized_archive):
            parser = ArchiveResult.objects.select_related("process").get(pk=parser_id)
            assert parser.status == ArchiveResult.StatusChoices.STARTED
            hook_pid = parser.process.pid
        assert urls_path.read_bytes() == previous_output
        os.kill(hook_pid, signal.SIGKILL)
        stdout, stderr = interrupted.communicate(timeout=30)
        assert interrupted.returncode == 0, stderr or stdout
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
        assert blocking_http_server.request_started.wait(30), "Rerun did not request the snapshot URL"
        with use_archivebox_db(initialized_archive):
            parser = ArchiveResult.objects.get(pk=parser_id)
            assert parser.status == ArchiveResult.StatusChoices.STARTED
            assert parser.process_id != failed_process_id
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
