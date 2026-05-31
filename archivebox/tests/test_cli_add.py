#!/usr/bin/env python3
"""
Comprehensive tests for archivebox add command.
Verify add creates snapshots in DB, crawls, source files, and archive directories.
"""

import os
import subprocess
from pathlib import Path

import pytest

from archivebox.core.models import Snapshot
from archivebox.crawls.models import Crawl
from archivebox.tests.conftest import run_queued_crawls
from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


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
    """Test that adding a single URL queues a crawl whose runner creates the snapshot."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0
    run_queued_crawls(tmp_path, disable_extractors_dict)

    with use_archivebox_db(tmp_path):
        snapshots = list(Snapshot.objects.values_list("url", flat=True))

    assert len(snapshots) == 1
    assert snapshots[0] == "https://example.com"


def test_add_bg_queues_crawl_without_creating_snapshots(tmp_path, process, disable_extractors_dict):
    """Background add should leave root snapshot creation to the runner."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--bg", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    with use_archivebox_db(tmp_path):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert snapshot_count == 0


def test_add_index_only_rejected_urls_leave_empty_crawl_for_runner_to_seal(tmp_path, process, disable_extractors_dict):
    """Index-only add only creates the crawl; rejected URLs are sealed by the runner."""
    os.chdir(tmp_path)
    result = subprocess.run(
        [
            "archivebox",
            "add",
            "--index-only",
            "--depth=0",
            "--url-denylist=example.com",
            "https://example.com",
        ],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    with use_archivebox_db(tmp_path):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert snapshot_count == 0

    run_queued_crawls(tmp_path, disable_extractors_dict)

    with use_archivebox_db(tmp_path):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.status == Crawl.StatusChoices.SEALED
    assert crawl.retry_at is None
    assert snapshot_count == 0


def test_add_creates_crawl_record(tmp_path, process, disable_extractors_dict):
    """Test that add command creates a Crawl record in the database."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )

    with use_archivebox_db(tmp_path):
        crawl_count = Crawl.objects.count()

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
    run_queued_crawls(tmp_path, disable_extractors_dict)

    with use_archivebox_db(tmp_path):
        snapshot_count = Snapshot.objects.count()
        urls = list(Snapshot.objects.order_by("url").values_list("url", flat=True))

    assert snapshot_count == 2
    assert urls[0] == "https://example.com"
    assert urls[1] == "https://example.org"


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
    run_queued_crawls(tmp_path, disable_extractors_dict)

    with use_archivebox_db(tmp_path):
        crawl_count = Crawl.objects.count()
        snapshot_count = Snapshot.objects.count()

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

    with use_archivebox_db(tmp_path):
        tags_str = Crawl.objects.values_list("tags_str", flat=True).get()

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

    with use_archivebox_db(tmp_path):
        crawl = Crawl.objects.get()

    assert crawl.persona_id
    assert crawl.config["ACTIVE_PERSONA"] == "Default"
    assert (tmp_path / "personas" / "Default" / "chrome_profile").is_dir()


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

    with use_archivebox_db(tmp_path):
        crawl = Crawl.objects.get()

    assert crawl.config["URL_ALLOWLIST"] == "example.com,*.example.com"
    assert crawl.config["URL_DENYLIST"] == "static.example.com"
    assert (tmp_path / "personas" / "Default" / "chrome_extensions").is_dir()


def test_add_duplicate_url_creates_separate_crawls(tmp_path, process, disable_extractors_dict):
    """Test that adding the same URL twice creates separate crawls and snapshots.

    Each 'add' command creates a new Crawl. Multiple crawls can archive the same URL.
    This allows re-archiving URLs at different times.
    """
    os.chdir(tmp_path)

    # Add URL first time
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    run_queued_crawls(tmp_path, disable_extractors_dict)

    # Add same URL second time with --update to opt out of ONLY_NEW.
    subprocess.run(
        ["archivebox", "add", "--index-only", "--update", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    run_queued_crawls(tmp_path, disable_extractors_dict)

    with use_archivebox_db(tmp_path):
        snapshot_count = Snapshot.objects.filter(url="https://example.com").count()
        crawl_count = Crawl.objects.count()

    # Each add creates a new crawl with its own snapshot
    assert crawl_count == 2
    assert snapshot_count == 2


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
    run_queued_crawls(tmp_path, disable_extractors_dict)

    with use_archivebox_db(tmp_path):
        snapshot_id = str(Snapshot.objects.values_list("id", flat=True).get())

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
    assert "--crawl-max-size" in result.stdout
    assert "--crawl-timeout" in result.stdout
    assert "--snapshot-max-size" in result.stdout
    assert "--tag" in result.stdout


def test_add_records_max_url_and_size_limits_on_crawl(tmp_path, process, disable_extractors_dict):
    os.chdir(tmp_path)
    result = subprocess.run(
        [
            "archivebox",
            "add",
            "--index-only",
            "--depth=1",
            "--max-urls=3",
            "--crawl-max-size=45mb",
            "--crawl-timeout=120",
            "--snapshot-max-size=5mb",
            "https://example.com",
        ],
        capture_output=True,
        env=disable_extractors_dict,
    )

    assert result.returncode == 0

    columns = {field.name for field in Crawl._meta.local_fields}
    with use_archivebox_db(tmp_path):
        config = Crawl.objects.values_list("config", flat=True).get() or {}

    assert {"max_urls", "crawl_max_size", "crawl_timeout", "snapshot_max_size"}.isdisjoint(columns)
    assert config["CRAWL_MAX_URLS"] == 3
    assert config["CRAWL_MAX_SIZE"] == 45 * 1024 * 1024
    assert config["CRAWL_TIMEOUT"] == 120
    assert config["SNAPSHOT_MAX_SIZE"] == 5 * 1024 * 1024


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


def test_add_index_only_queues_crawl_without_starting_runner(tmp_path, process, disable_extractors_dict):
    """Test that --index-only creates only a queued crawl and returns fast."""
    os.chdir(tmp_path)
    result = subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
        timeout=30,  # Should be fast
    )

    assert result.returncode == 0

    with use_archivebox_db(tmp_path):
        crawl = Crawl.objects.get()
        snapshot_count = Snapshot.objects.count()

    assert crawl.status == Crawl.StatusChoices.QUEUED
    assert crawl.retry_at is None
    assert snapshot_count == 0


def test_add_links_snapshot_to_crawl(tmp_path, process, disable_extractors_dict):
    """Test that add links the snapshot to the crawl via crawl_id."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    run_queued_crawls(tmp_path, disable_extractors_dict)

    with use_archivebox_db(tmp_path):
        crawl_id = Crawl.objects.values_list("id", flat=True).get()
        snapshot_crawl = Snapshot.objects.values_list("crawl_id", flat=True).get()

    assert snapshot_crawl == crawl_id


def test_add_sets_snapshot_timestamp(tmp_path, process, disable_extractors_dict):
    """Test that add sets a timestamp on the snapshot."""
    os.chdir(tmp_path)
    subprocess.run(
        ["archivebox", "add", "--index-only", "--depth=0", "https://example.com"],
        capture_output=True,
        env=disable_extractors_dict,
    )
    run_queued_crawls(tmp_path, disable_extractors_dict)

    with use_archivebox_db(tmp_path):
        timestamp = Snapshot.objects.values_list("timestamp", flat=True).get()

    assert timestamp is not None
    assert len(str(timestamp)) > 0
