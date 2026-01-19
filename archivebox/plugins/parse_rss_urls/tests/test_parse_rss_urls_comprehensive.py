#!/usr/bin/env python3
"""Comprehensive tests for parse_rss_urls extractor covering various RSS/Atom variants."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).parent.parent
SCRIPT_PATH = next(PLUGIN_DIR.glob('on_Snapshot__*_parse_rss_urls.*'), None)


class TestRssVariants:
    """Test various RSS format variants."""

    def test_rss_091(self, tmp_path):
        """Test RSS 0.91 format (oldest RSS version)."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<rss version="0.91">
  <channel>
    <title>RSS 0.91 Feed</title>
    <link>https://example.com</link>
    <description>Test RSS 0.91</description>
    <item>
      <title>RSS 0.91 Article</title>
      <link>https://example.com/article1</link>
      <description>An article in RSS 0.91 format</description>
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

        assert result.returncode == 0, f"Failed: {result.stderr}"
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])

        assert entry['url'] == 'https://example.com/article1'
        assert entry['title'] == 'RSS 0.91 Article'
        assert entry['plugin'] == 'parse_rss_urls'

    def test_rss_10_rdf(self, tmp_path):
        """Test RSS 1.0 (RDF) format."""
        input_file = tmp_path / 'feed.rdf'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://example.com">
    <title>RSS 1.0 Feed</title>
    <link>https://example.com</link>
  </channel>
  <item rdf:about="https://example.com/rdf1">
    <title>RDF Item 1</title>
    <link>https://example.com/rdf1</link>
    <dc:date>2024-01-15T10:30:00Z</dc:date>
    <dc:subject>Technology</dc:subject>
  </item>
  <item rdf:about="https://example.com/rdf2">
    <title>RDF Item 2</title>
    <link>https://example.com/rdf2</link>
    <dc:date>2024-01-16T14:20:00Z</dc:date>
  </item>
