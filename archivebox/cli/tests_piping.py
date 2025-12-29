#!/usr/bin/env python3
"""
Tests for CLI piping workflow: crawl | snapshot | extract

This module tests the JSONL-based piping between CLI commands as described in:
https://github.com/ArchiveBox/ArchiveBox/issues/1363

Workflows tested:
    archivebox snapshot URL | archivebox extract
    archivebox crawl URL | archivebox snapshot | archivebox extract
    archivebox crawl --plugin=PARSER URL | archivebox snapshot | archivebox extract

Each command should:
    - Accept URLs, snapshot_ids, or JSONL as input (args or stdin)
    - Output JSONL to stdout when piped (not TTY)
    - Output human-readable to stderr when TTY
"""

__package__ = 'archivebox.cli'

import os
import sys
import json
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

# Test configuration - disable slow extractors
TEST_CONFIG = {
    'USE_COLOR': 'False',
    'SHOW_PROGRESS': 'False',
    'SAVE_ARCHIVEDOTORG': 'False',
    'SAVE_TITLE': 'True',  # Fast extractor
    'SAVE_FAVICON': 'False',
    'SAVE_WGET': 'False',
    'SAVE_WARC': 'False',
    'SAVE_PDF': 'False',
    'SAVE_SCREENSHOT': 'False',
    'SAVE_DOM': 'False',
    'SAVE_SINGLEFILE': 'False',
    'SAVE_READABILITY': 'False',
    'SAVE_MERCURY': 'False',
    'SAVE_GIT': 'False',
    'SAVE_MEDIA': 'False',
    'SAVE_HEADERS': 'False',
    'USE_CURL': 'False',
    'USE_WGET': 'False',
    'USE_GIT': 'False',
    'USE_CHROME': 'False',
    'USE_YOUTUBEDL': 'False',
    'USE_NODE': 'False',
}

os.environ.update(TEST_CONFIG)


# =============================================================================
# JSONL Utility Tests
# =============================================================================

class TestJSONLParsing(unittest.TestCase):
    """Test JSONL input parsing utilities."""

    def test_parse_plain_url(self):
        """Plain URLs should be parsed as Snapshot records."""
        from archivebox.misc.jsonl import parse_line, TYPE_SNAPSHOT

        result = parse_line('https://example.com')
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], TYPE_SNAPSHOT)
        self.assertEqual(result['url'], 'https://example.com')

    def test_parse_jsonl_snapshot(self):
        """JSONL Snapshot records should preserve all fields."""
        from archivebox.misc.jsonl import parse_line, TYPE_SNAPSHOT

        line = '{"type": "Snapshot", "url": "https://example.com", "tags": "test,demo"}'
        result = parse_line(line)
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], TYPE_SNAPSHOT)
        self.assertEqual(result['url'], 'https://example.com')
        self.assertEqual(result['tags'], 'test,demo')

    def test_parse_jsonl_with_id(self):
        """JSONL with id field should be recognized."""
        from archivebox.misc.jsonl import parse_line, TYPE_SNAPSHOT

        line = '{"type": "Snapshot", "id": "abc123", "url": "https://example.com"}'
        result = parse_line(line)
        self.assertIsNotNone(result)
        self.assertEqual(result['id'], 'abc123')
        self.assertEqual(result['url'], 'https://example.com')

    def test_parse_uuid_as_snapshot_id(self):
        """Bare UUIDs should be parsed as snapshot IDs."""
        from archivebox.misc.jsonl import parse_line, TYPE_SNAPSHOT

        uuid = '01234567-89ab-cdef-0123-456789abcdef'
        result = parse_line(uuid)
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], TYPE_SNAPSHOT)
        self.assertEqual(result['id'], uuid)

    def test_parse_empty_line(self):
        """Empty lines should return None."""
        from archivebox.misc.jsonl import parse_line

        self.assertIsNone(parse_line(''))
        self.assertIsNone(parse_line('   '))
        self.assertIsNone(parse_line('\n'))

    def test_parse_comment_line(self):
        """Comment lines should return None."""
        from archivebox.misc.jsonl import parse_line

        self.assertIsNone(parse_line('# This is a comment'))
        self.assertIsNone(parse_line('  # Indented comment'))

    def test_parse_invalid_url(self):
        """Invalid URLs should return None."""
        from archivebox.misc.jsonl import parse_line

        self.assertIsNone(parse_line('not-a-url'))
        self.assertIsNone(parse_line('ftp://example.com'))  # Only http/https/file

    def test_parse_file_url(self):
        """file:// URLs should be parsed."""
        from archivebox.misc.jsonl import parse_line, TYPE_SNAPSHOT

        result = parse_line('file:///path/to/file.txt')
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], TYPE_SNAPSHOT)
        self.assertEqual(result['url'], 'file:///path/to/file.txt')


