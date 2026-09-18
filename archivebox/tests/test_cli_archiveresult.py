"""
Tests for archivebox archiveresult CLI command.

Tests cover:
- archiveresult create (from Snapshot JSONL, with --plugin, pass-through)
- archiveresult list (with filters)
- archiveresult update
- archiveresult delete
"""

import json

from archivebox.tests.conftest import (
    run_archivebox_cmd,
    parse_jsonl_output,
    create_test_url,
)

PROJECTOR_TEST_ENV = {
    "PLUGINS": "favicon",
    "SAVE_FAVICON": "True",
    "USE_COLOR": "False",
    "SHOW_PROGRESS": "False",
}


def create_projected_favicon(archive):
    """Run the public create/request/run pipeline and return its persisted result."""
    common = {"cwd": archive, "default_cli_env": True, "disable_extractors": True, "check": True}
    created = run_archivebox_cmd(["snapshot", "create", create_test_url()], **common)
    snapshot = parse_jsonl_output(created.stdout)[0]
    requested = run_archivebox_cmd(["archiveresult", "create", "--plugin=favicon"], stdin=json.dumps(snapshot), **common)
    run_archivebox_cmd(["run"], stdin=requested.stdout, timeout=120, env=PROJECTOR_TEST_ENV, **common)
    listed = run_archivebox_cmd(["archiveresult", "list", "--plugin=favicon", f"--snapshot-id={snapshot['id']}"], **common)
    records = parse_jsonl_output(listed.stdout)
    assert len(records) == 1
    return records[0]


class TestArchiveResultCreate:
    """Tests for `archivebox archiveresult create`."""

    def test_create_from_snapshot_jsonl(self, archivebox_cli, initialized_archive):
        """Create archive results from Snapshot JSONL input."""
        url = create_test_url()

        # Create a snapshot first
        _cmd_result = archivebox_cli(
            ["snapshot", "create", url],
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        snapshot = parse_jsonl_output(stdout1)[0]

        # Pipe snapshot to archiveresult create
        _cmd_result = archivebox_cli(
            ["archiveresult", "create", "--plugin=title"],
            stdin=json.dumps(snapshot),
        )
        stdout2, stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0, f"Command failed: {stderr}"

        records = parse_jsonl_output(stdout2)
        # Should have the Snapshot passed through and an ArchiveResult request emitted
        types = [r.get("type") for r in records]
        assert "Snapshot" in types
        assert "ArchiveResult" in types

        ar = next(r for r in records if r["type"] == "ArchiveResult")
        assert ar["plugin"] == "title"
        # Hook identity is known at scheduling time and is the durable retry
        # key. Emitting it here prevents multiple hooks in one plugin from
        # collapsing into the same ArchiveResult row.
        assert ar["hook_name"] == "on_Snapshot__54_title"
        assert "id" not in ar

    def test_create_with_specific_plugin(self, archivebox_cli, initialized_archive):
        """Create archive result for specific plugin."""
        url = create_test_url()
        _cmd_result = archivebox_cli(
            ["snapshot", "create", url],
        )
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        snapshot = parse_jsonl_output(stdout1)[0]

        _cmd_result = archivebox_cli(
            ["archiveresult", "create", "--plugin=screenshot"],
            stdin=json.dumps(snapshot),
        )
        stdout2, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout2)
        ar_records = [r for r in records if r.get("type") == "ArchiveResult"]
        assert len(ar_records) == 1
        assert all(record["plugin"] == "screenshot" for record in ar_records)
        assert [record["hook_name"] for record in ar_records] == ["on_Snapshot__51_screenshot"]

    def test_create_pass_through_crawl(self, archivebox_cli, initialized_archive):
        """Pass-through Crawl records unchanged."""
        url = create_test_url()

        # Create crawl and snapshot
        _cmd_result = run_archivebox_cmd(["crawl", "create", url], cwd=initialized_archive, default_cli_env=True, disable_extractors=True)
        stdout1, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode
        crawl = parse_jsonl_output(stdout1)[0]

        _cmd_result = archivebox_cli(
            ["snapshot", "create"],
            stdin=json.dumps(crawl),
        )
        stdout2, _, _ = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        # Now pipe all to archiveresult create
        _cmd_result = archivebox_cli(
            ["archiveresult", "create", "--plugin=title"],
            stdin=stdout2,
        )
        stdout3, _stderr, code = _cmd_result.stdout, _cmd_result.stderr, _cmd_result.returncode

        assert code == 0
        records = parse_jsonl_output(stdout3)

        types = [r.get("type") for r in records]
        assert "Crawl" in types
        assert "Snapshot" in types
        assert "ArchiveResult" in types

    def test_create_passes_through_cli_crawl_when_no_snapshots(self, archivebox_cli, initialized_archive):
        """A real Crawl with no Snapshot input passes through successfully."""
        crawl_result = archivebox_cli(
            ["crawl", "create", create_test_url()],
        )
        assert crawl_result.returncode == 0, crawl_result.stderr
        crawl_record = parse_jsonl_output(crawl_result.stdout)[0]

        result = archivebox_cli(
            ["archiveresult", "create"],
            stdin=crawl_result.stdout,
        )

        assert result.returncode == 0
        assert "Passed through" in result.stderr
        records = parse_jsonl_output(result.stdout)
        assert len(records) == 1
        assert records[0]["id"] == crawl_record["id"]


