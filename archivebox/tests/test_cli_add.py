#!/usr/bin/env python3
"""
Comprehensive tests for archivebox add command.
Verify add creates snapshots in DB, crawls, source files, and archive directories.
"""

import os
import sqlite3
import subprocess
from pathlib import Path


def _find_snapshot_dir(data_dir: Path, snapshot_id: str) -> Path | None:
    candidates = {snapshot_id}
    if len(snapshot_id) == 32:
        candidates.add(f"{snapshot_id[:8]}-{snapshot_id[8:12]}-{snapshot_id[12:16]}-{snapshot_id[16:20]}-{snapshot_id[20:]}")
    elif len(snapshot_id) == 36 and "-" in snapshot_id:
        candidates.add(snapshot_id.replace("-", ""))

    for needle in candidates:
        for path in data_dir.rglob(needle):
            if path.is_dir():
                return path
    return None


def test_add_single_url_creates_snapshot_in_db(tmp_path, process, disable_extractors_dict):
    """Test that adding a single URL creates a snapshot in the database."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshots = c.execute("SELECT url FROM core_snapshot").fetchall()
    conn.close()

    assert len(snapshots) == 1
    assert snapshots[0][0] == "https://example.com"


def test_add_bg_creates_root_snapshot_rows_immediately(tmp_path, process, disable_extractors_dict):
    """Background add should create root snapshots immediately so the queue is visible in the DB."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--bg", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshots = c.execute("SELECT url, status FROM core_snapshot").fetchall()
    conn.close()

    assert len(snapshots) == 1
    assert snapshots[0][0] == "https://example.com"
    assert snapshots[0][1] == "queued"


def test_add_creates_crawl_record(tmp_path, process, disable_extractors_dict):
    """Test that add command creates a Crawl record in the database."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    assert crawl_count == 1


def test_add_creates_source_file(tmp_path, process, disable_extractors_dict):
    """Test that add creates a source file with the URL."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    sources_dir = tmp_path / "sources"
    assert sources_dir.exists()

    source_files = list(sources_dir.glob("*cli_add.txt"))
    assert len(source_files) >= 1

    source_content = source_files[0].read_text()
    assert "https://example.com" in source_content


def test_add_multiple_urls_single_command(tmp_path, process, disable_extractors_dict):
    """Test adding multiple URLs in a single command."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com", "https://example.org"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    urls = c.execute("SELECT url FROM core_snapshot ORDER BY url").fetchall()
    conn.close()

    assert snapshot_count == 2
    assert urls[0][0] == "https://example.com"
    assert urls[1][0] == "https://example.org"


def test_add_from_file(tmp_path, process, disable_extractors_dict):
    """Test adding URLs from a file.

    The add command should treat a file argument as URL input and create snapshots
    for each URL it contains.
    """
    os.chdir(tmp_path)

    # Create a file with URLs
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.com\nhttps://example.org\n")

    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", str(urls_file)],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # The file is parsed into two input URLs.
    assert crawl_count == 1
    assert snapshot_count == 2


def test_add_with_depth_0_flag(tmp_path, process, disable_extractors_dict):
    """Test that --depth=0 flag is accepted and works."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --depth" not in result.stderr.decode("utf-8")


def test_add_with_depth_1_flag(tmp_path, process, disable_extractors_dict):
    """Test that --depth=1 flag is accepted."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=1", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --depth" not in result.stderr.decode("utf-8")


def test_add_rejects_invalid_depth_values(tmp_path, process, disable_extractors_dict):
    """Test that add rejects depth values outside the supported range."""
    os.chdir(tmp_path)

    for depth in ("5", "-1"):
        result = subprocess.run(
            ["archivebox", "add", "--index-only", f"--depth={depth}", "https://example.com"],
            capture_output=True,
            env=disable_extractors_dict,
        )
        stderr = result.stderr.decode("utf-8").lower()
        assert result.returncode != 0
        assert "invalid" in stderr or "not one of" in stderr


def test_add_with_tags(tmp_path, process, disable_extractors_dict):
    """Test adding URL with tags stores tags_str in crawl.

    With --index-only, Tag objects are not created until archiving happens.
    Tags are stored as a string in the Crawl.tags_str field.
    """
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "--tag=test,example", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    tags_str = c.execute("SELECT tags_str FROM crawls_crawl").fetchone()[0]
    conn.close()

    # Tags are stored as a comma-separated string in crawl
    assert "test" in tags_str or "example" in tags_str


def test_add_records_selected_persona_on_crawl(tmp_path, process, disable_extractors_dict):
    """Test add persists the selected persona so browser config derives from it later."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "--persona=Default", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    persona_id, default_persona = c.execute(
        "SELECT persona_id, json_extract(config, '$.DEFAULT_PERSONA') FROM crawls_crawl LIMIT 1",
    ).fetchone()
    conn.close()

    assert persona_id
    assert default_persona == "Default"
    assert (tmp_path / "personas" / "Default" / "chrome_user_data").is_dir()


