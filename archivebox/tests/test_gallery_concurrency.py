"""Capture queues keep running work and isolate schedules and manual requests."""

import hashlib
import json
import os
import re
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
    assembler = runpy.run_path(ROOT / "bin/screenshot_gallery_helpers.py")
    matrix = public["strategy"]["matrix"]["include"]
    assert {item["lane"]: tuple(item["plugins"].split(",")) for item in matrix} == assembler["PUBLIC_LANES"]
    assert len(matrix) == 12
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
    for job, capture_name in ((public, "Capture native public recipe"), (protected, "Build UI screenshot gallery")):
        capture = next(step for step in job["steps"] if step.get("name") == capture_name)
        assert "UI_SCREENSHOT_UNAVAILABLE_OUT" in capture["env"]
        assert capture.get("continue-on-error", "false") == "false"
    collector = (ROOT / "bin/collect_ui_screenshots.sh").read_text()
    assert "native_plugin_output_unavailable" in collector
    assert "record_supplementary_failure" in collector
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
    planner = runpy.run_path(ROOT / "bin/screenshot_gallery_helpers.py")["plugin_screenshot_plan"]
    assembler = runpy.run_path(ROOT / "bin/screenshot_gallery_helpers.py")
    plan = planner()
    recipes = assembler["recipes"]
    full = set(recipes(plan, False))
    base = set(recipes(plan, True))
    moved = full - base
    assert len(moved) == 23  # Six singleton, 15 compound and two browser automation visits.
    assert len(set().union(*assembler["PUBLIC_VIEWS"].values())) == 25
    assert {"Model preview (STL)", "Model preview (3MF)", "Model preview (GLB)"} <= assembler["PUBLIC_VIEWS"]["cad"]
    assert "Snapshot View (opendataloader)" in assembler["PUBLIC_VIEWS"]["documents"]
    # Keep the installed iWork recipe and its real PDF readiness check intact;
    # it is a singleton and must not inherit the Documents job's ODL preset.
    iwork = plan["overrides"]["iwork"]
    assert assembler["PUBLIC_VIEWS"]["iwork"] == {"Snapshot View (iwork)"}
    assert [example["plugins"] for example in plan["examples"] if example["url"] == iwork["url"]] == [["iwork"]]
    assert {recipe for recipe in moved if recipe.split("|")[0] == "iwork"} == {f"iwork|{iwork['url']}"}
    assert iwork["wait_for_text"] == "CoT-zuzalu-final.pdf"
    capture = next(
        step
        for step in workflow("screenshots.yml")["jobs"]["public_recipes"]["steps"]
        if step.get("name") == "Capture native public recipe"
    )
    odl_lanes = re.search(r"^\s*([a-z|]+)\) export OPENDATALOADER_ENABLED=True ;;$", capture["run"], re.MULTILINE)
    assert odl_lanes and "iwork" not in odl_lanes[1].split("|")

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
    assembler = runpy.run_path(ROOT / "bin/screenshot_gallery_helpers.py")
    generator = runpy.run_path(ROOT / "bin/screenshot_gallery_helpers.py")
    root = tmp_path / "shards"
    root.mkdir()
    env = {**os.environ, "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12", "GITHUB_RUN_ATTEMPT": "1"}
    env.pop("UI_SCREENSHOT_ALLOW_PARTIAL", None)
    env.pop("UI_SCREENSHOT_PLUGINS", None)
    pins = {name: assembler["version"](name) for name in ("abx-plugins", "abx-dl", "abxpkg", "abxbus")}
    identity = {key: env[key] for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")} | {"pins": pins}
    views = {name for lane_views in assembler["PUBLIC_VIEWS"].values() for name in lane_views}
    plan = generator["plugin_screenshot_plan"]()
    owners = plan["owned_views"]
    required = generator["REQUIRED_VIEW_NAMES"] | set(plan["required"]) | owners.keys()
    base = required - views
    absent = {"Snapshot View (figma)", "Snapshot View (liteparse)", "Snapshot View (chrome)"}
    assert absent <= owners.keys()
    status = assembler["recipe_status"]({name: "unavailable" if name in absent else "captured" for name in owners}, owners)

    def bundle(directory, lane, names, unavailable=absent):
        directory.mkdir()
        rows, files = [], {}
        for name in sorted(names - unavailable):
            slug = generator["re"].sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            for profile, (width, height) in assembler["CAPTURE_PROFILES"].items():
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
        lane_status = {
            assembler["recipe_id"](name, owner): status[assembler["recipe_id"](name, owner)]
            for name, owner in owners.items()
            if name in names
        }
        (directory / "receipt.json").write_text(json.dumps(dict(identity=identity, lane=lane, files=files, outcomes=lane_status)))

    for lane, names in {"base": base, **assembler["PUBLIC_VIEWS"]}.items():
        bundle(root / f"gallery-capture-1-{lane}", lane, names)
    manifest, outcomes = tmp_path / "gallery.jsonl", tmp_path / "outcomes.json"

    def merge(output):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "bin/screenshot_gallery_helpers.py"),
                "merge",
                str(root),
                str(output),
                str(manifest),
                "--recipe-outcomes-out",
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
    unavailable = tmp_path / "whole-unavailable.txt"
    unavailable.write_text("".join(name + "\n" for name in sorted(absent)))
    whole_out = tmp_path / "whole-outcomes.json"
    whole = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bin/screenshot_gallery_helpers.py"),
            "whole-outcomes",
            str(manifest),
            str(unavailable),
            str(whole_out),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert whole.returncode == 0, whole.stderr
    assert json.loads(whole_out.read_text()) == status
    render = subprocess.run(
        [
            sys.executable,
            str(ROOT / "bin/screenshot_gallery_helpers.py"),
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
    assert build["optional_recipe_captures"] == status
    assert "snapshot-view-canva-desktop.png" in build["files"]
    assert not any(name.startswith("snapshot-view-figma-") for name in build["files"])
    assert "snapshot-view-opendataloader-desktop.png" in build["files"]  # Healthy same-source sibling.
    assert "snapshot-view-liteparse-desktop.png" not in build["files"]
    assert "snapshot-view-chrome-desktop.png" not in build["files"]  # Default view, no URL recipe.
    assert "Plugin screenshots unavailable in this capture:" in (output / "index.html").read_text()
    assert {"login-desktop.png", "machine-settings-tablet.png"} <= build["files"].keys()
    restore = runpy.run_path(ROOT / "bin/screenshot_gallery_helpers.py")["validate_published_gallery"]
    assert restore(output, {"head_sha": env["GITHUB_SHA"]}) == build

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
    bad_base = root / "gallery-capture-1-base"
    shutil.rmtree(bad_base)
    bundle(bad_base, "base", base, unavailable=absent - {"Snapshot View (figma)"})
    assert "Capture disagrees with plugin view outcomes" in merge(tmp_path / "unavailable-with-files").stderr
    shutil.rmtree(bad_base)
    bundle(bad_base, "base", base)
    receipt_path = bad_base / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt_path.write_text(json.dumps(receipt | {"identity": identity | {"GITHUB_SHA": "b" * 40}}))
    assert "Mixed capture provenance: base" in merge(tmp_path / "mixed-revision").stderr
    forged = dict(receipt["outcomes"])
    forged["recipe-" + "0" * 16] = {"status": "unavailable", "views": ["login"]}
    receipt_path.write_text(json.dumps(receipt | {"outcomes": forged}))
    assert "Expected one explicit capture outcome" in merge(tmp_path / "forged-app-outcome").stderr


def test_new_plugin_ownership_is_derived_for_all_registered_views(tmp_path, monkeypatch):
    import abx_plugins

    monkeypatch.setattr(abx_plugins, "get_plugins_dir", lambda: tmp_path)
    plugin = tmp_path / "future_fixture"
    (plugin / "templates").mkdir(parents=True)
    (plugin / "templates/card.html").touch()
    config = {"properties": {"FUTURE_FIXTURE_ENABLED": {"default": True}}}
    (plugin / "config.json").write_text(json.dumps(config))
    planner = runpy.run_path(ROOT / "bin/screenshot_gallery_helpers.py")["plugin_screenshot_plan"]
    monkeypatch.setenv("UI_SCREENSHOT_PLUGINS", "future_fixture")
    assert planner()["owned_views"] == {"Snapshot View (future_fixture)": "future_fixture"}

    (plugin / "config.json").write_text(json.dumps(config | {"screenshot": "screenshot.json"}))
    (plugin / "screenshot.json").write_text(json.dumps({"url": "http://127.0.0.1:8123/demo", "outputs": [{"name": "Future detail"}]}))
    assert planner()["owned_views"] == {
        "Snapshot View (future_fixture)": "future_fixture",
        "Future detail": "future_fixture",
    }
    (plugin / "screenshot.json").write_text(json.dumps({"view": "Future importer", "config": True, "importer": "test"}))
    assert planner()["owned_views"] == dict.fromkeys(
        (
            "Future importer",
            "Future importer history",
            "Future importer snapshots",
            "Future importer export",
            "Future importer configuration",
        ),
        "future_fixture",
    )
    (plugin / "screenshot.json").write_text(json.dumps({"view": "Login", "config": True}))
    assert not planner()["owned_views"]  # Plugin cannot waive mandatory app coverage.


def test_anonymous_failed_plugin_still_packs_only_explicitly_attested_empty_shard(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    manifest = tmp_path / "capture.jsonl"
    manifest.touch()
    unavailable = tmp_path / "unavailable.txt"
    build = {"revision": "a" * 40, "capture_count": 0, "files": {}}
    (images / "build.json").write_text(json.dumps(build))
    env = {**os.environ, "GITHUB_SHA": build["revision"], "GITHUB_RUN_ID": "12", "GITHUB_RUN_ATTEMPT": "1"}
    env.pop("UI_SCREENSHOT_PLUGINS", None)
    bundle = tmp_path / "bundle"
    command = [
        sys.executable,
        str(ROOT / "bin/screenshot_gallery_helpers.py"),
        "pack",
        "git",
        str(manifest),
        str(images),
        str(bundle),
        "--unavailable",
        str(unavailable),
    ]

    for invalid in ("", "Login\n", "Snapshot View (git)\nSnapshot View (git)\n"):
        unavailable.write_text(invalid)
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert not bundle.exists()

    unavailable.write_text("Snapshot View (git)\n")
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert {path.name for path in bundle.iterdir()} == {"capture.jsonl", "receipt.json"}
    receipt = json.loads((bundle / "receipt.json").read_text())
    assert list(receipt["outcomes"].values()) == [{"status": "unavailable", "views": ["snapshot-view-git"]}]


def test_importer_terminal_failure_does_not_mask_infrastructure_or_a_healthy_sibling(monkeypatch):
    from types import SimpleNamespace
    import screenshot_gallery_helpers as gallery

    recipes = [{"plugin": name, "name": name, "feed": "fixture", "settings": {}} for name in ("failed_fixture", "healthy_fixture")]
    runs = {name["plugin"]: [] for name in recipes}
    calls = []

    def launch(command, **kwargs):
        args = tuple(command[3:])
        calls.append(args)
        if args[:2] == ("importer", "list"):
            result = [recipe | {"id": recipe["plugin"]} for recipe in recipes]
        elif args[:2] == ("importer", "runs"):
            result = runs[args[3]]
        elif args[:2] == ("manage", "importers"):
            source, action = args[3], args[5]
            failed = source == "failed_fixture"
            runs[source].append(
                {
                    "id": action + "-" + source,
                    "status": "failed" if failed else "succeeded",
                    "action": action,
                    "items": 1,
                    "crawl_id": "fixture-crawl",
                },
            )
            return SimpleNamespace(returncode=int(failed), stdout="", stderr="")
        elif args[0] == "run":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        else:
            pytest.fail(f"Unexpected gallery command {args!r}")
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")

    monkeypatch.setattr(gallery.subprocess, "run", launch)
    omitted = []
    views = gallery.prepare_importers("http://localhost:8123", recipes, on_unavailable=omitted.append)
    assert omitted == list(gallery.importer_view_names("failed_fixture"))
    assert {row.split("|")[0] for row in views} == set(gallery.importer_view_names("healthy_fixture"))
    assert ("run", "--crawl-id", "fixture-crawl") in calls

    def fail_before_native_result(command, **kwargs):
        if tuple(command[3:5]) == ("manage", "importers"):
            return SimpleNamespace(returncode=1, stdout="", stderr="Runner unavailable before enqueue")
        return launch(command, **kwargs)

    monkeypatch.setattr(gallery.subprocess, "run", fail_before_native_result)
    with pytest.raises(RuntimeError, match="Runner unavailable before enqueue"):
        gallery.prepare_importers("http://localhost:8123", recipes, on_unavailable=omitted.append)