class TestArchiveResultList:
    """Tests for `archivebox archiveresult list`."""

    def test_list_empty(self, archivebox_cli, initialized_archive):
        """List with no archive results returns empty."""
        result = archivebox_cli(
            ["archiveresult", "list"],
        )

        assert result.returncode == 0
        assert "Listed 0 archive results" in result.stderr

    def test_list_filter_by_status(self, archivebox_cli, initialized_archive):
        """Filter archive results by status."""
        # Create snapshot and materialize an archive result via the runner
        created = create_projected_favicon(initialized_archive)
        archivebox_cli(
            ["archiveresult", "update", "--status=queued"],
            stdin=json.dumps(created),
        )

        result = archivebox_cli(
            ["archiveresult", "list", "--status=queued"],
        )

        assert result.returncode == 0
        records = parse_jsonl_output(result.stdout)
        for r in records:
            assert r["status"] == "queued"

    def test_list_filter_by_plugin(self, archivebox_cli, initialized_archive):
        """Filter archive results by plugin."""
        create_projected_favicon(initialized_archive)

        result = archivebox_cli(
            ["archiveresult", "list", "--plugin=favicon"],
        )

        assert result.returncode == 0
        records = parse_jsonl_output(result.stdout)
        for r in records:
            assert r["plugin"] == "favicon"

    def test_list_with_limit(self, archivebox_cli, initialized_archive):
        """Limit number of results."""
        # Create multiple archive results
        for _ in range(3):
            create_projected_favicon(initialized_archive)

        result = archivebox_cli(
            ["archiveresult", "list", "--limit=2"],
        )

        assert result.returncode == 0
        records = parse_jsonl_output(result.stdout)
        assert len(records) == 2


class TestArchiveResultUpdate:
    """Tests for `archivebox archiveresult update`."""

    def test_update_status(self, archivebox_cli, initialized_archive):
        """Update archive result status."""
        ar = create_projected_favicon(initialized_archive)

        result = archivebox_cli(
            ["archiveresult", "update", "--status=failed"],
            stdin=json.dumps(ar),
        )

        assert result.returncode == 0
        assert "Updated 1 archive results" in result.stderr

        records = parse_jsonl_output(result.stdout)
        assert records[0]["status"] == "failed"


class TestArchiveResultDelete:
    """Tests for `archivebox archiveresult delete`."""

    def test_delete_requires_yes(self, archivebox_cli, initialized_archive):
        """Delete requires --yes flag."""
        ar = create_projected_favicon(initialized_archive)

        result = archivebox_cli(
            ["archiveresult", "delete"],
            stdin=json.dumps(ar),
        )

        assert result.returncode == 1
        assert "--yes" in result.stderr

    def test_delete_with_yes(self, archivebox_cli, initialized_archive):
        """Delete with --yes flag works."""
        ar = create_projected_favicon(initialized_archive)

        result = archivebox_cli(
            ["archiveresult", "delete", "--yes"],
            stdin=json.dumps(ar),
        )

        assert result.returncode == 0
        assert "Deleted 1 archive results" in result.stderr
