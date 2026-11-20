"""Record only allowlisted signals from a protected one-recipe Canva run."""

import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

PROFILES = {"desktop": (1600, 1000), "tablet": (1024, 1366), "mobile": (390, 844)}
PHASES = {
    "navigate": "on_Snapshot__30_chrome_navigate",
    "singlefile": "on_Snapshot__50_singlefile",
    "screenshot": "on_Snapshot__51_screenshot",
    "canva": "on_Snapshot__53_canva",
    "responses": "on_Snapshot__24_responses.daemon.bg",
    "tab": "on_Snapshot__01_chrome_tab.daemon.bg",
}


def safe_text(path):
    if path.is_file() and not path.is_symlink():
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 2 * 1024**2))
            return stream.read().decode(errors="replace")
    return ""


def phase_metrics(text):
    phases = {}
    for name, hook in PHASES.items():
        matches = re.findall(
            rf"(?m)^\s*{re.escape(hook)}\s+(succeeded|failed|noresults|skipped)\s+[^\n]*?\b(\d+(?:\.\d+)?)s/\d+s\b",
            text,
        )
        if matches:
            status, seconds = matches[-1]
            phases[name] = {"status": status, "elapsed_seconds": float(seconds)}
    return phases


def signals(text):
    return {
        "navigation_200": bool(re.search(r"page loaded http=200\b", text)),
        "singlefile_download_timeout": bool(re.search(r"SingleFile download for tab \d+ did not complete", text)),
        "renderer_crashed": "renderer crashed" in text.lower(),
        "unexpected_target_close": "closed unexpectedly" in text.lower(),
        "missing_target_marker": "target_id.txt" in text
        and bool(re.search(r"(?:No target_id\.txt found|target_id\.txt is missing)", text)),
        "tab_sigterm": "Received SIGTERM, closing chrome tab" in text,
    }


def read_counter(path):
    try:
        return path.read_text()
    except OSError:
        return ""


def memory():
    matches = re.findall(r"(?m)^0::(.*)$", read_counter(Path("/proc/self/cgroup")))
    root = (Path("/sys/fs/cgroup") / matches[0].lstrip("/")) if matches else Path("/sys/fs/cgroup")
    result = {}
    for name in ("memory.peak", "memory.swap.peak"):
        text = read_counter(root / name).strip()
        if text.isdecimal():
            result[name] = int(text)
    for key, value in re.findall(r"(?m)^(oom|oom_kill|oom_group_kill) (\d+)$", read_counter(root / "memory.events")):
        result[key] = int(value)
    return result


def verified_canva_images(directory):
    manifest = directory / "build.json"
    if not manifest.is_file():
        return {}
    build = json.loads(manifest.read_text())
    files = build["files"]
    expected = {f"snapshot-view-canva-{profile}.png": dimensions for profile, dimensions in PROFILES.items()}
    if files.keys() != expected.keys() or build["revision"] != os.environ["GITHUB_SHA"]:
        return {}
    for name, dimensions in expected.items():
        image = (directory / name).read_bytes()
        if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", image[16:24]) != dimensions:
            return {}
        if hashlib.sha256(image).hexdigest() != files[name]:
            return {}
    return files


def main(root):
    if not root.is_dir():
        return 1
    logs = [safe_text(root / "collector.log"), safe_text(root / "capture.log")]
    for pattern in (
        "**/canva-supplementary-capture.log",
        "**/on_Snapshot__01_chrome_tab*.stderr.log",
        "**/on_Snapshot__50_singlefile*.stderr.log",
    ):
        logs.extend(safe_text(path) for path in sorted((root / "failure").glob(pattern))[:4])
    text = "\n".join(logs)
    status = safe_text(root / "exit-code").strip()
    timestamps = {}
    for name in ("start", "end"):
        value = safe_text(root / name).strip()
        if re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
            timestamps[name] = value
    signs = {
        (match, int(code))
        for match, code in re.findall(
            r"target_crash status=(normal|abnormal|killed|crashed|oom|launch-failed|integrity-failure|still-running|unknown) error_code=(-?\d+)",
            text,
        )
    }
    digests = verified_canva_images(root / "png")
    report = {
        "revision": os.environ["GITHUB_SHA"],
        "start_end": timestamps,
        "exit_status": int(status) if status.isdecimal() else None,
        "phases": phase_metrics(text),
        "signals": signals(text),
        "target_crash_diagnostics": [{"status": name, "error_code": code} for name, code in sorted(signs)],
        "memory": memory(),
        "validated_canva_png_sha256": digests,
    }
    (root / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0 if status == "0" and len(digests) == len(PROFILES) else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
