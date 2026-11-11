"""The temporary native crash probe cannot inherit a provider persona."""

import os
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_canva_probe_is_manual_public_and_uses_gallery_settings():
    text = (ROOT / ".github/workflows/diagnose-canva.yml").read_text()
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["diagnose"]
    assert "environment" not in job
    assert "secrets." not in text
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["timeout-minutes"] == "20"
    steps = job["steps"]
    assert steps[0]["with"]["persist-credentials"] == "false"
    gallery = yaml.load((ROOT / ".github/workflows/screenshots.yml").read_text(), Loader=yaml.BaseLoader)
    for name in (
        "Install ArchiveBox and screenshot dependencies",
        "Install the matching Chrome sandbox helper",
        "Configure local Wayback submission service",
    ):
        assert next(s["run"] for s in steps if s["name"] == name) == next(
            s["run"] for s in gallery["jobs"]["deploy"]["steps"] if s["name"] == name
        )
    capture = next(s["run"] for s in steps if s["name"] == "Capture public Canva with native diagnostics")
    assert "env -i PATH=" in capture
    assert 'HOME="$public_root/home"' in capture
    assert "TIMEOUT=60 CHROME_HEADLESS=false CHROME_LOG_SUBPROCESS_OUTPUT=true" in capture
    assert "plugin-plan" in capture
    assert 'archivebox config --set "${enabled[@]}"' in capture
    assert "archivebox add --depth=0 --overwrite" in capture
    assert 'result.status == "succeeded"' in capture
    assert 'assert metrics["capture.font_payloads_preserved"]' in capture
    assert 'assert metrics["capture.public_title_preserved"]' in capture
    assert "beb4f5ebe5ec8cd10dae7f74dcc1f8b6cc7a3095550e5920d1cf951eaae8eae3" in capture
    assert "AUTH_STORAGE_FILE" not in capture and "COOKIES_FILE" not in capture
    assert "removeUnusedFonts" not in capture
    upload = next(s for s in steps if s["name"] == "Upload public diagnostics only")
    assert upload["with"]["path"].splitlines() == ["${{ env.CANVA_PUBLIC_ROOT }}/diagnostics/" + name for name in ("system-memory.json",)]
    assert "dmesg" not in text
    assert 'Right("stderr"' not in capture
    assert not any(step["name"] == "Retain bounded public capture log" for step in steps)
    for step in steps:
        if "run" in step:
            result = subprocess.run(["bash", "-n"], input=step["run"], text=True, capture_output=True)
            assert result.returncode == 0, result.stderr


def test_canva_probe_resource_report_does_not_read_credentials(tmp_path):
    workflow = yaml.load((ROOT / ".github/workflows/diagnose-canva.yml").read_text(), Loader=yaml.BaseLoader)
    step = next(s for s in workflow["jobs"]["diagnose"]["steps"] if s["name"] == "Record failed capture resource diagnostics")
    sentinel = "secret-provider-sentinel-never-export"
    (tmp_path / "provider-auth.json").write_text(sentinel)
    import json

    (tmp_path / "diagnostics").mkdir()
    (tmp_path / "diagnostics/system-memory.json").write_text(
        json.dumps(
            {
                "capture.font_count": 571,
                "capture.html_bytes": sentinel,
                "capture.url": sentinel,
                "unexpected": sentinel,
            },
        ),
    )
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        env={**os.environ, "CANVA_PUBLIC_ROOT": str(tmp_path), "PROVIDER_AUTH_STORAGE_JSON": sentinel},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = tmp_path / "diagnostics/system-memory.json"
    import json

    metrics = json.loads(report.read_text())
    assert all(isinstance(value, int) or value == "max" for value in metrics.values())
    assert all(key.endswith("_kB") or key.startswith("memory.") or key == "capture.font_count" for key in metrics)
    assert metrics["capture.font_count"] == 571
    assert "capture.html_bytes" not in metrics
    assert report.stat().st_size < 65536
    assert report.stat().st_mode & 0o077 == 0
    assert sentinel not in report.read_text() + result.stdout + result.stderr
    assert (tmp_path / "provider-auth.json").read_text() == sentinel


def test_capture_failure_classifier_keeps_only_fixed_labels():
    import ast
    import json
    import re

    workflow = yaml.load((ROOT / ".github/workflows/diagnose-canva.yml").read_text(), Loader=yaml.BaseLoader)
    capture = next(s["run"] for s in workflow["jobs"]["diagnose"]["steps"] if s["name"] == "Capture public Canva with native diagnostics")
    code = capture.split("<<'VERIFY'", 1)[1].split("VERIFY\n", 1)[0].lstrip()
    tree = ast.parse(code)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "classify_capture")
    namespace = {"re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "diagnostic-classifier", "exec"), namespace)
    sentinel = "private-cookie-url-sentinel"
    report = namespace["classify_capture"](
        [
            ("singlefile", "failed", 1, "SingleFile download timed out " + sentinel),
            ("chrome", "failed", 1, "[chrome] target_crash status=crashed error_code=5 " + sentinel),
            (sentinel, "failed", 9, sentinel),
        ],
    )
    assert report["failure.singlefile"] == report["failure.chrome"] == report["failure.other"] == 1
    assert report["indicator.renderer_crashed"] == 1
    assert report["native.error_code"] == 5
    assert report["process.singlefile.exit.0"] == 1
    assert report["indicator.timeout"] == 1
    assert report["indicator.target_closed"] == 0
    assert all(type(value) is int for value in report.values())
    assert sentinel not in json.dumps(report)
