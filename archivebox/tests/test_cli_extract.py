#!/usr/bin/env python3
"""Tests for archivebox extract command."""

import shutil
from pathlib import Path

import pytest
from abx_plugins import get_plugins_dir

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import cli_env, find_snapshot_dir, parse_jsonl_output, run_archivebox_cmd

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def archive_with_extractors(initialized_archive):
    result = run_archivebox_cmd(["install", "wget", "title"], cwd=initialized_archive, timeout=600)
    assert result.returncode == 0, result.stderr or result.stdout
    return initialized_archive


def test_extract_runs_on_existing_snapshots(archive_with_extractors):
    """Extract runs a requested plugin for an existing snapshot."""
    initialized_archive = archive_with_extractors
    env = cli_env(PLUGINS="wget,title")

    create_result = run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    snapshot = next(record for record in parse_jsonl_output(create_result.stdout) if record.get("type") == "Snapshot")
    snapshot_id = snapshot["id"]

    result = run_archivebox_cmd(
        ["extract", "--plugins=wget,title", snapshot_id],
        cwd=initialized_archive,
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr or result.stdout

    records = parse_jsonl_output(result.stdout)
    result_records = {
        record["plugin"]: record
        for record in records
        if record.get("type") == "ArchiveResult" and record.get("snapshot_id") == snapshot_id and record.get("plugin") in {"wget", "title"}
    }
    assert set(result_records) == {"wget", "title"}, records
    assert result_records["title"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["title"]["output_str"] == "Example Domain"
    assert result_records["wget"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["wget"]["output_str"] == "wget/example.com/index.html"

    with use_archivebox_db(initialized_archive):
        archiveresults = {row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin__in=("wget", "title"))}

    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot_id)
    assert snapshot_dir is not None
    title_path = snapshot_dir / "title" / "title.txt"
    wget_path = snapshot_dir / "wget" / "example.com" / "index.html"
    warc_files = list((snapshot_dir / "wget" / "warc").glob("*.warc.gz"))
    assert title_path.is_file()
    assert wget_path.is_file()
    assert warc_files
    assert title_path.read_text(encoding="utf-8").strip() == "Example Domain"
    assert "Example Domain" in wget_path.read_text(encoding="utf-8")
    assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["title"].output_str == "Example Domain"
    assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
    assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["wget"].output_str == "wget/example.com/index.html"
    assert archiveresults["wget"].output_files["example.com/index.html"]["size"] == wget_path.stat().st_size


def test_extract_runs_custom_plugin_discovered_from_data_dir(initialized_archive):
    """Custom plugins discovered by ArchiveBox must execute through abx-dl."""
    custom_plugin_name = "custom_parse_txt_urls"
    custom_plugin_dir = initialized_archive / "custom_plugins" / custom_plugin_name
    shutil.copytree(Path(get_plugins_dir()) / "parse_txt_urls", custom_plugin_dir)
    input_path = initialized_archive / "custom-plugin-input.txt"
    input_path.write_text("https://example.com\nhttps://example.org\n", encoding="utf-8")
    env = cli_env(PLUGINS=f"{custom_plugin_name},hashes", HASHES_ENABLED="True")

    create_result = run_archivebox_cmd(
        ["snapshot", "create", "https://archivebox.example/custom-plugin-input"],
        cwd=initialized_archive,
        env=env,
    )
    assert create_result.returncode == 0, create_result.stderr or create_result.stdout
    snapshot = next(record for record in parse_jsonl_output(create_result.stdout) if record.get("type") == "Snapshot")

    with use_archivebox_db(initialized_archive):
        staticfile_dir = Snapshot.objects.get(id=snapshot["id"]).output_dir / "staticfile"
    staticfile_dir.mkdir(parents=True)
    shutil.copy2(input_path, staticfile_dir / input_path.name)

    result = run_archivebox_cmd(
        ["extract", f"--plugins={custom_plugin_name},hashes", snapshot["id"]],
        cwd=initialized_archive,
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    records = parse_jsonl_output(result.stdout)
    custom_result = next(
        record for record in records if record.get("type") == "ArchiveResult" and record.get("plugin") == custom_plugin_name
    )
    hashes_result = next(record for record in records if record.get("type") == "ArchiveResult" and record.get("plugin") == "hashes")
    assert custom_result["status"] == ArchiveResult.StatusChoices.SUCCEEDED, custom_result
    assert custom_result["output_str"] == "2 URLs parsed"
    assert hashes_result["status"] == ArchiveResult.StatusChoices.SUCCEEDED, hashes_result

    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot["id"])
    assert snapshot_dir is not None
    urls_path = snapshot_dir / custom_plugin_name / "urls.jsonl"
    hashes_path = snapshot_dir / "hashes" / "hashes.json"
    assert urls_path.is_file()
    assert hashes_path.is_file()
    assert {record["url"] for record in parse_jsonl_output(urls_path.read_text(encoding="utf-8"))} == {
        "https://example.com",
        "https://example.org",
    }

    with use_archivebox_db(initialized_archive):
        archiveresults = {
            row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot["id"], plugin__in=(custom_plugin_name, "hashes"))
        }

    assert set(archiveresults) == {custom_plugin_name, "hashes"}
    assert archiveresults[custom_plugin_name].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults[custom_plugin_name].output_files["urls.jsonl"]["size"] == urls_path.stat().st_size
    assert archiveresults["hashes"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["hashes"].output_files["hashes.json"]["size"] == hashes_path.stat().st_size


def test_extract_preserves_snapshot_count(archive_with_extractors):
    """Extract queues work without creating duplicate snapshots."""
    initialized_archive = archive_with_extractors
    env = cli_env(PLUGINS="wget,title")

    create_result = run_archivebox_cmd(
        ["snapshot", "create", "https://example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    snapshot = next(record for record in parse_jsonl_output(create_result.stdout) if record.get("type") == "Snapshot")

    with use_archivebox_db(initialized_archive):
        count_before = Snapshot.objects.count()

    result = run_archivebox_cmd(
        ["extract", "--plugins=wget,title", snapshot["id"]],
        cwd=initialized_archive,
        env=env,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        count_after = Snapshot.objects.count()
        archiveresults = {row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot["id"], plugin__in=("wget", "title"))}

    assert count_after == count_before
    records = parse_jsonl_output(result.stdout)
    result_records = {
        record["plugin"]: record
        for record in records
        if record.get("type") == "ArchiveResult"
        and record.get("snapshot_id") == snapshot["id"]
        and record.get("plugin") in {"wget", "title"}
    }
    assert set(result_records) == {"wget", "title"}, records
    assert result_records["title"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["title"]["output_str"] == "Example Domain"
    assert result_records["wget"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["wget"]["output_str"] == "wget/example.com/index.html"
    snapshot_dir = find_snapshot_dir(initialized_archive, snapshot["id"])
    assert snapshot_dir is not None
    title_path = snapshot_dir / "title" / "title.txt"
    wget_path = snapshot_dir / "wget" / "example.com" / "index.html"
    warc_files = list((snapshot_dir / "wget" / "warc").glob("*.warc.gz"))
    assert title_path.is_file()
    assert wget_path.is_file()
    assert warc_files
    assert title_path.read_text(encoding="utf-8").strip() == "Example Domain"
    assert "Example Domain" in wget_path.read_text(encoding="utf-8")
    assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["title"].output_str == "Example Domain"
    assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
    assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["wget"].output_str == "wget/example.com/index.html"
    assert archiveresults["wget"].output_files["example.com/index.html"]["size"] == wget_path.stat().st_size
