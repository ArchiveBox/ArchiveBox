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
        == "f70b7a9d22c78e141af8ec77ebc8eca70dfb6beb327350bcc0c21ce3b45294b7"
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
    assert hashlib.sha256(source.encode()).hexdigest() == "c4f564574c50bc77256993549baf41a534c51839f83da5c0d85d71c081759de7"
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
    assert "97a37688f42f6aaf8080b0ec125e8082924a5ca0d85dd20328a8abbd1e6c4cf8" in source
    addition = next(line for line in source.splitlines() if line.strip().startswith("addition ="))
    assert "Number.isSafeInteger(t.detail.step)" in addition
    assert "t.detail.step>=0&&t.detail.step<=5" in addition
    assert "Number(Boolean(t.detail.frame))" in addition
    assert "await" not in addition and "sendMessage" not in addition and "pageURL" not in addition
    assert "page.on('console', recordPhase)" in capture
    assert "progress|blob|chunk|chunk_end|stage_start|stage_end" in capture
    assert 'assert metrics["capture.diagnostic_hash_class"] == 2' in capture
    assert 'metrics["capture.stage_setup_success_count"] == 1' in capture
    assert capture.index("STAGE_HOOK\n") < capture.index("archivebox init --quick")
    candidate = capture.split("<<'CANDIDATE_HOOK'", 1)[1].split("CANDIDATE_HOOK\n", 1)[0].lstrip()
    assert hashlib.sha256(candidate.encode()).hexdigest() == "c4f564574c50bc77256993549baf41a534c51839f83da5c0d85d71c081759de7"


def test_stage2_overlay_exact_bundle_and_no_new_async_control(tmp_path):
    import ast
    import hashlib
    import json
    import abx_plugins
    from abx_plugins.plugins.base.testing import install_required_binary_from_config

    workflow = yaml.load((ROOT / ".github/workflows/diagnose-canva.yml").read_text(), Loader=yaml.BaseLoader)
    capture = next(s["run"] for s in workflow["jobs"]["diagnose"]["steps"] if s["name"] == "Capture public Canva with native diagnostics")
    candidate = capture.split("<<'CANDIDATE_HOOK'", 1)[1].split("CANDIDATE_HOOK\n", 1)[0].lstrip()
    stage = capture.split("<<'STAGE_HOOK'", 1)[1].split("STAGE_HOOK\n", 1)[0].lstrip()
    literals = {}
    for statement in ast.parse(stage).body:
        if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
            try:
                literals[statement.targets[0].id] = ast.literal_eval(statement.value)
            except (ValueError, TypeError):
                pass
    plugin = Path(abx_plugins.__file__).parent / "plugins/singlefile"
    config = json.loads((plugin / "config.json").read_text())
    config["required_binaries"][0]["min_version"] = "1.36.0"
    install_plugin = tmp_path / "singlefile"
    install_plugin.mkdir()
    (install_plugin / "config.json").write_text(json.dumps(config))
    extensions = tmp_path / "lib/chromewebstore/extensions"
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path / "home"), "ABXPKG_LIB_DIR": str(tmp_path / "lib")}
    (tmp_path / "home").mkdir()
    env["CHROMEWEBSTORE_EXTENSIONS_DIR"] = str(extensions)
    install_required_binary_from_config(install_plugin, "singlefile", env=env)
    original_root = Path(json.loads((extensions / "singlefile.extension.json").read_text())["unpacked_path"])
    original = (original_root / "lib/single-file.js").read_text()
    constants = {}
    for statement in ast.parse(candidate).body:
        if isinstance(statement, ast.Assign) and isinstance(statement.targets[0], ast.Name):
            try:
                constants[statement.targets[0].id] = ast.literal_eval(statement.value)
            except (ValueError, TypeError):
                pass
    assert hashlib.sha256(original.encode()).hexdigest() == constants["ORIGINAL_SHA256"]
    pure = original
    for name, before in constants.items():
        if name.endswith("BEFORE"):
            after = constants[name.removesuffix("BEFORE") + "AFTER"]
            assert pure.count(before) == 1
            pure = pure.replace(before, after)
    assert hashlib.sha256(pure.encode()).hexdigest() == literals["pure_sha"]
    diagnostic = pure
    for before, after in literals["core_changes"]:
        assert diagnostic.count(before) == 1
        assert before.count("await ") == after.count("await ")
        assert before.count("Promise.") == after.count("Promise.")
        assert before.count("setTimeout(") == after.count("setTimeout(")
        diagnostic = diagnostic.replace(before, after)
    assert hashlib.sha256(diagnostic.encode()).hexdigest() == literals["diagnostic_core_sha"]
    assert literals["pure_sha"] != literals["diagnostic_core_sha"]
    restored = diagnostic
    for before, after in reversed(literals["core_changes"]):
        assert restored.count(after) == 1
        restored = restored.replace(after, before)
    assert restored == pure
    output = tmp_path / "diagnostic.js"
    output.write_text(diagnostic)
    checked = subprocess.run(["node", "--check", str(output)], text=True, capture_output=True)
    assert checked.returncode == 0, checked.stderr
    assert (original_root / "lib/single-file.js").read_text() == original
    assert "abxBoundary" not in candidate
    assert "a > 31 || b < 0 || b > 1048576" in capture
    assert "event.phase === 'detail' && event.a === a" in capture


def test_stage2_projection_rejects_arbitrary_content_and_bounds_records(tmp_path):
    import json

    workflow = yaml.load((ROOT / ".github/workflows/diagnose-canva.yml").read_text(), Loader=yaml.BaseLoader)
    capture = next(s["run"] for s in workflow["jobs"]["diagnose"]["steps"] if s["name"] == "Capture public Canva with native diagnostics")
    instrument = capture.split("<<'INSTRUMENT'", 1)[1].split("INSTRUMENT\n", 1)[0]
    projection = instrument.split("const recordPhaseText = ", 1)[1].split("const recordPhase =", 1)[0].strip()
    output = tmp_path / "phases.json"
    script = "const fs = require('fs'); const phases=[]; const saveStartedAt=Date.now();"
    script += f"const diagnosticPath={json.dumps(str(output))}; const record={projection}"
    script += "for(let i=0;i<2000;i++)record('ABX_PUBLIC_PHASE detail 22 '+i);"
    script += "for(let i=0;i<32;i++)record('ABX_PUBLIC_PHASE detail '+i+' 1');"
    script += "record('ABX_PUBLIC_PHASE stage_start 2 1');"
    script += "record('ABX_PUBLIC_PHASE detail 32 1');record('ABX_PUBLIC_PHASE detail 1 1048577');"
    script += "record('ABX_PUBLIC_PHASE detail 1 -1');record('ABX_PUBLIC_PHASE stage_start 2 99');"
    script += "record('ABX_PUBLIC_PHASE private-cookie-url-sentinel 0 1');"
    script += "record('ABX_PUBLIC_PHASE detail 1 1 private-cookie-url-sentinel');"
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    records = json.loads(output.read_text())
    assert len(records) == 33
    assert {record["a"] for record in records if record["phase"] == "detail"} == set(range(32))
    assert all(set(record) == {"phase", "a", "b", "elapsed_ms"} for record in records)
    assert all(record["b"] == 1 for record in records)
    assert "private-cookie-url-sentinel" not in output.read_text()
    assert output.stat().st_mode & 0o077 == 0
