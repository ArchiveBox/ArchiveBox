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
    import hashlib

    guard_start = patched.index("function validatePreparedSinglefile(")
    guard_end = patched.index("async function getExactChromeTab", guard_start)
    assert (
        hashlib.sha256(patched[guard_start:guard_end].strip().encode()).hexdigest()
        == "00e1063bac1eda719c83a4042f43381962c67be755bf8a8e19698959af4b0bf3"
    )
    assert patched.index("validatePreparedSinglefile(extension);", patched.index("const extension = { ...sessionEntry };")) < patched.index(
        "const manifest =",
        patched.index("const extension = { ...sessionEntry };"),
    )
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
        f"const traceStatePath = {json.dumps(str(tmp_path / 'trace-state.json'))};"
        + "const traceState = "
        + patched.split("const traceState = ", 1)[1].split(";", 1)[0]
        + ";"
        + "const writeTraceState = "
        + patched.split("const writeTraceState = ", 1)[1].split(";", 1)[0]
        + ";"
        + f"const tracePath = {json.dumps(str(trace_output))}; const names = {names};"
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
    assert json.loads((tmp_path / "trace-state.json").read_text())["data_batches"] == 1
    assert patched.index("writeTraceState();") < patched.index("createCDPSession();")
    assert "page.browser().on('disconnected'" in patched
    # Source drift fails explicitly rather than applying the diagnostic twice.
    repeat = subprocess.run(["uv", "run", "--no-sync", "python", "-c", code, str(helper)], text=True, capture_output=True)
    assert repeat.returncode != 0
    assert "differs from reviewed diagnostic base" in repeat.stderr


def test_public_probe_injects_reviewed_hook_before_crawl_discovery(tmp_path):
    import hashlib

    workflow = yaml.load((ROOT / ".github/workflows/diagnose-canva.yml").read_text(), Loader=yaml.BaseLoader)
    capture = next(s["run"] for s in workflow["jobs"]["diagnose"]["steps"] if s["name"] == "Capture public Canva with native diagnostics")
    source = capture.split("<<'CANDIDATE_HOOK'\n", 1)[1].split("CANDIDATE_HOOK\n", 1)[0]
    assert hashlib.sha256(source.encode()).hexdigest() == "c6a6858f005d9c98d941e0363e324a203c4309ce8ea970ee9732946801c7d6ff"
    compile(source, "candidate.py", "exec")
    assert capture.index("CANDIDATE_HOOK\n") < capture.index("archivebox init --quick") < capture.index("archivebox add --depth=0")
    assert "prepared_ok and selected_ok" in capture
    assert "selected-bundle.json" in capture
    assert "capture.setup_process_count" in capture
    assert "capture.prepared_file_count" in capture
    assert "capture.selected_hash_class" in capture
    assert 'assert metrics["capture.prepared_bundle_verified"]' in capture
    assert 'assert metrics["capture.failed_results"] == 0' in capture
    hook = tmp_path / "candidate.py"
    hook.write_text(source)
    code = capture.split("<<'CHECK_CANDIDATE'\n", 1)[1].split("CHECK_CANDIDATE\n", 1)[0]
    checked = subprocess.run(["uv", "run", "--no-sync", "python", "-c", code, str(hook)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
    hook.write_text(source + "# drift\n")
    rejected = subprocess.run(["uv", "run", "--no-sync", "python", "-c", code, str(hook)], capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "differs from reviewed hook" in rejected.stderr


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
            ("singlefile", "failed", 1, "SingleFile selected bundle SHA256 mismatch " + sentinel),
            ("chrome", "failed", 1, "[chrome] target_crash status=crashed error_code=5 " + sentinel),
            (sentinel, "failed", 9, sentinel),
        ],
    )
    assert report["failure.singlefile"] == report["failure.chrome"] == report["failure.other"] == 1
    assert report["indicator.guard_rejected"] == report["indicator.renderer_crashed"] == 1
    assert report["native.error_code"] == 5
    assert report["process.singlefile.exit.0"] == 1
    assert report["indicator.timeout"] == report["indicator.target_closed"] == 0
    assert all(type(value) is int for value in report.values())
    assert sentinel not in json.dumps(report)


def test_stage_probe_uses_private_prepared_runtime_and_fixed_numeric_events():
    import hashlib

    workflow = yaml.load((ROOT / ".github/workflows/diagnose-canva.yml").read_text(), Loader=yaml.BaseLoader)
    capture = next(s["run"] for s in workflow["jobs"]["diagnose"]["steps"] if s["name"] == "Capture public Canva with native diagnostics")
    source = capture.split("<<'STAGE_HOOK'", 1)[1].split("STAGE_HOOK\n", 1)[0].lstrip()
    compile(source, "stage-hook", "exec")
    assert "AGPL-3.0-or-later" in source
    assert "root.is_relative_to" in source and 'Path(config.PERSONAS_DIR) / ".singlefile"' in source
    assert 'root / "lib/single-file-extension.js"' in source
    assert "f7ffb981581faa31f4057037c1248c3405fdb503cf58b0566a6bbd3e3523a2b3" in source
    assert "0be550c69429dfc816c717e3bbe8c63278d3919c7ad83b3d7b40a31871c82d1b" in source
    addition = next(line for line in source.splitlines() if line.strip().startswith("addition ="))
    assert "Number.isSafeInteger(t.detail.step)" in addition
    assert "t.detail.step>=0&&t.detail.step<=5" in addition
    assert "!t.detail.frame" in addition
    assert "await" not in addition and "sendMessage" not in addition and "pageURL" not in addition
    assert "page.on('console', recordPhase)" in capture
    assert "progress|blob|chunk|chunk_end|stage_start|stage_end" in capture
    assert 'assert metrics["capture.diagnostic_hash_class"] == 2' in capture
    assert 'metrics["capture.stage_setup_success_count"] == 1' in capture
    assert capture.index("STAGE_HOOK\n") < capture.index("archivebox init --quick")
    candidate = capture.split("<<'CANDIDATE_HOOK'", 1)[1].split("CANDIDATE_HOOK\n", 1)[0].lstrip()
    assert hashlib.sha256(candidate.encode()).hexdigest() == "c6a6858f005d9c98d941e0363e324a203c4309ce8ea970ee9732946801c7d6ff"
