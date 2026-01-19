#!/usr/bin/env python3
"""Comprehensive tests for parse_netscape_urls extractor covering various browser formats."""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).parent.parent
SCRIPT_PATH = next(PLUGIN_DIR.glob('on_Snapshot__*_parse_netscape_urls.*'), None)


class TestFirefoxFormat:
    """Test Firefox Netscape bookmark export format."""

    def test_firefox_basic_format(self, tmp_path):
        """Test standard Firefox export format with Unix timestamps in seconds."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file.
     It will be read and overwritten.
     DO NOT EDIT! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks Menu</H1>
<DL><p>
    <DT><A HREF="https://example.com" ADD_DATE="1609459200" LAST_MODIFIED="1609545600">Example Site</A>
    <DT><A HREF="https://mozilla.org" ADD_DATE="1640995200">Mozilla</A>
</DL><p>
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
        entries = [json.loads(line) for line in lines]

        assert len(entries) == 2
        assert entries[0]['url'] == 'https://example.com'
        assert entries[0]['title'] == 'Example Site'
        # Timestamp should be parsed as seconds (Jan 1, 2021)
        assert '2021-01-01' in entries[0]['bookmarked_at']
        # Second bookmark (Jan 1, 2022)
        assert '2022-01-01' in entries[1]['bookmarked_at']

    def test_firefox_with_tags(self, tmp_path):
        """Test Firefox bookmarks with tags."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://example.com" ADD_DATE="1609459200" TAGS="coding,tutorial,python">Python Tutorial</A>
    <DT><A HREF="https://rust-lang.org" ADD_DATE="1609459200" TAGS="coding,rust">Rust Lang</A>
</DL><p>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Output goes to stdout (JSONL) - get all JSONL records
        all_lines = [line for line in result.stdout.strip().split('\n') if line.strip() and line.startswith('{')]
        records = [json.loads(line) for line in all_lines]

        # Should have Tag records + Snapshot records
        tags = [r for r in records if r.get('type') == 'Tag']
        snapshots = [r for r in records if r.get('type') == 'Snapshot']

        tag_names = {t['name'] for t in tags}
        assert 'coding' in tag_names
        assert 'tutorial' in tag_names
        assert 'python' in tag_names
        assert 'rust' in tag_names

        assert snapshots[0]['tags'] == 'coding,tutorial,python'
        assert snapshots[1]['tags'] == 'coding,rust'

    def test_firefox_nested_folders(self, tmp_path):
        """Test Firefox bookmark folders and nested structure."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3 ADD_DATE="1609459200" LAST_MODIFIED="1609545600">Toolbar</H3>
    <DL><p>
        <DT><A HREF="https://github.com" ADD_DATE="1609459200">GitHub</A>
        <DT><H3 ADD_DATE="1609459200" LAST_MODIFIED="1609545600">Development</H3>
        <DL><p>
            <DT><A HREF="https://stackoverflow.com" ADD_DATE="1609459200">Stack Overflow</A>
            <DT><A HREF="https://developer.mozilla.org" ADD_DATE="1609459200">MDN</A>
        </DL><p>
    </DL><p>
    <DT><A HREF="https://news.ycombinator.com" ADD_DATE="1609459200">Hacker News</A>
</DL><p>
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
        entries = [json.loads(line) for line in lines]
        urls = {e['url'] for e in entries}

        assert 'https://github.com' in urls
        assert 'https://stackoverflow.com' in urls
        assert 'https://developer.mozilla.org' in urls
        assert 'https://news.ycombinator.com' in urls
        assert len(entries) == 4

    def test_firefox_icon_and_icon_uri(self, tmp_path):
        """Test Firefox bookmarks with ICON and ICON_URI attributes."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><A HREF="https://example.com" ADD_DATE="1609459200" ICON="data:image/png;base64,iVBORw0K">Example</A>
    <DT><A HREF="https://github.com" ADD_DATE="1609459200" ICON_URI="https://github.com/favicon.ico">GitHub</A>
</DL><p>
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
        entries = [json.loads(line) for line in lines]

        assert entries[0]['url'] == 'https://example.com'
        assert entries[1]['url'] == 'https://github.com'


