#!/usr/bin/env python3
"""Unit tests for parse_txt_urls extractor."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).parent.parent
SCRIPT_PATH = next(PLUGIN_DIR.glob('on_Snapshot__*_parse_txt_urls.*'), None)


class TestParseTxtUrls:
    """Test the parse_txt_urls extractor CLI."""

    def test_extracts_urls_including_real_example_com(self, tmp_path):
        """Test extracting URLs from plain text including real example.com."""
        input_file = tmp_path / 'urls.txt'
        input_file.write_text('''
https://example.com
https://example.com/page
https://www.iana.org/domains/reserved
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        assert 'urls.jsonl' in result.stderr

        # Parse Snapshot records from stdout
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '"type": "Snapshot"' in line]
        assert len(lines) == 3

        urls = set()
        for line in lines:
            entry = json.loads(line)
            assert entry['type'] == 'Snapshot'
            assert 'url' in entry
            urls.add(entry['url'])

        # Verify real URLs are extracted correctly
        assert 'https://example.com' in urls
        assert 'https://example.com/page' in urls
        assert 'https://www.iana.org/domains/reserved' in urls

        # Verify ArchiveResult record
        assert '"type": "ArchiveResult"' in result.stdout
        assert '"status": "succeeded"' in result.stdout

    def test_extracts_urls_from_mixed_content(self, tmp_path):
        """Test extracting URLs embedded in prose text."""
        input_file = tmp_path / 'mixed.txt'
        input_file.write_text('''
Check out this great article at https://blog.example.com/post
You can also visit http://docs.test.org for more info.
Also see https://github.com/user/repo for the code.
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if '"type": "Snapshot"' in line]
        urls = {json.loads(line)['url'] for line in lines}

        assert 'https://blog.example.com/post' in urls
        assert 'http://docs.test.org' in urls
        assert 'https://github.com/user/repo' in urls

    def test_handles_markdown_urls(self, tmp_path):
        """Test handling URLs in markdown format with parentheses."""
        input_file = tmp_path / 'markdown.txt'
        input_file.write_text('''
[Example](https://example.com/page)
[Wiki](https://en.wikipedia.org/wiki/Article_(Disambiguation))
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if '"type": "Snapshot"' in line]
        urls = {json.loads(line)['url'] for line in lines}

        assert 'https://example.com/page' in urls
        assert any('wikipedia.org' in u for u in urls)

    def test_skips_when_no_urls_found(self, tmp_path):
        """Test that script returns skipped status when no URLs found."""
        input_file = tmp_path / 'empty.txt'
        input_file.write_text('no urls here, just plain text')

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
            [sys.executable, str(SCRIPT_PATH), '--url', 'file:///nonexistent/path.txt'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert 'Failed to fetch' in result.stderr

    def test_deduplicates_urls(self, tmp_path):
        """Test that duplicate URLs are deduplicated."""
        input_file = tmp_path / 'dupes.txt'
        input_file.write_text('''
https://example.com
https://example.com
https://example.com
https://other.com
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if '"type": "Snapshot"' in line]
        assert len(lines) == 2

    def test_outputs_to_stdout(self, tmp_path):
        """Test that output goes to stdout in JSONL format."""
        input_file = tmp_path / 'urls.txt'
        input_file.write_text('https://new.com\nhttps://other.com')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if '"type": "Snapshot"' in line]
        assert len(lines) == 2

        urls = {json.loads(line)['url'] for line in lines}
        assert 'https://new.com' in urls
        assert 'https://other.com' in urls

    def test_output_is_valid_json(self, tmp_path):
        """Test that output contains required fields."""
        input_file = tmp_path / 'urls.txt'
        input_file.write_text('https://example.com')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if '"type": "Snapshot"' in line]
        entry = json.loads(lines[0])
        assert entry['url'] == 'https://example.com'
        assert entry['type'] == 'Snapshot'
        assert entry['plugin'] == 'parse_txt_urls'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
