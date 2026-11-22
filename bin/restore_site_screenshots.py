#!/usr/bin/env -S uv run --no-project python
"""Restore validated screenshots, keeping capture and website revisions separate."""

import argparse
import hashlib
import importlib
import json
import os
import re
import subprocess
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
OPTIONAL_PROVIDER_CAPTURES = ("canva", "figma", "miro")
PROFILES = ("desktop", "tablet", "mobile")


def capture_revision_order(repo_dir):
    # Use immutable source ancestry, not upload time: an older manual capture
    # can finish after a newer automatic capture. Fail closed on shallow clones.
    shallow = subprocess.check_output(["git", "rev-parse", "--is-shallow-repository"], cwd=repo_dir, text=True).strip()
    if shallow != "false":
        raise ValueError("Screenshot source ordering requires complete Git history")
    revisions = subprocess.check_output(["git", "rev-list", "--first-parent", "HEAD"], cwd=repo_dir, text=True).splitlines()
    return {revision: rank for rank, revision in enumerate(revisions)}


def validate_optional_provider_captures(destination, manifest):
    # Older published artifacts did not record provider availability.
    if "optional_provider_captures" not in manifest:
        return
    outcomes = manifest["optional_provider_captures"]
    if (
        not isinstance(outcomes, dict)
        or set(outcomes) != set(OPTIONAL_PROVIDER_CAPTURES)
        or any(status not in ("captured", "unavailable") for status in outcomes.values())
    ):
        raise ValueError("Invalid optional provider capture outcomes")
    for provider, status in outcomes.items():
        names = {f"snapshot-view-{provider}-{profile}.png" for profile in PROFILES}
        present = names.intersection(manifest["files"])
        if status == "captured" and present != names:
            raise ValueError(f"Incomplete optional provider capture: {provider}")
        if status == "unavailable" and (
            present or any((destination / name).exists() or (destination / name).is_symlink() for name in names)
        ):
            raise ValueError(f"Unavailable provider includes screenshot files: {provider}")


def validate(destination, run=None):
    manifest = json.loads((destination / MANIFEST).read_text())
    if run and manifest["revision"] != run["head_sha"]:
        raise ValueError("Screenshot revision differs from the original capture run")
    if not manifest.get("files") or len(manifest["files"]) != manifest["capture_count"]:
        raise ValueError("Incomplete screenshot manifest")
    validate_optional_provider_captures(destination, manifest)
    for name, expected in manifest["files"].items():
        image = destination / artifacts.relative_path(name)
        if hashlib.sha256(image.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Screenshot checksum mismatch: {name}")
    if not (destination / "index.html").is_file():
        raise ValueError("Missing gallery content for the current renderer")
    return manifest


def capture_meets_published_floor(revision, published, revision_order):
    published_revision = published["revision"]
    if published_revision not in revision_order:
        raise ValueError("Published screenshot source is outside the checked-out Core lineage")
    return revision in revision_order and revision_order[revision] <= revision_order[published_revision]


def normalize_filenames(destination):
    """Migrate older capture artifacts to order-independent public filenames."""
    manifest_path = destination / MANIFEST
    manifest = validate(destination)
    names = {name: re.sub(r"^\d+-", "", name) for name in manifest["files"]}
    if len(set(names.values())) != len(names):
        raise ValueError("Screenshot names collide after removing capture-order prefixes")
    gallery_path = destination / "index.html"
    gallery = gallery_path.read_text()
    for old, new in names.items():
        if old != new:
            (destination / old).replace(destination / new)
            gallery = gallery.replace(f"./{old}", f"./{new}")
    manifest["files"] = {names[name]: digest for name, digest in manifest["files"].items()}
    gallery_path.write_text(gallery)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    validate(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    # An expired artifact must not let an older manual re-capture replace the
    # already-published gallery. Unknown/unavailable provenance fails closed.
    raw = artifacts.fetch(BASE, MANIFEST)
    manifest = json.loads(raw)
    if os.environ.get("GH_TOKEN"):
        revision_order = capture_revision_order(Path(__file__).resolve().parents[1])
        for run in artifacts.runs(REPO, "screenshots.yml", BRANCH, revision_order=revision_order):
            if not capture_meets_published_floor(run["head_sha"], manifest, revision_order):
                continue
            if "site-screenshots" not in artifacts.names(REPO, run):
                continue
            artifacts.download(REPO, run, "site-screenshots", args.destination)
            validate(args.destination, run)
            normalize_filenames(args.destination)
            print(f"Restored validated screenshots from {run['id']} ({run['head_sha']})")
            return
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
    normalize_filenames(args.destination)
    print(f"Restored {len(names)} published files from {manifest['revision']}")


if __name__ == "__main__":
    main()