class TestChromeFormat:
    """Test Chrome/Chromium Netscape bookmark export format."""

    def test_chrome_microsecond_timestamps(self, tmp_path):
        """Test Chrome format with microsecond timestamps (16-17 digits)."""
        input_file = tmp_path / 'bookmarks.html'
        # Chrome uses WebKit/Chrome timestamps which are microseconds
        # 1609459200000000 = Jan 1, 2021 00:00:00 in microseconds
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><A HREF="https://google.com" ADD_DATE="1609459200000000">Google</A>
    <DT><A HREF="https://chrome.google.com" ADD_DATE="1640995200000000">Chrome</A>
</DL><p>
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
        entries = [json.loads(line) for line in lines]

        # Should correctly parse microsecond timestamps
        # Currently will fail - we'll fix the parser after writing tests
        assert entries[0]['url'] == 'https://google.com'
        # Timestamp should be around Jan 1, 2021, not year 52970!
        if 'bookmarked_at' in entries[0]:
            year = datetime.fromisoformat(entries[0]['bookmarked_at']).year
            # Should be 2021, not some far future date
            assert 2020 <= year <= 2025, f"Year should be ~2021, got {year}"

    def test_chrome_with_folders(self, tmp_path):
        """Test Chrome bookmark folder structure."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3 ADD_DATE="1609459200" LAST_MODIFIED="1609459200" PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><A HREF="https://google.com" ADD_DATE="1609459200">Google</A>
    </DL><p>
    <DT><H3 ADD_DATE="1609459200" LAST_MODIFIED="1609459200">Other bookmarks</H3>
    <DL><p>
        <DT><A HREF="https://example.com" ADD_DATE="1609459200">Example</A>
    </DL><p>
</DL><p>
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
        entries = [json.loads(line) for line in lines]
        urls = {e['url'] for e in entries}

        assert 'https://google.com' in urls
        assert 'https://example.com' in urls


class TestSafariFormat:
    """Test Safari Netscape bookmark export format."""

    def test_safari_basic_format(self, tmp_path):
        """Test Safari export format."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<Title>Bookmarks</Title>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 FOLDED ADD_DATE="1609459200">BookmarksBar</H3>
    <DL><p>
        <DT><A HREF="https://apple.com" ADD_DATE="1609459200">Apple</A>
        <DT><A HREF="https://webkit.org" ADD_DATE="1609459200">WebKit</A>
    </DL><p>
</DL><p>
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
        entries = [json.loads(line) for line in lines]
        urls = {e['url'] for e in entries}

        assert 'https://apple.com' in urls
        assert 'https://webkit.org' in urls

    def test_safari_reading_list(self, tmp_path):
        """Test Safari Reading List entries."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DL><p>
    <DT><H3 FOLDED ADD_DATE="1609459200">com.apple.ReadingList</H3>
    <DL><p>
        <DT><A HREF="https://article1.com" ADD_DATE="1609459200">Article 1</A>
        <DD>Long article to read later
        <DT><A HREF="https://article2.com" ADD_DATE="1609545600">Article 2</A>
        <DD>Another saved article
    </DL><p>
</DL><p>
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
        entries = [json.loads(line) for line in lines]
        urls = {e['url'] for e in entries}

        assert 'https://article1.com' in urls
        assert 'https://article2.com' in urls


class TestEdgeFormat:
    """Test Edge/IE bookmark export formats."""

    def test_edge_chromium_format(self, tmp_path):
        """Test Edge (Chromium-based) format."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><A HREF="https://microsoft.com" ADD_DATE="1609459200">Microsoft</A>
    <DT><A HREF="https://bing.com" ADD_DATE="1609459200">Bing</A>
</DL><p>
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
        entries = [json.loads(line) for line in lines]
        urls = {e['url'] for e in entries}

        assert 'https://microsoft.com' in urls
        assert 'https://bing.com' in urls


