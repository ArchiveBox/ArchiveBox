"""
Tests for archivebox snapshot CLI command.

Tests cover:
- snapshot create (from URLs, from Crawl JSONL, pass-through)
- snapshot list (with filters)
- snapshot update
- snapshot delete
"""

import json
import os

import pytest

from archivebox.core.models import Snapshot, Tag
from archivebox.machine.models import Process
from archivebox.tests.conftest import (
    cli_env,
    create_test_url,
    parse_jsonl_output,
    run_archivebox_cmd,
)
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


class TestSnapshotCreate:
    """Tests for `archivebox snapshot create`."""

    def test_create_from_url_args(self, initialized_archive):
        """Create snapshot from URL arguments."""
        url = create_test_url()

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, f"Command failed: {stderr}"
        assert "Created" in stderr

        records = parse_jsonl_output(stdout)
        assert len(records) == 1
        assert records[0]["type"] == "Snapshot"
        assert records[0]["url"] == url

    def test_create_from_crawl_jsonl(self, initialized_archive):
        """Create snapshots from Crawl JSONL input."""
        url = create_test_url()

        # First create a crawl
        _cmd_result = run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        crawl = parse_jsonl_output(stdout1)[0]

        # Pipe crawl to snapshot create
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create"],
            stdin=json.dumps(crawl),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, f"Command failed: {stderr}"

        records = parse_jsonl_output(stdout2)
        # Should have the Crawl passed through and the Snapshot created
        types = [r.get("type") for r in records]
        assert "Crawl" in types
        assert "Snapshot" in types

        snapshot = next(r for r in records if r["type"] == "Snapshot")
        assert snapshot["url"] == url

    def test_create_with_tag(self, initialized_archive):
        """Create snapshot with --tag flag."""
        url = create_test_url()

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", "--tag=test-tag", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert "test-tag" in records[0].get("tags", "")

    def test_create_passes_through_tag_emitted_by_cli(self, initialized_archive):
        """A real Tag emitted by the CLI remains available to the next stage."""
        tag_result = run_archivebox_cmd(
            ["tag", "create", "snapshot-input-tag"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        assert tag_result.returncode == 0, tag_result.stderr
        tag_record = parse_jsonl_output(tag_result.stdout)[0]
        url = create_test_url()
        stdin = tag_result.stdout + url + "\n"

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create"],
            stdin=stdin,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)

        assert any(record.get("type") == "Tag" and record["id"] == tag_record["id"] for record in records)
        assert any(record.get("type") == "Snapshot" and record["url"] == url for record in records)

    def test_create_multiple_urls(self, initialized_archive):
        """Create snapshots from multiple URLs."""
        urls = [create_test_url() for _ in range(3)]

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create"] + urls,
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 3

        created_urls = {r["url"] for r in records}
        for url in urls:
            assert url in created_urls


class TestSnapshotList:
    """Tests for `archivebox snapshot list`."""

    def test_list_empty(self, initialized_archive):
        """List with no snapshots returns empty."""
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "list"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Listed 0 snapshots" in stderr

    def test_list_returns_created(self, initialized_archive):
        """List returns previously created snapshots."""
        url = create_test_url()
        run_archivebox_cmd(["snapshot", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "list"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) >= 1
        assert any(r.get("url") == url for r in records)

    def test_list_filter_by_status(self, initialized_archive):
        """Filter snapshots by status."""
        url = create_test_url()
        run_archivebox_cmd(["snapshot", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "list", "--status=queued"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        for r in records:
            assert r["status"] == "queued"

    def test_list_filter_by_url_contains(self, initialized_archive):
        """Filter snapshots by URL contains."""
        url = create_test_url(domain="unique-domain-12345.com")
        run_archivebox_cmd(["snapshot", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "list", "--url__icontains=unique-domain-12345"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 1
        assert "unique-domain-12345" in records[0]["url"]

    def test_list_with_limit(self, initialized_archive):
        """Limit number of results."""
        for _ in range(3):
            run_archivebox_cmd(
                ["snapshot", "create", create_test_url()],
                cwd=initialized_archive,
                default_cli_env=True,
                disable_extractors=True,
            )

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "list", "--limit=2"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 2

    def test_list_with_sort_and_limit(self, initialized_archive):
        """Sorting should be applied before limiting."""
        for _ in range(3):
            run_archivebox_cmd(
                ["snapshot", "create", create_test_url()],
                cwd=initialized_archive,
                default_cli_env=True,
                disable_extractors=True,
            )

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "list", "--limit=2", "--sort=-created_at"],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, f"Command failed: {stderr}"
        records = parse_jsonl_output(stdout)
        assert len(records) == 2


class TestSnapshotUpdate:
    """Tests for `archivebox snapshot update`."""

    def test_update_status(self, initialized_archive):
        """Update snapshot status."""
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        snapshot = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "update", "--status=started"],
            stdin=json.dumps(snapshot),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout2, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Updated 1 snapshots" in stderr

        records = parse_jsonl_output(stdout2)
        assert records[0]["status"] == "started"

    def test_update_add_tag(self, initialized_archive):
        """Update snapshot by adding tag."""
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        snapshot = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "update", "--tag=new-tag"],
            stdin=json.dumps(snapshot),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout2, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Updated 1 snapshots" in stderr


class TestSnapshotDelete:
    """Tests for `archivebox snapshot delete`."""

    def test_delete_requires_yes(self, initialized_archive):
        """Delete requires --yes flag."""
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        snapshot = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "delete"],
            stdin=json.dumps(snapshot),
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
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        snapshot = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "delete", "--yes"],
            stdin=json.dumps(snapshot),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Deleted 1 snapshots" in stderr

    def test_delete_dry_run(self, initialized_archive):
        """Dry run shows what would be deleted."""
        url = create_test_url()
        _cmd_result = run_archivebox_cmd(
            ["snapshot", "create", url],
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        snapshot = parse_jsonl_output(stdout1)[0]

        _cmd_result = run_archivebox_cmd(
            ["snapshot", "delete", "--dry-run"],
            stdin=json.dumps(snapshot),
            cwd=initialized_archive,
            default_cli_env=True,
            disable_extractors=True,
        )
        _stdout, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        assert "Would delete" in stderr


def test_snapshot_creates_snapshot_with_correct_url(tmp_path, initialized_archive):
    """Test that snapshot stores the exact URL in the database."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=tmp_path,
        env=env,
    )

    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.select_related("crawl__created_by").get(url="https://example.com")
        username = snapshot.crawl.created_by.username

    # Verify the crawl tree contains a relative symlink to the user-scoped snapshot output.
    snapshots_root = tmp_path / "archive" / "users" / username / "snapshots"
    crawl_root = tmp_path / "archive" / "users" / username / "crawls"
    symlinks = [p for p in crawl_root.rglob("*") if p.is_symlink() and p.resolve().is_dir() and p.resolve().is_relative_to(snapshots_root)]
    assert symlinks, "Snapshot symlink should exist under crawl dir"
    link_path = symlinks[0]

    assert link_path.is_symlink(), "Snapshot symlink should exist under crawl dir"
    link_target = os.readlink(link_path)
    assert not os.path.isabs(link_target), "Symlink should be relative"


def test_snapshot_multiple_urls_creates_multiple_records(tmp_path, initialized_archive):
    """Test that multiple URLs each get their own snapshot record."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        [
            "snapshot",
            "create",
            "https://example.com",
            "https://iana.org",
        ],
        cwd=tmp_path,
        env=env,
    )

    with use_archivebox_db(tmp_path):
        urls = list(Snapshot.objects.order_by("url").values_list("url", flat=True))

    assert "https://example.com" in urls
    assert "https://iana.org" in urls
    assert len(urls) >= 2


