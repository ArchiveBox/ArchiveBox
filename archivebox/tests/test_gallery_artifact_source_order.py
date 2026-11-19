"""Capture freshness is immutable Core ancestry, not completion time."""

import hashlib
import json
import runpy
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RESTORE = runpy.run_path(str(ROOT / "bin/restore_site_screenshots.py"))
ARTIFACTS = runpy.run_path(str(ROOT / ".github/pages/artifacts.py"))


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo, message):
    git(repo, "-c", "user.name=Gallery Test", "-c", "user.email=gallery@example.invalid", "commit", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def test_older_manual_finish_cannot_replace_newer_core_capture(tmp_path):
    git(tmp_path, "init", "-b", "dev")
    old = commit(tmp_path, "older Core source")
    current = commit(tmp_path, "newer Core source")
    git(tmp_path, "checkout", "-b", "other", old)
    unrelated = commit(tmp_path, "different lineage")
    git(tmp_path, "checkout", "dev")
    ranks = RESTORE["capture_revision_order"](tmp_path)
    assert ranks == {current: 0, old: 1}
    candidates = [
        {"id": 1, "created_at": "2026-11-19T22:00:00Z", "workflow_run": {"head_sha": old}},
        {"id": 2, "created_at": "2026-11-19T20:00:00Z", "workflow_run": {"head_sha": current}},
        {"id": 3, "created_at": "2026-11-19T23:00:00Z", "workflow_run": {"head_sha": unrelated}},
        {"id": 4, "created_at": "2026-11-19T21:00:00Z", "workflow_run": {"head_sha": current}},
    ]
    assert [item["id"] for item in ARTIFACTS["ordered_candidates"](candidates, ranks)] == [4, 2, 1]
    # Other consumers keep the existing completion-time contract.
    assert [item["id"] for item in ARTIFACTS["ordered_candidates"](candidates)] == [3, 1, 4, 2]
    # Newer capture artifact expired: a later old-source manual artifact cannot
    # lower the published revision; retain the existing public capture instead.
    assert not RESTORE["capture_meets_published_floor"](old, {"revision": current}, ranks)
    assert RESTORE["capture_meets_published_floor"](current, {"revision": old}, ranks)
    assert RESTORE["capture_meets_published_floor"](current, {"revision": current}, ranks)
    with pytest.raises(ValueError, match="outside the checked-out Core lineage"):
        RESTORE["capture_meets_published_floor"](current, {"revision": unrelated}, ranks)


def test_selected_capture_still_requires_exact_source_and_bytes(tmp_path):
    content = b"owned artifact validation fixture"
    (tmp_path / "capture.png").write_bytes(content)
    (tmp_path / "index.html").write_text("owned gallery validation fixture")
    manifest = {"revision": "a" * 40, "capture_count": 1, "files": {"capture.png": hashlib.sha256(content).hexdigest()}}
    (tmp_path / "build.json").write_text(json.dumps(manifest))
    assert RESTORE["validate"](tmp_path, {"head_sha": "a" * 40}) == manifest
    with pytest.raises(ValueError, match="revision differs"):
        RESTORE["validate"](tmp_path, {"head_sha": "b" * 40})
    (tmp_path / "capture.png").write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksum mismatch"):
        RESTORE["validate"](tmp_path, {"head_sha": "a" * 40})


def test_capture_order_rejects_incomplete_history(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-b", "dev")
    commit(source, "first")
    commit(source, "second")
    clone = tmp_path / "shallow"
    git(tmp_path, "clone", "--depth=1", source.as_uri(), str(clone))
    with pytest.raises(ValueError, match="complete Git history"):
        RESTORE["capture_revision_order"](clone)
