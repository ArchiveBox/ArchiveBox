"""Capture queues keep running work and isolate schedules and manual requests."""

import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import sys

import pytest

import yaml


ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_gallery_keeps_running_captures_and_only_replaces_waiting_pushes():
    capture = workflow("screenshots.yml")
    assert capture["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}-${{ github.event_name == 'workflow_dispatch' && format('manual-{0}-{1}', inputs.plugin_revision != '' && 'plugin-capture' || 'default', github.run_id) || github.event_name == 'schedule' && 'scheduled' || 'default' }}",
        "cancel-in-progress": "false",
    }
    assert set(capture["on"]) == {"push", "schedule", "workflow_dispatch"}
    assert capture["jobs"]["deploy"]["concurrency"] == {
        "group": "gallery-provider-capture-${{ github.ref }}",
        "cancel-in-progress": "false",
        "queue": "max",
    }


def test_gallery_artifact_still_requires_successful_exact_revision_validation():
    jobs = workflow("screenshots.yml")["jobs"]
    assemble = jobs["assemble"]
    assert assemble["needs"] == ["deploy", "public_recipes"]
    assert assemble["if"] == "inputs.plugin_revision == ''"
    assert assemble.get("continue-on-error", "false") == "false"

    public = jobs["public_recipes"]
    assembler = runpy.run_path(ROOT / "bin/assemble_screenshot_gallery.py")
    matrix = public["strategy"]["matrix"]["include"]
    assert {item["lane"]: tuple(item["plugins"].split(",")) for item in matrix} == assembler["PUBLIC_LANES"]
    assert len(matrix) == 11
    assert "environment" not in public
    assert "secrets." not in str(public)
    assert "inputs.plugin_revision == ''" in public["if"]
    public_upload = next(step for step in public["steps"] if step.get("name") == "Upload anonymous capture shard")
    assert public_upload["with"]["name"] == "gallery-capture-${{ github.run_attempt }}-${{ matrix.lane }}"
    base_upload = next(step for step in jobs["deploy"]["steps"] if step.get("name") == "Upload native base capture shard")
    assert base_upload["if"] == "inputs.plugin_revision == ''"
    assert base_upload["with"]["name"] == "gallery-capture-${{ github.run_attempt }}-base"
    protected = jobs["deploy"]
    assert protected["environment"] == "provider-capture"
    provider_step = next(step for step in protected["steps"] if step.get("name") == "Capture optional protected providers independently")
    assert provider_step["if"] == "inputs.plugin_revision == ''"
    assert provider_step["env"]["AUTH_STORAGE_FILE"] == "${{ runner.temp }}/provider-auth.json"
    assert "secrets." not in str(provider_step)
    assert "for provider in canva figma miro" in provider_step["run"]
    assert 'UI_SCREENSHOT_PLUGINS="$provider"' in provider_step["run"]
    assert provider_step.get("continue-on-error", "false") == "false"
    assert "UI_SCREENSHOT_ALLOW_PARTIAL" not in provider_step["run"]
    assert 'test -s "$AUTH_STORAGE_FILE"' in provider_step["run"]
    assert '[[ "$rc" != 42 || ! -f "$work/unavailable" || "$(cat "$work/unavailable")" != "$provider" ]]' in provider_step["run"]
    collector = (ROOT / "bin/collect_ui_screenshots.sh").read_text()
    assert 'sealed and states <= {"noresults", "failed"} and (provider_failed or owned_target_lost)' in collector
    assert 'plugin="chrome", hook_name="on_Snapshot__01_chrome_tab.daemon.bg", status="failed"' in collector
    assert 'Q(process__stderr__contains="tab closed unexpectedly!")' in collector
    assert "exit 42" in collector
    provider_upload = next(step for step in protected["steps"] if step.get("name") == "Upload protected provider outcomes")
    assert provider_upload["with"]["name"] == "gallery-capture-${{ github.run_attempt }}-protected-providers"
    download = next(step for step in assemble["steps"] if step.get("uses", "").startswith("actions/download-artifact@"))
    assert download["with"]["pattern"] == "gallery-capture-${{ github.run_attempt }}-*"
    assert "run-id" not in download["with"]

    # Explicit plugin captures still validate/upload directly. Normal captures
    # publish only after all same-attempt shards are assembled and validated.
    for job, build_name, condition in (
        (jobs["deploy"], "Build UI screenshot gallery", "inputs.plugin_revision != ''"),
        (assemble, "Assemble and render the complete gallery", "success()"),
    ):
        steps = job["steps"]
        names = [step.get("name") for step in steps]
        build = names.index(build_name)
        validate = names.index("Verify gallery was generated from this exact revision")
        upload = names.index("Save validated screenshots")
        assert build < validate < upload
        assert all(step.get("continue-on-error", "false") == "false" for step in (steps[build], steps[validate], steps[upload]))
        assert steps[validate].get("if", "success()") == steps[upload].get("if", "success()") == condition
        assert 'provenance["revision"] == os.environ["GITHUB_SHA"]' in steps[validate]["run"]
        assert 'provenance["version"] == version' in steps[validate]["run"]
        assert 'provenance["capture_count"] >= 3 * 35' in steps[validate]["run"]
        assert steps[upload]["with"]["name"] == "site-screenshots"
        assert steps[upload]["with"]["if-no-files-found"] == "error"


