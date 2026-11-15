"""Failure diagnostics must retain resource evidence without browser state."""

import os
import json
import runpy
from pathlib import Path
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_gallery_retains_navigation_and_cooldown_without_credentials(tmp_path):
    secret = "credential-sentinel-do-not-export"
    snapshot = tmp_path / "archive/users/system/snapshots/20261115/example.com/06af9ad7b9a17bf68000756c310c182d"
    (snapshot / "chrome").mkdir(parents=True)
    (snapshot / "headers").mkdir()
    (snapshot / "chrome/navigation.json").write_text(
        json.dumps(
            {
                "url": f"https://user:{secret}@example.com/?token={secret}",
                "finalUrl": f"https://example.com/{secret}",
                "error": f"HTTP 503: {secret}",
                "status": 503,
                "elapsed": 900,
                "attempts": 1,
                "retry_after_ms": 60000,
                "waitUntil": "domcontentloaded",
                "content_type": "text/html",
            },
        ),
    )
    (snapshot / "headers/headers.json").write_text(
        json.dumps(
            {
                "status": 503,
                "request_headers": {"Authorization": secret, "Cookie": secret},
                "response_headers": {"Set-Cookie": secret, "Retry-After": "60", "Date": "Sun, 15 Nov 2026 13:03:05 GMT"},
                "body": secret,
            },
        ),
    )
    generator = runpy.run_path(str(REPO_ROOT / "bin/generate_ui_screenshot_gallery.py"))
    output = tmp_path / "navigation.json"
    generator["write_navigation_diagnostics"](tmp_path, output)
    serialized = output.read_text()
    report = json.loads(serialized)
    assert report == [
        {
            "snapshot_id": snapshot.name,
            "navigation": {"status": 503, "elapsed": 900, "attempts": 1, "retry_after_ms": 60000},
            "headers_capture": {"status": 503, "retry-after": "60", "date": "Sun, 15 Nov 2026 13:03:05 GMT"},
        },
    ]
    assert secret not in serialized
    assert "example.com" not in serialized
    assert output.stat().st_mode & 0o077 == 0

    (snapshot / "headers/headers.json").write_text(
        json.dumps(
            {
                "response_headers": {"Retry-After": "Sun, 15 Nov 2026 13:04:05 GMT"},
            },
        ),
    )
    generator["write_navigation_diagnostics"](tmp_path, output)
    assert json.loads(output.read_text())[0]["headers_capture"] == {"retry-after": "Sun, 15 Nov 2026 13:04:05 GMT"}

    # Absent/invalid Retry-After must stay distinguishable from a server's hint.
    (snapshot / "headers/headers.json").write_text(
        json.dumps(
            {
                "response_headers": {"Retry-After": secret, "Date": secret},
            },
        ),
    )
    generator["write_navigation_diagnostics"](tmp_path, output)
    assert json.loads(output.read_text())[0]["headers_capture"] == {"retry-after": "invalid", "date": "invalid"}
    (snapshot / "headers/headers.json").unlink()
    generator["write_navigation_diagnostics"](tmp_path, output)
    assert json.loads(output.read_text())[0]["headers_capture"] == {}


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


@pytest.mark.django_db
def test_gallery_classifies_persisted_chrome_stderr_without_disclosing_values(tmp_path):
    from archivebox.machine.models import Machine, Process

    secret = "credential-sentinel-do-not-export"
    machine = Machine.current()
    common = {
        "machine": machine,
        "process_type": Process.TypeChoices.HOOK,
        "pwd": f"/private/{secret}/chrome",
        "cmd": ["chrome", f"--password={secret}"],
        "env": {"TOKEN": secret},
        "status": Process.StatusChoices.EXITED,
    }
    Process.objects.create(
        **common,
        exit_code=0,
        stderr=f"{secret}\n[*] Snapshot target ABC123 crashed: Page crashed! https://example.com/?token={secret}\n"
        "[*] Removed stale Chrome snapshot markers (renderer crashed)\n"
        "tab closed unexpectedly!\n",
    )
    Process.objects.create(**common, exit_code=0, stderr=f"tab closed unexpectedly! {secret}\n")
    Process.objects.create(
        **common,
        exit_code=1,
        stderr=secret * 10000 + "\nFATAL ERROR: Reached heap limit Allocation failed - JavaScript heap out of memory\n",
    )
    Process.objects.create(**common, exit_code=0, stderr=f"chromium exited successfully {secret}\n")
    Process.objects.create(
        **{**common, "pwd": "/private/other-plugin"},
        exit_code=1,
        stderr="Page crashed!",
    )
    generator = runpy.run_path(str(REPO_ROOT / "bin/generate_ui_screenshot_gallery.py"))
    output = tmp_path / "chrome-lifecycle.json"
    generator["write_chrome_lifecycle_diagnostics"](output)
    serialized = output.read_text()
    report = json.loads(serialized)
    assert report["processes_scanned"] == 4
    assert report["processes_omitted"] is False
    assert report["stderr_truncated_processes"] == 1
    assert report["reported_success_with_lifecycle_evidence"] == 2
    assert report["classifications"] == {
        "renderer_crashed": 1,
        "unexpected_target_close": 2,
        "heap_allocation_failure": 1,
        "browser_close_failed": 0,
    }
    assert secret not in serialized
    assert "example.com" not in serialized
    assert "ABC123" not in serialized
    assert output.stat().st_mode & 0o077 == 0
    assert len(serialized) < 2048
    assert Process.objects.filter(pwd=common["pwd"]).count() == 4


@pytest.mark.django_db
def test_gallery_chrome_diagnostics_bound_process_history(tmp_path):
    from archivebox.machine.models import Machine, Process

    machine = Machine.current()
    Process.objects.bulk_create(
        [
            Process(
                machine=machine,
                process_type=Process.TypeChoices.HOOK,
                pwd="/capture/chrome",
                exit_code=0,
                stderr="tab closed unexpectedly!",
            )
            for _ in range(129)
        ],
    )
    generator = runpy.run_path(str(REPO_ROOT / "bin/generate_ui_screenshot_gallery.py"))
    output = tmp_path / "chrome-lifecycle.json"
    generator["write_chrome_lifecycle_diagnostics"](output)
    report = json.loads(output.read_text())
    assert report["processes_scanned"] == 128
    assert report["processes_omitted"] is True
    assert report["classifications"]["unexpected_target_close"] == 128
    assert report["classifications"]["renderer_crashed"] == 0
