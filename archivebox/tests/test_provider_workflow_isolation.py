"""Live personal-session checks remain visible without gating releases."""

import json
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_live_provider_workflow_is_independent_and_preserves_coverage():
    def workflow(name):
        return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)

    live = workflow("provider-replay.yml")
    required = workflow("test-parallel.yml")
    ci = workflow("ci.yml")
    assert "provider-capture" not in required["jobs"]
    assert all("provider-replay.yml" not in job.get("uses", "") for job in ci["jobs"].values())
    assert live["on"]["push"]["branches"] == ["dev"]
    assert "schedule" in live["on"] and "workflow_dispatch" in live["on"]
    discovery = live["jobs"]["discover-tests"]
    assert "github.repository == 'ArchiveBox/ArchiveBox'" in discovery["if"]
    assert "github.ref == 'refs/heads/dev'" in discovery["if"]
    provider = live["jobs"]["provider-capture"]
    assert provider["environment"] == "provider-capture"
    assert provider["timeout-minutes"] == "30"
    assert "continue-on-error" not in provider
    assert all("continue-on-error" not in step for step in provider["steps"])
    checkout = next(step for step in provider["steps"] if "actions/checkout@" in step.get("uses", ""))
    assert checkout["with"]["ref"] == "${{ needs.discover-tests.outputs.sha }}"
    cleanup = next(step for step in provider["steps"] if step.get("name") == "Remove authentication and browser profiles")
    assert cleanup["if"] == "always()"
    output = subprocess.check_output([sys.executable, str(ROOT / ".github/scripts/discover_test_matrix.py")], text=True)
    matrix = json.loads(output.splitlines()[1])
    paths = [p for item in matrix for p in item["paths"]]
    assert len(paths) == len(set(paths))
    assert set(paths) == {p.relative_to(ROOT).as_posix() for p in (ROOT / "archivebox/tests").glob("test_*.py")}
    live_paths = [p for item in matrix if item["environment"] in {"provider-capture", "live-provider"} for p in item["paths"]]
    assert set(live_paths) == {"archivebox/tests/test_authenticated_provider_replay.py", "archivebox/tests/test_iwork_live_replay.py"}

    public = live["jobs"]["public-replay"]
    assert "environment" not in public
    assert "secrets." not in json.dumps(public)
    run = next(step for step in public["steps"] if step.get("name") == "Run real public CLI and replay acceptance")
    assert run["env"]["AUTH_STORAGE_FILE"] == ""
    assert run["env"]["CHROME_HEADLESS"] == "true"
