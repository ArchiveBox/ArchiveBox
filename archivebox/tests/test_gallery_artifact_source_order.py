"""Capture freshness is immutable Core ancestry, not completion time."""

import hashlib
import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


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


OPTIONAL_OUTCOMES = {"canva": "captured", "figma": "unavailable", "miro": "captured"}
OPTIONAL_PROFILES = ("desktop", "tablet", "mobile")


def write_provider_artifact(directory, outcomes, *, omit=None, stale=None):
    (directory / "index.html").write_text("<main>Gallery fixture</main>")
    files = {}
    names = ["navigation-tools-menu-desktop.png"]
    for provider in ("canva", "miro"):
        names.extend(f"snapshot-view-{provider}-{profile}.png" for profile in OPTIONAL_PROFILES)
    for name in names:
        if name == omit:
            continue
        content = name.encode()
        (directory / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()
    if stale:
        (directory / stale).write_bytes(b"unreferenced old screenshot")
    manifest = {"revision": "a" * 40, "capture_count": len(files), "files": files, "optional_provider_captures": outcomes}
    (directory / "build.json").write_text(json.dumps(manifest))
    return manifest


def test_restore_accepts_one_omitted_provider_and_keeps_complete_current_providers(tmp_path):
    manifest = write_provider_artifact(tmp_path, OPTIONAL_OUTCOMES)
    assert RESTORE["validate"](tmp_path, {"head_sha": "a" * 40}) == manifest
    assert all("figma" not in image for image in manifest["files"])


@pytest.mark.parametrize(
    "outcomes",
    [
        None,
        ["canva", "figma", "miro"],
        {"canva": "captured", "figma": "unavailable"},
        {**OPTIONAL_OUTCOMES, "icloud": "unavailable"},
        {**OPTIONAL_OUTCOMES, "figma": "failed selector: provider detail"},
    ],
)
def test_restore_rejects_malformed_optional_provider_metadata(tmp_path, outcomes):
    write_provider_artifact(tmp_path, outcomes)
    with pytest.raises(ValueError, match="Invalid optional provider capture outcomes"):
        RESTORE["validate"](tmp_path)


def test_restore_rejects_partial_capture_or_unlisted_stale_provider_bytes(tmp_path):
    write_provider_artifact(tmp_path, OPTIONAL_OUTCOMES, omit="snapshot-view-miro-mobile.png")
    with pytest.raises(ValueError, match="Incomplete optional provider capture: miro"):
        RESTORE["validate"](tmp_path)
    write_provider_artifact(tmp_path, OPTIONAL_OUTCOMES, stale="snapshot-view-figma-desktop.png")
    with pytest.raises(ValueError, match="Unavailable provider includes screenshot files: figma"):
        RESTORE["validate"](tmp_path)


def test_pages_overlay_cannot_restore_omitted_provider_from_tracked_old_png(tmp_path):
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-publicsite.yml").read_text())
    step = next(step for step in workflow["jobs"]["build"]["steps"] if step.get("name") == "Keep manually captured screenshots")
    opening, *body, closing = step["run"].strip().splitlines()
    assert opening.endswith("<<'PY'") and closing == "PY"
    python = "\n".join(body)
    git(tmp_path, "init", "-b", "dev")
    screenshots = tmp_path / "publicsite/screenshots"
    screenshots.mkdir(parents=True)
    runner = tmp_path / "runner"
    manual = runner / "manual-screenshots"
    manual.mkdir(parents=True)
    for name in ("snapshot-view-figma-desktop.png", "snapshot-view-ytdlp-desktop.png"):
        source = screenshots / name
        source.write_bytes(name.encode())
        git(tmp_path, "add", str(source.relative_to(tmp_path)))
        source.rename(manual / name)
    write_provider_artifact(screenshots, OPTIONAL_OUTCOMES)
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/manual-screenshot-captures.json").write_text("{}")
    subprocess.run([sys.executable, "-c", python], cwd=tmp_path, env={**os.environ, "RUNNER_TEMP": str(runner)}, check=True)

    manifest = json.loads((screenshots / "build.json").read_text())
    assert manifest["optional_provider_captures"] == OPTIONAL_OUTCOMES
    assert "snapshot-view-figma-desktop.png" not in manifest["files"]
    assert not (screenshots / "snapshot-view-figma-desktop.png").exists()
    assert "snapshot-view-ytdlp-desktop.png" in manifest["manual_captures"]
    assert (screenshots / "snapshot-view-ytdlp-desktop.png").is_file()
    assert RESTORE["validate"](screenshots) == manifest
