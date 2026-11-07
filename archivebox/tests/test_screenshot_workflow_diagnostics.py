"""Failure diagnostics must retain resource evidence without browser state."""

import os
from pathlib import Path
import subprocess

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_screenshot_failure_resource_diagnostics_are_bounded_and_private(tmp_path):
    workflow = yaml.load((REPO_ROOT / ".github/workflows/screenshots.yml").read_text(), Loader=yaml.BaseLoader)
    steps = workflow["jobs"]["deploy"]["steps"]
    diagnostic = next(step for step in steps if step.get("name") == "Record failed capture resource diagnostics")
    upload = next(step for step in steps if step.get("name") == "Retain failed gallery frame and request diagnostics")
    assert diagnostic["if"] == "failure()"
    assert steps.index(diagnostic) < steps.index(upload)
    assert upload["with"]["path"] == "${{ runner.temp }}/gallery-failure-diagnostics"
    secret = "private-persona-data-must-not-appear"
    persona = tmp_path / "provider-auth.json"
    persona.write_text(secret)
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", diagnostic["run"]],
        env={**os.environ, "RUNNER_TEMP": str(tmp_path), "PROVIDER_AUTH_STORAGE_JSON": secret},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    outputs = list((tmp_path / "gallery-failure-diagnostics").iterdir())
    assert [path.name for path in outputs] == ["system-memory.log"]
    report = outputs[0].read_text()
    assert "Memory totals" in report
    assert "Cgroup memory" in report
    assert "Kernel memory/process failures" in report
    assert secret not in report + result.stdout + result.stderr
    assert outputs[0].stat().st_mode & 0o077 == 0
    assert outputs[0].stat().st_size < 65536
    assert persona.read_text() == secret