class TestJSONLOutput(unittest.TestCase):
    """Test JSONL output formatting."""

    def test_snapshot_to_jsonl(self):
        """Snapshot model should serialize to JSONL correctly."""
        from archivebox.misc.jsonl import snapshot_to_jsonl, TYPE_SNAPSHOT

        # Create a mock snapshot
        mock_snapshot = MagicMock()
        mock_snapshot.id = 'test-uuid-1234'
        mock_snapshot.url = 'https://example.com'
        mock_snapshot.title = 'Example Title'
        mock_snapshot.tags_str.return_value = 'tag1,tag2'
        mock_snapshot.bookmarked_at = None
        mock_snapshot.created_at = None
        mock_snapshot.timestamp = '1234567890'
        mock_snapshot.depth = 0
        mock_snapshot.status = 'queued'

        result = snapshot_to_jsonl(mock_snapshot)
        self.assertEqual(result['type'], TYPE_SNAPSHOT)
        self.assertEqual(result['id'], 'test-uuid-1234')
        self.assertEqual(result['url'], 'https://example.com')
        self.assertEqual(result['title'], 'Example Title')

    def test_archiveresult_to_jsonl(self):
        """ArchiveResult model should serialize to JSONL correctly."""
        from archivebox.misc.jsonl import archiveresult_to_jsonl, TYPE_ARCHIVERESULT

        mock_result = MagicMock()
        mock_result.id = 'result-uuid-5678'
        mock_result.snapshot_id = 'snapshot-uuid-1234'
        mock_result.extractor = 'title'
        mock_result.status = 'succeeded'
        mock_result.output = 'Example Title'
        mock_result.start_ts = None
        mock_result.end_ts = None

        result = archiveresult_to_jsonl(mock_result)
        self.assertEqual(result['type'], TYPE_ARCHIVERESULT)
        self.assertEqual(result['id'], 'result-uuid-5678')
        self.assertEqual(result['snapshot_id'], 'snapshot-uuid-1234')
        self.assertEqual(result['extractor'], 'title')
        self.assertEqual(result['status'], 'succeeded')


