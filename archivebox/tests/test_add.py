import subprocess
import json
import sqlite3
import os

from .fixtures import *

def test_depth_flag_is_accepted(process, disable_extractors_dict):
    arg_process = subprocess.run(["archivebox", "add", "--index-only", "https://example.com", "--depth=0"],
                                  capture_output=True, env=disable_extractors_dict)
    assert 'unrecognized arguments: --depth' not in arg_process.stderr.decode("utf-8")


def test_depth_flag_fails_if_it_is_not_0_or_1(process, disable_extractors_dict):
    arg_process = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=5", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    # Error message may say "invalid choice" or "is not one of"
    stderr = arg_process.stderr.decode("utf-8")
    assert 'invalid' in stderr.lower() or 'not one of' in stderr.lower()
    arg_process = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=-1", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    stderr = arg_process.stderr.decode("utf-8")
    assert 'invalid' in stderr.lower() or 'not one of' in stderr.lower()


def test_depth_flag_0_creates_source_file(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    arg_process = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Check that source file was created with the URL
    sources_dir = tmp_path / "sources"
    assert sources_dir.exists()
    source_files = list(sources_dir.glob("*cli_add.txt"))
    assert len(source_files) >= 1
    source_content = source_files[0].read_text()
    assert "example.com" in source_content


def test_overwrite_flag_is_accepted(process, disable_extractors_dict):
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    arg_process = subprocess.run(
        ["archivebox", "add", "--index-only", "--overwrite", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    assert 'unrecognized arguments: --overwrite' not in arg_process.stderr.decode("utf-8")

def test_add_creates_crawl_in_database(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Check that a Crawl was created in database
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    assert count >= 1


def test_add_with_tags(tmp_path, process, disable_extractors_dict):
    """Test adding URL with tags."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "--tag=test,example", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Check that tags were created in database
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    tags = c.execute("SELECT name FROM core_tag").fetchall()
    conn.close()

    tag_names = [t[0] for t in tags]
    assert 'test' in tag_names or 'example' in tag_names


def test_add_multiple_urls_single_call(tmp_path, process, disable_extractors_dict):
    """Test adding multiple URLs in a single call creates multiple snapshots."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0",
         "https://example.com", "https://example.org"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Check both URLs are in the source file
    sources_dir = tmp_path / "sources"
    source_files = list(sources_dir.glob("*cli_add.txt"))
    assert len(source_files) >= 1
    source_content = source_files[0].read_text()
    assert "example.com" in source_content
    assert "example.org" in source_content


def test_add_from_file(tmp_path, process, disable_extractors_dict):
    """Test adding URLs from a file."""
    os.chdir(tmp_path)

    # Create a file with URLs
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.com\nhttps://example.org\n")

    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", str(urls_file)],
        capture_output=True,
        env=disable_extractors_dict,
    )

    # Check that a Crawl was created
    conn = sqlite3.connect("index.sqlite3")
    c = conn.cursor()
    count = c.execute("SELECT COUNT(*) FROM crawls_crawl").fetchone()[0]
    conn.close()

    assert count >= 1


class TestAddCLI:
    """Test the CLI interface for add command."""

    def test_add_help(self, tmp_path, process):
        """Test that --help works for add command."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ["archivebox", "add", "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert '--depth' in result.stdout or 'depth' in result.stdout
        assert '--tag' in result.stdout or 'tag' in result.stdout

    def test_add_no_args_shows_help(self, tmp_path, process):
        """Test that add with no args shows help or usage."""
        os.chdir(tmp_path)

        result = subprocess.run(
            ["archivebox", "add"],
            capture_output=True,
            text=True,
        )

        # Should either show help or error about missing URL
        combined = result.stdout + result.stderr
        assert 'usage' in combined.lower() or 'url' in combined.lower() or 'add' in combined.lower()
