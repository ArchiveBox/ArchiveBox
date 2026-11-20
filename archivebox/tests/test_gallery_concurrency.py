"""Capture queues keep running work and isolate schedules and manual requests."""

from pathlib import Path
import runpy

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
    assert len(matrix) == 10
    assert "environment" not in public
    assert "secrets." not in str(public)
    assert "inputs.plugin_revision == ''" in public["if"]
    public_upload = next(step for step in public["steps"] if step.get("name") == "Upload anonymous capture shard")
    assert public_upload["with"]["name"] == "gallery-capture-${{ github.run_attempt }}-${{ matrix.lane }}"
    base_upload = next(step for step in jobs["deploy"]["steps"] if step.get("name") == "Upload native base capture shard")
    assert base_upload["if"] == "inputs.plugin_revision == ''"
    assert base_upload["with"]["name"] == "gallery-capture-${{ github.run_attempt }}-base"
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
    moved = full - base
    assert len(moved) == 20  # Five proven singleton visits + 15 compound visits.
    assert len(set().union(*assembler["PUBLIC_VIEWS"].values())) == 22
    assert {"Model preview (STL)", "Model preview (3MF)", "Model preview (GLB)"} <= assembler["PUBLIC_VIEWS"]["cad"]
    assert "Snapshot View (opendataloader)" in assembler["PUBLIC_VIEWS"]["documents"]

    # Whole source groups, including the same PDF visited for both extractors,
    # must reproduce the locked full plan. A newly coupled protected provider fails.
    recipe = next(item for item in plan["examples"] if "opendataloader" in item["plugins"])
    assert set(recipe["plugins"]) == {"liteparse", "opendataloader"}
    recipe["plugins"].append("canva")
    with pytest.raises(ValueError, match="split a native source"):
        list(recipes(plan, True))