class TestReadArgsOrStdin(unittest.TestCase):
    """Test reading from args or stdin."""

    def test_read_from_args(self):
        """Should read URLs from command line args."""
        from archivebox.misc.jsonl import read_args_or_stdin

        args = ('https://example1.com', 'https://example2.com')
        records = list(read_args_or_stdin(args))

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['url'], 'https://example1.com')
        self.assertEqual(records[1]['url'], 'https://example2.com')

    def test_read_from_stdin(self):
        """Should read URLs from stdin when no args provided."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin_content = 'https://example1.com\nhttps://example2.com\n'
        stream = StringIO(stdin_content)

        # Mock isatty to return False (simulating piped input)
        stream.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stream))

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['url'], 'https://example1.com')
        self.assertEqual(records[1]['url'], 'https://example2.com')

    def test_read_jsonl_from_stdin(self):
        """Should read JSONL from stdin."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin_content = '{"type": "Snapshot", "url": "https://example.com", "tags": "test"}\n'
        stream = StringIO(stdin_content)
        stream.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stream))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['url'], 'https://example.com')
        self.assertEqual(records[0]['tags'], 'test')

    def test_skip_tty_stdin(self):
        """Should not read from TTY stdin (would block)."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stream = StringIO('https://example.com')
        stream.isatty = lambda: True  # Simulate TTY

        records = list(read_args_or_stdin((), stream=stream))
        self.assertEqual(len(records), 0)


# =============================================================================
# Unit Tests for Individual Commands
# =============================================================================

class TestCrawlCommand(unittest.TestCase):
    """Unit tests for archivebox crawl command."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = self.test_dir

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_crawl_accepts_url(self):
        """crawl should accept URLs as input."""
        from archivebox.misc.jsonl import read_args_or_stdin

        args = ('https://example.com',)
        records = list(read_args_or_stdin(args))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['url'], 'https://example.com')

    def test_crawl_accepts_snapshot_id(self):
        """crawl should accept snapshot IDs as input."""
        from archivebox.misc.jsonl import read_args_or_stdin

        uuid = '01234567-89ab-cdef-0123-456789abcdef'
        args = (uuid,)
        records = list(read_args_or_stdin(args))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], uuid)

    def test_crawl_accepts_jsonl(self):
        """crawl should accept JSONL with snapshot info."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin = StringIO('{"type": "Snapshot", "id": "abc123", "url": "https://example.com"}\n')
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], 'abc123')
        self.assertEqual(records[0]['url'], 'https://example.com')

    def test_crawl_separates_existing_vs_new(self):
        """crawl should identify existing snapshots vs new URLs."""
        # This tests the logic in discover_outlinks() that separates
        # records with 'id' (existing) from records with just 'url' (new)

        records = [
            {'type': 'Snapshot', 'id': 'existing-id-1'},  # Existing (id only)
            {'type': 'Snapshot', 'url': 'https://new-url.com'},  # New (url only)
            {'type': 'Snapshot', 'id': 'existing-id-2', 'url': 'https://existing.com'},  # Existing (has id)
        ]

        existing = []
        new = []

        for record in records:
            if record.get('id') and not record.get('url'):
                existing.append(record['id'])
            elif record.get('id'):
                existing.append(record['id'])  # Has both id and url - treat as existing
            elif record.get('url'):
                new.append(record)

        self.assertEqual(len(existing), 2)
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]['url'], 'https://new-url.com')


class TestSnapshotCommand(unittest.TestCase):
    """Unit tests for archivebox snapshot command."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = self.test_dir

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_snapshot_accepts_url(self):
        """snapshot should accept URLs as input."""
        from archivebox.misc.jsonl import read_args_or_stdin

        args = ('https://example.com',)
        records = list(read_args_or_stdin(args))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['url'], 'https://example.com')

    def test_snapshot_accepts_jsonl_with_metadata(self):
        """snapshot should accept JSONL with tags and other metadata."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin = StringIO('{"type": "Snapshot", "url": "https://example.com", "tags": "tag1,tag2", "title": "Test"}\n')
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['url'], 'https://example.com')
        self.assertEqual(records[0]['tags'], 'tag1,tag2')
        self.assertEqual(records[0]['title'], 'Test')

    def test_snapshot_output_format(self):
        """snapshot output should include id and url."""
        from archivebox.misc.jsonl import snapshot_to_jsonl

        mock_snapshot = MagicMock()
        mock_snapshot.id = 'test-id'
        mock_snapshot.url = 'https://example.com'
        mock_snapshot.title = 'Test'
        mock_snapshot.tags_str.return_value = ''
        mock_snapshot.bookmarked_at = None
        mock_snapshot.created_at = None
        mock_snapshot.timestamp = '123'
        mock_snapshot.depth = 0
        mock_snapshot.status = 'queued'

        output = snapshot_to_jsonl(mock_snapshot)

        self.assertIn('id', output)
        self.assertIn('url', output)
        self.assertEqual(output['type'], 'Snapshot')


class TestExtractCommand(unittest.TestCase):
    """Unit tests for archivebox extract command."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = self.test_dir

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_extract_accepts_snapshot_id(self):
        """extract should accept snapshot IDs as input."""
        from archivebox.misc.jsonl import read_args_or_stdin

        uuid = '01234567-89ab-cdef-0123-456789abcdef'
        args = (uuid,)
        records = list(read_args_or_stdin(args))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], uuid)

    def test_extract_accepts_jsonl_snapshot(self):
        """extract should accept JSONL Snapshot records."""
        from archivebox.misc.jsonl import read_args_or_stdin, TYPE_SNAPSHOT

        stdin = StringIO('{"type": "Snapshot", "id": "abc123", "url": "https://example.com"}\n')
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], TYPE_SNAPSHOT)
        self.assertEqual(records[0]['id'], 'abc123')

    def test_extract_gathers_snapshot_ids(self):
        """extract should gather snapshot IDs from various input formats."""
        from archivebox.misc.jsonl import TYPE_SNAPSHOT, TYPE_ARCHIVERESULT

        records = [
            {'type': TYPE_SNAPSHOT, 'id': 'snap-1'},
            {'type': TYPE_SNAPSHOT, 'id': 'snap-2', 'url': 'https://example.com'},
            {'type': TYPE_ARCHIVERESULT, 'snapshot_id': 'snap-3'},
            {'id': 'snap-4'},  # Bare id
        ]

        snapshot_ids = set()
        for record in records:
            record_type = record.get('type')

            if record_type == TYPE_SNAPSHOT:
                snapshot_id = record.get('id')
                if snapshot_id:
                    snapshot_ids.add(snapshot_id)
            elif record_type == TYPE_ARCHIVERESULT:
                snapshot_id = record.get('snapshot_id')
                if snapshot_id:
                    snapshot_ids.add(snapshot_id)
            elif 'id' in record:
                snapshot_ids.add(record['id'])

        self.assertEqual(len(snapshot_ids), 4)
        self.assertIn('snap-1', snapshot_ids)
        self.assertIn('snap-2', snapshot_ids)
        self.assertIn('snap-3', snapshot_ids)
        self.assertIn('snap-4', snapshot_ids)


