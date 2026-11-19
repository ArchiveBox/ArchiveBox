"""Gallery navigation checks use the exact rule IDs created for the run."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from archivebox.api.webhook_screenshots import gallery_entries


@pytest.mark.parametrize("label", ["Rule actions", "Rule event input", "Rule scripts", "Webhook process logs"])
def test_rule_gallery_validates_exact_editor_url(tmp_path, label):
    base_url = "http://admin.archivebox.localhost:5797"
    rule_ids = ["00000000000000000000000000000001", "00000000000000000000000000000002", "00000000000000000000000000000003"]
    _, capture_url, expected_path, _, _ = next(
        entry.split("|") for entry in gallery_entries(base_url, rule_ids) if entry.startswith(f"{label}|")
    )
    expected_rule_id = rule_ids[2] if label in {"Rule scripts", "Webhook process logs"} else rule_ids[0]
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


@pytest.mark.django_db(transaction=True)
def test_gallery_process_logs_show_real_selected_hook_commands(admin_client, admin_user):
    from urllib.parse import urlsplit
    from archivebox.api.webhook_events import emit_event
    from archivebox.tests.test_webhook_actions import make_hook, make_snapshot, action_processes

    hook = make_hook(
        admin_user,
        [
            {"type": "python", "code": "import sys\nprint(sys.stdin.read())"},
            {"type": "shell", "command": "cat"},
        ],
    )
    snapshot = make_snapshot(admin_user)
    emit_event(snapshot, "BEFORE_CAPTURE")
    processes = action_processes(hook)
    assert len(processes) == 2
    assert all(process.exit_code == 0 and process.status == "exited" for process in processes)
    entry = next(
        entry
        for entry in gallery_entries("http://admin.archivebox.localhost:5797", [str(hook.pk)] * 3)
        if entry.startswith("Webhook process logs|")
    )
    _, url, expected_path, _, mode = entry.split("|")
    assert expected_path == urlsplit(url).path + "?" + urlsplit(url).query
    response = admin_client.get(expected_path, HTTP_HOST="admin.archivebox.localhost:5797")
    assert response.status_code == 200
    assert set(response.context["cl"].result_list.values_list("pk", flat=True)) == {process.pk for process in processes}
    assert mode == "wait-text:bash -c cat"
    assert mode.removeprefix("wait-text:") in response.content.decode()
