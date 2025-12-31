"""
Tests for archivebox snapshot CLI command.

Tests cover:
- snapshot create (from URLs, from Crawl JSONL, pass-through)
- snapshot list (with filters)
- snapshot update
- snapshot delete
"""

import json
import pytest

from archivebox.tests.conftest import (
    run_archivebox_cmd,
    parse_jsonl_output,
    assert_jsonl_contains_type,
    create_test_url,
)


class TestSnapshotCreate:
    """Tests for `archivebox snapshot create`."""

    def test_create_from_url_args(self, initialized_archive):
        """Create snapshot from URL arguments."""
        url = create_test_url()

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'create', url],
            data_dir=initialized_archive,
        )

        assert code == 0, f"Command failed: {stderr}"
        assert 'Created' in stderr

        records = parse_jsonl_output(stdout)
        assert len(records) == 1
        assert records[0]['type'] == 'Snapshot'
        assert records[0]['url'] == url

    def test_create_from_crawl_jsonl(self, initialized_archive):
        """Create snapshots from Crawl JSONL input."""
        url = create_test_url()

        # First create a crawl
        stdout1, _, _ = run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)
        crawl = parse_jsonl_output(stdout1)[0]

        # Pipe crawl to snapshot create
        stdout2, stderr, code = run_archivebox_cmd(
            ['snapshot', 'create'],
            stdin=json.dumps(crawl),
            data_dir=initialized_archive,
        )

        assert code == 0, f"Command failed: {stderr}"

        records = parse_jsonl_output(stdout2)
        # Should have the Crawl passed through and the Snapshot created
        types = [r.get('type') for r in records]
        assert 'Crawl' in types
        assert 'Snapshot' in types

        snapshot = next(r for r in records if r['type'] == 'Snapshot')
        assert snapshot['url'] == url

    def test_create_with_tag(self, initialized_archive):
        """Create snapshot with --tag flag."""
        url = create_test_url()

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'create', '--tag=test-tag', url],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert 'test-tag' in records[0].get('tags_str', '')

    def test_create_pass_through_other_types(self, initialized_archive):
        """Pass-through records of other types unchanged."""
        tag_record = {'type': 'Tag', 'id': 'fake-tag-id', 'name': 'test'}
        url = create_test_url()
        stdin = json.dumps(tag_record) + '\n' + json.dumps({'url': url})

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'create'],
            stdin=stdin,
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)

        types = [r.get('type') for r in records]
        assert 'Tag' in types
        assert 'Snapshot' in types

    def test_create_multiple_urls(self, initialized_archive):
        """Create snapshots from multiple URLs."""
        urls = [create_test_url() for _ in range(3)]

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'create'] + urls,
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 3

        created_urls = {r['url'] for r in records}
        for url in urls:
            assert url in created_urls


class TestSnapshotList:
    """Tests for `archivebox snapshot list`."""

    def test_list_empty(self, initialized_archive):
        """List with no snapshots returns empty."""
        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'list'],
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Listed 0 snapshots' in stderr

    def test_list_returns_created(self, initialized_archive):
        """List returns previously created snapshots."""
        url = create_test_url()
        run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'list'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) >= 1
        assert any(r.get('url') == url for r in records)

    def test_list_filter_by_status(self, initialized_archive):
        """Filter snapshots by status."""
        url = create_test_url()
        run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'list', '--status=queued'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        for r in records:
            assert r['status'] == 'queued'

    def test_list_filter_by_url_contains(self, initialized_archive):
        """Filter snapshots by URL contains."""
        url = create_test_url(domain='unique-domain-12345.com')
        run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'list', '--url__icontains=unique-domain-12345'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 1
        assert 'unique-domain-12345' in records[0]['url']

    def test_list_with_limit(self, initialized_archive):
        """Limit number of results."""
        for _ in range(3):
            run_archivebox_cmd(['snapshot', 'create', create_test_url()], data_dir=initialized_archive)

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'list', '--limit=2'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 2


class TestSnapshotUpdate:
    """Tests for `archivebox snapshot update`."""

    def test_update_status(self, initialized_archive):
        """Update snapshot status."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout2, stderr, code = run_archivebox_cmd(
            ['snapshot', 'update', '--status=started'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Updated 1 snapshots' in stderr

        records = parse_jsonl_output(stdout2)
        assert records[0]['status'] == 'started'

    def test_update_add_tag(self, initialized_archive):
        """Update snapshot by adding tag."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout2, stderr, code = run_archivebox_cmd(
            ['snapshot', 'update', '--tag=new-tag'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Updated 1 snapshots' in stderr


class TestSnapshotDelete:
    """Tests for `archivebox snapshot delete`."""

    def test_delete_requires_yes(self, initialized_archive):
        """Delete requires --yes flag."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'delete'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        assert code == 1
        assert '--yes' in stderr

    def test_delete_with_yes(self, initialized_archive):
        """Delete with --yes flag works."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'delete', '--yes'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Deleted 1 snapshots' in stderr

    def test_delete_dry_run(self, initialized_archive):
        """Dry run shows what would be deleted."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout, stderr, code = run_archivebox_cmd(
            ['snapshot', 'delete', '--dry-run'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Would delete' in stderr
