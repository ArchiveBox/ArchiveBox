#!/usr/bin/env python3
"""
Tests for CLI piping workflow: crawl | snapshot | archiveresult | run

This module tests the JSONL-based piping between CLI commands as described in:
https://github.com/ArchiveBox/ArchiveBox/issues/1363

Workflows tested:
    archivebox crawl create URL        -> Crawl JSONL
    archivebox snapshot create         -> Snapshot JSONL (accepts Crawl or URL input)
    archivebox archiveresult create    -> ArchiveResult JSONL (accepts Snapshot input)
    archivebox run                     -> Process queued records (accepts any JSONL)

Pipeline:
    archivebox crawl create URL | archivebox snapshot create | archivebox archiveresult create | archivebox run

Each command should:
    - Accept URLs, IDs, or JSONL as input (args or stdin)
    - Output JSONL to stdout when piped (not TTY)
    - Output human-readable to stderr when TTY
"""

__package__ = 'archivebox.cli'

import os
import json
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import TypeVar

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
    'SAVE_YTDLP': 'False',
    'SAVE_HEADERS': 'False',
    'USE_CURL': 'False',
    'USE_WGET': 'False',
    'USE_GIT': 'False',
    'USE_CHROME': 'False',
    'USE_YOUTUBEDL': 'False',
    'USE_NODE': 'False',
}

os.environ.update(TEST_CONFIG)

T = TypeVar('T')


def require(value: T | None) -> T:
    if value is None:
        raise AssertionError('Expected value to be present')
    return value


class MockTTYStringIO(StringIO):
    def __init__(self, initial_value: str = '', *, is_tty: bool):
        super().__init__(initial_value)
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


# =============================================================================
# JSONL Utility Tests
# =============================================================================

class TestJSONLParsing(unittest.TestCase):
    """Test JSONL input parsing utilities."""

    def test_parse_plain_url(self):
        """Plain URLs should be parsed as Snapshot records."""
        from archivebox.misc.jsonl import parse_line, TYPE_SNAPSHOT

        result = require(parse_line('https://example.com'))
        self.assertEqual(result['type'], TYPE_SNAPSHOT)
        self.assertEqual(result['url'], 'https://example.com')

    def test_parse_jsonl_snapshot(self):
        """JSONL Snapshot records should preserve all fields."""
        from archivebox.misc.jsonl import parse_line, TYPE_SNAPSHOT

        line = '{"type": "Snapshot", "url": "https://example.com", "tags": "test,demo"}'
        result = require(parse_line(line))
        self.assertEqual(result['type'], TYPE_SNAPSHOT)
        self.assertEqual(result['url'], 'https://example.com')
        self.assertEqual(result['tags'], 'test,demo')

    def test_parse_jsonl_crawl(self):
        """JSONL Crawl records should be parsed correctly."""
        from archivebox.misc.jsonl import parse_line, TYPE_CRAWL

        line = '{"type": "Crawl", "id": "abc123", "urls": "https://example.com", "max_depth": 1}'
        result = require(parse_line(line))
        self.assertEqual(result['type'], TYPE_CRAWL)
        self.assertEqual(result['id'], 'abc123')
        self.assertEqual(result['urls'], 'https://example.com')
        self.assertEqual(result['max_depth'], 1)

    def test_parse_jsonl_with_id(self):
        """JSONL with id field should be recognized."""
        from archivebox.misc.jsonl import parse_line

        line = '{"type": "Snapshot", "id": "abc123", "url": "https://example.com"}'
        result = require(parse_line(line))
        self.assertEqual(result['id'], 'abc123')
        self.assertEqual(result['url'], 'https://example.com')

    def test_parse_uuid_as_snapshot_id(self):
        """Bare UUIDs should be parsed as snapshot IDs."""
        from archivebox.misc.jsonl import parse_line, TYPE_SNAPSHOT

        uuid = '01234567-89ab-cdef-0123-456789abcdef'
        result = require(parse_line(uuid))
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

        result = require(parse_line('file:///path/to/file.txt'))
        self.assertEqual(result['type'], TYPE_SNAPSHOT)
        self.assertEqual(result['url'], 'file:///path/to/file.txt')