def test_pages_publication_stays_serialized_and_rejects_cancelled_captures():
    pages = workflow("deploy-publicsite.yml")
    assert pages["concurrency"] == {
        "group": "pages-${{ github.event_name == 'pull_request' && github.ref || 'production' }}",
        "cancel-in-progress": "false",
    }
    assert pages["jobs"]["build"]["if"] == ("github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'")


def test_anonymous_gallery_batches_keep_all_required_native_views(monkeypatch):
    monkeypatch.delenv("UI_SCREENSHOT_PLUGINS", raising=False)
    planner = runpy.run_path(ROOT / "bin/generate_ui_screenshot_gallery.py")["plugin_screenshot_plan"]
    assembler = runpy.run_path(ROOT / "bin/assemble_screenshot_gallery.py")
    plan = planner()
    recipes = assembler["recipes"]
    full = set(recipes(plan, False))
    base = set(recipes(plan, True))
    optional = assembler["OPTIONAL_PROVIDER_VIEWS"]
    assert set(optional) == {"canva", "figma", "miro"}
    assert {recipe for recipe in full - base if recipe.split("|")[0] in optional} == {
        f"{provider}|{plan['overrides'][provider]['url']}" for provider in optional
    }
    moved = {recipe for recipe in full - base if recipe.split("|")[0] not in optional}
    assert len(moved) == 22  # Five singleton, 15 compound and two browser automation visits.
    assert len(set().union(*assembler["PUBLIC_VIEWS"].values())) == 24
    assert {"Model preview (STL)", "Model preview (3MF)", "Model preview (GLB)"} <= assembler["PUBLIC_VIEWS"]["cad"]
    assert "Snapshot View (opendataloader)" in assembler["PUBLIC_VIEWS"]["documents"]
    automation = assembler["PUBLIC_LANES"]["browser-automation"]
    assert assembler["PUBLIC_VIEWS"]["browser-automation"] == {f"Snapshot View ({plugin})" for plugin in automation}
    assert {recipe for recipe in moved if recipe.split("|")[0] in automation} == {
        f"{plugin}|https://pirate.github.io/stress-tests/challenge.html?plugin={plugin}" for plugin in automation
    }
    for plugin in automation:
        override = plan["overrides"][plugin]
        assert override["output_plugin"] == "screenshot"
        config = override["config_overrides"]
        assert config.keys() == {f"{plugin.upper()}_SCRIPT", f"{plugin.upper()}_TIMEOUT"}
        assert config[f"{plugin.upper()}_SCRIPT"]
        assert [example["plugins"] for example in plan["examples"] if example["url"] == override["url"]] == [[plugin]]

    # Whole source groups, including the same PDF visited for both extractors,
    # must reproduce the locked full plan. A newly coupled protected provider fails.
    recipe = next(item for item in plan["examples"] if "opendataloader" in item["plugins"])
    assert set(recipe["plugins"]) == {"liteparse", "opendataloader"}
    recipe["plugins"].append("canva")
    with pytest.raises(ValueError, match="split a native source"):
        list(recipes(plan, True))