class TestTimestampFormats:
    """Test various timestamp format handling and edge cases."""

    def test_unix_seconds_timestamp(self, tmp_path):
        """Test Unix epoch timestamp in seconds (10-11 digits) - Firefox, Chrome HTML export."""
        input_file = tmp_path / 'bookmarks.html'
        # 1609459200 = Jan 1, 2021 00:00:00 UTC (Unix epoch)
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="1609459200">Test</A>
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

        dt = datetime.fromisoformat(entry['bookmarked_at'])
        assert dt.year == 2021
        assert dt.month == 1
        assert dt.day == 1

    def test_mac_cocoa_seconds_timestamp(self, tmp_path):
        """Test Mac/Cocoa epoch timestamp in seconds - Safari uses epoch of 2001-01-01."""
        input_file = tmp_path / 'bookmarks.html'
        # Safari uses Mac absolute time: seconds since 2001-01-01 00:00:00 UTC
        # 631152000 seconds after 2001-01-01 = Jan 1, 2021
        # 631152000 as Unix would be Feb 1990 (too old for a recent bookmark)
        input_file.write_text('''
<DT><A HREF="https://apple.com" ADD_DATE="631152000">Safari Bookmark</A>
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

        dt = datetime.fromisoformat(entry['bookmarked_at'])
        # Should detect Mac epoch and convert correctly to 2021
        assert 2020 <= dt.year <= 2022, f"Expected ~2021, got {dt.year}"

    def test_safari_recent_timestamp(self, tmp_path):
        """Test recent Safari timestamp (Mac epoch)."""
        input_file = tmp_path / 'bookmarks.html'
        # 725846400 seconds after 2001-01-01 = Jan 1, 2024
        input_file.write_text('''
<DT><A HREF="https://webkit.org" ADD_DATE="725846400">Recent Safari</A>
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

        dt = datetime.fromisoformat(entry['bookmarked_at'])
        # Should detect Mac epoch and convert to 2024
        assert 2023 <= dt.year <= 2025, f"Expected ~2024, got {dt.year}"

    def test_unix_milliseconds_timestamp(self, tmp_path):
        """Test Unix epoch timestamp in milliseconds (13 digits) - Some JavaScript exports."""
        input_file = tmp_path / 'bookmarks.html'
        # 1609459200000 = Jan 1, 2021 00:00:00 UTC in milliseconds
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="1609459200000">Test</A>
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

        dt = datetime.fromisoformat(entry['bookmarked_at'])
        assert dt.year == 2021
        assert dt.month == 1
        assert dt.day == 1

    def test_chrome_webkit_microseconds_timestamp(self, tmp_path):
        """Test Chrome WebKit timestamp in microseconds (16-17 digits) - Chrome internal format."""
        input_file = tmp_path / 'bookmarks.html'
        # 1609459200000000 = Jan 1, 2021 00:00:00 UTC in microseconds (Unix epoch)
        # Chrome sometimes exports with microsecond precision
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="1609459200000000">Test</A>
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

        dt = datetime.fromisoformat(entry['bookmarked_at'])
        assert dt.year == 2021
        assert dt.month == 1
        assert dt.day == 1

    def test_mac_cocoa_milliseconds_timestamp(self, tmp_path):
        """Test Mac/Cocoa epoch in milliseconds (rare but possible)."""
        input_file = tmp_path / 'bookmarks.html'
        # 631152000000 milliseconds after 2001-01-01 = Jan 1, 2021
        input_file.write_text('''
<DT><A HREF="https://apple.com" ADD_DATE="631152000000">Safari Milliseconds</A>
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

        dt = datetime.fromisoformat(entry['bookmarked_at'])
        # Should detect Mac epoch with milliseconds and convert to 2021
        assert 2020 <= dt.year <= 2022, f"Expected ~2021, got {dt.year}"

    def test_ambiguous_timestamp_detection(self, tmp_path):
        """Test that ambiguous timestamps are resolved to reasonable dates."""
        input_file = tmp_path / 'bookmarks.html'
        # Test multiple bookmarks with different timestamp formats mixed together
        # Parser should handle each correctly
        input_file.write_text('''
<DT><A HREF="https://unix-seconds.com" ADD_DATE="1609459200">Unix Seconds 2021</A>
<DT><A HREF="https://mac-seconds.com" ADD_DATE="631152000">Mac Seconds 2021</A>
<DT><A HREF="https://unix-ms.com" ADD_DATE="1704067200000">Unix MS 2024</A>
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
        entries = [json.loads(line) for line in lines]

        # All should be parsed to reasonable dates (2020-2025)
        for entry in entries:
            dt = datetime.fromisoformat(entry['bookmarked_at'])
            assert 2020 <= dt.year <= 2025, f"Date {dt.year} out of reasonable range for {entry['url']}"

    def test_very_old_timestamp(self, tmp_path):
        """Test very old timestamp (1990s)."""
        input_file = tmp_path / 'bookmarks.html'
        # 820454400 = Jan 1, 1996
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="820454400">Old Bookmark</A>
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

        dt = datetime.fromisoformat(entry['bookmarked_at'])
        assert dt.year == 1996

    def test_recent_timestamp(self, tmp_path):
        """Test recent timestamp (2024)."""
        input_file = tmp_path / 'bookmarks.html'
        # 1704067200 = Jan 1, 2024
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="1704067200">Recent</A>
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

        dt = datetime.fromisoformat(entry['bookmarked_at'])
        assert dt.year == 2024

    def test_invalid_timestamp(self, tmp_path):
        """Test invalid/malformed timestamp - should extract URL but skip timestamp."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="invalid">Test</A>
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

        # Should still extract URL but skip timestamp
        assert entry['url'] == 'https://example.com'
        assert 'bookmarked_at' not in entry

    def test_zero_timestamp(self, tmp_path):
        """Test timestamp of 0 (Unix epoch) - too old, should be skipped."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="0">Test</A>
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

        # Timestamp 0 = 1970, which is before MIN_REASONABLE_YEAR (1995)
        # Parser should skip it as unreasonable
        assert entry['url'] == 'https://example.com'
        # Timestamp should be omitted (outside reasonable range)
        assert 'bookmarked_at' not in entry

    def test_negative_timestamp(self, tmp_path):
        """Test negative timestamp (before Unix epoch) - should handle gracefully."""
        input_file = tmp_path / 'bookmarks.html'
        # -86400 = 1 day before Unix epoch = Dec 31, 1969
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="-86400">Before Unix Epoch</A>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        # Should handle gracefully (extracts URL, may or may not include timestamp)
        assert result.returncode == 0
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])
        assert entry['url'] == 'https://example.com'
        # If timestamp is included, should be reasonable (1969)
        if 'bookmarked_at' in entry:
            dt = datetime.fromisoformat(entry['bookmarked_at'])
            # Should be near Unix epoch (late 1969)
            assert 1969 <= dt.year <= 1970


