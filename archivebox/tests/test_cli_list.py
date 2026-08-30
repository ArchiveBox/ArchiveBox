"""
Tests for archivebox list command.
Verify list emits snapshot JSONL and applies the documented filters.
"""

import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from archivebox.core.models import Snapshot
from archivebox.cli.archivebox_snapshot import iter_snapshot_json
from archivebox.tests.conftest import create_test_url, parse_jsonl_output, run_archivebox_cmd, run_queued_crawls, cli_env

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def test_static_export_creates_detail_page_for_unarchived_snapshot(snapshot):
    from archivebox.config import CONSTANTS

    snapshot_dir = Path(snapshot.output_dir)
    assert snapshot_dir.is_dir()
    assert not any(snapshot_dir.iterdir())
    snapshot_dir.rmdir()
    assert not snapshot_dir.exists()

    html = Snapshot.objects.filter(pk=snapshot.pk).to_html(with_headers=True)

    static_path = snapshot_dir.relative_to(CONSTANTS.DATA_DIR).as_posix()
    detail_path = snapshot_dir / "index.html"
    assert f"./{static_path}/index.html" in html
    # The portable export command emits JSONL records; index.json is a legacy
    # filename that is not created and leaves a broken footer link offline.
    assert 'href="./index.jsonl"' in html
    assert 'href="./index.json"' not in html
    root_manifest = CONSTANTS.DATA_DIR / "index.jsonl"
    assert root_manifest.exists()
    manifest_records = [json.loads(line) for line in root_manifest.read_text().splitlines() if line.strip()]
    assert [record["id"] for record in manifest_records] == [str(snapshot.id)]
    # JSON and JSONL are alternate containers for one static-export schema;
    # consumers must not see TYPE/tags/archive paths change by file format.
    assert manifest_records[0]["TYPE"] == "core.models.Snapshot"
    assert "type" not in manifest_records[0]
    assert isinstance(manifest_records[0]["tags"], list)
    assert manifest_records[0]["archive_path"] == static_path
    assert manifest_records[0]["archive_url"] == f"./{static_path}/index.html"
    assert detail_path.exists()
    detail_html = detail_path.read_text()
    assert f"/snapshot/{snapshot.id.hex}" not in detail_html
    assert "/admin/" not in detail_html


def test_static_exports_use_filesystem_paths_not_live_django_routes(snapshot):
    from archivebox.config import CONSTANTS
    from archivebox.core.models import ArchiveResult

    snapshot_dir = Path(snapshot.output_dir)
    screenshot_dir = snapshot_dir / "screenshot"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = screenshot_dir / "screenshot.png"
    screenshot_file.write_bytes(b"real screenshot")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="screenshot",
        hook_name="on_Snapshot__50_screenshot.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="screenshot.png",
        output_files={"screenshot.png": {"size": screenshot_file.stat().st_size}},
        output_size=screenshot_file.stat().st_size,
    )
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="chrome_screencast",
        hook_name="on_Snapshot__02_chrome_screencast.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="2 screencast frames (0 kept)",
        output_files={"hook.stderr.log": {"size": 12}},
        output_size=12,
    )
    wget_dir = snapshot_dir / "wget"
    wget_dir.mkdir()
    wget_file = wget_dir / "index%3A.html"
    wget_file.write_text("archived page")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="wget",
        hook_name="on_Snapshot__35_wget.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="index%3A.html",
        output_files={"index%3A.html": {"size": wget_file.stat().st_size}},
        output_size=wget_file.stat().st_size,
    )
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="staticfile",
        hook_name="on_Snapshot__26_staticfile.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="prenav.json",
        output_files={"prenav.json": {"size": 66}},
        output_size=66,
    )
    ytdlp_dir = snapshot_dir / "ytdlp"
    ytdlp_dir.mkdir()
    media_file = ytdlp_dir / "saved.m4a"
    media_file.write_bytes(b"audio")
    ArchiveResult.objects.create(
        snapshot=snapshot,
        plugin="ytdlp",
        hook_name="on_Snapshot__60_ytdlp.py",
        status=ArchiveResult.StatusChoices.SUCCEEDED,
        output_str="saved.m4a",
        output_files={
            "saved.m4a": {"size": media_file.stat().st_size},
            "deleted.temp.m4a": {"size": 123},
        },
        output_size=media_file.stat().st_size,
    )
    hashes_dir = snapshot_dir / "hashes"
    hashes_dir.mkdir()
    (hashes_dir / "hashes.json").write_text(
        json.dumps(
            {
                "screenshot/screenshot.png": {"size": screenshot_file.stat().st_size},
                "wget/index%3A.html": {"size": wget_file.stat().st_size},
                "staticfile/prenav.json": {"size": 66},
                "ytdlp/saved.m4a": {"size": media_file.stat().st_size},
                "ytdlp/deleted.temp.m4a": {"size": 123},
            },
        ),
    )
    static_path = snapshot_dir.relative_to(CONSTANTS.DATA_DIR).as_posix()
    queryset = Snapshot.objects.filter(pk=snapshot.pk).prefetch_related("tags")

    html = queryset.to_html(with_headers=True)
    [record] = json.loads(queryset.to_json(with_headers=False))
    detail_html = snapshot_dir / "index.html"

    assert f"./{static_path}/index.html" in html
    assert f"./{static_path}/screenshot/screenshot.png" in html
    assert f"./{static_path}/wget/index%253A.html" in html
    assert f"./{static_path}/index.jsonl" in html
    assert f"/snapshot/{snapshot.id.hex}" not in html
    assert "/web/" not in html
    assert "/static/" not in html
    assert "/None" not in html
    assert "staticfile/prenav.json" not in html
    assert record["archive_path"] == static_path
    assert record["archive_url"] == f"./{static_path}/index.html"
    assert detail_html.exists()
    rendered_detail = detail_html.read_text()
    assert "core/snapshot.html" not in rendered_detail
    assert "screenshot/screenshot.png" in rendered_detail
    assert "staticfile/prenav.json" not in rendered_detail
    assert "ytdlp/saved.m4a" in rendered_detail
    assert "ytdlp/deleted.temp.m4a" not in rendered_detail
    assert f"/snapshot/{snapshot.id.hex}" not in rendered_detail


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
