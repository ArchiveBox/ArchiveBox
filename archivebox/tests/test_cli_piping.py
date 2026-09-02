"""
Tests for JSONL piping contracts and `archivebox run`.

This file covers both:
- low-level JSONL/stdin parsing behavior that makes CLI piping work
- subprocess integration for the supported records `archivebox run` consumes
"""

import os
import pty
import sys
import uuid
from importlib.resources import files
from pathlib import Path

import pytest

from archivebox.core.models import Snapshot
from archivebox.machine.models import Binary
from archivebox.tests.conftest import (
    assert_jsonl_only,
    create_test_url,
    parse_jsonl_output,
    run_archivebox_cmd,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


PIPE_TEST_ENV = {
    "PLUGINS": "favicon",
    "SAVE_FAVICON": "True",
    "USE_COLOR": "False",
    "SHOW_PROGRESS": "False",
}


def run_real_txt_parser(tmp_path, text):
    """Run the shipped text parser and return its real snapshot output directory."""
    from archivebox.tests.conftest import run_test_hook

    snap_dir = tmp_path / "parser-snapshot"
    staticfile_dir = snap_dir / "staticfile"
    output_dir = snap_dir / "parse_txt_urls"
    staticfile_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    (staticfile_dir / "input.txt").write_text(text, encoding="utf-8")
    hook_path = Path(str(files("abx_plugins.plugins.parse_txt_urls").joinpath("on_Snapshot__71_parse_txt_urls.py")))
    process = run_test_hook(
        hook_path,
        output_dir,
        config={"ABXPKG_LIB_DIR": str(tmp_path / "lib"), "SNAP_DIR": str(snap_dir)},
        timeout=30,
        url="file:///input.txt",
        depth=0,
    )
    process.refresh_from_db()
    assert process.exit_code == 0, process.stderr
    return snap_dir


def test_parse_line_accepts_supported_piping_inputs():
    """The JSONL parser should normalize the input forms CLI pipes accept."""
    from archivebox.misc.jsonl import TYPE_SNAPSHOT, parse_line

    assert parse_line("") is None
    assert parse_line("   ") is None
    assert parse_line("# comment") is None
    assert parse_line("not-a-url") is None
    assert parse_line("ftp://example.com") is None

    plain_url = parse_line("https://example.com")
    assert plain_url == {"type": TYPE_SNAPSHOT, "url": "https://example.com"}

    assert parse_line("file:///tmp/example.txt") is None


def test_read_args_or_stdin_handles_args_stdin_and_mixed_jsonl(tmp_path, initialized_archive):
    """Piping helpers should consume args, structured JSONL, and pass-through records."""
    from archivebox.misc.jsonl import TYPE_CRAWL, read_args_or_stdin

    records = list(read_args_or_stdin(("https://example1.com", "https://example2.com")))
    assert [record["url"] for record in records] == ["https://example1.com", "https://example2.com"]

    local_file = tmp_path / "urls.txt"
    local_file.write_text("https://from-file-arg.example\n")
    assert list(read_args_or_stdin((str(local_file),))) == []

    snapshot_result = run_archivebox_cmd(
        ["snapshot", "create", "--tag=test", "https://jsonl-url.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
        check=True,
    )
    crawl_result = run_archivebox_cmd(
        ["crawl", "create", "https://crawl-url.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
        check=True,
    )
    snapshot_record = next(record for record in parse_jsonl_output(snapshot_result.stdout) if record.get("type") == "Snapshot")

    read_fd, write_fd = os.pipe()
    os.write(
        write_fd,
        f"https://plain-url.com\n{snapshot_result.stdout}{crawl_result.stdout}{snapshot_record['id']}\nnot valid json\n".encode(),
    )
    os.close(write_fd)
    with os.fdopen(read_fd, encoding="utf-8") as pipe_stream:
        assert pipe_stream.isatty() is False
        stdin_records = list(read_args_or_stdin((), stream=pipe_stream))
    assert any(record.get("url") == "https://plain-url.com" for record in stdin_records)
    assert any(record.get("type") == "Snapshot" and record.get("id") == snapshot_record["id"] for record in stdin_records)
    assert any(record.get("type") == TYPE_CRAWL and record.get("urls") == "https://crawl-url.com" for record in stdin_records)
    assert any(
        record.get("type") == "Snapshot" and record.get("id") == snapshot_record["id"] and len(record) == 2 for record in stdin_records
    )

    master_fd, slave_fd = pty.openpty()
    try:
        with os.fdopen(slave_fd, encoding="utf-8") as tty_stream:
            assert tty_stream.isatty() is True
            assert list(read_args_or_stdin((), stream=tty_stream)) == []
    finally:
        os.close(master_fd)


def test_collect_urls_from_plugins_reads_only_parser_outputs(tmp_path):
    """Parser extractor `urls.jsonl` outputs should be discoverable for recursive piping."""
    from archivebox.plugins.hooks import collect_urls_from_plugins

    snap_dir = run_real_txt_parser(tmp_path, "https://html-link-1.com https://html-link-2.com")
    (snap_dir / "screenshot").mkdir()

    urls = collect_urls_from_plugins(snap_dir)
    assert {url["url"] for url in urls} == {"https://html-link-1.com", "https://html-link-2.com"}
    assert {url["plugin"] for url in urls} == {"parse_txt_urls"}

    assert collect_urls_from_plugins(snap_dir / "nonexistent") == []


def test_collect_urls_from_plugins_trims_markdown_suffixes(tmp_path):
    from archivebox.plugins.hooks import collect_urls_from_plugins

    snap_dir = run_real_txt_parser(tmp_path, "[favorites](https://docs.sweeting.me/s/youtube-favorites)**")

    urls = collect_urls_from_plugins(snap_dir)
    assert len(urls) == 1
    assert urls[0]["url"] == "https://docs.sweeting.me/s/youtube-favorites"


def test_collect_urls_from_plugins_trims_trailing_punctuation(tmp_path):
    from archivebox.plugins.hooks import collect_urls_from_plugins

    snap_dir = run_real_txt_parser(tmp_path, "https://github.com/ArchiveBox/ArchiveBox. https://github.com/abc?abc#234234?.")

    urls = collect_urls_from_plugins(snap_dir)
    assert [url["url"] for url in urls] == [
        "https://github.com/ArchiveBox/ArchiveBox",
        "https://github.com/abc?abc#234234",
    ]


def test_crawl_create_stdout_pipes_into_run(initialized_archive):
    """`archivebox crawl create | archivebox run` should queue and materialize snapshots."""
    url = create_test_url()

    _cmd_result = run_archivebox_cmd(
        ["crawl", "create", url],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    create_stdout, create_stderr, create_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert create_code == 0, create_stderr
    assert_jsonl_only(create_stdout)

    crawl = next(record for record in parse_jsonl_output(create_stdout) if record.get("type") == "Crawl")

    _cmd_result = run_archivebox_cmd(
        ["run"],
        stdin=create_stdout,
        cwd=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
        default_cli_env=True,
        disable_extractors=True,
    )
    run_stdout, run_stderr, run_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert run_code == 0, run_stderr
    assert_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    assert any(record.get("type") == "Crawl" and record.get("id") == crawl["id"] for record in run_records)

    with use_archivebox_db(initialized_archive):
        snapshot_count = Snapshot.objects.filter(crawl_id=uuid.UUID(crawl["id"])).count()
    assert isinstance(snapshot_count, int)
    assert snapshot_count >= 1


def test_snapshot_list_stdout_pipes_into_run(initialized_archive):
    """`archivebox snapshot list | archivebox run` should requeue listed snapshots."""
    url = create_test_url()

    _cmd_result = run_archivebox_cmd(
        ["snapshot", "create", url],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    create_stdout, create_stderr, create_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert create_code == 0, create_stderr
    snapshot = next(record for record in parse_jsonl_output(create_stdout) if record.get("type") == "Snapshot")

    _cmd_result = run_archivebox_cmd(
        ["snapshot", "list", "--status=queued", f"--url__icontains={snapshot['id']}"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    list_stdout, list_stderr, list_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    if list_code != 0 or not parse_jsonl_output(list_stdout):
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "list", f"--url__icontains={url}"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        list_stdout, list_stderr, list_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert list_code == 0, list_stderr
    assert_jsonl_only(list_stdout)

    _cmd_result = run_archivebox_cmd(
        ["run"],
        stdin=list_stdout,
        cwd=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
        default_cli_env=True,
        disable_extractors=True,
    )
    run_stdout, run_stderr, run_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert run_code == 0, run_stderr
    assert_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    assert any(record.get("type") == "Snapshot" and record.get("id") == snapshot["id"] for record in run_records)

    with use_archivebox_db(initialized_archive):
        snapshot_status = Snapshot.objects.values_list("status", flat=True).get(pk=uuid.UUID(snapshot["id"]))
    assert snapshot_status == "sealed"


def test_archiveresult_list_stdout_pipes_into_run(initialized_archive):
    """`archivebox archiveresult list | archivebox run` should preserve clean JSONL stdout."""
    url = create_test_url()

    _cmd_result = run_archivebox_cmd(
        ["snapshot", "create", url],
        cwd=initialized_archive,
        env=PIPE_TEST_ENV,
        default_cli_env=True,
        disable_extractors=True,
    )
    snapshot_stdout, snapshot_stderr, snapshot_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert snapshot_code == 0, snapshot_stderr

    _cmd_result = run_archivebox_cmd(
        ["archiveresult", "create", "--plugin=favicon"],
        stdin=snapshot_stdout,
        cwd=initialized_archive,
        env=PIPE_TEST_ENV,
        default_cli_env=True,
        disable_extractors=True,
    )
    ar_create_stdout, ar_create_stderr, ar_create_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert ar_create_code == 0, ar_create_stderr

    run_archivebox_cmd(
        ["run"],
        stdin=ar_create_stdout,
        cwd=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
        default_cli_env=True,
        disable_extractors=True,
    )

    _cmd_result = run_archivebox_cmd(
        ["archiveresult", "list", "--plugin=favicon"],
        cwd=initialized_archive,
        env=PIPE_TEST_ENV,
        default_cli_env=True,
        disable_extractors=True,
    )
    list_stdout, list_stderr, list_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert list_code == 0, list_stderr
    assert_jsonl_only(list_stdout)
    listed_records = parse_jsonl_output(list_stdout)
    archiveresult = next(record for record in listed_records if record.get("type") == "ArchiveResult")

    _cmd_result = run_archivebox_cmd(
        ["run"],
        stdin=list_stdout,
        cwd=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
        default_cli_env=True,
        disable_extractors=True,
    )
    run_stdout, run_stderr, run_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert run_code == 0, run_stderr
    assert_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    assert any(record.get("type") == "ArchiveResult" and record.get("id") == archiveresult["id"] for record in run_records)


def test_binary_create_stdout_pipes_into_run(initialized_archive):
    """`archivebox binary create | archivebox run` should queue the binary record for processing."""
    _cmd_result = run_archivebox_cmd(
        ["binary", "create", "--name=python3", f"--abspath={sys.executable}", "--version=test"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    create_stdout, create_stderr, create_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert create_code == 0, create_stderr
    assert_jsonl_only(create_stdout)

    binary = next(record for record in parse_jsonl_output(create_stdout) if record.get("type") in {"BinaryRequest", "Binary"})

    _cmd_result = run_archivebox_cmd(
        ["run"],
        stdin=create_stdout,
        cwd=initialized_archive,
        timeout=120,
        default_cli_env=True,
        disable_extractors=True,
    )
    run_stdout, run_stderr, run_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert run_code == 0, run_stderr
    assert_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    assert any(record.get("type") in {"BinaryRequest", "Binary"} and record.get("id") == binary["id"] for record in run_records)

    with use_archivebox_db(initialized_archive):
        status = Binary.objects.values_list("status", flat=True).get(pk=uuid.UUID(binary["id"]))
    assert status in {"queued", "installed"}


def test_multi_stage_pipeline_into_run(initialized_archive):
    """`crawl create | snapshot create | archiveresult create | run` should preserve JSONL and finish work."""
    url = create_test_url()

    _cmd_result = run_archivebox_cmd(
        ["crawl", "create", url],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    crawl_stdout, crawl_stderr, crawl_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert crawl_code == 0, crawl_stderr
    assert_jsonl_only(crawl_stdout)

    _cmd_result = run_archivebox_cmd(
        ["snapshot", "create"],
        stdin=crawl_stdout,
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    snapshot_stdout, snapshot_stderr, snapshot_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert snapshot_code == 0, snapshot_stderr
    assert_jsonl_only(snapshot_stdout)

    _cmd_result = run_archivebox_cmd(
        ["archiveresult", "create", "--plugin=favicon"],
        stdin=snapshot_stdout,
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    archiveresult_stdout, archiveresult_stderr, archiveresult_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert archiveresult_code == 0, archiveresult_stderr
    assert_jsonl_only(archiveresult_stdout)

    _cmd_result = run_archivebox_cmd(
        ["run"],
        stdin=archiveresult_stdout,
        cwd=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
        default_cli_env=True,
        disable_extractors=True,
    )
    run_stdout, run_stderr, run_code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert run_code == 0, run_stderr
    assert_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    snapshot = next(record for record in run_records if record.get("type") == "Snapshot")
    assert any(record.get("type") == "ArchiveResult" for record in run_records)

    with use_archivebox_db(initialized_archive):
        snapshot_status = Snapshot.objects.values_list("status", flat=True).get(pk=uuid.UUID(snapshot["id"]))
    assert snapshot_status == "sealed"
