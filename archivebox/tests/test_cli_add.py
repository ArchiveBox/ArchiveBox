#!/usr/bin/env python3
"""
Comprehensive tests for archivebox add command.
Verify add creates snapshots in DB, crawls, source files, and archive directories.
"""

import os
import json
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


def test_add_memory_preflight_fails_before_creating_crawl(initialized_archive, capsys):
    from archivebox.workers.supervisord_util import MIN_CRAWL_AVAILABLE_MEMORY_BYTES, require_crawl_memory

    assert MIN_CRAWL_AVAILABLE_MEMORY_BYTES == 512 * 1024 * 1024
    require_crawl_memory(MIN_CRAWL_AVAILABLE_MEMORY_BYTES)

    with use_archivebox_db(initialized_archive):
        before_crawls = Crawl.objects.count()
        before_processes = Process.objects.count()

        with pytest.raises(SystemExit) as err:
            require_crawl_memory(MIN_CRAWL_AVAILABLE_MEMORY_BYTES - 1)

        assert Crawl.objects.count() == before_crawls
        assert Process.objects.count() == before_processes

    assert err.value.code == 1
    output = capsys.readouterr().err
    assert "Not enough available memory to archive a crawl" in output
    assert "No crawl, runner, or Sonic workers were started" in output
    assert "configure swap" in output


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

    _cmd_result = run_archivebox_cmd(
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
    stdout, stderr, returncode = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
    assert returncode == 0, stderr or stdout

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
