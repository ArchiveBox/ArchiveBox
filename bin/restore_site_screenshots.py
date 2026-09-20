#!/usr/bin/env -S uv run --no-project python
"""Restore validated screenshots, keeping capture and website revisions separate."""

import argparse
import hashlib
import importlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PAGES = Path(__file__).resolve().parents[1] / ".github/pages"
sys.path.insert(0, str(PAGES))
artifacts = importlib.import_module("artifacts")

# Repository-specific capture contract.
REPO = "ArchiveBox/ArchiveBox"
BRANCH = "dev"
BASE = "https://archivebox.io/screenshots/"
MANIFEST = "build.json"


def validate(destination, run=None):
    manifest = json.loads((destination / MANIFEST).read_text())
    if run and manifest["revision"] != run["head_sha"]:
        raise ValueError("Screenshot revision differs from the original capture run")
    if not manifest.get("files") or len(manifest["files"]) != manifest["capture_count"]:
        raise ValueError("Incomplete screenshot manifest")
    for name, expected in manifest["files"].items():
        image = destination / artifacts.relative_path(name)
        if hashlib.sha256(image.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Screenshot checksum mismatch: {name}")
    if not (destination / "index.html").is_file():
        raise ValueError("Missing gallery content for the current renderer")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    if os.environ.get("GH_TOKEN"):
        for run in artifacts.runs(REPO, "screenshots.yml", BRANCH):
            if "site-screenshots" not in artifacts.names(REPO, run):
                continue
            artifacts.download(REPO, run, "site-screenshots", args.destination)
            validate(args.destination, run)
            print(f"Restored validated screenshots from {run['id']} ({run['head_sha']})")
            return
    raw = artifacts.fetch(BASE, MANIFEST)
    manifest = json.loads(raw)
    names = [*manifest["files"], "index.html"]

    def restore(name):
        target = args.destination / artifacts.relative_path(name)
        data = artifacts.fetch(BASE, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(restore, names))
    (args.destination / MANIFEST).write_bytes(raw)
    validate(args.destination)
    print(f"Restored {len(names)} published files from {manifest['revision']}")


if __name__ == "__main__":
    main()
