"""Run actual discovery and verify trusted authenticated acceptance routing."""

import json
import os
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_authenticated_files_have_separate_trusted_matrix(tmp_path):
    result = subprocess.run(
        ["uv", "run", "--no-project", "python", str(ROOT / ".github/scripts/discover_test_matrix.py")],
        cwd=tmp_path,
        env={**os.environ, "TEST_FILE": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    matrix = json.loads(result.stdout.splitlines()[-1])
    authenticated = [item for item in matrix if item["environment"] == "provider-capture"]
    ordinary = [item for item in matrix if not item["environment"]]
    discovered = list((ROOT / "archivebox/tests").glob("test_*.py"))
    expected_auth = {
        file.relative_to(ROOT).as_posix()
        for file in discovered
        if "# ci-environment: provider-capture" in file.read_text().splitlines()[:5]
    }
    assert expected_auth == {"archivebox/tests/test_authenticated_provider_replay.py"}
    assert {path for item in authenticated for path in item["paths"]} == expected_auth
    assert not expected_auth & {path for item in ordinary for path in item["paths"]}
    assigned = Counter(path for item in matrix for path in item["paths"])
    assert assigned == Counter(file.relative_to(ROOT).as_posix() for file in discovered)
    assert all(item["ugnas"] is False for item in authenticated)
