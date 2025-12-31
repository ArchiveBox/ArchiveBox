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

from archivebox.tests.conftest import (
    run_archivebox_cmd,
    parse_jsonl_output,
    assert_jsonl_contains_type,
    create_test_url,
    create_test_crawl_json,
)


class TestCrawlCreate:
    """Tests for `archivebox crawl create`."""

    def test_create_from_url_args(self, initialized_archive):
        """Create crawl from URL arguments."""
        url = create_test_url()

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'create', url],
            data_dir=initialized_archive,
        )

        assert code == 0, f"Command failed: {stderr}"
        assert 'Created crawl' in stderr

        # Check JSONL output
        records = parse_jsonl_output(stdout)
        assert len(records) == 1
        assert records[0]['type'] == 'Crawl'
        assert url in records[0]['urls']

    def test_create_from_stdin_urls(self, initialized_archive):
        """Create crawl from stdin URLs (one per line)."""
        urls = [create_test_url() for _ in range(3)]
        stdin = '\n'.join(urls)

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'create'],
            stdin=stdin,
            data_dir=initialized_archive,
        )

        assert code == 0, f"Command failed: {stderr}"

        records = parse_jsonl_output(stdout)
        assert len(records) == 1
        crawl = records[0]
        assert crawl['type'] == 'Crawl'
        # All URLs should be in the crawl
        for url in urls:
            assert url in crawl['urls']

    def test_create_with_depth(self, initialized_archive):
        """Create crawl with --depth flag."""
        url = create_test_url()

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'create', '--depth=2', url],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert records[0]['max_depth'] == 2

    def test_create_with_tag(self, initialized_archive):
        """Create crawl with --tag flag."""
        url = create_test_url()

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'create', '--tag=test-tag', url],
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
            ['crawl', 'create'],
            stdin=stdin,
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)

        # Should have both the passed-through Tag and the new Crawl
        types = [r.get('type') for r in records]
        assert 'Tag' in types
        assert 'Crawl' in types

    def test_create_pass_through_existing_crawl(self, initialized_archive):
        """Existing Crawl records (with id) are passed through."""
        # First create a crawl
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)
        crawl = parse_jsonl_output(stdout1)[0]

        # Now pipe it back - should pass through
        stdout2, stderr, code = run_archivebox_cmd(
            ['crawl', 'create'],
            stdin=json.dumps(crawl),
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout2)
        assert len(records) == 1
        assert records[0]['id'] == crawl['id']


class TestCrawlList:
    """Tests for `archivebox crawl list`."""

    def test_list_empty(self, initialized_archive):
        """List with no crawls returns empty."""
        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'list'],
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Listed 0 crawls' in stderr

    def test_list_returns_created(self, initialized_archive):
        """List returns previously created crawls."""
        url = create_test_url()
        run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'list'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) >= 1
        assert any(url in r.get('urls', '') for r in records)

    def test_list_filter_by_status(self, initialized_archive):
        """Filter crawls by status."""
        url = create_test_url()
        run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'list', '--status=queued'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        for r in records:
            assert r['status'] == 'queued'

    def test_list_with_limit(self, initialized_archive):
        """Limit number of results."""
        # Create multiple crawls
        for _ in range(3):
            run_archivebox_cmd(['crawl', 'create', create_test_url()], data_dir=initialized_archive)

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'list', '--limit=2'],
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) == 2


class TestCrawlUpdate:
    """Tests for `archivebox crawl update`."""

    def test_update_status(self, initialized_archive):
        """Update crawl status."""
        # Create a crawl
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)
        crawl = parse_jsonl_output(stdout1)[0]

        # Update it
        stdout2, stderr, code = run_archivebox_cmd(
            ['crawl', 'update', '--status=started'],
            stdin=json.dumps(crawl),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Updated 1 crawls' in stderr

        records = parse_jsonl_output(stdout2)
        assert records[0]['status'] == 'started'


class TestCrawlDelete:
    """Tests for `archivebox crawl delete`."""

    def test_delete_requires_yes(self, initialized_archive):
        """Delete requires --yes flag."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)
        crawl = parse_jsonl_output(stdout1)[0]

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'delete'],
            stdin=json.dumps(crawl),
            data_dir=initialized_archive,
        )

        assert code == 1
        assert '--yes' in stderr

    def test_delete_with_yes(self, initialized_archive):
        """Delete with --yes flag works."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)
        crawl = parse_jsonl_output(stdout1)[0]

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'delete', '--yes'],
            stdin=json.dumps(crawl),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Deleted 1 crawls' in stderr

    def test_delete_dry_run(self, initialized_archive):
        """Dry run shows what would be deleted."""
        url = create_test_url()
        stdout1, _, _ = run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)
        crawl = parse_jsonl_output(stdout1)[0]

        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'delete', '--dry-run'],
            stdin=json.dumps(crawl),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'Would delete' in stderr
        assert 'dry run' in stderr.lower()
