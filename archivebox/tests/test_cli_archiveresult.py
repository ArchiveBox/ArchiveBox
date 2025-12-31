"""
Tests for archivebox archiveresult CLI command.

Tests cover:
- archiveresult create (from Snapshot JSONL, with --plugin, pass-through)
- archiveresult list (with filters)
- archiveresult update
- archiveresult delete
"""

import json
import pytest

from archivebox.tests.conftest import (
    run_archivebox_cmd,
    parse_jsonl_output,
    create_test_url,
)


class TestArchiveResultCreate:
    """Tests for `archivebox archiveresult create`."""

    def test_create_from_snapshot_jsonl(self, initialized_archive):
        """Create archive results from Snapshot JSONL input."""
        url = create_test_url()

        # Create a snapshot first
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        # Pipe snapshot to archiveresult create
        stdout2, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=title'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        assert code == 0, f"Command failed: {stderr}"

        records = parse_jsonl_output(stdout2)
        # Should have the Snapshot passed through and ArchiveResult created
        types = [r.get('type') for r in records]
        assert 'Snapshot' in types
        assert 'ArchiveResult' in types

        ar = next(r for r in records if r['type'] == 'ArchiveResult')
        assert ar['plugin'] == 'title'

    def test_create_with_specific_plugin(self, initialized_archive):
        """Create archive result for specific plugin."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout2, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=screenshot'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout2)
        ar_records = [r for r in records if r.get('type') == 'ArchiveResult']
        assert len(ar_records) >= 1
        assert ar_records[0]['plugin'] == 'screenshot'

    def test_create_pass_through_crawl(self, initialized_archive):
        """Pass-through Crawl records unchanged."""
        url = create_test_url()

        # Create crawl and snapshot
        stdout1, _, _ = run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)
        crawl = parse_jsonl_output(stdout1)[0]

        stdout2, _, _ = run_archivebox_cmd(
            ['snapshot', 'create'],
            stdin=json.dumps(crawl),
            data_dir=initialized_archive,
        )

        # Now pipe all to archiveresult create
        stdout3, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=title'],
            stdin=stdout2,
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout3)

        types = [r.get('type') for r in records]
        assert 'Crawl' in types
        assert 'Snapshot' in types
        assert 'ArchiveResult' in types

    def test_create_pass_through_only_when_no_snapshots(self, initialized_archive):
        """Only pass-through records but no new snapshots returns success."""
        crawl_record = {'type': 'Crawl', 'id': 'fake-id', 'urls': 'https://example.com'}

        stdout, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'create'],
            stdin=json.dumps(crawl_record),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Passed through' in stderr


class TestArchiveResultList:
    """Tests for `archivebox archiveresult list`."""

    def test_list_empty(self, initialized_archive):
        """List with no archive results returns empty."""
        stdout, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'list'],
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Listed 0 archive results' in stderr

    def test_list_filter_by_status(self, initialized_archive):
        """Filter archive results by status."""
        # Create snapshot and archive result
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]
        run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=title'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        stdout, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'list', '--status=queued'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        for r in records:
            assert r['status'] == 'queued'

    def test_list_filter_by_plugin(self, initialized_archive):
        """Filter archive results by plugin."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]
        run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=title'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        stdout, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'list', '--plugin=title'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        for r in records:
            assert r['plugin'] == 'title'

    def test_list_with_limit(self, initialized_archive):
        """Limit number of results."""
        # Create multiple archive results
        for _ in range(3):
            url = create_test_url()
            stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
            snapshot = parse_jsonl_output(stdout1)[0]
            run_archivebox_cmd(
                ['archiveresult', 'create', '--plugin=title'],
                stdin=json.dumps(snapshot),
                data_dir=initialized_archive,
            )

        stdout, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'list', '--limit=2'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 2


class TestArchiveResultUpdate:
    """Tests for `archivebox archiveresult update`."""

    def test_update_status(self, initialized_archive):
        """Update archive result status."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout2, _, _ = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=title'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )
        ar = next(r for r in parse_jsonl_output(stdout2) if r.get('type') == 'ArchiveResult')

        stdout3, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'update', '--status=failed'],
            stdin=json.dumps(ar),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Updated 1 archive results' in stderr

        records = parse_jsonl_output(stdout3)
        assert records[0]['status'] == 'failed'


class TestArchiveResultDelete:
    """Tests for `archivebox archiveresult delete`."""

    def test_delete_requires_yes(self, initialized_archive):
        """Delete requires --yes flag."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout2, _, _ = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=title'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )
        ar = next(r for r in parse_jsonl_output(stdout2) if r.get('type') == 'ArchiveResult')

        stdout, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'delete'],
            stdin=json.dumps(ar),
            data_dir=initialized_archive,
        )

        assert code == 1
        assert '--yes' in stderr

    def test_delete_with_yes(self, initialized_archive):
        """Delete with --yes flag works."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout2, _, _ = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=title'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )
        ar = next(r for r in parse_jsonl_output(stdout2) if r.get('type') == 'ArchiveResult')

        stdout, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'delete', '--yes'],
            stdin=json.dumps(ar),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Deleted 1 archive results' in stderr
