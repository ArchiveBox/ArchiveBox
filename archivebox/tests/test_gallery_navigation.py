"""Gallery navigation checks use the exact rule IDs created for the run."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from archivebox.api.webhook_screenshots import gallery_entries


@pytest.mark.parametrize("label", ["Rule actions", "Rule event input", "Rule scripts"])
def test_rule_gallery_validates_exact_editor_url(tmp_path, label):
    base_url = "http://admin.archivebox.localhost:5797"
    rule_ids = ["00000000000000000000000000000001", "00000000000000000000000000000002", "00000000000000000000000000000003"]
    _, capture_url, expected_path, _, _ = next(
        entry.split("|") for entry in gallery_entries(base_url, rule_ids) if entry.startswith(f"{label}|")
    )
    expected_rule_id = rule_ids[2] if label == "Rule scripts" else rule_ids[0]
    wrong_rule_id = rule_ids[1]
    validator = Path(__file__).resolve().parents[2] / "bin/generate_ui_screenshot_gallery.py"
    report = tmp_path / "report.json"

    def validate(final_url):
        report.write_text(json.dumps({"checks": {"status": 200, "finalUrl": final_url}}))
        return subprocess.run(
            [sys.executable, str(validator), "validate", str(report), expected_path],
            capture_output=True,
            text=True,
            timeout=10,
        )

    correct = validate(capture_url)
    assert correct.returncode == 0, correct.stderr
    wrong_rule = validate(capture_url.replace(expected_rule_id, wrong_rule_id))
    assert wrong_rule.returncode == 1
    assert "expected final query" in wrong_rule.stderr
    if label == "Rule event input":
        missing_preview = validate(capture_url.removesuffix("&preview=1"))
        assert missing_preview.returncode == 1
        assert "expected final query" in missing_preview.stderr


def test_rule_preview_gallery_requires_rendered_table_heading():
    # Native Brave reproduction: Django admin renders th text uppercase. The
    # screenshot runner checks visible innerText, not the mixed-case DOM source.
    entry = next(
        entry
        for entry in gallery_entries("http://admin.archivebox.localhost:5797", ["first", "second", "third"])
        if entry.startswith("Rule event input|")
    )
    assert entry.split("|")[4] == "wait-text:PLANNED ACTIONS"
