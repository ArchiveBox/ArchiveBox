"""
Tests for CLI JSONL piping with real URL archiving.

Tests the REAL piping workflows users will run:
- archivebox crawl create URL | archivebox run
- archivebox snapshot create URL | archivebox run
- archivebox archiveresult list --status=failed | archivebox run
- Pass-through behavior (accumulating records through pipeline)

Uses module-scoped fixture for speed - init runs ONCE per test file.
Uses inline mode in orchestrator for fast processing (no subprocess overhead).
"""

import json
import pytest

from archivebox.tests.conftest import run_archivebox_cmd, parse_jsonl, create_url


class TestCrawlPipeline:
    """Test: archivebox crawl create URL | archivebox run"""

    def test_crawl_create_outputs_jsonl(self, shared_archive):
        """crawl create outputs Crawl JSONL to stdout."""
        url = create_url("crawl-test")
        stdout, stderr, code = run_archivebox_cmd(
            ['crawl', 'create', url],
            data_dir=shared_archive,
        )
        assert code == 0, stderr
        records = parse_jsonl(stdout)
        assert len(records) == 1
        assert records[0]['type'] == 'Crawl'
        assert url in records[0]['urls']

    def test_crawl_pipe_to_run(self, shared_archive):
        """crawl create | run - processes with inline mode (fast)."""
        url = create_url("pipe-to-run")

        # Create crawl
        stdout1, _, code1 = run_archivebox_cmd(
            ['crawl', 'create', url],
            data_dir=shared_archive,
        )
        assert code1 == 0

        # Pipe to run (uses inline mode for fast processing)
        stdout2, stderr2, code2 = run_archivebox_cmd(
            ['run'],
            stdin=stdout1,
            data_dir=shared_archive,
            timeout=30,
        )
        assert code2 == 0, stderr2

        # run outputs processed records
        records = parse_jsonl(stdout2)
        assert len(records) >= 1
        assert any(r.get('type') == 'Crawl' for r in records)


class TestSnapshotPipeline:
    """Test: archivebox snapshot create URL | archivebox run"""

    def test_snapshot_from_crawl(self, shared_archive):
        """snapshot create accepts Crawl JSONL and creates Snapshots."""
        url = create_url("snap-from-crawl")

        # Create crawl
        stdout1, _, _ = run_archivebox_cmd(
            ['crawl', 'create', url],
            data_dir=shared_archive,
        )

        # Pipe to snapshot create
        stdout2, stderr, code = run_archivebox_cmd(
            ['snapshot', 'create'],
            stdin=stdout1,
            data_dir=shared_archive,
        )
        assert code == 0, stderr

        records = parse_jsonl(stdout2)
        types = {r['type'] for r in records}

        # Should have Crawl (passed through) and Snapshot (created)
        assert 'Crawl' in types
        assert 'Snapshot' in types

    def test_snapshot_pipe_to_run(self, shared_archive):
        """snapshot create | run - processes with inline mode."""
        url = create_url("snap-to-run")

        # Create snapshot
        stdout1, _, code1 = run_archivebox_cmd(
            ['snapshot', 'create', url],
            data_dir=shared_archive,
        )
        assert code1 == 0

        # Pipe to run
        stdout2, stderr2, code2 = run_archivebox_cmd(
            ['run'],
            stdin=stdout1,
            data_dir=shared_archive,
            timeout=30,
        )
        assert code2 == 0, stderr2

        records = parse_jsonl(stdout2)
        snapshots = [r for r in records if r.get('type') == 'Snapshot']
        assert len(snapshots) >= 1


class TestArchiveResultPipeline:
    """Test: snapshot | archiveresult create --plugin=X | run"""

    def test_archiveresult_from_snapshot(self, shared_archive):
        """archiveresult create accepts Snapshot JSONL."""
        url = create_url("ar-from-snap")

        # Create snapshot
        stdout1, _, _ = run_archivebox_cmd(
            ['snapshot', 'create', url],
            data_dir=shared_archive,
        )

        # Pipe to archiveresult create
        stdout2, stderr, code = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=headers'],
            stdin=stdout1,
            data_dir=shared_archive,
        )
        assert code == 0, stderr

        records = parse_jsonl(stdout2)
        types = {r['type'] for r in records}

        # Should have Snapshot (passed through) and ArchiveResult (created)
        assert 'Snapshot' in types
        assert 'ArchiveResult' in types