def test_optional_gallery_artifact_is_only_same_build_complete_captures(tmp_path):
    assembler = runpy.run_path(ROOT / "bin/assemble_screenshot_gallery.py")
    generator = runpy.run_path(ROOT / "bin/generate_ui_screenshot_gallery.py")
    root = tmp_path / "shards"
    root.mkdir()
    env = {**os.environ, "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12", "GITHUB_RUN_ATTEMPT": "1"}
    env.pop("UI_SCREENSHOT_ALLOW_PARTIAL", None)
    env.pop("UI_SCREENSHOT_PLUGINS", None)
    pins = {name: assembler["version"](name) for name in ("abx-plugins", "abx-dl", "abxpkg", "abxbus")}
    identity = {key: env[key] for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")} | {"pins": pins}
    views = {name for lane_views in assembler["PUBLIC_VIEWS"].values() for name in lane_views}
    optional = assembler["OPTIONAL_PROVIDER_VIEWS"]
    plan = generator["plugin_screenshot_plan"]()
    required = generator["REQUIRED_VIEW_NAMES"] | set(plan["required"])
    base = required - views - set(optional.values())

    def bundle(directory, lane, names):
        directory.mkdir()
        rows, files = [], {}
        for name in sorted(names):
            slug = generator["re"].sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            for profile, (width, height) in assembler["PROFILES"].items():
                filename = f"{slug}-{profile}.png"
                # This fixture exercises transport, not browser screenshot generation.
                data = assembler["PNG_HEADER"] + b"\0" * 8 + struct.pack(">II", width, height)
                (directory / filename).write_bytes(data)
                files[filename] = hashlib.sha256(data).hexdigest()
                rows.append(
                    dict(
                        name=name,
                        url="https://example.invalid/",
                        source="test",
                        profile=profile,
                        filename=filename,
                        width=width,
                        height=height,
                        ttfb_ms=None,
                    ),
                )
        (directory / "capture.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        (directory / "receipt.json").write_text(json.dumps(dict(identity=identity, lane=lane, files=files)))

    for lane, names in {"base": base, **assembler["PUBLIC_VIEWS"]}.items():
        bundle(root / f"gallery-capture-1-{lane}", lane, names)
    protected = root / "gallery-capture-1-protected-providers"
    protected.mkdir()
    status = {"canva": "captured", "figma": "unavailable", "miro": "captured"}
    (protected / "status.json").write_text(json.dumps(dict(identity=identity, status=status)))
    for provider in ("canva", "miro"):
        bundle(protected / provider, provider, {optional[provider]})
    manifest, outcomes = tmp_path / "gallery.jsonl", tmp_path / "outcomes.json"

    def merge(output):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "bin/assemble_screenshot_gallery.py"),
                "merge",
                str(root),
                str(output),
                str(manifest),
                "--provider-status-out",
                str(outcomes),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )

    output = tmp_path / "screenshots"
    valid = merge(output)
    assert valid.returncode == 0, valid.stderr
    assert json.loads(outcomes.read_text()) == status
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bin/generate_ui_screenshot_gallery.py"),
            "build",
            str(manifest),
            str(tmp_path / "Screenshots.md"),
            str(output / "index.html"),
            str(outcomes),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert render.returncode == 0, render.stderr
    build = json.loads((output / "build.json").read_text())
    assert build["revision"] == env["GITHUB_SHA"]
    assert build["optional_provider_captures"] == status
    assert "snapshot-view-canva-desktop.png" in build["files"]
    assert not any(name.startswith("snapshot-view-figma-") for name in build["files"])
    assert "Optional provider screenshots unavailable in this capture: Figma." in (output / "index.html").read_text()

    required_png = root / "gallery-capture-1-git/snapshot-view-git-desktop.png"
    original_png = required_png.read_bytes()
    required_png.unlink()
    assert "Missing or invalid PNG" in merge(tmp_path / "missing-required-png").stderr
    required_png.write_bytes(b"corrupt")
    assert "Invalid capture dimensions or checksum" in merge(tmp_path / "invalid-required-png").stderr
    required_png.write_bytes(original_png)
    shutil.rmtree(root / "gallery-capture-1-git")
    assert "Unexpected or missing capture artifacts" in merge(tmp_path / "missing-required").stderr
    bundle(root / "gallery-capture-1-git", "git", assembler["PUBLIC_VIEWS"]["git"])
    bundle(protected / "figma", "figma", {optional["figma"]})
    assert "artifacts disagree with recorded outcomes" in merge(tmp_path / "unavailable-with-files").stderr
    shutil.rmtree(protected / "figma")
    (protected / "canva" / "snapshot-view-canva-desktop.png").unlink()
    assert "Missing or invalid PNG" in merge(tmp_path / "incomplete-provider").stderr
    (protected / "status.json").write_text(json.dumps(dict(identity=identity | {"GITHUB_SHA": "b" * 40}, status=status)))
    assert "Mixed optional provider provenance" in merge(tmp_path / "mixed-revision").stderr