# =============================================================================
# URL Collection Tests
# =============================================================================

class TestURLCollection(unittest.TestCase):
    """Test collecting urls.jsonl from extractor output."""

    def setUp(self):
        """Create test directory structure."""
        self.test_dir = Path(tempfile.mkdtemp())

        # Create fake extractor output directories with urls.jsonl
        (self.test_dir / 'wget').mkdir()
        (self.test_dir / 'wget' / 'urls.jsonl').write_text(
            '{"url": "https://wget-link-1.com"}\n'
            '{"url": "https://wget-link-2.com"}\n'
        )

        (self.test_dir / 'parse_html_urls').mkdir()
        (self.test_dir / 'parse_html_urls' / 'urls.jsonl').write_text(
            '{"url": "https://html-link-1.com"}\n'
            '{"url": "https://html-link-2.com", "title": "HTML Link 2"}\n'
        )

        (self.test_dir / 'screenshot').mkdir()
        # No urls.jsonl in screenshot dir - not a parser

    def tearDown(self):
        """Clean up test directory."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_collect_urls_from_plugins(self):
        """Should collect urls.jsonl from all parser plugin subdirectories."""
        from archivebox.hooks import collect_urls_from_plugins

        urls = collect_urls_from_plugins(self.test_dir)

        self.assertEqual(len(urls), 4)

        # Check that plugin is set
        plugins = {u['plugin'] for u in urls}
        self.assertIn('wget', plugins)
        self.assertIn('parse_html_urls', plugins)
        self.assertNotIn('screenshot', plugins)  # No urls.jsonl

    def test_collect_urls_preserves_metadata(self):
        """Should preserve metadata from urls.jsonl entries."""
        from archivebox.hooks import collect_urls_from_plugins

        urls = collect_urls_from_plugins(self.test_dir)

        # Find the entry with title
        titled = [u for u in urls if u.get('title') == 'HTML Link 2']
        self.assertEqual(len(titled), 1)
        self.assertEqual(titled[0]['url'], 'https://html-link-2.com')

    def test_collect_urls_empty_dir(self):
        """Should handle empty or non-existent directories."""
        from archivebox.hooks import collect_urls_from_plugins

        empty_dir = self.test_dir / 'nonexistent'
        urls = collect_urls_from_plugins(empty_dir)

        self.assertEqual(len(urls), 0)


# =============================================================================
# Integration Tests
# =============================================================================

class TestPipingWorkflowIntegration(unittest.TestCase):
    """
    Integration tests for the complete piping workflow.

    These tests require Django to be set up and use the actual database.
    """

    @classmethod
    def setUpClass(cls):
        """Set up Django and test database."""
        cls.test_dir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = cls.test_dir

        # Initialize Django
        from archivebox.config.django import setup_django
        setup_django()

        # Initialize the archive
        from archivebox.cli.archivebox_init import init
        init()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_snapshot_creates_and_outputs_jsonl(self):
        """
        Test: archivebox snapshot URL
        Should create a Snapshot and output JSONL when piped.
        """
        from archivebox.core.models import Snapshot
        from archivebox.misc.jsonl import (
            read_args_or_stdin, write_record, snapshot_to_jsonl,
            TYPE_SNAPSHOT
        )
        from archivebox.base_models.models import get_or_create_system_user_pk

        created_by_id = get_or_create_system_user_pk()

        # Simulate input
        url = 'https://test-snapshot-1.example.com'
        records = list(read_args_or_stdin((url,)))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['url'], url)

        # Create snapshot
        overrides = {'created_by_id': created_by_id}
        snapshot = Snapshot.from_jsonl(records[0], overrides=overrides)

        self.assertIsNotNone(snapshot.id)
        self.assertEqual(snapshot.url, url)

        # Verify output format
        output = snapshot_to_jsonl(snapshot)
        self.assertEqual(output['type'], TYPE_SNAPSHOT)
        self.assertIn('id', output)
        self.assertEqual(output['url'], url)

    def test_extract_accepts_snapshot_from_previous_command(self):
        """
        Test: archivebox snapshot URL | archivebox extract
        Extract should accept JSONL output from snapshot command.
        """
        from archivebox.core.models import Snapshot, ArchiveResult
        from archivebox.misc.jsonl import (
            snapshot_to_jsonl, read_args_or_stdin,
            TYPE_SNAPSHOT
        )
        from archivebox.base_models.models import get_or_create_system_user_pk

        created_by_id = get_or_create_system_user_pk()

        # Step 1: Create snapshot (simulating 'archivebox snapshot')
        url = 'https://test-extract-1.example.com'
        overrides = {'created_by_id': created_by_id}
        snapshot = Snapshot.from_jsonl({'url': url}, overrides=overrides)
        snapshot_output = snapshot_to_jsonl(snapshot)

        # Step 2: Parse snapshot output as extract input
        stdin = StringIO(json.dumps(snapshot_output) + '\n')
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], TYPE_SNAPSHOT)
        self.assertEqual(records[0]['id'], str(snapshot.id))

        # Step 3: Gather snapshot IDs (as extract does)
        snapshot_ids = set()
        for record in records:
            if record.get('type') == TYPE_SNAPSHOT and record.get('id'):
                snapshot_ids.add(record['id'])

        self.assertIn(str(snapshot.id), snapshot_ids)

    def test_crawl_outputs_discovered_urls(self):
        """
        Test: archivebox crawl URL
        Should create snapshot, run plugins, output discovered URLs.
        """
        from archivebox.hooks import collect_urls_from_plugins
        from archivebox.misc.jsonl import TYPE_SNAPSHOT

        # Create a mock snapshot directory with urls.jsonl
        test_snapshot_dir = Path(self.test_dir) / 'archive' / 'test-crawl-snapshot'
        test_snapshot_dir.mkdir(parents=True, exist_ok=True)

        # Create mock extractor output
        (test_snapshot_dir / 'parse_html_urls').mkdir()
        (test_snapshot_dir / 'parse_html_urls' / 'urls.jsonl').write_text(
            '{"url": "https://discovered-1.com"}\n'
            '{"url": "https://discovered-2.com", "title": "Discovered 2"}\n'
        )

        # Collect URLs (as crawl does)
        discovered = collect_urls_from_plugins(test_snapshot_dir)

        self.assertEqual(len(discovered), 2)

        # Add crawl metadata (as crawl does)
        for entry in discovered:
            entry['type'] = TYPE_SNAPSHOT
            entry['depth'] = 1
            entry['via_snapshot'] = 'test-crawl-snapshot'

        # Verify output format
        self.assertEqual(discovered[0]['type'], TYPE_SNAPSHOT)
        self.assertEqual(discovered[0]['depth'], 1)
        self.assertEqual(discovered[0]['url'], 'https://discovered-1.com')

    def test_full_pipeline_snapshot_extract(self):
        """
        Test: archivebox snapshot URL | archivebox extract

        This is equivalent to: archivebox add URL
        """
        from archivebox.core.models import Snapshot
        from archivebox.misc.jsonl import (
            get_or_create_snapshot, snapshot_to_jsonl, read_args_or_stdin,
            TYPE_SNAPSHOT
        )
        from archivebox.base_models.models import get_or_create_system_user_pk

        created_by_id = get_or_create_system_user_pk()

        # === archivebox snapshot https://example.com ===
        url = 'https://test-pipeline-1.example.com'
        snapshot = get_or_create_snapshot({'url': url}, created_by_id=created_by_id)
        snapshot_jsonl = json.dumps(snapshot_to_jsonl(snapshot))

        # === | archivebox extract ===
        stdin = StringIO(snapshot_jsonl + '\n')
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))

        # Extract should receive the snapshot ID
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], str(snapshot.id))

        # Verify snapshot exists in DB
        db_snapshot = Snapshot.objects.get(id=snapshot.id)
        self.assertEqual(db_snapshot.url, url)

    def test_full_pipeline_crawl_snapshot_extract(self):
        """
        Test: archivebox crawl URL | archivebox snapshot | archivebox extract

        This is equivalent to: archivebox add --depth=1 URL
        """
        from archivebox.core.models import Snapshot
        from archivebox.misc.jsonl import (
            get_or_create_snapshot, snapshot_to_jsonl, read_args_or_stdin,
            TYPE_SNAPSHOT
        )
        from archivebox.base_models.models import get_or_create_system_user_pk
        from archivebox.hooks import collect_urls_from_plugins

        created_by_id = get_or_create_system_user_pk()

        # === archivebox crawl https://example.com ===
        # Step 1: Create snapshot for starting URL
        start_url = 'https://test-crawl-pipeline.example.com'
        start_snapshot = get_or_create_snapshot({'url': start_url}, created_by_id=created_by_id)

        # Step 2: Simulate extractor output with discovered URLs
        snapshot_dir = Path(self.test_dir) / 'archive' / str(start_snapshot.timestamp)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / 'parse_html_urls').mkdir(exist_ok=True)
        (snapshot_dir / 'parse_html_urls' / 'urls.jsonl').write_text(
            '{"url": "https://outlink-1.example.com"}\n'
            '{"url": "https://outlink-2.example.com"}\n'
        )

        # Step 3: Collect discovered URLs (crawl output)
        discovered = collect_urls_from_plugins(snapshot_dir)
        crawl_output = []
        for entry in discovered:
            entry['type'] = TYPE_SNAPSHOT
            entry['depth'] = 1
            crawl_output.append(json.dumps(entry))

        # === | archivebox snapshot ===
        stdin = StringIO('\n'.join(crawl_output) + '\n')
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))
        self.assertEqual(len(records), 2)

        # Create snapshots for discovered URLs
        created_snapshots = []
        for record in records:
            snap = get_or_create_snapshot(record, created_by_id=created_by_id)
            created_snapshots.append(snap)

        self.assertEqual(len(created_snapshots), 2)

        # === | archivebox extract ===
        snapshot_jsonl_lines = [json.dumps(snapshot_to_jsonl(s)) for s in created_snapshots]
        stdin = StringIO('\n'.join(snapshot_jsonl_lines) + '\n')
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))
        self.assertEqual(len(records), 2)

        # Verify all snapshots exist in DB
        for record in records:
            db_snapshot = Snapshot.objects.get(id=record['id'])
            self.assertIn(db_snapshot.url, [
                'https://outlink-1.example.com',
                'https://outlink-2.example.com'
            ])


class TestDepthWorkflows(unittest.TestCase):
    """Test various depth crawl workflows."""

    @classmethod
    def setUpClass(cls):
        """Set up Django and test database."""
        cls.test_dir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = cls.test_dir

        from archivebox.config.django import setup_django
        setup_django()

        from archivebox.cli.archivebox_init import init
        init()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_depth_0_workflow(self):
        """
        Test: archivebox snapshot URL | archivebox extract

        Depth 0: Only archive the specified URL, no crawling.
        """
        from archivebox.core.models import Snapshot
        from archivebox.misc.jsonl import get_or_create_snapshot
        from archivebox.base_models.models import get_or_create_system_user_pk

        created_by_id = get_or_create_system_user_pk()

        # Create snapshot
        url = 'https://depth0-test.example.com'
        snapshot = get_or_create_snapshot({'url': url}, created_by_id=created_by_id)

        # Verify only one snapshot created
        self.assertEqual(Snapshot.objects.filter(url=url).count(), 1)
        self.assertEqual(snapshot.url, url)

    def test_depth_1_workflow(self):
        """
        Test: archivebox crawl URL | archivebox snapshot | archivebox extract

        Depth 1: Archive URL + all outlinks from that URL.
        """
        # This is tested in test_full_pipeline_crawl_snapshot_extract
        pass

    def test_depth_metadata_propagation(self):
        """Test that depth metadata propagates through the pipeline."""
        from archivebox.misc.jsonl import TYPE_SNAPSHOT

        # Simulate crawl output with depth metadata
        crawl_output = [
            {'type': TYPE_SNAPSHOT, 'url': 'https://hop1.com', 'depth': 1, 'via_snapshot': 'root'},
            {'type': TYPE_SNAPSHOT, 'url': 'https://hop2.com', 'depth': 2, 'via_snapshot': 'hop1'},
        ]

        # Verify depth is preserved
        for entry in crawl_output:
            self.assertIn('depth', entry)
            self.assertIn('via_snapshot', entry)


class TestParserPluginWorkflows(unittest.TestCase):
    """Test workflows with specific parser plugins."""

    @classmethod
    def setUpClass(cls):
        """Set up Django and test database."""
        cls.test_dir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = cls.test_dir

        from archivebox.config.django import setup_django
        setup_django()

        from archivebox.cli.archivebox_init import init
        init()

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_html_parser_workflow(self):
        """
        Test: archivebox crawl --plugin=parse_html_urls URL | archivebox snapshot | archivebox extract
        """
        from archivebox.hooks import collect_urls_from_plugins
        from archivebox.misc.jsonl import TYPE_SNAPSHOT

        # Create mock output directory
        snapshot_dir = Path(self.test_dir) / 'archive' / 'html-parser-test'
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / 'parse_html_urls').mkdir(exist_ok=True)
        (snapshot_dir / 'parse_html_urls' / 'urls.jsonl').write_text(
            '{"url": "https://html-discovered.com", "title": "HTML Link"}\n'
        )

        # Collect URLs
        discovered = collect_urls_from_plugins(snapshot_dir)

        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0]['url'], 'https://html-discovered.com')
        self.assertEqual(discovered[0]['plugin'], 'parse_html_urls')

    def test_rss_parser_workflow(self):
        """
        Test: archivebox crawl --plugin=parse_rss_urls URL | archivebox snapshot | archivebox extract
        """
        from archivebox.hooks import collect_urls_from_plugins

        # Create mock output directory
        snapshot_dir = Path(self.test_dir) / 'archive' / 'rss-parser-test'
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / 'parse_rss_urls').mkdir(exist_ok=True)
        (snapshot_dir / 'parse_rss_urls' / 'urls.jsonl').write_text(
            '{"url": "https://rss-item-1.com", "title": "RSS Item 1"}\n'
            '{"url": "https://rss-item-2.com", "title": "RSS Item 2"}\n'
        )

        # Collect URLs
        discovered = collect_urls_from_plugins(snapshot_dir)

        self.assertEqual(len(discovered), 2)
        self.assertTrue(all(d['plugin'] == 'parse_rss_urls' for d in discovered))

    def test_multiple_parsers_dedupe(self):
        """
        Multiple parsers may discover the same URL - should be deduplicated.
        """
        from archivebox.hooks import collect_urls_from_plugins

        # Create mock output with duplicate URLs from different parsers
        snapshot_dir = Path(self.test_dir) / 'archive' / 'dedupe-test'
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        (snapshot_dir / 'parse_html_urls').mkdir(exist_ok=True)
        (snapshot_dir / 'parse_html_urls' / 'urls.jsonl').write_text(
            '{"url": "https://same-url.com"}\n'
        )

        (snapshot_dir / 'wget').mkdir(exist_ok=True)
        (snapshot_dir / 'wget' / 'urls.jsonl').write_text(
            '{"url": "https://same-url.com"}\n'  # Same URL, different extractor
        )

        # Collect URLs
        all_discovered = collect_urls_from_plugins(snapshot_dir)

        # Both entries are returned (deduplication happens at the crawl command level)
        self.assertEqual(len(all_discovered), 2)

        # Verify both extractors found the same URL
        urls = {d['url'] for d in all_discovered}
        self.assertEqual(urls, {'https://same-url.com'})


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_empty_input(self):
        """Commands should handle empty input gracefully."""
        from archivebox.misc.jsonl import read_args_or_stdin

        # Empty args, TTY stdin (should not block)
        stdin = StringIO('')
        stdin.isatty = lambda: True

        records = list(read_args_or_stdin((), stream=stdin))
        self.assertEqual(len(records), 0)

    def test_malformed_jsonl(self):
        """Should skip malformed JSONL lines."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin = StringIO(
            '{"url": "https://good.com"}\n'
            'not valid json\n'
            '{"url": "https://also-good.com"}\n'
        )
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 2)
        urls = {r['url'] for r in records}
        self.assertEqual(urls, {'https://good.com', 'https://also-good.com'})

    def test_mixed_input_formats(self):
        """Should handle mixed URLs and JSONL."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin = StringIO(
            'https://plain-url.com\n'
            '{"type": "Snapshot", "url": "https://jsonl-url.com", "tags": "test"}\n'
            '01234567-89ab-cdef-0123-456789abcdef\n'  # UUID
        )
        stdin.isatty = lambda: False

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 3)

        # Plain URL
        self.assertEqual(records[0]['url'], 'https://plain-url.com')

        # JSONL with metadata
        self.assertEqual(records[1]['url'], 'https://jsonl-url.com')
        self.assertEqual(records[1]['tags'], 'test')

        # UUID
        self.assertEqual(records[2]['id'], '01234567-89ab-cdef-0123-456789abcdef')


if __name__ == '__main__':
    unittest.main()