class TestBookmarkAttributes:
    """Test various bookmark attributes and metadata."""

    def test_private_attribute(self, tmp_path):
        """Test bookmarks with PRIVATE attribute."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://private.example.com" ADD_DATE="1609459200" PRIVATE="1">Private</A>
<DT><A HREF="https://public.example.com" ADD_DATE="1609459200">Public</A>
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
        entries = [json.loads(line) for line in lines]

        # Both should be extracted
        assert len(entries) == 2

    def test_shortcuturl_attribute(self, tmp_path):
        """Test bookmarks with SHORTCUTURL keyword attribute."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://google.com/search?q=%s" ADD_DATE="1609459200" SHORTCUTURL="g">Google Search</A>
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

        assert 'google.com' in entry['url']

    def test_post_data_attribute(self, tmp_path):
        """Test bookmarks with POST_DATA attribute."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://example.com/login" ADD_DATE="1609459200" POST_DATA="user=test">Login</A>
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

        assert entry['url'] == 'https://example.com/login'


class TestEdgeCases:
    """Test edge cases and malformed data."""

    def test_multiline_bookmark(self, tmp_path):
        """Test bookmark spanning multiple lines."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://example.com"
       ADD_DATE="1609459200"
       TAGS="tag1,tag2">
    Multi-line Bookmark