</rdf:RDF>
        ''')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Failed: {result.stderr}"
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '\"type\": \"Snapshot\"' in line]
        entries = [json.loads(line) for line in lines if json.loads(line)['type'] == 'Snapshot']

        urls = {e['url'] for e in entries}
        assert 'https://example.com/rdf1' in urls
        assert 'https://example.com/rdf2' in urls
        assert any(e.get('bookmarked_at') for e in entries)

    def test_rss_20_with_full_metadata(self, tmp_path):
        """Test RSS 2.0 with all standard metadata fields."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Full RSS 2.0</title>
    <link>https://example.com</link>
    <description>Complete RSS 2.0 feed</description>
    <item>
      <title>Complete Article</title>
      <link>https://example.com/complete</link>
      <description>Full description here</description>
      <author>author@example.com</author>
      <category>Technology</category>
      <category>Programming</category>
      <guid>https://example.com/complete</guid>
      <pubDate>Mon, 15 Jan 2024 10:30:00 GMT</pubDate>
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
        content = result.stdout.strip()
        lines = content.split('\n')

        # Check for Tag records
        tags = [json.loads(line) for line in lines if json.loads(line)['type'] == 'Tag']
        tag_names = {t['name'] for t in tags}
        assert 'Technology' in tag_names
        assert 'Programming' in tag_names

        # Check Snapshot record
        snapshots = [json.loads(line) for line in lines if json.loads(line)['type'] == 'Snapshot']
        entry = snapshots[0]
        assert entry['url'] == 'https://example.com/complete'
        assert entry['title'] == 'Complete Article'
        assert 'bookmarked_at' in entry
        assert entry['tags'] == 'Technology,Programming' or entry['tags'] == 'Programming,Technology'


class TestAtomVariants:
    """Test various Atom format variants."""

    def test_atom_10_full(self, tmp_path):
        """Test Atom 1.0 with full metadata."""
        input_file = tmp_path / 'feed.atom'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom 1.0 Feed</title>
  <updated>2024-01-15T00:00:00Z</updated>
  <entry>
    <title>Atom Entry 1</title>
    <link href="https://atom.example.com/1"/>
    <id>urn:uuid:1234-5678</id>
    <updated>2024-01-15T10:30:00Z</updated>
    <published>2024-01-14T08:00:00Z</published>
    <category term="science"/>
    <category term="research"/>
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
        lines = [line for line in result.stdout.strip().split('\n') if line.strip()]

        tags = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Tag']
        tag_names = {t['name'] for t in tags}
        assert 'science' in tag_names
        assert 'research' in tag_names

        snapshots = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Snapshot']
        entry = snapshots[0]
        assert entry['url'] == 'https://atom.example.com/1'
        assert 'bookmarked_at' in entry

    def test_atom_with_alternate_link(self, tmp_path):
        """Test Atom feed with alternate link types."""
        input_file = tmp_path / 'feed.atom'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Alternate Links</title>
  <entry>
    <title>Entry with alternate</title>
    <link rel="alternate" type="text/html" href="https://atom.example.com/article"/>
    <link rel="self" href="https://atom.example.com/feed"/>
    <updated>2024-01-15T10:30:00Z</updated>
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
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])
        # feedparser should pick the alternate link
        assert 'atom.example.com/article' in entry['url']


class TestDateFormats:
    """Test various date format handling."""

    def test_rfc822_date(self, tmp_path):
        """Test RFC 822 date format (RSS 2.0 standard)."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>RFC 822 Date</title>
      <link>https://example.com/rfc822</link>
      <pubDate>Wed, 15 Jan 2020 10:30:45 GMT</pubDate>
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
        assert 'bookmarked_at' in entry
        assert '2020-01-15' in entry['bookmarked_at']

    def test_iso8601_date(self, tmp_path):
        """Test ISO 8601 date format (Atom standard)."""
        input_file = tmp_path / 'feed.atom'
        input_file.write_text('''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>ISO 8601 Date</title>
    <link href="https://example.com/iso"/>
    <published>2024-01-15T10:30:45.123Z</published>
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
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])
        assert 'bookmarked_at' in entry
        assert '2024-01-15' in entry['bookmarked_at']

    def test_updated_vs_published_date(self, tmp_path):
        """Test that published date is preferred over updated date."""
        input_file = tmp_path / 'feed.atom'
        input_file.write_text('''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Date Priority Test</title>
    <link href="https://example.com/dates"/>
    <published>2024-01-10T10:00:00Z</published>
    <updated>2024-01-15T10:00:00Z</updated>
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
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])
        # Should use published date (Jan 10) not updated date (Jan 15)
        assert '2024-01-10' in entry['bookmarked_at']

    def test_only_updated_date(self, tmp_path):
        """Test fallback to updated date when published is missing."""
        input_file = tmp_path / 'feed.atom'
        input_file.write_text('''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Only Updated</title>
    <link href="https://example.com/updated"/>
    <updated>2024-01-20T10:00:00Z</updated>
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
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])
        assert '2024-01-20' in entry['bookmarked_at']

    def test_no_date(self, tmp_path):
        """Test entries without any date."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>No Date</title>
      <link>https://example.com/nodate</link>
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
        assert 'bookmarked_at' not in entry


class TestTagsAndCategories:
    """Test various tag and category formats."""

    def test_rss_categories(self, tmp_path):
        """Test RSS 2.0 category elements."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Multi Category</title>
      <link>https://example.com/cats</link>
      <category>Tech</category>
      <category>Web</category>
      <category>Programming</category>
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
        lines = [line for line in result.stdout.strip().split('\n') if line.strip()]

        tags = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Tag']
        tag_names = {t['name'] for t in tags}
        assert 'Tech' in tag_names
        assert 'Web' in tag_names
        assert 'Programming' in tag_names

        snapshots = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Snapshot']
        entry = snapshots[0]
        tags_list = entry['tags'].split(',')
        assert len(tags_list) == 3

    def test_atom_categories(self, tmp_path):
        """Test Atom category elements with various attributes."""
        input_file = tmp_path / 'feed.atom'
        input_file.write_text('''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom Categories</title>
    <link href="https://example.com/atomcats"/>
    <category term="python" scheme="http://example.com/categories" label="Python Programming"/>
    <category term="django" label="Django Framework"/>
    <updated>2024-01-15T10:00:00Z</updated>
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
        lines = [line for line in result.stdout.strip().split('\n') if line.strip()]

        tags = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Tag']
        tag_names = {t['name'] for t in tags}
        # feedparser extracts the 'term' attribute
        assert 'python' in tag_names
        assert 'django' in tag_names

    def test_no_tags(self, tmp_path):
        """Test entries without tags."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>No Tags</title>
      <link>https://example.com/notags</link>
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
        assert 'tags' not in entry or entry['tags'] == ''

    def test_duplicate_tags(self, tmp_path):
        """Test that duplicate tags are handled properly."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Duplicate Tags</title>
      <link>https://example.com/dups</link>
      <category>Python</category>
      <category>Python</category>
      <category>Web</category>
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
        lines = [line for line in result.stdout.strip().split('\n') if line.strip()]
        tags = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Tag']
        # Tag records should be unique
        tag_names = [t['name'] for t in tags]
        assert tag_names.count('Python') == 1


class TestCustomNamespaces:
    """Test custom namespace handling (Dublin Core, Media RSS, etc.)."""

    def test_dublin_core_metadata(self, tmp_path):
        """Test Dublin Core namespace fields."""
        input_file = tmp_path / 'feed.rdf'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="https://example.com">
    <title>Dublin Core Feed</title>
  </channel>
  <item rdf:about="https://example.com/dc1">
    <title>Dublin Core Article</title>
    <link>https://example.com/dc1</link>
    <dc:creator>John Doe</dc:creator>
    <dc:subject>Technology</dc:subject>
    <dc:date>2024-01-15T10:30:00Z</dc:date>
    <dc:rights>Copyright 2024</dc:rights>
  </item>
</rdf:RDF>
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
        snapshots = [json.loads(line) for line in lines if json.loads(line)['type'] == 'Snapshot']
        entry = snapshots[0]

        assert entry['url'] == 'https://example.com/dc1'
        assert entry['title'] == 'Dublin Core Article'
        # feedparser should parse dc:date as bookmarked_at
        assert 'bookmarked_at' in entry

    def test_media_rss_namespace(self, tmp_path):
        """Test Media RSS namespace (common in podcast feeds)."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Media RSS Feed</title>
    <item>
      <title>Podcast Episode 1</title>
      <link>https://example.com/podcast/1</link>
      <media:content url="https://example.com/audio.mp3" type="audio/mpeg"/>
      <media:thumbnail url="https://example.com/thumb.jpg"/>
      <pubDate>Mon, 15 Jan 2024 10:00:00 GMT</pubDate>
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

        assert entry['url'] == 'https://example.com/podcast/1'
        assert entry['title'] == 'Podcast Episode 1'

    def test_itunes_namespace(self, tmp_path):
        """Test iTunes namespace (common in podcast feeds)."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>iTunes Podcast</title>
    <item>
      <title>Episode 1: Getting Started</title>
      <link>https://example.com/ep1</link>
      <itunes:author>Jane Smith</itunes:author>
      <itunes:duration>45:30</itunes:duration>
      <itunes:keywords>programming, tutorial, beginner</itunes:keywords>
      <pubDate>Tue, 16 Jan 2024 08:00:00 GMT</pubDate>
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
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '\"type\": \"Snapshot\"' in line]
        snapshots = [json.loads(line) for line in lines if json.loads(line)['type'] == 'Snapshot']
        entry = snapshots[0]

        assert entry['url'] == 'https://example.com/ep1'
        assert entry['title'] == 'Episode 1: Getting Started'


class TestEdgeCases:
    """Test edge cases and malformed data."""

    def test_missing_title(self, tmp_path):
        """Test entries without title."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <link>https://example.com/notitle</link>
      <pubDate>Mon, 15 Jan 2024 10:00:00 GMT</pubDate>
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

        assert entry['url'] == 'https://example.com/notitle'
        assert 'title' not in entry

    def test_missing_link(self, tmp_path):
        """Test entries without link (should be skipped)."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>No Link</title>
      <description>This entry has no link</description>
    </item>
    <item>
      <title>Has Link</title>
      <link>https://example.com/haslink</link>
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

        # Should only have the entry with a link
        assert entry['url'] == 'https://example.com/haslink'
        assert '1 URL' in result.stdout

    def test_html_entities_in_title(self, tmp_path):
        """Test HTML entities in titles are properly decoded."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Using &lt;div&gt; &amp; &lt;span&gt; tags</title>
      <link>https://example.com/html</link>
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

        assert entry['title'] == 'Using <div> & <span> tags'

    def test_special_characters_in_tags(self, tmp_path):
        """Test special characters in tags."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Special Tags</title>
      <link>https://example.com/special</link>
      <category>C++</category>
      <category>Node.js</category>
      <category>Web/Mobile</category>
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
        lines = [line for line in result.stdout.strip().split('\n') if line.strip()]

        tags = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Tag']
        tag_names = {t['name'] for t in tags}
        assert 'C++' in tag_names
        assert 'Node.js' in tag_names
        assert 'Web/Mobile' in tag_names

    def test_cdata_sections(self, tmp_path):
        """Test CDATA sections in titles and descriptions."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title><![CDATA[Using <strong>HTML</strong> in titles]]></title>
      <link>https://example.com/cdata</link>
      <description><![CDATA[Content with <em>markup</em>]]></description>
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

        # feedparser should strip HTML tags
        assert 'HTML' in entry['title']
        assert entry['url'] == 'https://example.com/cdata'

    def test_relative_urls(self, tmp_path):
        """Test that relative URLs are preserved (feedparser handles them)."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <link>https://example.com</link>
    <item>
      <title>Relative URL</title>
      <link>/article/relative</link>
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

        # feedparser may convert relative to absolute, or leave as-is
        assert 'article/relative' in entry['url']

    def test_unicode_characters(self, tmp_path):
        """Test Unicode characters in feed content."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Unicode: 日本語 Français 中文 العربية</title>
      <link>https://example.com/unicode</link>
      <category>日本語</category>
      <category>Français</category>
    </item>
  </channel>
</rss>
        ''', encoding='utf-8')

        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), '--url', f'file://{input_file}'],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        # Output goes to stdout (JSONL)
        lines = [line for line in result.stdout.strip().split('\n') if line.strip()]

        snapshots = [json.loads(line) for line in lines if json.loads(line)['type'] == 'Snapshot']
        entry = snapshots[0]
        assert '日本語' in entry['title']
        assert 'Français' in entry['title']

    def test_very_long_title(self, tmp_path):
        """Test handling of very long titles."""
        long_title = 'A' * 1000
        input_file = tmp_path / 'feed.rss'
        input_file.write_text(f'''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>{long_title}</title>
      <link>https://example.com/long</link>
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

        assert len(entry['title']) == 1000
        assert entry['title'] == long_title

    def test_multiple_entries_batch(self, tmp_path):
        """Test processing a large batch of entries."""
        items = []
        for i in range(100):
            items.append(f'''
    <item>
      <title>Article {i}</title>
      <link>https://example.com/article/{i}</link>
      <category>Tag{i % 10}</category>
      <pubDate>Mon, {15 + (i % 15)} Jan 2024 10:00:00 GMT</pubDate>
    </item>
            ''')

        input_file = tmp_path / 'feed.rss'
        input_file.write_text(f'''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Large Feed</title>
    {''.join(items)}
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
        lines = [line for line in result.stdout.strip().split('\n') if line.strip()]

        # Should have 10 unique tags (Tag0-Tag9) + 100 snapshots
        tags = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Tag']
        snapshots = [json.loads(line) for line in lines if json.loads(line).get('type') == 'Snapshot']

        assert len(tags) == 10
        assert len(snapshots) == 100


class TestRealWorldFeeds:
    """Test patterns from real-world RSS feeds."""

    def test_medium_style_feed(self, tmp_path):
        """Test Medium-style feed structure."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Medium Feed</title>
    <item>
      <title>Article Title</title>
      <link>https://medium.com/@user/article-slug-123abc</link>
      <guid isPermaLink="false">https://medium.com/p/123abc</guid>
      <pubDate>Wed, 15 Jan 2024 10:30:00 GMT</pubDate>
      <category>Programming</category>
      <category>JavaScript</category>
      <dc:creator xmlns:dc="http://purl.org/dc/elements/1.1/">Author Name</dc:creator>
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
        lines = [line for line in result.stdout.strip().split('\n') if line.strip() and '\"type\": \"Snapshot\"' in line]

        snapshots = [json.loads(line) for line in lines if json.loads(line)['type'] == 'Snapshot']
        entry = snapshots[0]
        assert 'medium.com' in entry['url']
        assert entry['title'] == 'Article Title'

    def test_reddit_style_feed(self, tmp_path):
        """Test Reddit-style feed structure."""
        input_file = tmp_path / 'feed.rss'
        input_file.write_text('''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Reddit Feed</title>
  <entry>
    <title>Post Title</title>
    <link href="https://www.reddit.com/r/programming/comments/abc123/post_title/"/>
    <updated>2024-01-15T10:30:00+00:00</updated>
    <category term="programming" label="r/programming"/>
    <id>t3_abc123</id>
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

        snapshots = [json.loads(line) for line in lines if json.loads(line)['type'] == 'Snapshot']
        entry = snapshots[0]
        assert 'reddit.com' in entry['url']

    def test_youtube_style_feed(self, tmp_path):
        """Test YouTube-style feed structure."""
        input_file = tmp_path / 'feed.atom'
        input_file.write_text('''<?xml version="1.0"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <title>YouTube Channel</title>
  <entry>
    <title>Video Title</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"/>
    <published>2024-01-15T10:30:00+00:00</published>
    <yt:videoId>dQw4w9WgXcQ</yt:videoId>
    <yt:channelId>UCxxxxxxxx</yt:channelId>
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
        lines = [line for line in result.stdout.strip().split('\n') if '\"type\": \"Snapshot\"' in line]
        entry = json.loads(lines[0])

        assert 'youtube.com' in entry['url']
        assert 'dQw4w9WgXcQ' in entry['url']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
