"""
Tests for archivebox crawl CLI command.

Tests cover:
- crawl create (with URLs, from stdin, pass-through)
- crawl list (with filters)
- crawl update
- crawl delete
"""

import json

import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import (
    cli_env,
    create_test_url,
    parse_jsonl_output,
    run_archivebox_cmd,
    run_queued_crawls,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


class TestCrawlCreate:
    """Tests for `archivebox crawl create`."""

    def test_create_from_url_args(self, initialized_archive):
        """Create crawl from URL arguments."""
        url = create_test_url()

        _cmd_result = run_archivebox_cmd(
            ["crawl", "create", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, f"Command failed: {stderr}"
        assert "Created crawl" in stderr

        # Check JSONL output
        records = parse_jsonl_output(stdout)
        assert len(records) == 1
        assert records[0]["type"] == "Crawl"
        assert url in records[0]["urls"]

    def test_create_from_stdin_urls(self, initialized_archive):
        """Create crawl from stdin URLs (one per line)."""
        urls = [create_test_url() for _ in range(3)]
        stdin = "\n".join(urls)

        _cmd_result = run_archivebox_cmd(
            ["crawl", "create"],
            stdin=stdin,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, f"Command failed: {stderr}"

        records = parse_jsonl_output(stdout)
        assert len(records) == 1
        crawl = records[0]
        assert crawl["type"] == "Crawl"
        # All URLs should be in the crawl
        for url in urls:
            assert url in crawl["urls"]

    def test_create_with_depth(self, initialized_archive):
        """Create crawl with --depth flag."""
        url = create_test_url()

        _cmd_result = run_archivebox_cmd(
            ["crawl", "create", "--depth=2", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert records[0]["max_depth"] == 2

    def test_create_with_tag(self, initialized_archive):
        """Create crawl with --tag flag."""
        url = create_test_url()

        _cmd_result = run_archivebox_cmd(
            ["crawl", "create", "--tag=test-tag", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert "test-tag" in records[0].get("tags_str", "")

    def test_create_pass_through_other_types(self, initialized_archive):
        """Pass-through records of other types unchanged."""
        tag_record = {"type": "Tag", "id": "fake-tag-id", "name": "test"}
        url = create_test_url()
        stdin = json.dumps(tag_record) + "\n" + json.dumps({"url": url})

        _cmd_result = run_archivebox_cmd(
            ["crawl", "create"],
            stdin=stdin,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)

        # Should have both the passed-through Tag and the new Crawl
        types = [r.get("type") for r in records]
        assert "Tag" in types
        assert "Crawl" in types

    def test_create_pass_through_existing_crawl(self, initialized_archive):
        """Existing Crawl records (with id) are passed through."""
        # First create a crawl
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        crawl = parse_jsonl_output(stdout1)[0]

        # Now pipe it back - should pass through
        _cmd_result = run_archivebox_cmd(
            ["crawl", "create"],
            stdin=json.dumps(crawl),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout2)
        assert len(records) == 1
        assert records[0]["id"] == crawl["id"]


class TestCrawlList:
    """Tests for `archivebox crawl list`."""

    def test_list_empty(self, initialized_archive):
        """List with no crawls returns empty."""
        _cmd_result = run_archivebox_cmd(
            ["crawl", "list"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Listed 0 crawls" in stderr

    def test_list_returns_created(self, initialized_archive):
        """List returns previously created crawls."""
        url = create_test_url()
        run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

        _cmd_result = run_archivebox_cmd(
            ["crawl", "list"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) >= 1
        assert any(url in r.get("urls", "") for r in records)

    def test_list_filter_by_status(self, initialized_archive):
        """Filter crawls by status."""
        url = create_test_url()
        run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

        _cmd_result = run_archivebox_cmd(
            ["crawl", "list", "--status=queued"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        for r in records:
            assert r["status"] == "queued"

    def test_list_with_limit(self, initialized_archive):
        """Limit number of results."""
        # Create multiple crawls
        for _ in range(3):
            run_archivebox_cmd(
                ["crawl", "create", create_test_url()],
                cwd=initialized_archive,
                default_cli_env=True,
                disable_extractors=True,
            )

        _cmd_result = run_archivebox_cmd(
            ["crawl", "list", "--limit=2"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 2


class TestCrawlUpdate:
    """Tests for `archivebox crawl update`."""

    def test_update_status(self, initialized_archive):
        """Update crawl status."""
        # Create a crawl
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        crawl = parse_jsonl_output(stdout1)[0]

        # Update it
        _cmd_result = run_archivebox_cmd(
            ["crawl", "update", "--status=started"],
            stdin=json.dumps(crawl),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Updated 1 crawls" in stderr

        records = parse_jsonl_output(stdout2)
        assert records[0]["status"] == "started"


class TestCrawlDelete:
    """Tests for `archivebox crawl delete`."""

    def test_delete_requires_yes(self, initialized_archive):
        """Delete requires --yes flag."""
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        crawl = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["crawl", "delete"],
            stdin=json.dumps(crawl),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 1
        assert "--yes" in stderr

    def test_delete_with_yes(self, initialized_archive):
        """Delete with --yes flag works."""
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        crawl = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["crawl", "delete", "--yes"],
            stdin=json.dumps(crawl),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Deleted 1 crawls" in stderr

    def test_delete_dry_run(self, initialized_archive):
        """Dry run shows what would be deleted."""
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        crawl = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["crawl", "delete", "--dry-run"],
            stdin=json.dumps(crawl),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Would delete" in stderr
        assert "dry run" in stderr.lower()


def test_crawl_creates_crawl_object(initialized_archive):
    """Test that crawl command creates a Crawl object."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["crawl", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.order_by("-created_at").first()

    assert crawl is not None, "Crawl object should be created"


def test_crawl_depth_sets_max_depth_in_crawl(initialized_archive):
    """Test that --depth option sets max_depth in the Crawl object."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["crawl", "create", "--depth=2", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.order_by("-created_at").first()

    assert crawl is not None
    assert crawl.max_depth == 2, "Crawl max_depth should match --depth=2"


def test_crawl_creates_snapshot_for_url(initialized_archive):
    """Test that crawl creates a Snapshot for the input URL."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["crawl", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.filter(url="https://example.com").first()

    assert snapshot is not None, "Snapshot should be created for input URL"


def test_crawl_links_snapshot_to_crawl(initialized_archive):
    """Test that Snapshot is linked to Crawl via crawl_id."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["crawl", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.order_by("-created_at").first()
        assert crawl is not None
        snapshot = Snapshot.objects.filter(url="https://example.com").first()

    assert snapshot is not None
    assert snapshot.crawl_id == crawl.id, "Snapshot should be linked to Crawl"


def test_crawl_multiple_urls_creates_multiple_snapshots(initialized_archive):
    """Test that crawling multiple URLs creates multiple snapshots."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        [
            "crawl",
            "create",
            "https://example.com",
            "https://iana.org",
        ],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        urls = list(Snapshot.objects.order_by("url").values_list("url", flat=True))

    assert "https://example.com" in urls
    assert "https://iana.org" in urls


def test_crawl_path_argument_is_rejected_but_stdin_file_contents_create_snapshot(initialized_archive):
    """Local file paths are not URL args; users must pipe file contents through stdin."""
    env = cli_env(disable_extractors=True)

    urls_file = initialized_archive / "urls.txt"
    urls_file.write_text("https://example.com\nhttps://iana.org\n", encoding="utf-8")

    path_result = run_archivebox_cmd(
        ["crawl", "create", str(urls_file)],
        cwd=initialized_archive,
        env=env,
    )
    assert path_result.returncode == 1
    assert "No URLs provided" in path_result.stderr

    with use_archivebox_db(initialized_archive):
        assert Crawl.objects.count() == 0
        assert Snapshot.objects.count() == 0

    stdin_result = run_archivebox_cmd(
        ["crawl", "create"],
        stdin=urls_file.read_text(encoding="utf-8"),
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    assert stdin_result.returncode == 0
    run_queued_crawls(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        urls = set(Snapshot.objects.values_list("url", flat=True))

    assert "https://example.com" in urls
    assert "https://iana.org" in urls
    assert str(urls_file) not in urls


def test_crawl_persists_input_urls_on_crawl(initialized_archive):
    """Test that crawl input URLs are stored on the Crawl record."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["crawl", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )

    with use_archivebox_db(initialized_archive):
        crawl = Crawl.objects.order_by("-created_at").first()

    assert crawl is not None, "Crawl should be created for crawl input"
    assert "https://example.com" in crawl.urls, "Crawl should persist input URLs"


class TestCrawlCLI:
    """Test the CLI interface for crawl command."""

    def test_cli_help(self, tmp_path, initialized_archive):
        """Test that --help works for crawl command."""

        result = run_archivebox_cmd(
            ["crawl", "--help"],
        )

        assert result.returncode == 0
        assert "create" in result.stdout