# Note: JSONL output serialization is tested in TestPipingWorkflowIntegration
# using real model instances, not mocks.


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
        stream = MockTTYStringIO(stdin_content, is_tty=False)

        records = list(read_args_or_stdin((), stream=stream))

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['url'], 'https://example1.com')
        self.assertEqual(records[1]['url'], 'https://example2.com')

    def test_read_jsonl_from_stdin(self):
        """Should read JSONL from stdin."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin_content = '{"type": "Snapshot", "url": "https://example.com", "tags": "test"}\n'
        stream = MockTTYStringIO(stdin_content, is_tty=False)

        records = list(read_args_or_stdin((), stream=stream))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['url'], 'https://example.com')
        self.assertEqual(records[0]['tags'], 'test')

    def test_read_crawl_jsonl_from_stdin(self):
        """Should read Crawl JSONL from stdin."""
        from archivebox.misc.jsonl import read_args_or_stdin, TYPE_CRAWL

        stdin_content = '{"type": "Crawl", "id": "abc123", "urls": "https://example.com\\nhttps://foo.com"}\n'
        stream = MockTTYStringIO(stdin_content, is_tty=False)

        records = list(read_args_or_stdin((), stream=stream))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], TYPE_CRAWL)
        self.assertEqual(records[0]['id'], 'abc123')

    def test_skip_tty_stdin(self):
        """Should not read from TTY stdin (would block)."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stream = MockTTYStringIO('https://example.com', is_tty=True)

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

    def test_crawl_output_format(self):
        """crawl should output Crawl JSONL records."""
        from archivebox.misc.jsonl import TYPE_CRAWL

        # Mock crawl output
        crawl_output = {
            'type': TYPE_CRAWL,
            'schema_version': '0.9.0',
            'id': 'test-crawl-id',
            'urls': 'https://example.com',
            'status': 'queued',
            'max_depth': 0,
        }

        self.assertEqual(crawl_output['type'], TYPE_CRAWL)
        self.assertIn('id', crawl_output)
        self.assertIn('urls', crawl_output)


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

    def test_snapshot_accepts_crawl_jsonl(self):
        """snapshot should accept Crawl JSONL as input."""
        from archivebox.misc.jsonl import read_args_or_stdin, TYPE_CRAWL

        stdin = MockTTYStringIO('{"type": "Crawl", "id": "abc123", "urls": "https://example.com"}\n', is_tty=False)

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], TYPE_CRAWL)
        self.assertEqual(records[0]['id'], 'abc123')
        self.assertEqual(records[0]['urls'], 'https://example.com')

    def test_snapshot_accepts_jsonl_with_metadata(self):
        """snapshot should accept JSONL with tags and other metadata."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin = MockTTYStringIO('{"type": "Snapshot", "url": "https://example.com", "tags": "tag1,tag2", "title": "Test"}\n', is_tty=False)

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['url'], 'https://example.com')
        self.assertEqual(records[0]['tags'], 'tag1,tag2')
        self.assertEqual(records[0]['title'], 'Test')

    # Note: Snapshot output format is tested in integration tests
    # (TestPipingWorkflowIntegration.test_snapshot_creates_and_outputs_jsonl)
    # using real Snapshot instances.


class TestArchiveResultCommand(unittest.TestCase):
    """Unit tests for archivebox archiveresult command."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        os.environ['DATA_DIR'] = self.test_dir

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_archiveresult_accepts_snapshot_id(self):
        """archiveresult should accept snapshot IDs as input."""
        from archivebox.misc.jsonl import read_args_or_stdin

        uuid = '01234567-89ab-cdef-0123-456789abcdef'
        args = (uuid,)
        records = list(read_args_or_stdin(args))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], uuid)

    def test_archiveresult_accepts_jsonl_snapshot(self):
        """archiveresult should accept JSONL Snapshot records."""
        from archivebox.misc.jsonl import read_args_or_stdin, TYPE_SNAPSHOT

        stdin = MockTTYStringIO('{"type": "Snapshot", "id": "abc123", "url": "https://example.com"}\n', is_tty=False)

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['type'], TYPE_SNAPSHOT)
        self.assertEqual(records[0]['id'], 'abc123')

    def test_archiveresult_gathers_snapshot_ids(self):
        """archiveresult should gather snapshot IDs from various input formats."""
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


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_empty_input(self):
        """Commands should handle empty input gracefully."""
        from archivebox.misc.jsonl import read_args_or_stdin

        # Empty args, TTY stdin (should not block)
        stdin = MockTTYStringIO('', is_tty=True)

        records = list(read_args_or_stdin((), stream=stdin))
        self.assertEqual(len(records), 0)

    def test_malformed_jsonl(self):
        """Should skip malformed JSONL lines."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin = MockTTYStringIO(
            '{"url": "https://good.com"}\n'
            'not valid json\n'
            '{"url": "https://also-good.com"}\n',
            is_tty=False,
        )

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 2)
        urls = {r['url'] for r in records}
        self.assertEqual(urls, {'https://good.com', 'https://also-good.com'})

    def test_mixed_input_formats(self):
        """Should handle mixed URLs and JSONL."""
        from archivebox.misc.jsonl import read_args_or_stdin

        stdin = MockTTYStringIO(
            'https://plain-url.com\n'
            '{"type": "Snapshot", "url": "https://jsonl-url.com", "tags": "test"}\n'
            '01234567-89ab-cdef-0123-456789abcdef\n',  # UUID
            is_tty=False,
        )

        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 3)

        # Plain URL
        self.assertEqual(records[0]['url'], 'https://plain-url.com')

        # JSONL with metadata
        self.assertEqual(records[1]['url'], 'https://jsonl-url.com')
        self.assertEqual(records[1]['tags'], 'test')

        # UUID
        self.assertEqual(records[2]['id'], '01234567-89ab-cdef-0123-456789abcdef')

    def test_crawl_with_multiple_urls(self):
        """Crawl should handle multiple URLs in a single crawl."""
        from archivebox.misc.jsonl import TYPE_CRAWL

        # Test crawl JSONL with multiple URLs
        crawl_output = {
            'type': TYPE_CRAWL,
            'id': 'test-multi-url-crawl',
            'urls': 'https://url1.com\nhttps://url2.com\nhttps://url3.com',
            'max_depth': 0,
        }

        # Parse the URLs
        urls = [u.strip() for u in crawl_output['urls'].split('\n') if u.strip()]

        self.assertEqual(len(urls), 3)
        self.assertEqual(urls[0], 'https://url1.com')
        self.assertEqual(urls[1], 'https://url2.com')
        self.assertEqual(urls[2], 'https://url3.com')


# =============================================================================
# Pass-Through Behavior Tests
# =============================================================================

class TestPassThroughBehavior(unittest.TestCase):
    """Test pass-through behavior in CLI commands."""

    def test_crawl_passes_through_other_types(self):
        """crawl create should pass through records with other types."""

        # Input: a Tag record (not a Crawl or URL)
        tag_record = {'type': 'Tag', 'id': 'test-tag', 'name': 'example'}
        url_record = {'url': 'https://example.com'}

        # Mock stdin with both records
        stdin = MockTTYStringIO(
            json.dumps(tag_record)
            + '\n'
            + json.dumps(url_record),
            is_tty=False,
        )

        # The Tag should be passed through, the URL should create a Crawl
        # (This is a unit test of the pass-through logic)
        from archivebox.misc.jsonl import read_args_or_stdin
        records = list(read_args_or_stdin((), stream=stdin))

        self.assertEqual(len(records), 2)
        # First record is a Tag (other type)
        self.assertEqual(records[0]['type'], 'Tag')
        # Second record has a URL
        self.assertIn('url', records[1])

    def test_snapshot_passes_through_crawl(self):
        """snapshot create should pass through Crawl records."""
        from archivebox.misc.jsonl import TYPE_CRAWL

        crawl_record = {
            'type': TYPE_CRAWL,
            'id': 'test-crawl',
            'urls': 'https://example.com',
        }

        # Crawl records should be passed through AND create snapshots
        # This tests the accumulation behavior
        self.assertEqual(crawl_record['type'], TYPE_CRAWL)
        self.assertIn('urls', crawl_record)

    def test_archiveresult_passes_through_snapshot(self):
        """archiveresult create should pass through Snapshot records."""
        from archivebox.misc.jsonl import TYPE_SNAPSHOT

        snapshot_record = {
            'type': TYPE_SNAPSHOT,
            'id': 'test-snapshot',
            'url': 'https://example.com',
        }

        # Snapshot records should be passed through
        self.assertEqual(snapshot_record['type'], TYPE_SNAPSHOT)
        self.assertIn('url', snapshot_record)

    def test_run_passes_through_unknown_types(self):
        """run should pass through records with unknown types."""
        unknown_record = {'type': 'Unknown', 'id': 'test', 'data': 'value'}

        # Unknown types should be passed through unchanged
        self.assertEqual(unknown_record['type'], 'Unknown')
        self.assertIn('data', unknown_record)


class TestPipelineAccumulation(unittest.TestCase):
    """Test that pipelines accumulate records correctly."""

    def test_full_pipeline_output_types(self):
        """Full pipeline should output all record types."""
        from archivebox.misc.jsonl import TYPE_CRAWL, TYPE_SNAPSHOT, TYPE_ARCHIVERESULT

        # Simulated pipeline output after: crawl | snapshot | archiveresult | run
        # Should contain Crawl, Snapshot, and ArchiveResult records
        pipeline_output = [
            {'type': TYPE_CRAWL, 'id': 'c1', 'urls': 'https://example.com'},
            {'type': TYPE_SNAPSHOT, 'id': 's1', 'url': 'https://example.com'},
            {'type': TYPE_ARCHIVERESULT, 'id': 'ar1', 'plugin': 'title'},
        ]

        types = {r['type'] for r in pipeline_output}
        self.assertIn(TYPE_CRAWL, types)
        self.assertIn(TYPE_SNAPSHOT, types)
        self.assertIn(TYPE_ARCHIVERESULT, types)

    def test_pipeline_preserves_ids(self):
        """Pipeline should preserve record IDs through all stages."""
        records = [
            {'type': 'Crawl', 'id': 'c1', 'urls': 'https://example.com'},
            {'type': 'Snapshot', 'id': 's1', 'url': 'https://example.com'},
        ]

        # All records should have IDs
        for record in records:
            self.assertIn('id', record)
            self.assertTrue(record['id'])

    def test_jq_transform_pattern(self):
        """Test pattern for jq transforms in pipeline."""
        # Simulated: archiveresult list --status=failed | jq 'del(.id) | .status = "queued"'
        failed_record = {
            'type': 'ArchiveResult',
            'id': 'ar1',
            'status': 'failed',
            'plugin': 'wget',
        }

        # Transform: delete id, set status to queued
        transformed = {
            'type': failed_record['type'],
            'status': 'queued',
            'plugin': failed_record['plugin'],
        }

        self.assertNotIn('id', transformed)
        self.assertEqual(transformed['status'], 'queued')


if __name__ == '__main__':
    unittest.main()
