"""
Tests for archivebox list command.
Verify list emits snapshot JSONL and applies the documented filters.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.cli.archivebox_snapshot import iter_snapshot_json
from archivebox.tests.conftest import create_test_url, parse_jsonl_output, run_archivebox_cmd, run_queued_crawls, cli_env

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_streaming_json_matches_snapshot_serializer(initialized_archive):
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        user = get_user_model().objects.create_user(username="streaming-json-parity")
        crawl = Crawl.objects.create(
            urls="https://example.com/a\nhttps://example.com/b",
            created_by=user,
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        populated = Snapshot.objects.create(
            crawl=crawl,
            url="https://example.com/a",
            timestamp="20260721220000000000000000000001",
            title="Populated title",
            status=Snapshot.StatusChoices.SEALED,
            retry_at=None,
            output_size=42,
        )
        populated.save_tags(["éclair", "Zulu", "alpha"])
        empty = Snapshot.objects.create(
            crawl=crawl,
            url="https://example.com/b",
            timestamp="20260721220000000000000000000002",
            title=None,
            status=Snapshot.StatusChoices.QUEUED,
            output_size=0,
        )
        queryset = Snapshot.objects.filter(id__in=(populated.id, empty.id)).order_by("url")

        expected = [snapshot.to_json() for snapshot in queryset.prefetch_related("tags")]
        actual = list(iter_snapshot_json(queryset))

    assert actual == expected
    assert [record["url"] for record in actual] == ["https://example.com/a", "https://example.com/b"]


def test_list_limit_zero_streams_one_million_snapshots_without_materializing(initialized_archive, tmp_path):
    """Regression: archivebox list --limit=0 must stream unbounded result sets."""
    from archivebox.crawls.models import Crawl

    with use_archivebox_db(initialized_archive):
        user = get_user_model().objects.create_user(username="million-snapshot-list")
        crawl = Crawl.objects.create(
            urls="https://example.com",
            created_by=user,
            status=Crawl.StatusChoices.SEALED,
            retry_at=None,
        )
        now = timezone.now().isoformat()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE seq(n) AS (
                    SELECT 1
                    UNION ALL
                    SELECT n + 1 FROM seq WHERE n < 1000000
                )
                INSERT INTO core_snapshot (
                    id,
                    url,
                    timestamp,
                    title,
                    bookmarked_at,
                    created_at,
                    modified_at,
                    downloaded_at,
                    fs_version,
                    crawl_id,
                    config,
                    current_step,
                    depth,
                    notes,
                    num_uses_failed,
                    num_uses_succeeded,
                    retry_at,
                    status,
                    delete_at,
                    output_size,
                    parent_snapshot_id
                )
                SELECT
                    lower(hex(randomblob(16))),
                    'https://example.com/page-' || n,
                    printf('9%031d', n),
                    '',
                    %s,
                    %s,
                    %s,
                    NULL,
                    '0.9.0',
                    %s,
                    '{}',
                    0,
                    0,
                    '',
                    0,
                    0,
                    NULL,
                    'sealed',
                    NULL,
                    0,
                    NULL
                FROM seq
                """,
                [now, now, now, str(crawl.id).replace("-", "")],
            )

    output_path = tmp_path / "million-snapshots.jsonl"
    with output_path.open("w") as stdout:
        result = run_archivebox_cmd(
            ["list", "--limit=0"],
            cwd=initialized_archive,
            stdout=stdout,
            default_cli_env=True,
            disable_extractors=True,
        )

    assert result.returncode == 0, result.stderr
    with output_path.open() as stdout:
        assert sum(1 for line in stdout if line.startswith("{")) == 1000000


