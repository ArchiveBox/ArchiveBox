"""
Tests for archivebox run CLI command.

Tests cover:
- run with stdin JSONL (Crawl, Snapshot, ArchiveResult)
- create-or-update behavior (records with/without id)
- pass-through output (for chaining)
"""

import json
import pytest

from archivebox.tests.conftest import (
    run_archivebox_cmd,
    parse_jsonl_output,
    create_test_url,
    create_test_crawl_json,
    create_test_snapshot_json,
)


class TestRunWithCrawl:
    """Tests for `archivebox run` with Crawl input."""

    def test_run_with_new_crawl(self, initialized_archive):
        """Run creates and processes a new Crawl (no id)."""
        crawl_record = create_test_crawl_json()

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(crawl_record),
            data_dir=initialized_archive,
            timeout=120,
        )

        assert code == 0, f"Command failed: {stderr}"

        # Should output the created Crawl
        records = parse_jsonl_output(stdout)
        crawl_records = [r for r in records if r.get('type') == 'Crawl']
        assert len(crawl_records) >= 1
        assert crawl_records[0].get('id')  # Should have an id now

    def test_run_with_existing_crawl(self, initialized_archive):
        """Run re-queues an existing Crawl (with id)."""
        url = create_test_url()

        # First create a crawl
        stdout1, _, _ = run_archivebox_cmd(['crawl', 'create', url], data_dir=initialized_archive)
        crawl = parse_jsonl_output(stdout1)[0]

        # Run with the existing crawl
        stdout2, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(crawl),
            data_dir=initialized_archive,
            timeout=120,
        )

        assert code == 0
        records = parse_jsonl_output(stdout2)
        assert len(records) >= 1


class TestRunWithSnapshot:
    """Tests for `archivebox run` with Snapshot input."""

    def test_run_with_new_snapshot(self, initialized_archive):
        """Run creates and processes a new Snapshot (no id, just url)."""
        snapshot_record = create_test_snapshot_json()

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(snapshot_record),
            data_dir=initialized_archive,
            timeout=120,
        )

        assert code == 0, f"Command failed: {stderr}"

        records = parse_jsonl_output(stdout)
        snapshot_records = [r for r in records if r.get('type') == 'Snapshot']
        assert len(snapshot_records) >= 1
        assert snapshot_records[0].get('id')

    def test_run_with_existing_snapshot(self, initialized_archive):
        """Run re-queues an existing Snapshot (with id)."""
        url = create_test_url()

        # First create a snapshot
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        # Run with the existing snapshot
        stdout2, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
            timeout=120,
        )

        assert code == 0
        records = parse_jsonl_output(stdout2)
        assert len(records) >= 1

    def test_run_with_plain_url(self, initialized_archive):
        """Run accepts plain URL records (no type field)."""
        url = create_test_url()
        url_record = {'url': url}

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(url_record),
            data_dir=initialized_archive,
            timeout=120,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        assert len(records) >= 1


class TestRunWithArchiveResult:
    """Tests for `archivebox run` with ArchiveResult input."""

    def test_run_requeues_failed_archiveresult(self, initialized_archive):
        """Run re-queues a failed ArchiveResult."""
        url = create_test_url()

        # Create snapshot and archive result
        stdout1, _, _ = run_archivebox_cmd(['snapshot', 'create', url], data_dir=initialized_archive)
        snapshot = parse_jsonl_output(stdout1)[0]

        stdout2, _, _ = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=title'],
            stdin=json.dumps(snapshot),
            data_dir=initialized_archive,
        )
        ar = next(r for r in parse_jsonl_output(stdout2) if r.get('type') == 'ArchiveResult')

        # Update to failed
        ar['status'] = 'failed'
        run_archivebox_cmd(
            ['archiveresult', 'update', '--status=failed'],
            stdin=json.dumps(ar),
            data_dir=initialized_archive,
        )

        # Now run should re-queue it
        stdout3, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(ar),
            data_dir=initialized_archive,
            timeout=120,
        )

        assert code == 0
        records = parse_jsonl_output(stdout3)
        ar_records = [r for r in records if r.get('type') == 'ArchiveResult']
        assert len(ar_records) >= 1


class TestRunPassThrough:
    """Tests for pass-through behavior in `archivebox run`."""

    def test_run_passes_through_unknown_types(self, initialized_archive):
        """Run passes through records with unknown types."""
        unknown_record = {'type': 'Unknown', 'id': 'fake-id', 'data': 'test'}

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(unknown_record),
            data_dir=initialized_archive,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        unknown_records = [r for r in records if r.get('type') == 'Unknown']
        assert len(unknown_records) == 1
        assert unknown_records[0]['data'] == 'test'

    def test_run_outputs_all_processed_records(self, initialized_archive):
        """Run outputs all processed records for chaining."""
        url = create_test_url()
        crawl_record = create_test_crawl_json(urls=[url])

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(crawl_record),
            data_dir=initialized_archive,
            timeout=120,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)
        # Should have at least the Crawl in output
        assert len(records) >= 1


class TestRunMixedInput:
    """Tests for `archivebox run` with mixed record types."""

    def test_run_handles_mixed_types(self, initialized_archive):
        """Run handles mixed Crawl/Snapshot/ArchiveResult input."""
        crawl = create_test_crawl_json()
        snapshot = create_test_snapshot_json()
        unknown = {'type': 'Tag', 'id': 'fake', 'name': 'test'}

        stdin = '\n'.join([
            json.dumps(crawl),
            json.dumps(snapshot),
            json.dumps(unknown),
        ])

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=stdin,
            data_dir=initialized_archive,
            timeout=120,
        )

        assert code == 0
        records = parse_jsonl_output(stdout)

        types = set(r.get('type') for r in records)
        # Should have processed Crawl and Snapshot, passed through Tag
        assert 'Crawl' in types or 'Snapshot' in types or 'Tag' in types


class TestRunEmpty:
    """Tests for `archivebox run` edge cases."""

    def test_run_empty_stdin(self, initialized_archive):
        """Run with empty stdin returns success."""
        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin='',
            data_dir=initialized_archive,
        )

        assert code == 0

    def test_run_no_records_to_process(self, initialized_archive):
        """Run with only pass-through records shows message."""
        unknown = {'type': 'Unknown', 'id': 'fake'}

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(unknown),
            data_dir=initialized_archive,
        )

        assert code == 0
        assert 'No records to process' in stderr
