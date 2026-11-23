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
RESTORE = runpy.run_path(str(ROOT / "bin/screenshot_gallery_helpers.py"))
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
    assert not RESTORE["capture_meets_published_floor"](old, {"revision": current}, ranks, repo_dir=tmp_path)
    assert RESTORE["capture_meets_published_floor"](current, {"revision": old}, ranks, repo_dir=tmp_path)
    assert RESTORE["capture_meets_published_floor"](current, {"revision": current}, ranks, repo_dir=tmp_path)
    with pytest.raises(ValueError, match="outside the checked-out Core lineage"):
        RESTORE["capture_meets_published_floor"](current, {"revision": unrelated}, ranks, repo_dir=tmp_path)


def test_selected_capture_still_requires_exact_source_and_bytes(tmp_path):
    content = b"owned artifact validation fixture"
    (tmp_path / "capture.png").write_bytes(content)
    (tmp_path / "index.html").write_text("owned gallery validation fixture")
    manifest = {"revision": "a" * 40, "capture_count": 1, "files": {"capture.png": hashlib.sha256(content).hexdigest()}}
    (tmp_path / "build.json").write_text(json.dumps(manifest))
    assert RESTORE["validate_published_gallery"](tmp_path, {"head_sha": "a" * 40}) == manifest
    with pytest.raises(ValueError, match="revision differs"):
        RESTORE["validate_published_gallery"](tmp_path, {"head_sha": "b" * 40})
    (tmp_path / "capture.png").write_bytes(b"modified")
    with pytest.raises(ValueError, match="checksum mismatch"):
        RESTORE["validate_published_gallery"](tmp_path, {"head_sha": "a" * 40})


def test_published_capture_survives_merging_remote_dev_as_second_parent(tmp_path):
    git(tmp_path, "init", "-b", "dev")
    base = commit(tmp_path, "common source")
    git(tmp_path, "checkout", "-b", "local-fixes")
    local = commit(tmp_path, "local fixes without published changes")
    git(tmp_path, "checkout", "dev")
    published = commit(tmp_path, "published capture source")
    git(tmp_path, "checkout", "local-fixes")
    git(
        tmp_path,
        "-c",
        "user.name=Gallery Test",
        "-c",
        "user.email=gallery@example.invalid",
        "merge",
        "--no-ff",
        "dev",
        "-m",
        "merge remote dev",
    )
    merged = git(tmp_path, "rev-parse", "HEAD")
    ranks = RESTORE["capture_revision_order"](tmp_path)
    assert set(ranks) == {base, local, published, merged}
    assert RESTORE["capture_meets_published_floor"](merged, {"revision": published}, ranks, repo_dir=tmp_path)
    assert RESTORE["capture_meets_published_floor"](published, {"revision": published}, ranks, repo_dir=tmp_path)
    assert not RESTORE["capture_meets_published_floor"](local, {"revision": published}, ranks, repo_dir=tmp_path)
    assert not RESTORE["capture_meets_published_floor"](published, {"revision": local}, ranks, repo_dir=tmp_path)


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


OPTIONAL_OUTCOMES = {"subtitle": "captured", "photobooth": "unavailable", "new-source": "captured"}
OPTIONAL_PROFILES = ("desktop", "tablet", "mobile")


def write_provider_artifact(directory, outcomes, *, omit=None, stale=None):
    (directory / "index.html").write_text("<main>Gallery fixture</main>")
    files = {}
    names = ["navigation-tools-menu-desktop.png"]
    for provider in ("subtitle", "new-source"):
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
    assert RESTORE["validate_published_gallery"](tmp_path, {"head_sha": "a" * 40}) == manifest
    assert all("photobooth" not in image for image in manifest["files"])
    assert all(f"snapshot-view-new-source-{profile}.png" in manifest["files"] for profile in OPTIONAL_PROFILES)


@pytest.mark.parametrize(
    "outcomes",
    [
        None,
        ["subtitle", "photobooth"],
        {},
        {**OPTIONAL_OUTCOMES, "../unsafe": "unavailable"},
        {**OPTIONAL_OUTCOMES, "photobooth": "failed selector: provider detail"},
    ],
)
def test_restore_rejects_malformed_optional_provider_metadata(tmp_path, outcomes):
    write_provider_artifact(tmp_path, outcomes)
    with pytest.raises(ValueError, match="Invalid optional provider capture outcomes"):
        RESTORE["validate_published_gallery"](tmp_path)


