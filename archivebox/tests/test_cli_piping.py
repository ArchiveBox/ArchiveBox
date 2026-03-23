"""
Tests for JSONL piping contracts and `archivebox run`.

This file covers both:
- low-level JSONL/stdin parsing behavior that makes CLI piping work
- subprocess integration for the supported records `archivebox run` consumes
"""

import sqlite3
import sys
import uuid
from io import StringIO
from pathlib import Path

from archivebox.tests.conftest import (
    create_test_url,
    parse_jsonl_output,
    run_archivebox_cmd,
)


PIPE_TEST_ENV = {
    "PLUGINS": "favicon",
    "SAVE_FAVICON": "True",
    "USE_COLOR": "False",
    "SHOW_PROGRESS": "False",
}


class MockTTYStringIO(StringIO):
    def __init__(self, initial_value: str = "", *, is_tty: bool):
        super().__init__(initial_value)
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def _stdout_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.strip()]


def _assert_stdout_is_jsonl_only(stdout: str) -> None:
    lines = _stdout_lines(stdout)
    assert lines, "Expected stdout to contain JSONL records"
    assert all(line.lstrip().startswith("{") for line in lines), stdout


def _sqlite_param(value: object) -> object:
    if not isinstance(value, str):
        return value
    try:
        return uuid.UUID(value).hex
    except ValueError:
        return value


