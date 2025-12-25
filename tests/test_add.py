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