def test_restore_rejects_partial_capture_or_unlisted_stale_provider_bytes(tmp_path):
    write_provider_artifact(tmp_path, OPTIONAL_OUTCOMES, omit="snapshot-view-new-source-mobile.png")
    with pytest.raises(ValueError, match="Incomplete optional provider capture: new-source"):
        RESTORE["validate_published_gallery"](tmp_path)
    write_provider_artifact(tmp_path, OPTIONAL_OUTCOMES, stale="snapshot-view-photobooth-desktop.png")
    with pytest.raises(ValueError, match="Unavailable provider includes screenshot files: photobooth"):
        RESTORE["validate_published_gallery"](tmp_path)


MISSING_RECIPE = "recipe-" + "a" * 16
HEALTHY_RECIPE = "recipe-" + "b" * 16
GENERIC_OUTCOMES = {
    MISSING_RECIPE: {"status": "unavailable", "views": ["archive-output-photobooth"]},
    HEALTHY_RECIPE: {"status": "captured", "views": ["archive-output-subtitle"]},
}


def write_recipe_artifact(directory, outcomes, *, missing_profile=None, stale=None):
    names = ["navigation-tools-menu-desktop.png"]
    names.extend(f"archive-output-subtitle-{profile}.png" for profile in OPTIONAL_PROFILES if profile != missing_profile)
    files = {}
    for name in names:
        content = name.encode()
        (directory / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()
    if stale:
        (directory / stale).write_bytes(b"old unlisted plugin screenshot")
    manifest = {
        "revision": "a" * 40,
        "capture_count": len(files),
        "files": files,
        "optional_recipe_captures": outcomes,
    }
    (directory / "index.html").write_text("<main>Gallery fixture</main>")
    (directory / "build.json").write_text(json.dumps(manifest))
    return manifest


def test_restore_accepts_generic_plugin_outcomes_without_named_provider_rule(tmp_path):
    manifest = write_recipe_artifact(tmp_path, GENERIC_OUTCOMES)
    assert RESTORE["validate_published_gallery"](tmp_path, {"head_sha": "a" * 40}) == manifest
    assert "navigation-tools-menu-desktop.png" in manifest["files"]


@pytest.mark.parametrize(
    "outcomes",
    [
        None,
        {"provider-untyped": {"status": "unavailable", "views": ["valid"]}},
        {MISSING_RECIPE: {"status": "failure details", "views": ["valid"]}},
        {MISSING_RECIPE: {"status": "unavailable", "views": ["core/route"]}},
        {MISSING_RECIPE: {"status": "unavailable", "views": ["safe", "safe"]}},
        {MISSING_RECIPE: {"status": "unavailable", "views": ["zebra", "alpha"]}},
        {MISSING_RECIPE: {"status": "unavailable", "views": ["same"]}, HEALTHY_RECIPE: {"status": "unavailable", "views": ["same"]}},
    ],
)
def test_restore_rejects_malformed_generic_recipe_outcomes(tmp_path, outcomes):
    write_recipe_artifact(tmp_path, outcomes)
    with pytest.raises(ValueError, match="Invalid optional gallery recipe outcome"):
        RESTORE["validate_published_gallery"](tmp_path)


def test_restore_rejects_mixed_old_and_new_optional_provenance(tmp_path):
    manifest = write_recipe_artifact(tmp_path, GENERIC_OUTCOMES)
    manifest["optional_provider_captures"] = {"older-source": "unavailable"}
    (tmp_path / "build.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid optional gallery recipe outcomes"):
        RESTORE["validate_published_gallery"](tmp_path)


def test_restore_rejects_incomplete_generic_capture_or_stale_omitted_bytes(tmp_path):
    write_recipe_artifact(tmp_path, GENERIC_OUTCOMES, missing_profile="mobile")
    with pytest.raises(ValueError, match="Incomplete optional gallery recipe capture"):
        RESTORE["validate_published_gallery"](tmp_path)
    write_recipe_artifact(tmp_path, GENERIC_OUTCOMES, stale="archive-output-photobooth-desktop.png")
    with pytest.raises(ValueError, match="Unavailable gallery recipe includes screenshot files"):
        RESTORE["validate_published_gallery"](tmp_path)


@pytest.mark.parametrize("legacy", [True, False])
def test_pages_overlay_cannot_restore_omitted_view_from_tracked_old_png(tmp_path, legacy):
    omitted_view = "snapshot-view-photobooth" if legacy else "archive-output-photobooth"
    omitted_filename = f"{omitted_view}-desktop.png"
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
    for name in (omitted_filename, "snapshot-view-ytdlp-desktop.png"):
        source = screenshots / name
        source.write_bytes(name.encode())
        git(tmp_path, "add", str(source.relative_to(tmp_path)))
        source.rename(manual / name)
    if legacy:
        write_provider_artifact(screenshots, OPTIONAL_OUTCOMES)
    else:
        write_recipe_artifact(screenshots, {MISSING_RECIPE: {"status": "unavailable", "views": [omitted_view]}})
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github/manual-screenshot-captures.json").write_text("{}")
    subprocess.run([sys.executable, "-c", python], cwd=tmp_path, env={**os.environ, "RUNNER_TEMP": str(runner)}, check=True)

    manifest = json.loads((screenshots / "build.json").read_text())
    if legacy:
        assert manifest["optional_provider_captures"] == OPTIONAL_OUTCOMES
    else:
        assert manifest["optional_recipe_captures"] == {MISSING_RECIPE: {"status": "unavailable", "views": [omitted_view]}}
    assert omitted_filename not in manifest["files"]
    assert not (screenshots / omitted_filename).exists()
    assert "snapshot-view-ytdlp-desktop.png" in manifest["manual_captures"]
    assert (screenshots / "snapshot-view-ytdlp-desktop.png").is_file()
    assert RESTORE["validate_published_gallery"](screenshots) == manifest


def test_qualified_gallery_omission_only_removes_its_feature_figure_in_every_locale(tmp_path):
    import re
    import shutil

    output = tmp_path / "site"
    shutil.copytree(ROOT / "publicsite", output)
    gallery = output / "screenshots"
    available = "future-confirmed-view-desktop.png"
    missing = "future-unavailable-view-desktop.png"
    # Exercise actual localized homepage markup, but use provider-neutral names.
    replaced = "snapshot-view-tlsnotary-desktop.png"
    locales = [output / "index.html", *(output / name / "index.html" for name in ("ar", "es", "fr", "ru", "zh"))]
    for homepage in locales:
        text = homepage.read_text()
        original = next(line for line in text.splitlines() if 'class="card-shot"' in line and replaced in line)
        feature = original.replace(replaced, missing)
        healthy = feature.replace(missing, available)
        homepage.write_text(text.replace(original, feature + "\n" + healthy))
    owned = {available}
    for homepage in locales:
        text = re.sub(r"<!-- ARCHIVEBOX:MARQUEE -->.*?<!-- /ARCHIVEBOX:MARQUEE -->", "", homepage.read_text(), flags=re.DOTALL)
        owned.update(name for name in re.findall(r'src="/screenshots/([a-z0-9-]+\.png)"', text) if name != missing)
    for name in owned:
        (gallery / name).write_bytes(b"fixture screenshot")
    (gallery / "index.html").write_text(
        '<!doctype html><head><title>Gallery</title><meta name="description" content="Screenshots">'
        '<meta property="og:image" content="https://example.invalid/gallery.png">'
        '<link rel="canonical" href="https://archivebox.io/screenshots/"></head><body>'
        "<!-- ARCHIVEBOX:HEADER --><main>Qualified gallery</main><!-- ARCHIVEBOX:FOOTER-START -->"
        "<!-- ARCHIVEBOX:FOOTER-END --></body></html>",
    )
    manifest = {
        "revision": "a" * 40,
        "capture_count": len(owned),
        "files": {name: hashlib.sha256(b"fixture screenshot").hexdigest() for name in owned},
        "optional_recipe_captures": {
            "recipe-0123456789abcdef": {"status": "unavailable", "views": ["future-unavailable-view"]},
        },
    }
    (gallery / "build.json").write_text(json.dumps(manifest))
    assert RESTORE["validate_published_gallery"](gallery, {"head_sha": "a" * 40}) == manifest
    render = [sys.executable, str(ROOT / ".github/pages/site.py"), "render", str(output)]
    subprocess.run(render, check=True, capture_output=True, text=True)
    for homepage in locales:
        html = homepage.read_text()
        assert missing not in html
        assert html.count(available) == 2
        assert "ARCHIVEBOX:MARQUEE" in html
    assert json.loads((gallery / "build.json").read_text()) == manifest

    # The same omitted image outside its complete feature figure is a broken
    # dependency, not something the site renderer may silently strip.
    english = locales[0]
    english.write_text(english.read_text() + f'<img src="/screenshots/{missing}" alt="Unexpected reference">')
    failure = subprocess.run(render, capture_output=True, text=True)
    assert failure.returncode != 0
    assert f"missing local resource /screenshots/{missing}" in failure.stderr
