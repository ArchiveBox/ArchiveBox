"""Validate and compare a three-recipe native gallery pilot; never publish to Pages."""

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

PROFILES = {"desktop": (1600, 1000), "tablet": (1024, 1366), "mobile": (390, 844)}
RECIPES = ("papersdl", "staticfile", "ytdlp")
LANES = {"serial": RECIPES, **{recipe: (recipe,) for recipe in RECIPES}}
CAPTURE_STEP = "Capture anonymous native provider fixture"
UPLOAD_STEP = "Upload pilot evidence, never a site-screenshots artifact"


def validate_images(lane, source, files):
    expected = {f"snapshot-view-{plugin}-{profile}.png": dimensions for plugin in LANES[lane] for profile, dimensions in PROFILES.items()}
    if files.keys() != expected.keys():
        raise ValueError(f"Unexpected pilot view coverage for {lane}: {sorted(files)}")
    for name, dimensions in expected.items():
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid image path: {name}")
        image = path.read_bytes()
        if len(image) < 24 or image[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", image[16:24]) != dimensions:
            raise ValueError(f"Unexpected PNG dimensions: {name}")
        if hashlib.sha256(image).hexdigest() != files[name]:
            raise ValueError(f"Capture checksum mismatch: {name}")


def run_identity():
    return {key: os.environ[key] for key in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")}


def collect(lane, source, output):
    manifest = json.loads((source / "build.json").read_text())
    identity = run_identity()
    if manifest["revision"] != identity["GITHUB_SHA"] or manifest["capture_count"] != len(manifest["files"]):
        raise ValueError("Pilot manifest does not match the exact current capture")
    validate_images(lane, source, manifest["files"])
    output.mkdir()
    for name in manifest["files"]:
        shutil.copyfile(source / name, output / name)
    receipt = {
        **identity,
        "lane": lane,
        "version": manifest["version"],
        "pins": {package: version(package) for package in ("abx-plugins", "abx-dl", "abxpkg", "abxbus")},
        "files": manifest["files"],
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def api(path):
    repo = os.environ["GITHUB_REPOSITORY"]
    return json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                f"repos/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}{path}",
            ],
        ),
    )


def seconds(first, last):
    return round(
        (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds(),
        1,
    )


def report(jobs, artifacts, run_created):
    lines = [
        "| Lane | Run → runner start | Setup | Native collector + render | Validate/upload | Run start → artifact |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    observed = {}
    for lane in LANES:
        job = jobs[lane]
        steps = {step["name"]: step for step in job["steps"]}
        capture = steps[CAPTURE_STEP]
        upload = steps[UPLOAD_STEP]
        if capture["conclusion"] != "success" or upload["conclusion"] != "success":
            raise ValueError(
                f"Pilot lane {lane} did not successfully capture and upload",
            )
        artifact = artifacts[lane]
        finished = max(artifact["created_at"], upload["completed_at"], key=datetime.fromisoformat)
        values = (
            seconds(run_created, job["started_at"]),
            seconds(job["started_at"], capture["started_at"]),
            seconds(capture["started_at"], capture["completed_at"]),
            seconds(capture["completed_at"], finished),
            seconds(run_created, finished),
        )
        observed[lane] = values[-1]
        lines.append(
            f"| {lane} | " + " | ".join(f"{value:g}s" for value in values) + " |",
        )
    serial = observed["serial"]
    parallel = max(observed[lane] for lane in RECIPES)
    lines += [
        "",
        f"Serial treatment ready after {serial:g}s. All sharded artifacts ready after {parallel:g}s.",
        "Start is workflow creation (attempt start for reruns); runner delay and browser provisioning count.",
        "Three-recipe anonymous pilot only. No production gallery artifact or Pages deployment was generated.",
        "These are not full-gallery or start-to-live timings.",
    ]
    return "\n".join(lines) + "\n"


def compare(root):
    identity = run_identity()
    artifacts = {}
    receipts = []
    for lane in LANES:
        artifact_name = f"gallery-shard-pilot-{identity['GITHUB_RUN_ATTEMPT']}-{lane}"
        bundle = root / artifact_name
        receipt = json.loads((bundle / "receipt.json").read_text())
        if receipt["lane"] != lane or any(receipt[key] != value for key, value in identity.items()):
            raise ValueError(f"Mixed capture identity in {lane}")
        validate_images(lane, bundle, receipt["files"])
        receipts.append(receipt)
        artifacts[artifact_name] = lane
    if any((receipt["version"], receipt["pins"]) != (receipts[0]["version"], receipts[0]["pins"]) for receipt in receipts):
        raise ValueError("Mixed package pins across pilot lanes")
    run = api("")
    if run["head_sha"] != identity["GITHUB_SHA"]:
        raise ValueError("Unexpected workflow revision")
    attempt = identity["GITHUB_RUN_ATTEMPT"]
    jobs = {}
    for job in api(f"/attempts/{attempt}/jobs?per_page=100")["jobs"]:
        lane = job["name"].removeprefix("pilot-")
        if lane in LANES and job["name"] == f"pilot-{lane}":
            jobs[lane] = job
    downloads = {
        artifacts[row["name"]]: row
        for row in api("/artifacts?per_page=100")["artifacts"]
        if row["name"] in artifacts and not row["expired"]
    }
    if jobs.keys() != LANES.keys() or downloads.keys() != LANES.keys():
        raise ValueError(
            "GitHub did not report all expected capture jobs/artifacts for this attempt",
        )
    origin = run["created_at"] if attempt == "1" else api(f"/attempts/{attempt}")["run_started_at"]
    summary = report(jobs, downloads, origin)
    print(summary, end="")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as stream:
        stream.write(summary)


if __name__ == "__main__":
    if sys.argv[1] == "collect":
        collect(sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4]))
    elif sys.argv[1] == "compare":
        compare(Path(sys.argv[2]))
    else:
        raise SystemExit("Use collect or compare")
