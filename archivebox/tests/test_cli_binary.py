#!/usr/bin/env python3
"""
Tests for archivebox binary command.
"""

import sys

from archivebox.tests.conftest import parse_jsonl_output, run_archivebox_cmd


def test_binary_help_runs_successfully(tmp_path):
    """The binary command should be registered and expose help."""

    result = run_archivebox_cmd(["binary", "--help"])

    assert result.returncode == 0
    assert "binary" in result.stdout.lower()
    assert "list" in result.stdout


def test_binary_registration_preserves_distinct_installations(initialized_archive, tmp_path):
    # Migrated collections can contain several versions/paths of one binary.
    # Register real Python installations through the CLI without rewriting the
    # metadata referenced by earlier Processes. --version is optional.
    alternate_path = tmp_path / "python-alternate"
    alternate_path.symlink_to(sys.executable)
    version = sys.version.split()[0]
    installations = [(sys.executable, version), (str(alternate_path), version), (sys.executable, "")]
    registered = []
    for abspath, binary_version in installations:
        args = ["binary", "create", "--name=python", f"--abspath={abspath}"]
        if binary_version:
            args.append(f"--version={binary_version}")
        result = run_archivebox_cmd(args, cwd=initialized_archive)
        assert result.returncode == 0, result.stderr
        records = [record for record in parse_jsonl_output(result.stdout) if record.get("type") == "Binary"]
        assert len(records) == 1, result.stdout + result.stderr
        record = records[0]
        assert record["abspath"] == abspath
        assert record["version"] == binary_version
        assert record["status"] == "installed"
        registered.append(record)

    assert len({record["id"] for record in registered}) == len(installations)
    result = run_archivebox_cmd(
        ["binary", "create", "--name=python", f"--abspath={sys.executable}", f"--version={version}"],
        cwd=initialized_archive,
    )
    assert result.returncode == 0, result.stderr
    record = next(record for record in parse_jsonl_output(result.stdout) if record.get("type") == "Binary")
    assert record["id"] == registered[0]["id"]
    result = run_archivebox_cmd(["binary", "list", "--name=python"], cwd=initialized_archive)
    assert result.returncode == 0, result.stderr
    rows = [record for record in parse_jsonl_output(result.stdout) if record.get("type") == "Binary"]
    assert {(row["id"], row["abspath"], row["version"]) for row in rows} == {
        (row["id"], row["abspath"], row["version"]) for row in registered
    }