def _db_value(data_dir: Path, sql: str, params: tuple[object, ...] = ()) -> object | None:
    conn = sqlite3.connect(data_dir / "index.sqlite3")
    try:
        row = conn.execute(sql, tuple(_sqlite_param(param) for param in params)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def test_parse_line_accepts_supported_piping_inputs():
    """The JSONL parser should normalize the input forms CLI pipes accept."""
    from archivebox.misc.jsonl import TYPE_CRAWL, TYPE_SNAPSHOT, parse_line

    assert parse_line("") is None
    assert parse_line("   ") is None
    assert parse_line("# comment") is None
    assert parse_line("not-a-url") is None
    assert parse_line("ftp://example.com") is None

    plain_url = parse_line("https://example.com")
    assert plain_url == {"type": TYPE_SNAPSHOT, "url": "https://example.com"}

    file_url = parse_line("file:///tmp/example.txt")
    assert file_url == {"type": TYPE_SNAPSHOT, "url": "file:///tmp/example.txt"}

    snapshot_json = parse_line('{"type":"Snapshot","url":"https://example.com","tags":"tag1,tag2"}')
    assert snapshot_json is not None
    assert snapshot_json["type"] == TYPE_SNAPSHOT
    assert snapshot_json["tags"] == "tag1,tag2"

    crawl_json = parse_line('{"type":"Crawl","id":"abc123","urls":"https://example.com","max_depth":1}')
    assert crawl_json is not None
    assert crawl_json["type"] == TYPE_CRAWL
    assert crawl_json["id"] == "abc123"
    assert crawl_json["max_depth"] == 1

    snapshot_id = "01234567-89ab-cdef-0123-456789abcdef"
    parsed_id = parse_line(snapshot_id)
    assert parsed_id == {"type": TYPE_SNAPSHOT, "id": snapshot_id}

    compact_snapshot_id = "0123456789abcdef0123456789abcdef"
    compact_parsed_id = parse_line(compact_snapshot_id)
    assert compact_parsed_id == {"type": TYPE_SNAPSHOT, "id": compact_snapshot_id}


def test_read_args_or_stdin_handles_args_stdin_and_mixed_jsonl():
    """Piping helpers should consume args, structured JSONL, and pass-through records."""
    from archivebox.misc.jsonl import TYPE_CRAWL, read_args_or_stdin

    records = list(read_args_or_stdin(("https://example1.com", "https://example2.com")))
    assert [record["url"] for record in records] == ["https://example1.com", "https://example2.com"]

    stdin_records = list(
        read_args_or_stdin(
            (),
            stream=MockTTYStringIO(
                "https://plain-url.com\n"
                '{"type":"Snapshot","url":"https://jsonl-url.com","tags":"test"}\n'
                '{"type":"Tag","id":"tag-1","name":"example"}\n'
                "01234567-89ab-cdef-0123-456789abcdef\n"
                "not valid json\n",
                is_tty=False,
            ),
        ),
    )
    assert len(stdin_records) == 4
    assert stdin_records[0]["url"] == "https://plain-url.com"
    assert stdin_records[1]["url"] == "https://jsonl-url.com"
    assert stdin_records[1]["tags"] == "test"
    assert stdin_records[2]["type"] == "Tag"
    assert stdin_records[2]["name"] == "example"
    assert stdin_records[3]["id"] == "01234567-89ab-cdef-0123-456789abcdef"

    crawl_records = list(
        read_args_or_stdin(
            (),
            stream=MockTTYStringIO(
                '{"type":"Crawl","id":"crawl-1","urls":"https://example.com\\nhttps://foo.com"}\n',
                is_tty=False,
            ),
        ),
    )
    assert len(crawl_records) == 1
    assert crawl_records[0]["type"] == TYPE_CRAWL
    assert crawl_records[0]["id"] == "crawl-1"

    tty_records = list(read_args_or_stdin((), stream=MockTTYStringIO("https://example.com", is_tty=True)))
    assert tty_records == []


def test_collect_urls_from_plugins_reads_only_parser_outputs(tmp_path):
    """Parser extractor `urls.jsonl` outputs should be discoverable for recursive piping."""
    from archivebox.hooks import collect_urls_from_plugins

    (tmp_path / "wget").mkdir()
    (tmp_path / "wget" / "urls.jsonl").write_text(
        '{"url":"https://wget-link-1.com"}\n{"url":"https://wget-link-2.com"}\n',
        encoding="utf-8",
    )
    (tmp_path / "parse_html_urls").mkdir()
    (tmp_path / "parse_html_urls" / "urls.jsonl").write_text(
        '{"url":"https://html-link-1.com"}\n{"url":"https://html-link-2.com","title":"HTML Link 2"}\n',
        encoding="utf-8",
    )
    (tmp_path / "screenshot").mkdir()

    urls = collect_urls_from_plugins(tmp_path)
    assert len(urls) == 4
    assert {url["plugin"] for url in urls} == {"wget", "parse_html_urls"}
    titled = [url for url in urls if url.get("title") == "HTML Link 2"]
    assert len(titled) == 1
    assert titled[0]["url"] == "https://html-link-2.com"

    assert collect_urls_from_plugins(tmp_path / "nonexistent") == []


def test_collect_urls_from_plugins_trims_markdown_suffixes(tmp_path):
    from archivebox.hooks import collect_urls_from_plugins

    (tmp_path / "parse_html_urls").mkdir()
    (tmp_path / "parse_html_urls" / "urls.jsonl").write_text(
        '{"url":"https://docs.sweeting.me/s/youtube-favorites)**"}\n',
        encoding="utf-8",
    )

    urls = collect_urls_from_plugins(tmp_path)
    assert len(urls) == 1
    assert urls[0]["url"] == "https://docs.sweeting.me/s/youtube-favorites"


def test_collect_urls_from_plugins_trims_trailing_punctuation(tmp_path):
    from archivebox.hooks import collect_urls_from_plugins

    (tmp_path / "parse_html_urls").mkdir()
    (tmp_path / "parse_html_urls" / "urls.jsonl").write_text(
        ('{"url":"https://github.com/ArchiveBox/ArchiveBox."}\n{"url":"https://github.com/abc?abc#234234?."}\n'),
        encoding="utf-8",
    )

    urls = collect_urls_from_plugins(tmp_path)
    assert [url["url"] for url in urls] == [
        "https://github.com/ArchiveBox/ArchiveBox",
        "https://github.com/abc?abc#234234",
    ]


def test_crawl_create_stdout_pipes_into_run(initialized_archive):
    """`archivebox crawl create | archivebox run` should queue and materialize snapshots."""
    url = create_test_url()

    create_stdout, create_stderr, create_code = run_archivebox_cmd(
        ["crawl", "create", url],
        data_dir=initialized_archive,
    )
    assert create_code == 0, create_stderr
    _assert_stdout_is_jsonl_only(create_stdout)

    crawl = next(record for record in parse_jsonl_output(create_stdout) if record.get("type") == "Crawl")

    run_stdout, run_stderr, run_code = run_archivebox_cmd(
        ["run"],
        stdin=create_stdout,
        data_dir=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
    )
    assert run_code == 0, run_stderr
    _assert_stdout_is_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    assert any(record.get("type") == "Crawl" and record.get("id") == crawl["id"] for record in run_records)

    snapshot_count = _db_value(
        initialized_archive,
        "SELECT COUNT(*) FROM core_snapshot WHERE crawl_id = ?",
        (crawl["id"],),
    )
    assert isinstance(snapshot_count, int)
    assert snapshot_count >= 1


def test_snapshot_list_stdout_pipes_into_run(initialized_archive):
    """`archivebox snapshot list | archivebox run` should requeue listed snapshots."""
    url = create_test_url()

    create_stdout, create_stderr, create_code = run_archivebox_cmd(
        ["snapshot", "create", url],
        data_dir=initialized_archive,
    )
    assert create_code == 0, create_stderr
    snapshot = next(record for record in parse_jsonl_output(create_stdout) if record.get("type") == "Snapshot")

    list_stdout, list_stderr, list_code = run_archivebox_cmd(
        ["snapshot", "list", "--status=queued", f"--url__icontains={snapshot['id']}"],
        data_dir=initialized_archive,
    )
    if list_code != 0 or not parse_jsonl_output(list_stdout):
        list_stdout, list_stderr, list_code = run_archivebox_cmd(
            ["snapshot", "list", f"--url__icontains={url}"],
            data_dir=initialized_archive,
        )
    assert list_code == 0, list_stderr
    _assert_stdout_is_jsonl_only(list_stdout)

    run_stdout, run_stderr, run_code = run_archivebox_cmd(
        ["run"],
        stdin=list_stdout,
        data_dir=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
    )
    assert run_code == 0, run_stderr
    _assert_stdout_is_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    assert any(record.get("type") == "Snapshot" and record.get("id") == snapshot["id"] for record in run_records)

    snapshot_status = _db_value(
        initialized_archive,
        "SELECT status FROM core_snapshot WHERE id = ?",
        (snapshot["id"],),
    )
    assert snapshot_status == "sealed"


def test_archiveresult_list_stdout_pipes_into_run(initialized_archive):
    """`archivebox archiveresult list | archivebox run` should preserve clean JSONL stdout."""
    url = create_test_url()

    snapshot_stdout, snapshot_stderr, snapshot_code = run_archivebox_cmd(
        ["snapshot", "create", url],
        data_dir=initialized_archive,
    )
    assert snapshot_code == 0, snapshot_stderr

    ar_create_stdout, ar_create_stderr, ar_create_code = run_archivebox_cmd(
        ["archiveresult", "create", "--plugin=favicon"],
        stdin=snapshot_stdout,
        data_dir=initialized_archive,
    )
    assert ar_create_code == 0, ar_create_stderr

    run_archivebox_cmd(
        ["run"],
        stdin=ar_create_stdout,
        data_dir=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
    )

    list_stdout, list_stderr, list_code = run_archivebox_cmd(
        ["archiveresult", "list", "--plugin=favicon"],
        data_dir=initialized_archive,
    )
    assert list_code == 0, list_stderr
    _assert_stdout_is_jsonl_only(list_stdout)
    listed_records = parse_jsonl_output(list_stdout)
    archiveresult = next(record for record in listed_records if record.get("type") == "ArchiveResult")

    run_stdout, run_stderr, run_code = run_archivebox_cmd(
        ["run"],
        stdin=list_stdout,
        data_dir=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
    )
    assert run_code == 0, run_stderr
    _assert_stdout_is_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    assert any(record.get("type") == "ArchiveResult" and record.get("id") == archiveresult["id"] for record in run_records)


def test_binary_create_stdout_pipes_into_run(initialized_archive):
    """`archivebox binary create | archivebox run` should queue the binary record for processing."""
    create_stdout, create_stderr, create_code = run_archivebox_cmd(
        ["binary", "create", "--name=python3", f"--abspath={sys.executable}", "--version=test"],
        data_dir=initialized_archive,
    )
    assert create_code == 0, create_stderr
    _assert_stdout_is_jsonl_only(create_stdout)

    binary = next(
        record
        for record in parse_jsonl_output(create_stdout)
        if record.get("type") in {"BinaryRequest", "Binary"}
    )

    run_stdout, run_stderr, run_code = run_archivebox_cmd(
        ["run"],
        stdin=create_stdout,
        data_dir=initialized_archive,
        timeout=120,
    )
    assert run_code == 0, run_stderr
    _assert_stdout_is_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    assert any(
        record.get("type") in {"BinaryRequest", "Binary"} and record.get("id") == binary["id"]
        for record in run_records
    )

    status = _db_value(
        initialized_archive,
        "SELECT status FROM machine_binary WHERE id = ?",
        (binary["id"],),
    )
    assert status in {"queued", "installed"}


def test_multi_stage_pipeline_into_run(initialized_archive):
    """`crawl create | snapshot create | archiveresult create | run` should preserve JSONL and finish work."""
    url = create_test_url()

    crawl_stdout, crawl_stderr, crawl_code = run_archivebox_cmd(
        ["crawl", "create", url],
        data_dir=initialized_archive,
    )
    assert crawl_code == 0, crawl_stderr
    _assert_stdout_is_jsonl_only(crawl_stdout)

    snapshot_stdout, snapshot_stderr, snapshot_code = run_archivebox_cmd(
        ["snapshot", "create"],
        stdin=crawl_stdout,
        data_dir=initialized_archive,
    )
    assert snapshot_code == 0, snapshot_stderr
    _assert_stdout_is_jsonl_only(snapshot_stdout)

    archiveresult_stdout, archiveresult_stderr, archiveresult_code = run_archivebox_cmd(
        ["archiveresult", "create", "--plugin=favicon"],
        stdin=snapshot_stdout,
        data_dir=initialized_archive,
    )
    assert archiveresult_code == 0, archiveresult_stderr
    _assert_stdout_is_jsonl_only(archiveresult_stdout)

    run_stdout, run_stderr, run_code = run_archivebox_cmd(
        ["run"],
        stdin=archiveresult_stdout,
        data_dir=initialized_archive,
        timeout=120,
        env=PIPE_TEST_ENV,
    )
    assert run_code == 0, run_stderr
    _assert_stdout_is_jsonl_only(run_stdout)

    run_records = parse_jsonl_output(run_stdout)
    snapshot = next(record for record in run_records if record.get("type") == "Snapshot")
    assert any(record.get("type") == "ArchiveResult" for record in run_records)

    snapshot_status = _db_value(
        initialized_archive,
        "SELECT status FROM core_snapshot WHERE id = ?",
        (snapshot["id"],),
    )
    assert snapshot_status == "sealed"