def test_snapshot_tag_creates_tag_and_links_to_snapshot(tmp_path, initialized_archive):
    """Test that --tag creates tag record and links it to the snapshot."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        [
            "snapshot",
            "create",
            "--tag=mytesttag",
            "https://example.com",
        ],
        cwd=tmp_path,
        env=env,
    )

    with use_archivebox_db(tmp_path):
        tag = Tag.objects.filter(name="mytesttag").first()
        assert tag is not None, "Tag 'mytesttag' should exist in core_tag"
        snapshot = Snapshot.objects.filter(url="https://example.com").first()
        assert snapshot is not None
        assert snapshot.tags.filter(pk=tag.pk).exists(), "Tag should be linked to snapshot via core_snapshot_tags"


def test_snapshot_jsonl_output_has_correct_structure(tmp_path, initialized_archive):
    """Test that JSONL output contains required fields with correct types."""
    env = cli_env(disable_extractors=True)

    # Pass URL as argument instead of stdin for more reliable behavior
    result = run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=tmp_path,
        env=env,
    )

    # Parse JSONL output lines
    records = Process.parse_records_from_text(result.stdout)
    snapshot_records = [r for r in records if r.get("type") == "Snapshot"]

    assert len(snapshot_records) >= 1, "Should output at least one Snapshot JSONL record"

    record = snapshot_records[0]
    assert record.get("type") == "Snapshot"
    assert "id" in record, "Snapshot record should have 'id' field"
    assert "url" in record, "Snapshot record should have 'url' field"
    assert record["url"] == "https://example.com"


def test_snapshot_with_tag_stores_tag_name(tmp_path, initialized_archive):
    """Test that title is stored when provided via tag option."""
    env = cli_env(disable_extractors=True)

    # Use command line args instead of stdin
    run_archivebox_cmd(
        ["snapshot", "create", "--tag=customtag", "https://example.com"],
        cwd=tmp_path,
        env=env,
    )

    with use_archivebox_db(tmp_path):
        tag = Tag.objects.filter(name="customtag").first()

    assert tag is not None
    assert tag.name == "customtag"


def test_snapshot_with_depth_sets_snapshot_depth(tmp_path, initialized_archive):
    """Test that --depth sets snapshot depth when creating snapshots."""
    env = cli_env(disable_extractors=True)

    run_archivebox_cmd(
        [
            "snapshot",
            "create",
            "--depth=1",
            "https://example.com",
        ],
        cwd=tmp_path,
        env=env,
    )

    with use_archivebox_db(tmp_path):
        snapshot = Snapshot.objects.order_by("-created_at").first()

    assert snapshot is not None, "Snapshot should be created when depth is provided"
    assert snapshot.depth == 1, "Snapshot depth should match --depth value"


def test_snapshot_allows_duplicate_urls_across_crawls(tmp_path, initialized_archive):
    """Snapshot create auto-creates a crawl per run; same URL can appear multiple times."""
    env = cli_env(disable_extractors=True)

    # Add same URL twice
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=tmp_path,
        env=env,
    )
    run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=tmp_path,
        env=env,
    )

    with use_archivebox_db(tmp_path):
        count = Snapshot.objects.filter(url="https://example.com").count()

    assert count == 2, "Same URL should create separate snapshots across different crawls"