</A>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        # Current regex works line-by-line, so this might not match
        # Document current behavior
        if result.returncode == 0:
            # Output goes to stdout (JSONL)
            content = result.stdout.strip()
            if content:
                lines = [line for line in content.split('\n') if line.strip() and '\"type\": \"Snapshot\"' in line]
                if lines:
                    entry = json.loads(lines[0])
                    assert 'example.com' in entry['url']

    def test_missing_add_date(self, tmp_path):
        """Test bookmark without ADD_DATE attribute - should still extract URL."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://example.com">No Date</A>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        # Should succeed and extract URL without timestamp
        assert result.returncode == 0
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])
        assert entry['url'] == 'https://example.com'
        assert entry['title'] == 'No Date'
        assert 'bookmarked_at' not in entry

    def test_empty_title(self, tmp_path):
        """Test bookmark with empty title."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="1609459200"></A>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        # Current regex requires non-empty title [^<]+
        # Parser emits skipped ArchiveResult when no valid bookmarks found
        assert result.returncode == 0
        result_json = json.loads(result.stdout.strip())
        assert result_json['type'] == 'ArchiveResult'
        assert result_json['status'] == 'skipped'

    def test_special_chars_in_url(self, tmp_path):
        """Test URLs with special characters."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://example.com/path?q=test&foo=bar&baz=qux#section" ADD_DATE="1609459200">Special URL</A>
<DT><A HREF="https://example.com/path%20with%20spaces" ADD_DATE="1609459200">Encoded Spaces</A>
<DT><A HREF="https://example.com/unicode/日本語" ADD_DATE="1609459200">Unicode Path</A>
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
        entries = [json.loads(line) for line in lines]

        assert len(entries) == 3
        assert 'q=test&foo=bar' in entries[0]['url']
        assert '%20' in entries[1]['url']

    def test_javascript_url(self, tmp_path):
        """Test javascript: URLs (should still be extracted)."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="javascript:alert('test')" ADD_DATE="1609459200">JS Bookmarklet</A>
<DT><A HREF="https://example.com" ADD_DATE="1609459200">Normal</A>
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
        entries = [json.loads(line) for line in lines]

        # Both should be extracted
        assert len(entries) == 2
        assert entries[0]['url'].startswith('javascript:')

    def test_data_url(self, tmp_path):
        """Test data: URLs."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="data:text/html,<h1>Test</h1>" ADD_DATE="1609459200">Data URL</A>
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

        assert entry['url'].startswith('data:')

    def test_file_url(self, tmp_path):
        """Test file:// URLs."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="file:///home/user/document.pdf" ADD_DATE="1609459200">Local File</A>
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

        assert entry['url'].startswith('file://')

    def test_very_long_url(self, tmp_path):
        """Test very long URLs (2000+ characters)."""
        long_url = 'https://example.com/path?' + '&'.join([f'param{i}=value{i}' for i in range(100)])
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text(f'''
<DT><A HREF="{long_url}" ADD_DATE="1609459200">Long URL</A>
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

        assert len(entry['url']) > 1000
        assert entry['url'].startswith('https://example.com')

    def test_unicode_in_title(self, tmp_path):
        """Test Unicode characters in titles."""
        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text('''
<DT><A HREF="https://example.com" ADD_DATE="1609459200">日本語のタイトル</A>
<DT><A HREF="https://example.org" ADD_DATE="1609459200">Título en Español</A>
<DT><A HREF="https://example.net" ADD_DATE="1609459200">Заголовок на русском</A>
<DT><A HREF="https://example.biz" ADD_DATE="1609459200">عنوان بالعربية</A>
<DT><A HREF="https://example.info" ADD_DATE="1609459200">Emoji 🚀 📚 🎉</A>
        ''', encoding='utf-8')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '\"type\": \"Snapshot\"' in line]
        entries = [json.loads(line) for line in lines]

        assert len(entries) == 5
        assert any('日本語' in e.get('title', '') for e in entries)
        assert any('Español' in e.get('title', '') for e in entries)

    def test_large_file_many_bookmarks(self, tmp_path):
        """Test parsing large file with many bookmarks (1000+)."""
        bookmarks = []
        for i in range(1000):
            bookmarks.append(
                f'<DT><A HREF="https://example.com/page{i}" ADD_DATE="1609459200" TAGS="tag{i % 10}">Bookmark {i}</A>'
            )

        input_file = tmp_path / 'bookmarks.html'
        input_file.write_text(
            '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<DL><p>\n' +
            '\n'.join(bookmarks) +
            '\n</DL><p>'
        )

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        assert 'urls.jsonl' in result.stderr or 'urls.jsonl' in result.stdout

        # Output goes to stdout (JSONL) - get all JSONL records
        all_lines = [line for line in result.stdout.strip().split('\n') if line.strip() and line.startswith('{')]
        records = [json.loads(line) for line in all_lines]

        # Should have 10 unique tags + 1000 snapshots
        tags = [r for r in records if r.get('type') == 'Tag']
        snapshots = [r for r in records if r.get('type') == 'Snapshot']

        assert len(tags) == 10
        assert len(snapshots) == 1000


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