def test_list_outputs_existing_snapshots_as_jsonl(initialized_archive):
    """Test that list prints one JSON object per stored snapshot."""
    env = cli_env(disable_extractors=True)
    for url in ["https://example.com", "https://iana.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
            check=True,
        )
    run_queued_crawls(initialized_archive, env)
    with use_archivebox_db(initialized_archive):
        Snapshot.objects.get(url="https://example.com").save_tags(["z-tag", "a-tag"])

    result = run_archivebox_cmd(
        ["list"],
        timeout=30,
    )

    rows = parse_jsonl_output(result.stdout)
    urls = {row["url"] for row in rows}
    rows_by_url = {row["url"]: row for row in rows}

    assert result.returncode == 0, result.stderr
    assert "https://example.com" in urls
    assert "https://iana.org" in urls
    assert rows_by_url["https://example.com"]["tags"] == "a-tag,z-tag"


def test_list_filters_by_url_icontains(initialized_archive):
    """Test that list --url__icontains returns only matching snapshots."""
    env = cli_env(disable_extractors=True)
    for url in ["https://example.com", "https://iana.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
            check=True,
        )
    run_queued_crawls(initialized_archive, env)

    result = run_archivebox_cmd(
        ["list", "--url__icontains", "example.com"],
        timeout=30,
    )

    rows = parse_jsonl_output(result.stdout)
    assert result.returncode == 0, result.stderr
    assert len(rows) == 1
    assert rows[0]["url"] == "https://example.com"


def test_list_filters_by_crawl_id_and_limit(initialized_archive):
    """Test that crawl-id and limit filters constrain the result set."""
    env = cli_env(disable_extractors=True)
    for url in ["https://example.com", "https://iana.org"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
            check=True,
        )
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        crawl_id = str(Snapshot.objects.values_list("crawl_id", flat=True).get(url="https://example.com"))

    result = run_archivebox_cmd(
        ["list", "--crawl-id", crawl_id, "--limit", "1"],
        timeout=30,
    )

    rows = parse_jsonl_output(result.stdout)
    assert result.returncode == 0, result.stderr
    assert len(rows) == 1
    assert rows[0]["crawl_id"].replace("-", "") == crawl_id.replace("-", "")
    assert rows[0]["url"] == "https://example.com"


