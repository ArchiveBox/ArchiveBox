"""Qualify the two anonymous automation recipes and attest to actual pilot PNGs."""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = ("playwright", "puppeteer")
PINS = {"abx-plugins": "1.13.799", "abx-dl": "1.13.375", "abxpkg": "1.13.101", "abxbus": "2.5.91"}
BLOBS = {
    "bin/generate_ui_screenshot_gallery.py": "b673b91a1e9856b6cfe945d60cafb3017558a7c1",
    "bin/collect_ui_screenshots.sh": "69ecbecb0f1fcddd59b64fa9a1d8e69316dc1c68",
}
SOURCE_SHA256 = "23d135c1ca2c8bd2f975fb4c92f83c18e82357ea6c632928e6b464a957178b67"
PROFILES = {"desktop": (1600, 1000), "tablet": (1024, 1366), "mobile": (390, 844)}
FILES = {f"snapshot-view-{plugin}-{profile}.png": size for plugin in PLUGINS for profile, size in PROFILES.items()}


def pins():
    return {package: version(package) for package in PINS}


def native_plan(plugins):
    return json.loads(
        subprocess.check_output(
            [sys.executable, "-B", ROOT / "bin/generate_ui_screenshot_gallery.py", "plugin-plan"],
            env={**os.environ, "UI_SCREENSHOT_PLUGINS": ",".join(plugins)},
        ),
    )


def preflight(output):
    for path, expected in BLOBS.items():
        if subprocess.check_output(["git", "hash-object", ROOT / path], text=True).strip() != expected:
            raise ValueError(f"Unexpected production source: {path}")
    if pins() != PINS:
        raise ValueError("Unexpected locked pilot runtime")
    full = native_plan(())
    selected = native_plan(PLUGINS)
    examples = [item for item in full["examples"] if set(item["plugins"]) & set(PLUGINS)]
    overrides = {plugin: full["overrides"][plugin] for plugin in PLUGINS}
    if (
        selected["examples"] != examples
        or selected["overrides"] != overrides
        or selected["required"] != [f"Snapshot View ({plugin})" for plugin in PLUGINS]
        or selected["importer_views"]
        or selected["config_views"]
    ):
        raise ValueError("Pilot is not the exact selected native plan")
    source_sha256 = hashlib.sha256(json.dumps({"examples": examples, "overrides": overrides}, sort_keys=True).encode()).hexdigest()
    if source_sha256 != SOURCE_SHA256 or len(examples) != 2:
        raise ValueError("Unexpected anonymous fixture inputs or output settings")
    output.write_text(json.dumps({"source_projection_sha256": source_sha256, "visits": len(examples)}, indent=2) + "\n")


def collect(preflight_path, native_dir, evidence):
    reviewed = json.loads(preflight_path.read_text())
    if reviewed != {"source_projection_sha256": SOURCE_SHA256, "visits": 2} or pins() != PINS:
        raise ValueError("Pilot preflight or locked runtime changed")
    manifest = json.loads((native_dir / "build.json").read_text())
    identity = {key: os.environ[key] for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")}
    files = manifest["files"]
    if manifest["revision"] != identity["GITHUB_SHA"] or files.keys() != FILES.keys() or manifest["capture_count"] != len(FILES):
        raise ValueError("Pilot manifest is not the six exact PNGs at this workflow revision")
    for name, size in FILES.items():
        path = native_dir / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid capture path: {name}")
        data = path.read_bytes()
        if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", data[16:24]) != size:
            raise ValueError(f"Invalid capture dimensions: {name}")
        if hashlib.sha256(data).hexdigest() != files[name]:
            raise ValueError(f"Capture checksum mismatch: {name}")
    evidence.mkdir()
    for name in FILES:
        shutil.copyfile(native_dir / name, evidence / name)
    receipt = {**identity, **reviewed, "pins": PINS, "version": manifest["version"], "files": files}
    (evidence / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    match sys.argv[1:]:
        case ["preflight", output]:
            preflight(Path(output))
        case ["collect", qualified, native_dir, evidence]:
            collect(Path(qualified), Path(native_dir), Path(evidence))
        case _:
            raise SystemExit("Expected preflight OUTPUT or collect QUALIFIED NATIVE_DIR EVIDENCE")
