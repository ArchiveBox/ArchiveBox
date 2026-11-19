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
    capture = workflow("screenshots.yml")
    steps = capture["jobs"]["deploy"]["steps"]
    names = [step.get("name") for step in steps]
    validate = names.index("Verify gallery was generated from this exact revision")
    upload = names.index("Save validated screenshots")
    assert names.index("Build UI screenshot gallery") < validate < upload
    assert steps[upload].get("if", "success()") == "success()"
    assert 'provenance["revision"] == os.environ["GITHUB_SHA"]' in steps[validate]["run"]


def test_pages_publication_stays_serialized_and_rejects_cancelled_captures():
    pages = workflow("deploy-publicsite.yml")
    assert pages["concurrency"] == {
        "group": "pages-${{ github.event_name == 'pull_request' && github.ref || 'production' }}",
        "cancel-in-progress": "false",
    }
    assert pages["jobs"]["build"]["if"] == ("github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'")
