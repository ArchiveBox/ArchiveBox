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
GALLERY_VIEW_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PROFILES = ("desktop", "tablet", "mobile")


def capture_revision_order(repo_dir):
    # Use immutable source ancestry, not upload time: an older manual capture
    # can finish after a newer automatic capture. Fail closed on shallow clones.
    shallow = subprocess.check_output(["git", "rev-parse", "--is-shallow-repository"], cwd=repo_dir, text=True).strip()
    if shallow != "false":
        raise ValueError("Screenshot source ordering requires complete Git history")
    revisions = subprocess.check_output(["git", "rev-list", "--topo-order", "HEAD"], cwd=repo_dir, text=True).splitlines()
    return {revision: rank for rank, revision in enumerate(revisions)}


def validate_optional_provider_captures(destination, manifest):
    # Older published artifacts did not record provider availability.
    if "optional_provider_captures" not in manifest:
        return
    outcomes = manifest["optional_provider_captures"]
    if (
        not isinstance(outcomes, dict)
        or not outcomes
        or any(not GALLERY_VIEW_SLUG.fullmatch(provider) for provider in outcomes)
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


def validate_optional_recipe_captures(destination, manifest):
    if "optional_recipe_captures" not in manifest:
        return
    outcomes = manifest["optional_recipe_captures"]
    if not isinstance(outcomes, dict) or "optional_provider_captures" in manifest:
        raise ValueError("Invalid optional gallery recipe outcomes")
    seen_views = set()
    for recipe, outcome in outcomes.items():
        if (
            not re.fullmatch(r"recipe-[a-f0-9]{16}", recipe)
            or not isinstance(outcome, dict)
            or set(outcome) != {"status", "views"}
            or outcome["status"] not in ("captured", "unavailable")
            or not isinstance(outcome["views"], list)
            or not outcome["views"]
            or any(not isinstance(view, str) or not GALLERY_VIEW_SLUG.fullmatch(view) for view in outcome["views"])
            or outcome["views"] != sorted(set(outcome["views"]))
            or seen_views.intersection(outcome["views"])
        ):
            raise ValueError("Invalid optional gallery recipe outcome")
        seen_views.update(outcome["views"])
        for view in outcome["views"]:
            names = {f"{view}-{profile}.png" for profile in PROFILES}
            present = names.intersection(manifest["files"])
            if outcome["status"] == "captured" and present != names:
                raise ValueError(f"Incomplete optional gallery recipe capture: {recipe}")
            if outcome["status"] == "unavailable" and (
                present or any((destination / name).exists() or (destination / name).is_symlink() for name in names)
            ):
                raise ValueError(f"Unavailable gallery recipe includes screenshot files: {recipe}")


def validate(destination, run=None):
    manifest = json.loads((destination / MANIFEST).read_text())
    if run and manifest["revision"] != run["head_sha"]:
        raise ValueError("Screenshot revision differs from the original capture run")
    if not manifest.get("files") or len(manifest["files"]) != manifest["capture_count"]:
        raise ValueError("Incomplete screenshot manifest")
    validate_optional_provider_captures(destination, manifest)
    validate_optional_recipe_captures(destination, manifest)
    for name, expected in manifest["files"].items():
        image = destination / artifacts.relative_path(name)
        if hashlib.sha256(image.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Screenshot checksum mismatch: {name}")
    if not (destination / "index.html").is_file():
        raise ValueError("Missing gallery content for the current renderer")
    return manifest


def capture_meets_published_floor(revision, published, revision_order, *, repo_dir):
    published_revision = published["revision"]
    if published_revision not in revision_order:
        raise ValueError("Published screenshot source is outside the checked-out Core lineage")
    if revision not in revision_order:
        return False
    # Both sides of a merge belong to Core history, but a topological rank
    # alone cannot prove that one side includes the other's published changes.
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", published_revision, revision], cwd=repo_dir, check=False)
    if ancestry.returncode not in (0, 1):
        ancestry.check_returncode()
    return ancestry.returncode == 0


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
        repo_dir = Path(__file__).resolve().parents[1]
        revision_order = capture_revision_order(repo_dir)
        for run in artifacts.runs(REPO, "screenshots.yml", BRANCH, revision_order=revision_order):
            if not capture_meets_published_floor(run["head_sha"], manifest, revision_order, repo_dir=repo_dir):
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