class TestFullPipeline:
    """Test: crawl create | snapshot create | archiveresult create | run"""

    def test_full_four_stage_pipeline(self, shared_archive):
        """Full 4-stage pipeline with real processing."""
        url = create_url("full-pipeline")

        # Stage 1: crawl create
        out1, _, code1 = run_archivebox_cmd(
            ['crawl', 'create', url],
            data_dir=shared_archive,
        )
        assert code1 == 0

        # Stage 2: snapshot create
        out2, _, code2 = run_archivebox_cmd(
            ['snapshot', 'create'],
            stdin=out1,
            data_dir=shared_archive,
        )
        assert code2 == 0

        # Stage 3: archiveresult create
        out3, _, code3 = run_archivebox_cmd(
            ['archiveresult', 'create', '--plugin=headers'],
            stdin=out2,
            data_dir=shared_archive,
        )
        assert code3 == 0

        # Stage 4: run (inline mode)
        out4, stderr, code4 = run_archivebox_cmd(
            ['run'],
            stdin=out3,
            data_dir=shared_archive,
            timeout=30,
        )
        assert code4 == 0, stderr

        # Final output should have records
        records = parse_jsonl(out4)
        types = {r['type'] for r in records}
        assert len(types) >= 1


class TestPassThrough:
    """Test pass-through behavior - unknown types pass through unchanged."""

    def test_unknown_type_passes_through(self, shared_archive):
        """Records with unknown types pass through all commands."""
        unknown = {'type': 'CustomType', 'id': 'test-123', 'data': 'preserved'}
        url = create_url("passthrough")

        stdin = json.dumps(unknown) + '\n' + url

        stdout, _, code = run_archivebox_cmd(
            ['crawl', 'create'],
            stdin=stdin,
            data_dir=shared_archive,
        )
        assert code == 0

        records = parse_jsonl(stdout)
        types = {r['type'] for r in records}

        # CustomType should be passed through
        assert 'CustomType' in types
        assert 'Crawl' in types

        # Data should be preserved
        custom = next(r for r in records if r['type'] == 'CustomType')
        assert custom['data'] == 'preserved'


class TestListCommands:
    """Test list commands with filters."""

    def test_crawl_list_filter_status(self, shared_archive):
        """crawl list --status=queued filters correctly."""
        # Create a crawl first
        url = create_url("list-filter")
        run_archivebox_cmd(['crawl', 'create', url], data_dir=shared_archive)

        # List with filter
        stdout, _, code = run_archivebox_cmd(
            ['crawl', 'list', '--status=queued'],
            data_dir=shared_archive,
        )
        assert code == 0

        records = parse_jsonl(stdout)
        for r in records:
            assert r['status'] == 'queued'

    def test_snapshot_list_outputs_jsonl(self, shared_archive):
        """snapshot list outputs JSONL for piping."""
        stdout, _, code = run_archivebox_cmd(
            ['snapshot', 'list'],
            data_dir=shared_archive,
        )
        assert code == 0
        # Output is valid JSONL (even if empty)
        records = parse_jsonl(stdout)
        for r in records:
            assert r['type'] == 'Snapshot'


class TestRunBehavior:
    """Test run's create-or-update behavior."""

    def test_run_creates_from_url_record(self, shared_archive):
        """run creates Snapshot from URL record without id."""
        url = create_url("run-create")
        record = {'url': url, 'type': 'Snapshot'}

        stdout, stderr, code = run_archivebox_cmd(
            ['run'],
            stdin=json.dumps(record),
            data_dir=shared_archive,
            timeout=30,
        )
        assert code == 0, stderr

        records = parse_jsonl(stdout)
        snapshots = [r for r in records if r.get('type') == 'Snapshot']
        assert len(snapshots) >= 1
        assert snapshots[0].get('id')  # Should have ID after creation
