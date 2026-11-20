"""Automatic captures may supersede each other, never explicit manual captures."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_gallery_automatic_preemption_preserves_manual_runs():
    capture = workflow("screenshots.yml")
    assert capture["concurrency"] == {
        "group": "${{ github.workflow }}-${{ github.ref }}-${{ github.event_name == 'workflow_dispatch' && format('manual-{0}-{1}', inputs.plugin_revision != '' && 'plugin-capture' || 'default', github.run_id) || 'default' }}",
        "cancel-in-progress": "${{ github.event_name == 'push' }}",
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
    assert public["strategy"]["matrix"]["plugin"] == ["git", "packageregistry", "papersdl", "staticfile", "ytdlp"]
    assert "inputs.plugin_revision == ''" in public["if"]
    public_upload = next(step for step in public["steps"] if step.get("name") == "Upload anonymous capture shard")
    assert public_upload["with"]["name"] == "gallery-capture-${{ github.run_attempt }}-${{ matrix.plugin }}"
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
