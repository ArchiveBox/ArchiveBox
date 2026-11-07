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
    assert "AUTH_STORAGE_FILE" not in capture and "COOKIES_FILE" not in capture
    assert "removeUnusedFonts" not in capture
    upload = next(s for s in steps if s["name"] == "Upload public diagnostics only")
    assert upload["with"]["path"].splitlines() == [
        "${{ env.CANVA_PUBLIC_ROOT }}/diagnostics/" + name for name in ("singlefile-phases.json", "v8-gc.json", "system-memory.json")
    ]
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
    assert all(key.endswith("_kB") or key.startswith("memory.") for key in metrics)
    assert report.stat().st_size < 65536
    assert report.stat().st_mode & 0o077 == 0
    assert sentinel not in report.read_text() + result.stdout + result.stderr
    assert (tmp_path / "provider-auth.json").read_text() == sentinel


def test_public_probe_instruments_actual_helper_without_changing_capture_options(tmp_path):
    import abx_plugins

    workflow = yaml.load((ROOT / ".github/workflows/diagnose-canva.yml").read_text(), Loader=yaml.BaseLoader)
    capture = next(s["run"] for s in workflow["jobs"]["diagnose"]["steps"] if s["name"] == "Capture public Canva with native diagnostics")
    code = capture.split("<<'INSTRUMENT'", 1)[1].split("INSTRUMENT\n", 1)[0].lstrip()
    original = (Path(abx_plugins.__file__).parent / "plugins/singlefile/singlefile_extension_save.js").read_text()
    helper = tmp_path / "singlefile_extension_save.js"
    helper.write_text(original)
    result = subprocess.run(
        ["uv", "run", "--no-sync", "python", "-c", code, str(helper)],
        text=True,
        capture_output=True,
        env={**os.environ, "PUBLIC_ROOT": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    patched = helper.read_text()
    assert "process.env.PUBLIC_ROOT" not in patched
    assert str(tmp_path / "diagnostics") in patched
    assert patched.index("helperPage = await") < patched.index("helperPage.on('console'")
    assert patched.count("Tracing.start") == 1
    assert "traceBufferSizeInKb: 1024" in patched
    assert "events.length > 2048" in patched
    assert "phases.length > 512" in patched
    assert "CHROME_ARGS_EXTRA" not in patched
    for line in original.splitlines():
        if "captureProfile[key]" in line or "const downloadTimeoutMs" in line or "withTimeout(" in line:
            assert line in patched
    syntax = subprocess.run(["node", "--check", str(helper)], text=True, capture_output=True)
    assert syntax.returncode == 0, syntax.stderr
    # Execute the exact trace projection on sentinel-bearing input, without a browser mock.
    import json

    names = patched.split("    const names = ", 1)[1].split(";", 1)[0]
    projection = patched.split("trace.on('Tracing.dataCollected', ", 1)[1].split("\n    });", 1)[0]
    trace_output = tmp_path / "trace.json"
    sentinel = "private-url-token-sentinel"
    probe = (
        "const fs = require('fs'); const events = []; let omitted = 0;"
        f"const tracePath = {json.dumps(str(trace_output))}; const names = {names};"
        f"const collect = {projection} }};"
        "collect({value: "
        + json.dumps(
            [
                {"name": "MajorGC", "ts": 1, "dur": 2, "pid": 3, "args": {"usedHeapSizeAfter": 123, "url": sentinel}},
                {"name": sentinel, "ts": 4, "args": {"allocated": 100}},
            ],
        )
        + "});"
    )
    projected = subprocess.run(["node", "-e", probe], text=True, capture_output=True)
    assert projected.returncode == 0, projected.stderr
    serialized = trace_output.read_text()
    assert sentinel not in serialized
    assert json.loads(serialized)["events"] == [{"name": "MajorGC", "ts": 1, "dur": 2, "pid": 3, "usedHeapSizeAfter": 123}]
    # Source drift fails explicitly rather than applying the diagnostic twice.
    repeat = subprocess.run(["uv", "run", "--no-sync", "python", "-c", code, str(helper)], text=True, capture_output=True)
    assert repeat.returncode != 0
    assert "diagnostic anchor changed" in repeat.stderr
