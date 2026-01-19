#!/usr/bin/env python3
"""Unit tests for parse_html_urls extractor."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).parent.parent
SCRIPT_PATH = next(PLUGIN_DIR.glob('on_Snapshot__*_parse_html_urls.*'), None)


class TestParseHtmlUrls:
    """Test the parse_html_urls extractor CLI."""

    def test_parses_real_example_com(self, tmp_path):
        """Test parsing real https://example.com and extracting its links."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', 'https://example.com'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30
        )

        assert result.returncode == 0, f"Failed to parse example.com: {result.stderr}"

        # Verify stdout contains JSONL records for discovered URLs
        # example.com links to iana.org
        assert 'iana.org' in result.stdout or 'example' in result.stdout, "Expected links from example.com not found"

        # Verify ArchiveResult record is present
        assert '"type": "ArchiveResult"' in result.stdout, "Missing ArchiveResult record"
        assert '"status": "succeeded"' in result.stdout, "Missing success status"

    def test_extracts_href_urls(self, tmp_path):
        """Test extracting URLs from anchor tags."""
        input_file = tmp_path / 'page.html'
        input_file.write_text('''
<!DOCTYPE html>
<html>
<body>
    <a href="https://example.com">Example</a>
    <a href="https://foo.bar/page">Foo</a>
    <a href="http://test.org">Test</a>
</body>
</html>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert 'urls.jsonl' in result.stderr

        # Parse Snapshot records from stdout
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '"type": "Snapshot"' in line]
        assert len(lines) == 3, f"Expected 3 Snapshot records, got {len(lines)}"

        urls = set()
        for line in lines:
            entry = json.loads(line)
            assert entry['type'] == 'Snapshot'
            assert 'url' in entry
            urls.add(entry['url'])

        assert 'https://example.com' in urls
        assert 'https://foo.bar/page' in urls
        assert 'http://test.org' in urls

        # Verify ArchiveResult record
        assert '"type": "ArchiveResult"' in result.stdout
        assert '"status": "succeeded"' in result.stdout

        urls_file = tmp_path / 'urls.jsonl'
        assert urls_file.exists(), "urls.jsonl not created"
        file_lines = [line for line in urls_file.read_text().splitlines() if line.strip()]
        assert len(file_lines) == 3, f"Expected 3 urls.jsonl entries, got {len(file_lines)}"

    def test_ignores_non_http_schemes(self, tmp_path):
        """Test that non-http schemes are ignored."""
        input_file = tmp_path / 'page.html'
        input_file.write_text('''
<html>
<body>
    <a href="mailto:test@example.com">Email</a>
    <a href="javascript:void(0)">JS</a>
    <a href="tel:+1234567890">Phone</a>
    <a href="https://valid.com">Valid</a>
</body>
</html>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0

        # Parse Snapshot records from stdout
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '"type": "Snapshot"' in line]
        assert len(lines) == 1, f"Expected 1 Snapshot record, got {len(lines)}"

        entry = json.loads(lines[0])
        assert entry['url'] == 'https://valid.com'

    def test_handles_html_entities(self, tmp_path):
        """Test that HTML entities in URLs are decoded."""
        input_file = tmp_path / 'page.html'
        input_file.write_text('''
<html>
<body>
    <a href="https://example.com/page?a=1&amp;b=2">Link</a>
</body>
</html>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if '"type": "Snapshot"' in line]
        entry = json.loads(lines[0])
        assert entry['url'] == 'https://example.com/page?a=1&b=2'

    def test_deduplicates_urls(self, tmp_path):
        """Test that duplicate URLs are deduplicated."""
        input_file = tmp_path / 'page.html'
        input_file.write_text('''
<html>
<body>
    <a href="https://example.com">Link 1</a>
    <a href="https://example.com">Link 2</a>
    <a href="https://example.com">Link 3</a>
</body>
</html>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if '"type": "Snapshot"' in line]
        assert len(lines) == 1

    def test_excludes_source_url(self, tmp_path):
        """Test that the source URL itself is excluded from results."""
        input_file = tmp_path / 'page.html'
        source_url = f'file://{input_file}'
        input_file.write_text(f'''
<html>
<body>
    <a href="{source_url}">Self</a>
    <a href="https://other.com">Other</a>
</body>
</html>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', source_url],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        lines = [line for line in result.stdout.strip().split('\n') if '"type": "Snapshot"' in line]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry['url'] == 'https://other.com'

    def test_skips_when_no_urls_found(self, tmp_path):
        """Test that script returns skipped status when no URLs found."""
        input_file = tmp_path / 'page.html'
        input_file.write_text('<html><body>No links here</body></html>')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert 'urls.jsonl' in result.stderr
        assert '"status": "skipped"' in result.stdout

    def test_handles_malformed_html(self, tmp_path):
        """Test handling of malformed HTML."""
        input_file = tmp_path / 'malformed.html'
        input_file.write_text('''
<html>
<body>
    <a href="https://example.com">Unclosed tag
    <a href="https://other.com">Another link</a>
</body>
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

    def test_output_is_valid_json(self, tmp_path):
        """Test that output contains required fields."""
        input_file = tmp_path / 'page.html'
        input_file.write_text('<a href="https://example.com">Link</a>')

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
        assert entry['plugin'] == 'parse_html_urls'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
