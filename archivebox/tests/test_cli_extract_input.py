"""Tests for archivebox extract input handling and pipelines."""

import json
import subprocess

import pytest

from archivebox.core.models import ArchiveResult, Snapshot
from archivebox.tests.conftest import cli_env, find_snapshot_dir, parse_jsonl_output, run_archivebox_cmd

from archivebox.tests.test_orm_helpers import use_archivebox_db

pytestmark = pytest.mark.django_db(transaction=True)


def create_extract_snapshot(initialized_archive, env, url="https://example.com"):
    run_archivebox_cmd(
        ["snapshot", "create", url],
        cwd=initialized_archive,
        env=env,
        check=True,
    )


def test_extract_archiveresult_record_queues_one_plugin_result(initialized_archive):
    env = cli_env(PLUGINS="archivewebpage")
    create_extract_snapshot(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        snapshot_id = Snapshot.objects.values_list("id", flat=True).first()

    hook_name = "on_Snapshot__65_archivewebpage_stop"
    request = json.dumps(
        {
            "type": "ArchiveResult",
            "snapshot_id": str(snapshot_id),
            "plugin": "archivewebpage",
            "hook_name": hook_name,
            "status": "queued",
        },
    )
    result = run_archivebox_cmd(
        ["extract", "--no-wait"],
        cwd=initialized_archive,
        input=f"{request}\n",
        env=env,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    with use_archivebox_db(initialized_archive):
        rows = list(
            ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin="archivewebpage").values_list("hook_name", "status"),
        )
    assert rows == [("", ArchiveResult.StatusChoices.QUEUED)]


def test_extract_runs_on_snapshot_id(initialized_archive):
    """Test that extract command accepts a snapshot ID."""
    env = cli_env(PLUGINS="wget,title")
    create_extract_snapshot(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        snapshot_id = Snapshot.objects.values_list("id", flat=True).first()

    # Run extract on the snapshot
    result = run_archivebox_cmd(
        ["extract", "--plugins=wget,title", str(snapshot_id)],
        cwd=initialized_archive,
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    records = parse_jsonl_output(result.stdout)
    result_records = {
        record["plugin"]: record
        for record in records
        if record.get("type") == "ArchiveResult"
        and record.get("snapshot_id") == str(snapshot_id)
        and record.get("plugin") in {"wget", "title"}
    }
    assert set(result_records) == {"wget", "title"}, records
    assert result_records["title"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["title"]["output_str"] == "Example Domain"
    assert result_records["wget"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["wget"]["output_str"] == "wget/example.com/index.html"
    with use_archivebox_db(initialized_archive):
        archiveresults = {row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin__in=("wget", "title"))}
    snapshot_dir = find_snapshot_dir(initialized_archive, str(snapshot_id))
    assert snapshot_dir is not None
    title_path = snapshot_dir / "title" / "title.txt"
    wget_path = snapshot_dir / "wget" / "example.com" / "index.html"
    assert title_path.is_file()
    assert wget_path.is_file()
    assert title_path.read_text(encoding="utf-8").strip() == "Example Domain"
    assert "Example Domain" in wget_path.read_text(encoding="utf-8")
    assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["title"].output_str == "Example Domain"
    assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
    assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["wget"].output_str == "wget/example.com/index.html"
    assert archiveresults["wget"].output_files["example.com/index.html"]["size"] == wget_path.stat().st_size


def test_extract_with_enabled_extractor_creates_archiveresult(initialized_archive):
    """Test that extract creates ArchiveResult when extractor is enabled."""
    env = cli_env(PLUGINS="wget,title")
    create_extract_snapshot(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        snapshot_id = Snapshot.objects.values_list("id", flat=True).first()

    # Run extract with title extractor enabled
    env = env.copy()
    result = run_archivebox_cmd(
        ["extract", "--plugins=wget,title", str(snapshot_id)],
        cwd=initialized_archive,
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    records = parse_jsonl_output(result.stdout)
    result_records = {
        record["plugin"]: record
        for record in records
        if record.get("type") == "ArchiveResult"
        and record.get("snapshot_id") == str(snapshot_id)
        and record.get("plugin") in {"wget", "title"}
    }
    assert set(result_records) == {"wget", "title"}, records
    assert result_records["title"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["title"]["output_str"] == "Example Domain"
    assert result_records["wget"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["wget"]["output_str"] == "wget/example.com/index.html"
    with use_archivebox_db(initialized_archive):
        archiveresults = {row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin__in=("wget", "title"))}
    snapshot_dir = find_snapshot_dir(initialized_archive, str(snapshot_id))
    assert snapshot_dir is not None
    title_path = snapshot_dir / "title" / "title.txt"
    wget_path = snapshot_dir / "wget" / "example.com" / "index.html"
    assert title_path.is_file()
    assert wget_path.is_file()
    assert title_path.read_text(encoding="utf-8").strip() == "Example Domain"
    assert "Example Domain" in wget_path.read_text(encoding="utf-8")
    assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["title"].output_str == "Example Domain"
    assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
    assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["wget"].output_str == "wget/example.com/index.html"
    assert archiveresults["wget"].output_files["example.com/index.html"]["size"] == wget_path.stat().st_size


def test_extract_plugin_option_accepted(initialized_archive):
    """Test that --plugin option is accepted."""
    env = cli_env(PLUGINS="wget,title")
    create_extract_snapshot(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        snapshot_id = Snapshot.objects.values_list("id", flat=True).first()

    result = run_archivebox_cmd(
        ["extract", "--plugins=wget,title", str(snapshot_id)],
        cwd=initialized_archive,
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    records = parse_jsonl_output(result.stdout)
    result_records = {
        record["plugin"]: record
        for record in records
        if record.get("type") == "ArchiveResult"
        and record.get("snapshot_id") == str(snapshot_id)
        and record.get("plugin") in {"wget", "title"}
    }
    assert set(result_records) == {"wget", "title"}, records
    assert result_records["title"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["title"]["output_str"] == "Example Domain"
    assert result_records["wget"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["wget"]["output_str"] == "wget/example.com/index.html"
    with use_archivebox_db(initialized_archive):
        archiveresults = {row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin__in=("wget", "title"))}
    snapshot_dir = find_snapshot_dir(initialized_archive, str(snapshot_id))
    assert snapshot_dir is not None
    title_path = snapshot_dir / "title" / "title.txt"
    wget_path = snapshot_dir / "wget" / "example.com" / "index.html"
    assert title_path.is_file()
    assert wget_path.is_file()
    assert title_path.read_text(encoding="utf-8").strip() == "Example Domain"
    assert "Example Domain" in wget_path.read_text(encoding="utf-8")
    assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["title"].output_str == "Example Domain"
    assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
    assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["wget"].output_str == "wget/example.com/index.html"
    assert archiveresults["wget"].output_files["example.com/index.html"]["size"] == wget_path.stat().st_size


def test_extract_stdin_snapshot_id(initialized_archive):
    """Test that extract reads snapshot IDs from stdin."""
    env = cli_env(PLUGINS="wget,title")
    create_extract_snapshot(initialized_archive, env)

    with use_archivebox_db(initialized_archive):
        snapshot_id = Snapshot.objects.values_list("id", flat=True).first()

    result = run_archivebox_cmd(
        ["extract", "--plugins=wget,title"],
        cwd=initialized_archive,
        input=f"{snapshot_id}\n",
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    records = parse_jsonl_output(result.stdout)
    result_records = {
        record["plugin"]: record
        for record in records
        if record.get("type") == "ArchiveResult"
        and record.get("snapshot_id") == str(snapshot_id)
        and record.get("plugin") in {"wget", "title"}
    }
    assert set(result_records) == {"wget", "title"}, records
    assert result_records["title"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["title"]["output_str"] == "Example Domain"
    assert result_records["wget"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["wget"]["output_str"] == "wget/example.com/index.html"
    with use_archivebox_db(initialized_archive):
        archiveresults = {row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin__in=("wget", "title"))}
    snapshot_dir = find_snapshot_dir(initialized_archive, str(snapshot_id))
    assert snapshot_dir is not None
    title_path = snapshot_dir / "title" / "title.txt"
    wget_path = snapshot_dir / "wget" / "example.com" / "index.html"
    assert title_path.is_file()
    assert wget_path.is_file()
    assert title_path.read_text(encoding="utf-8").strip() == "Example Domain"
    assert "Example Domain" in wget_path.read_text(encoding="utf-8")
    assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["title"].output_str == "Example Domain"
    assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
    assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["wget"].output_str == "wget/example.com/index.html"
    assert archiveresults["wget"].output_files["example.com/index.html"]["size"] == wget_path.stat().st_size


def test_extract_stdin_jsonl_input(initialized_archive):
    """Test that extract reads JSONL records from stdin."""
    env = cli_env(PLUGINS="wget,title")
    create_extract_snapshot(initialized_archive, env)

    list_result = run_archivebox_cmd(
        ["snapshot", "list", "--url__icontains=example.com"],
        cwd=initialized_archive,
        env=env,
        check=True,
    )
    snapshot_record = next(record for record in parse_jsonl_output(list_result.stdout) if record.get("type") == "Snapshot")
    snapshot_id = snapshot_record["id"]

    result = run_archivebox_cmd(
        ["extract", "--plugins=wget,title"],
        cwd=initialized_archive,
        input=list_result.stdout,
        env=env,
        timeout=90,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    records = parse_jsonl_output(result.stdout)
    result_records = {
        record["plugin"]: record
        for record in records
        if record.get("type") == "ArchiveResult"
        and record.get("snapshot_id") == str(snapshot_id)
        and record.get("plugin") in {"wget", "title"}
    }
    assert set(result_records) == {"wget", "title"}, records
    assert result_records["title"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["title"]["output_str"] == "Example Domain"
    assert result_records["wget"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["wget"]["output_str"] == "wget/example.com/index.html"
    with use_archivebox_db(initialized_archive):
        archiveresults = {row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin__in=("wget", "title"))}
    snapshot_dir = find_snapshot_dir(initialized_archive, str(snapshot_id))
    assert snapshot_dir is not None
    title_path = snapshot_dir / "title" / "title.txt"
    wget_path = snapshot_dir / "wget" / "example.com" / "index.html"
    assert title_path.is_file()
    assert wget_path.is_file()
    assert title_path.read_text(encoding="utf-8").strip() == "Example Domain"
    assert "Example Domain" in wget_path.read_text(encoding="utf-8")
    assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["title"].output_str == "Example Domain"
    assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
    assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["wget"].output_str == "wget/example.com/index.html"
    assert archiveresults["wget"].output_files["example.com/index.html"]["size"] == wget_path.stat().st_size


def test_extract_pipeline_from_snapshot(initialized_archive):
    """Test piping snapshot output to extract."""
    env = cli_env(PLUGINS="wget,title")

    result = subprocess.run(
        ["bash", "-lc", "set -o pipefail; archivebox snapshot create https://example.com | archivebox extract --plugins=wget,title"],
        cwd=initialized_archive,
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    with use_archivebox_db(initialized_archive):
        snapshot = Snapshot.objects.filter(url="https://example.com").first()

    assert snapshot is not None, "Snapshot should be created by pipeline"
    records = parse_jsonl_output(result.stdout)
    result_records = {
        record["plugin"]: record
        for record in records
        if record.get("type") == "ArchiveResult"
        and record.get("snapshot_id") == str(snapshot.id)
        and record.get("plugin") in {"wget", "title"}
    }
    assert set(result_records) == {"wget", "title"}, records
    assert result_records["title"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["title"]["output_str"] == "Example Domain"
    assert result_records["wget"]["status"] == ArchiveResult.StatusChoices.SUCCEEDED
    assert result_records["wget"]["output_str"] == "wget/example.com/index.html"
    with use_archivebox_db(initialized_archive):
        archiveresults = {row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot.id, plugin__in=("wget", "title"))}
    snapshot_dir = find_snapshot_dir(initialized_archive, str(snapshot.id))
    assert snapshot_dir is not None
    title_path = snapshot_dir / "title" / "title.txt"
    wget_path = snapshot_dir / "wget" / "example.com" / "index.html"
    assert title_path.is_file()
    assert wget_path.is_file()
    assert title_path.read_text(encoding="utf-8").strip() == "Example Domain"
    assert "Example Domain" in wget_path.read_text(encoding="utf-8")
    assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["title"].output_str == "Example Domain"
    assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
    assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
    assert archiveresults["wget"].output_str == "wget/example.com/index.html"
    assert archiveresults["wget"].output_files["example.com/index.html"]["size"] == wget_path.stat().st_size


def test_extract_multiple_snapshots(initialized_archive):
    """Test extracting from multiple snapshots."""
    env = cli_env(PLUGINS="wget,title")

    create_extract_snapshot(initialized_archive, env, "https://example.com")
    create_extract_snapshot(initialized_archive, env, "https://example.org")

    with use_archivebox_db(initialized_archive):
        snapshot_ids = list(Snapshot.objects.values_list("id", flat=True))

    assert len(snapshot_ids) >= 2, "Should have at least 2 snapshots"

    # Extract from all snapshots
    ids_input = "\n".join(str(snapshot_id) for snapshot_id in snapshot_ids) + "\n"
    result = run_archivebox_cmd(
        ["extract", "--plugins=wget,title"],
        cwd=initialized_archive,
        input=ids_input,
        env=env,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr

    with use_archivebox_db(initialized_archive):
        count = Snapshot.objects.count()
        result_rows = list(ArchiveResult.objects.filter(plugin__in=("wget", "title")).values_list("snapshot_id", "plugin", "status"))

    assert count >= 2, "Both snapshots should still exist after extraction"
    assert len(result_rows) == len(snapshot_ids) * 2
    assert {(snapshot_id, plugin) for snapshot_id, plugin, _status in result_rows} == {
        (snapshot_id, plugin) for snapshot_id in snapshot_ids for plugin in ("wget", "title")
    }
    assert all(status == ArchiveResult.StatusChoices.SUCCEEDED for _snapshot_id, _plugin, status in result_rows)
    for snapshot_id in snapshot_ids:
        with use_archivebox_db(initialized_archive):
            snapshot = Snapshot.objects.get(id=snapshot_id)
            archiveresults = {
                row.plugin: row for row in ArchiveResult.objects.filter(snapshot_id=snapshot_id, plugin__in=("wget", "title"))
            }
        snapshot_dir = find_snapshot_dir(initialized_archive, str(snapshot_id))
        assert snapshot_dir is not None
        title_path = snapshot_dir / "title" / "title.txt"
        domain = snapshot.url.split("://", 1)[1].rstrip("/")
        wget_path = snapshot_dir / "wget" / domain / "index.html"
        assert title_path.is_file()
        assert wget_path.is_file()
        assert title_path.read_text(encoding="utf-8").strip() == archiveresults["title"].output_str
        assert "<html" in wget_path.read_text(encoding="utf-8").lower()
        assert archiveresults["title"].status == ArchiveResult.StatusChoices.SUCCEEDED
        assert archiveresults["title"].output_str
        assert archiveresults["title"].output_files["title.txt"]["size"] == title_path.stat().st_size
        assert archiveresults["wget"].status == ArchiveResult.StatusChoices.SUCCEEDED
        assert archiveresults["wget"].output_str == f"wget/{domain}/index.html"
        assert archiveresults["wget"].output_files[f"{domain}/index.html"]["size"] == wget_path.stat().st_size


class TestExtractCLI:
    """Test the CLI interface for extract command."""

    def test_cli_help(self, initialized_archive):
        """Test that --help works for extract command."""

        result = run_archivebox_cmd(
            ["extract", "--help"],
        )

        assert result.returncode == 0
        assert "--plugin" in result.stdout or "-p" in result.stdout
        assert "--wait" in result.stdout or "--no-wait" in result.stdout

    def test_cli_no_snapshots_shows_warning(self, initialized_archive):
        """Test that running without snapshots shows a warning."""

        result = run_archivebox_cmd(
            ["extract"],
            input="",
        )

        assert result.returncode == 1
        assert "No" in result.stderr
