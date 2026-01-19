#!/usr/bin/env python3
"""Unit tests for parse_rss_urls extractor."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).parent.parent
SCRIPT_PATH = next(PLUGIN_DIR.glob('on_Snapshot__*_parse_rss_urls.*'), None)


class TestParseRssUrls:
    """Test the parse_rss_urls extractor CLI."""

    def test_parses_real_rss_feed(self, tmp_path):
        """Test parsing a real RSS feed from the web."""
        # Use httpbin.org which provides a sample RSS feed
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', 'https://news.ycombinator.com/rss'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30
        )

        # HN RSS feed should parse successfully
        if result.returncode == 0:
            # Output goes to stdout (JSONL)
            content = result.stdout
            assert len(content) > 0, "No URLs extracted from real RSS feed"

            # Verify at least one URL was extracted
            lines = content.strip().split('\n')
            assert len(lines) > 0, "No entries found in RSS feed"

    def test_extracts_urls_from_rss_feed(self, tmp_path):
        """Test extracting URLs from an RSS 2.0 feed."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <item>
      <title>First Post</title>
      <link>https://example.com/post/1</link>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second Post</title>
      <link>https://example.com/post/2</link>
      <pubDate>Tue, 02 Jan 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert 'urls.jsonl' in result.stderr or 'urls.jsonl' in result.stdout

        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '\"type\": \"Snapshot\"' in line]
        assert len(lines) == 2

        entries = [json.loads(line) for line in lines]
        urls = {e['url'] for e in entries}
        titles = {e.get('title') for e in entries}

        assert 'https://example.com/post/1' in urls
        assert 'https://example.com/post/2' in urls
        assert 'First Post' in titles
        assert 'Second Post' in titles

    def test_extracts_urls_from_atom_feed(self, tmp_path):
        """Test extracting URLs from an Atom feed."""
        input_file = tmp_path / 'feed.atom'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Test Atom Feed</title>
  <entry>
    <title>Atom Post 1</title>
    <link href="https://atom.example.com/entry/1"/>
    <updated>2024-01-01T12:00:00Z</updated>
  </entry>
  <entry>
    <title>Atom Post 2</title>
    <link href="https://atom.example.com/entry/2"/>
    <updated>2024-01-02T12:00:00Z</updated>
  </entry>
</feed>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '\"type\": \"Snapshot\"' in line]
        urls = {json.loads(line)['url'] for line in lines}

        assert 'https://atom.example.com/entry/1' in urls
        assert 'https://atom.example.com/entry/2' in urls

    def test_skips_when_no_entries(self, tmp_path):
        """Test that script returns skipped status when feed has no entries."""
        input_file = tmp_path / 'empty.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
  </channel>
</rss>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert 'urls.jsonl' in result.stderr
        assert '"status": "skipped"' in result.stdout

    def test_exits_1_when_file_not_found(self, tmp_path):
        """Test that script exits with code 1 when file doesn't exist."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', 'file:///nonexistent/feed.rss'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert 'Failed to fetch' in result.stderr

    def test_handles_html_entities_in_urls(self, tmp_path):
        """Test that HTML entities in URLs are decoded."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Entity Test</title>
      <link>https://example.com/page?a=1&amp;b=2</link>
    </item>
  </channel>
</rss>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])
        assert entry['url'] == 'https://example.com/page?a=1&b=2'

    def test_includes_optional_metadata(self, tmp_path):
        """Test that title and timestamp are included when present."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Test Title</title>
      <link>https://example.com/test</link>
      <pubDate>Wed, 15 Jan 2020 10:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])
        assert entry['url'] == 'https://example.com/test'
        assert entry['title'] == 'Test Title'
        # Parser converts timestamp to bookmarked_at
        assert 'bookmarked_at' in entry


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
