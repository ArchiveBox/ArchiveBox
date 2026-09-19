#!/usr/bin/env python3
"""Restore validated capture output without running application CI."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
from urllib.error import HTTPError
from urllib.request import urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("kind", choices=["archivebox", "ios", "extension"])
parser.add_argument("destination", type=Path)
args = parser.parse_args()
args.destination.mkdir(parents=True, exist_ok=True)
# Only successful default-branch capture runs are eligible, never PR artifacts.
if os.environ.get("GH_TOKEN"):
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = "dev" if args.kind == "archivebox" else "main"
    runs = json.loads(
        subprocess.check_output(
            ["gh", "api", f"repos/{repo}/actions/workflows/screenshots.yml/runs?branch={branch}&status=success&per_page=100"],
        ),
    )
    for run in runs["workflow_runs"]:
        if run["event"] not in ("push", "workflow_dispatch"):
            continue
        artifacts = json.loads(subprocess.check_output(["gh", "api", f"repos/{repo}/actions/runs/{run['id']}/artifacts"]))
        if any(a["name"] == "site-screenshots" and not a["expired"] for a in artifacts["artifacts"]):
            subprocess.run(
                ["gh", "run", "download", str(run["id"]), "--repo", repo, "--name", "site-screenshots", "--dir", str(args.destination)],
                check=True,
            )
            print(f"Restored validated captures from run {run['id']} ({run['head_sha']})")
            raise SystemExit(0)
# Published captures remain available even after Actions artifacts expire.
base, manifest_name = {
    "archivebox": ("https://archivebox.io/screenshots/", "build.json"),
    "ios": ("https://app.archivebox.io/screenshots/", "manifest.json"),
    "extension": ("https://extension.archivebox.io/screenshots/", "manifest.json"),
}[args.kind]


def fetch(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name:
        raise ValueError(f"Unsafe capture path: {name}")
    with urlopen(base + name, timeout=60) as response:
        data = response.read()
    expected = hashes.get(name)
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Capture checksum mismatch: {name}")
    target = args.destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


try:
    with urlopen(base + manifest_name, timeout=60) as response:
        raw = response.read()
except HTTPError as error:
    if error.code == 404 and args.kind == "ios":
        print("No complete native gallery published yet; use the curated README screenshots.")
        raise SystemExit(0)
    raise
manifest = json.loads(raw)
hashes = {}
if args.kind == "archivebox":
    hashes = manifest["files"]
    names = [*hashes, "index.html"]
elif args.kind == "extension":
    names = [image["file"] for capture in manifest["screenshots"] for image in capture["images"]]
else:
    if manifest.get("complete") is not True:
        raise ValueError("Published native gallery must be complete")
    names = [capture["path"] for capture in manifest["captures"]]
with ThreadPoolExecutor(max_workers=8) as pool:
    list(pool.map(fetch, names))
(args.destination / manifest_name).write_bytes(raw)
print(f"Restored {len(names)} published capture files, retaining revision {manifest['revision']}")