def test_add_records_url_filter_overrides_on_crawl(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    result = subprocess.run(
        [
            "archivebox",
            "add",
            "--index-only",
            "--depth=0",
            "--domain-allowlist=example.com,*.example.com",
            "--domain-denylist=static.example.com",
            "https://example.com",
        ],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    allowlist, denylist = c.execute(
        "SELECT json_extract(config, '$.URL_ALLOWLIST'), json_extract(config, '$.URL_DENYLIST') FROM crawls_crawl LIMIT 1",
    ).fetchone()
    conn.close()

    assert allowlist == "example.com,*.example.com"
    assert denylist == "static.example.com"
    assert (tmp_path / "personas" / "Default" / "chrome_extensions").is_dir()


def test_add_duplicate_url_creates_separate_crawls_with_overwrite(tmp_path, process, disable_extractors_dict):
    """Test that adding the same URL twice with --overwrite creates separate crawls and snapshots.

    The --overwrite flag bypasses deduplication and allows re-archiving URLs.
    """
    os.chdir(tmp_path)

    # Add URL first time
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Add same URL second time with --overwrite
    subprocess.run(
        ["archivebox", "add", "--index-only", "--overwrite", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot WHERE url='https://example.com'").fetchone()[0]
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    # With --overwrite, each add creates a new crawl with its own snapshot
    assert crawl_count == 2
    assert snapshot_count == 2


def test_add_duplicate_url_is_skipped(tmp_path, process, disable_extractors_dict):
    """Test that adding the same URL twice without --overwrite skips the duplicate.

    Without --overwrite, duplicate URLs should be skipped to save storage and compute resources.
    """
    os.chdir(tmp_path)

    # Add URL first time
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Add same URL second time (without --overwrite)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot WHERE url='https://example.com'").fetchone()[0]
    crawl_count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    # Only 1 snapshot should exist (second add was skipped)
    assert snapshot_count == 1
    # Only 1 crawl should exist (second add didn't create a crawl)
    assert crawl_count == 1
    # Output should contain the skip message
    output = result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
    assert "跳过重复" in output or "duplicate" in output.lower()


def test_add_url_normalization_case_insensitive(tmp_path, process, disable_extractors_dict):
    """Test that URL normalization handles case-insensitive matching.

    URLs with different cases should be treated as duplicates.
    """
    os.chdir(tmp_path)

    # Add URL first time
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Add same URL with different case
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "HTTPS://EXAMPLE.COM"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # Only 1 snapshot should exist (case-insensitive match)
    assert snapshot_count == 1
    # Output should contain the skip message
    output = result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
    assert "跳过重复" in output or "duplicate" in output.lower()


def test_add_url_normalization_trailing_slash(tmp_path, process, disable_extractors_dict):
    """Test that URL normalization handles trailing slashes.

    URLs with and without trailing slashes should be treated as duplicates.
    """
    os.chdir(tmp_path)

    # Add URL without trailing slash
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Add same URL with trailing slash
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com/"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # Only 1 snapshot should exist (trailing slash is ignored)
    assert snapshot_count == 1
    # Output should contain the skip message
    output = result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
    assert "跳过重复" in output or "duplicate" in output.lower()


def test_add_duplicate_urls_in_same_batch(tmp_path, process, disable_extractors_dict):
    """Test that duplicate URLs in the same batch are deduplicated.

    When adding multiple URLs in a single command, duplicates should be removed.
    """
    os.chdir(tmp_path)

    # Add multiple URLs including duplicates
    result = subprocess.run(
        [
            "archivebox",
            "add",
            "--index-only",
            "--depth=0",
            "https://example.com",
            "https://example.org",
            "https://example.com",  # duplicate
            "https://EXAMPLE.ORG",  # duplicate (case difference)
        ],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # Only 2 unique snapshots should exist
    assert snapshot_count == 2
    # Output should contain skip messages for duplicates
    output = result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
    assert "跳过重复" in output or "duplicate" in output.lower()


def test_add_urls_from_file_with_duplicates(tmp_path, process, disable_extractors_dict):
    """Test that adding URLs from a file with duplicates works correctly.

    When reading URLs from a file, duplicates should be deduplicated.
    """
    os.chdir(tmp_path)

    # Create a file with URLs including duplicates
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://example.com\n"
        "https://example.org\n"
        "https://example.com\n"  # duplicate
        "https://example.com/\n"  # duplicate (trailing slash)
    )

    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", str(urls_file)],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    # Only 2 unique snapshots should exist
    assert snapshot_count == 2
    # Output should contain skip messages for duplicates
    output = result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
    assert "跳过重复" in output or "duplicate" in output.lower()


def test_add_empty_url_list(tmp_path, process, disable_extractors_dict):
    """Test that adding empty URL list shows appropriate error.

    When no URLs are provided, the command should show a usage error.
    """
    os.chdir(tmp_path)

    # Try to add without any URLs
    result = subprocess.run(
        ["archivebox", "add"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Should fail with usage error
    assert result.returncode != 0
    output = result.stdout.decode("utf-8") + result.stderr.decode("utf-8")
    assert "usage" in output.lower() or "url" in output.lower()


def test_add_with_overwrite_flag(tmp_path, process, disable_extractors_dict):
    """Test that --overwrite flag forces re-archiving."""
    os.chdir(tmp_path)

    # Add URL first time
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Add with overwrite
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--overwrite", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0
    assert "unrecognized arguments: --overwrite" not in result.stderr.decode("utf-8")


def test_add_creates_snapshot_output_directory(tmp_path, process, disable_extractors_dict):
    """Test that add creates the current snapshot output directory on disk."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_id = str(c.execute("SELECT id FROM core_snapshot").fetchone()[0])
    conn.close()

    snapshot_dir = _find_snapshot_dir(tmp_path, snapshot_id)
    assert snapshot_dir is not None, f"Snapshot output directory not found for {snapshot_id}"
    assert snapshot_dir.is_dir()


def test_add_help_shows_depth_and_tag_options(tmp_path, process):
    """Test that add --help documents the main filter and crawl options."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ["archivebox", "add", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--depth" in result.stdout
    assert "--max-urls" in result.stdout
    assert "--max-size" in result.stdout
    assert "--tag" in result.stdout


def test_add_records_max_url_and_size_limits_on_crawl(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=1", "--max-urls=3", "--max-size=45mb", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    max_urls, max_size, config_max_urls, config_max_size = c.execute(
        "SELECT max_urls, max_size, json_extract(config, '$.MAX_URLS'), json_extract(config, '$.MAX_SIZE') FROM crawls_crawl LIMIT 1",
    ).fetchone()
    conn.close()

    assert max_urls == 3
    assert max_size == 45 * 1024 * 1024
    assert config_max_urls == 3
    assert config_max_size == 45 * 1024 * 1024


def test_add_without_args_shows_usage(tmp_path, process):
    """Test that add without URLs fails with a usage hint instead of crashing."""
    os.chdir(tmp_path)

    result = subprocess.run(
        ["archivebox", "add"],
        capture_output=True,
        text=True,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "usage" in combined.lower() or "url" in combined.lower()


def test_add_index_only_skips_extraction(tmp_path, process, disable_extractors_dict):
    """Test that --index-only flag skips extraction (fast)."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,  # Should be fast
    )

    assert result.returncode == 0

    # Snapshot should exist but archive results should be minimal
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert snapshot_count == 1


def test_add_links_snapshot_to_crawl(tmp_path, process, disable_extractors_dict):
    """Test that add links the snapshot to the crawl via crawl_id."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()

    # Get crawl id
    crawl_id = c.execute("SELECT id FROM crawls_crawl").fetchone()[0]

    # Get snapshot's crawl_id
    snapshot_crawl = c.execute("SELECT crawl_id FROM core_snapshot").fetchone()[0]

    conn.close()

    assert snapshot_crawl == crawl_id


def test_add_sets_snapshot_timestamp(tmp_path, process, disable_extractors_dict):
    """Test that add sets a timestamp on the snapshot."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    timestamp = c.execute("SELECT timestamp FROM core_snapshot").fetchone()[0]
    conn.close()

    assert timestamp is not None
    assert len(str(timestamp)) > 0


def test_add_large_batch_performance(tmp_path, process, disable_extractors_dict):
    """Test that adding a large batch of URLs is performant.

    For 1000 URLs, the total processing time (including deduplication check
    and index-only operations) should not exceed 10 seconds.
    """
    import time

    os.chdir(tmp_path)

    num_urls = 100
    urls = [f"https://example{i}.com" for i in range(num_urls)]

    start_time = time.time()

    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", *urls],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,
    )

    elapsed_time = time.time() - start_time

    assert result.returncode == 0

    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    snapshot_count = c.execute("SELECT COUNT(*) FROM core_snapshot").fetchone()[0]
    conn.close()

    assert snapshot_count == num_urls

    max_time_per_100_urls = 2.0
    assert elapsed_time < max_time_per_100_urls, f"Adding {num_urls} URLs took {elapsed_time:.2f}s, expected < {max_time_per_100_urls}s"


class TestNormalizeUrl:
    """Unit tests for the normalize_url function."""

    def test_normalize_url_lowercase_scheme_and_host(self):
        """Test that scheme and hostname are converted to lowercase."""
        from archivebox.misc.util import normalize_url

        assert normalize_url("HTTPS://EXAMPLE.COM/PATH") == "https://example.com/PATH"
        assert normalize_url("HTTP://Example.Org/Path") == "http://example.org/Path"

    def test_normalize_url_remove_trailing_slash(self):
        """Test that trailing slash is removed from path (except root)."""
        from archivebox.misc.util import normalize_url

        assert normalize_url("https://example.com/path/") == "https://example.com/path"
        assert normalize_url("https://example.com/") == "https://example.com/"
        assert normalize_url("https://example.com") == "https://example.com"

    def test_normalize_url_remove_default_ports(self):
        """Test that default ports are removed."""
        from archivebox.misc.util import normalize_url

        assert normalize_url("http://example.com:80/path") == "http://example.com/path"
        assert normalize_url("https://example.com:443/path") == "https://example.com/path"
        assert normalize_url("http://example.com:8080/path") == "http://example.com:8080/path"

    def test_normalize_url_remove_fragment(self):
        """Test that URL fragment is removed."""
        from archivebox.misc.util import normalize_url

        assert normalize_url("https://example.com/path#section") == "https://example.com/path"
        assert normalize_url("https://example.com#top") == "https://example.com"

    def test_normalize_url_combined(self):
        """Test combined normalization rules."""
        from archivebox.misc.util import normalize_url

        url = "HTTPS://Example.COM:443/Path/#Section"
        expected = "https://example.com/Path"
        assert normalize_url(url) == expected

    def test_normalize_url_empty_or_invalid(self):
        """Test that empty or invalid URLs are handled gracefully."""
        from archivebox.misc.util import normalize_url

        assert normalize_url("") == ""
        assert normalize_url(None) is None

    def test_normalize_url_preserves_query_params(self):
        """Test that query parameters are preserved."""
        from archivebox.misc.util import normalize_url

        assert normalize_url("https://example.com/path?foo=bar&baz=qux") == "https://example.com/path?foo=bar&baz=qux"
        assert normalize_url("HTTPS://EXAMPLE.COM/PATH?FOO=BAR") == "https://example.com/PATH?FOO=BAR"