def test_list_filters_by_status(initialized_archive):
    """Test that list can filter using the current snapshot status."""
    env = cli_env(disable_extractors=True)
    run_archivebox_cmd(
        ["add", "--index-only", "--depth=0", "https://example.com"],
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        status = Snapshot.objects.values_list("status", flat=True).get()

    result = run_archivebox_cmd(
        ["list", "--status", status],
        timeout=30,
    )

    rows = parse_jsonl_output(result.stdout)
    assert result.returncode == 0, result.stderr
    assert len(rows) == 1
    assert rows[0]["status"] == status


def test_list_help_lists_filter_options(initialized_archive):
    """Test that list --help documents the supported filter flags."""

    result = run_archivebox_cmd(
        ["list", "--help"],
        timeout=30,
    )

    assert result.returncode == 0
    assert "--url__icontains" in result.stdout
    assert "--crawl-id" in result.stdout
    assert "--limit" in result.stdout
    assert "--search" in result.stdout
    assert "--json" in result.stdout
    assert "--html" in result.stdout
    assert "--with-headers" in result.stdout


def test_list_allows_sort_with_limit(initialized_archive):
    """Test that list can sort and then apply limit without queryset slicing errors."""
    env = cli_env(disable_extractors=True)
    for url in ["https://example.com", "https://iana.org", "https://example.net"]:
        run_archivebox_cmd(
            ["add", "--index-only", "--depth=0", url],
            env=env,
            check=True,
        )
    run_queued_crawls(initialized_archive, env)

    result = run_archivebox_cmd(
        ["list", "--limit", "2", "--sort", "-created_at"],
        timeout=30,
    )

    rows = parse_jsonl_output(result.stdout)
    assert result.returncode == 0, result.stderr
    assert len(rows) == 2


def test_snapshot_list_search_meta(initialized_archive):
    """snapshot list should support metadata search mode."""
    url = create_test_url(domain="meta-search-example.com")
    run_archivebox_cmd(["snapshot", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

    _cmd_result = run_archivebox_cmd(
        ["snapshot", "list", "--search=meta", "meta-search-example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code == 0, f"Command failed: {stderr}"
    records = parse_jsonl_output(stdout)
    assert len(records) == 1
    assert "meta-search-example.com" in records[0]["url"]


def test_list_search_meta_matches_metadata(initialized_archive):
    """top-level list --search=meta should apply metadata search to the queryset."""
    url = create_test_url(domain="top-level-meta-search-example.com")
    run_archivebox_cmd(["snapshot", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

    _cmd_result = run_archivebox_cmd(
        ["list", "--search=meta", "top-level-meta-search-example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code == 0, f"Command failed: {stderr}"
    records = parse_jsonl_output(stdout)
    assert len(records) == 1
    assert "top-level-meta-search-example.com" in records[0]["url"]


def test_search_command_finds_snapshots(initialized_archive):
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )

    _cmd_result = run_archivebox_cmd(["search", "example"], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
    stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code == 0, stderr
    assert "example" in stdout


def test_search_command_returns_no_results_for_missing_term(initialized_archive):
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )

    _cmd_result = run_archivebox_cmd(
        ["search", "nonexistentterm12345"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    _stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code in [0, 1]


def test_search_command_on_empty_archive(initialized_archive):
    _cmd_result = run_archivebox_cmd(["search", "anything"], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
    _stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code in [0, 1]


def test_search_command_outputs_matching_snapshots_as_jsonl(initialized_archive):
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )

    _cmd_result = run_archivebox_cmd(["search"], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
    stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code == 0, stderr
    records = parse_jsonl_output(stdout)
    assert any("example.com" in row.get("url", "") for row in records)


def test_search_command_json_outputs_matching_snapshots(initialized_archive):
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )

    result = run_archivebox_cmd(["search", "--json"], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert any("example.com" in row.get("url", "") for row in payload)


def test_search_command_json_with_headers_wraps_links_payload(initialized_archive):
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )

    result = run_archivebox_cmd(
        ["search", "--json", "--with-headers"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "links" in payload
    assert any("example.com" in row.get("url", "") for row in payload["links"])


def test_search_command_html_outputs_markup(initialized_archive):
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )

    result = run_archivebox_cmd(["search", "--html"], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

    assert result.returncode == 0, result.stderr
    assert "<" in result.stdout
    assert "example.com" in result.stdout


def test_search_command_csv_outputs_requested_column(initialized_archive):
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )

    _cmd_result = run_archivebox_cmd(
        ["search", "--csv", "url", "--with-headers"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code == 0, stderr
    assert "url" in stdout
    assert "example.com" in stdout


def test_search_command_with_headers_requires_structured_output_format(initialized_archive):
    _cmd_result = run_archivebox_cmd(["search", "--with-headers"], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
    _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code != 0
    assert "requires" in stderr.lower()
    assert "json" in stderr.lower()


def test_search_command_sort_option_runs_successfully(initialized_archive):
    for url in ["https://iana.org", "https://example.com"]:
        run_archivebox_cmd(["snapshot", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

    _cmd_result = run_archivebox_cmd(
        ["search", "--csv", "url", "--sort=url"],
        cwd=initialized_archive,
        default_cli_env=True,
        disable_extractors=True,
    )
    stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code == 0, stderr
    assert "example.com" in stdout or "iana.org" in stdout


def test_search_command_help_lists_supported_filters(initialized_archive):
    _cmd_result = run_archivebox_cmd(["search", "--help"], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
    stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

    assert code == 0
    assert "--url__icontains" in stdout
    assert "--crawl-id" in stdout
    assert "--status" in stdout
    assert "--sort" in stdout
    assert "--json" in stdout
    assert "--html" in stdout
